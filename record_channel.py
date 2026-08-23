# -*- encoding: utf-8 -*-

from chat_downloader import ChatDownloader
import scrapetube
import requests, json, sys, os, time, psutil, io, re, math
from http.cookiejar import (MozillaCookieJar, Cookie)
from datetime import datetime, timedelta
import dateutil.parser
import threading
import subprocess, glob
from zoneinfo import ZoneInfo
import mysql.connector
import smtplib, ssl
import mimetypes
from email.message import EmailMessage

# Database class
# Warning : it's not possible to create two concurrent cursors on the same connection then run a statement on each at the same time
# without having errors such 2013 (HY000): Lost connection to MySQL server during query
# So we use global object self.connection only outside threads and for threads we create a new Mysql connection
class Database():
    def __init__(self, params_database):
        self.params_database = params_database
        self.connection = None
        self.connect()

    def connect(self):
        self.connection = mysql.connector.connect(
                host=self.params_database['mysql_host'],
                user=self.params_database['mysql_user'],
                password=self.params_database['mysql_pwd'],
                database=self.params_database['mysql_database']
        )
            
    def getConnection(self):
        # Always ensure using a working Mysql connection
        if self.connection is not None and self.connection.is_connected():
            pass
        else:
            self.connect()
        
        return self.connection

    def __del__(self):
        if self.connection is not None and self.connection.is_connected():
            self.connection.close()

class Program():
    def __init__(self, idchannel, urlchannel, settings):
        self.idchannel = idchannel
        self.urlchannel = urlchannel
        self.handlechannel = self.urlchannel.replace("https://www.youtube.com/@", "")
        self.settings = settings
        self.tzinfo = ZoneInfo(self.settings['tz'])
        self.initStreamlinkTimeout()
        self.initLoggingFile()
        self.initDebug()

        self.recordThreadList = []
        self.chatThreadList = []
            
    def initLoggingFile(self):
        loggingfilename = os.path.dirname(os.path.realpath(__file__)) + "/record_" + self.idchannel
        self.loggingfile = open(loggingfilename + ".log", "a", encoding="utf-8")

    def initDatabase(self):
        try:
            self.db = Database(self.settings['params_database'])
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()

    def initDebug(self):
        self.debug_modes = [{"label": 'normal', 'value': 1}, {"label": 'debug', 'value': 2}]
        self.debug_mode_default = {"label": 'normal', 'value': 2}
        self.debug_mode_selected = self.searchInList(self.debug_modes, 'label', self.settings['level_debug_selected'])

        if self.debug_mode_selected is None:
            # or better : self.debug_mode_selected = self.debug_mode_default
            self.debug_mode_selected = self.searchInList(self.debug_modes, 'label', 'normal')

    def initStreamlinkTimeout(self):
        # Get value next to --stream-timeout in streamlink_options settings
        self.stream_timeout = 0
        if self.settings['record_video']['record_live_tool'] == 'streamlink':
            if "--stream-timeout" in self.settings['record_video'].get('streamlink_options'):
                try:
                    self.stream_timeout = int(self.settings['record_video']['streamlink_options'][self.settings['record_video']['streamlink_options'].index("--stream-timeout") + 1])
                except Exception as e:
                    pass
    
    def getDateNow(self):
        timestamp_now = datetime.now().timestamp()
        date = datetime.fromtimestamp(timestamp_now, self.tzinfo)
        dateString = date.strftime(self.settings['dateFormats']['dateString'])
        dateDBString = date.strftime(self.settings['dateFormats']['dateDBString'])
        dateFileString = date.strftime(self.settings['dateFormats']['dateFileString'])
        
        dateNow = {"object": date, "dateString": dateString, "dateDBString": dateDBString, "dateFileString": dateFileString}
        
        return dateNow

    def safely_get_value_from_key(self, *args, default=None):
        obj = args[0]
        keys = args[1:]

        for key in keys:
            try:
                obj = obj[key]
            except Exception:
                return default

        return obj   

    def searchInList(self, listElements, attribute, value):
        found = None

        for el in listElements:
            if el[attribute] == value:
                found = el
                break

        return found

    def isLogMessage(self, debug_mode_message):
        isLog = False
        
        if debug_mode_message['value'] <= self.debug_mode_selected['value']:
            isLog = True
            
        return isLog

    def writelog(self, message, type_message = 'normal'):
        # If type_message don't exist, we select normal one
        debug_mode_message = self.searchInList(self.debug_modes, 'label', type_message)
        if debug_mode_message is None:
            debug_mode_message = self.debug_mode_default

        # Do we print this type_message with the self.debug_mode_selected ?
        if not self.isLogMessage(debug_mode_message):
            return    
        
        dateNow = self.getDateNow()
        self.loggingfile.write(dateNow["dateString"] + " : " + message + "\n")
        # Write in real time
        self.loggingfile.flush()
            
    def initChannel(self):
        # Get handle from idchannel
        channelInfosURL = "https://www.googleapis.com/youtube/v3/channels?key=" + self.settings['YoutubeAPIV3']['youtubeKey'] + "&id=" + self.idchannel + "&part=snippet"
        print(channelInfosURL)
        try:
            response = requests.get(channelInfosURL)
            channelInfosResponse = response.text
            if response.status_code == 200:
                channel_json = json.loads(channelInfosResponse)
                
                if channel_json.get('pageInfo').get('totalResults') == 0:
                    print(f"[×] channel={self.idchannel} Error channelInfosURL {channelInfosURL} : channel not found")
                    self.writelog(f"[×] channel={self.idchannel} Error channelInfosURL {channelInfosURL} : channel not found")
                    self.exitProgram()
                
                item = channel_json.get('items')[0]
                snippet = item.get('snippet')
                self.handlechannel = snippet.get('customUrl')[1:len(snippet.get('customUrl'))]
                self.urlchannel = "https://www.youtube.com/@" + self.handlechannel
            else:
                print(f"[×] channel={self.idchannel} Response of channelInfosURL {channelInfosURL} isn't OK : {response.status_code} {response.text}")
                self.writelog(f"[×] channel={self.idchannel} Response of channelInfosURL {channelInfosURL} isn't OK : {response.status_code} {response.text}")
                self.exitProgram()
        except Exception as e:
            print(f"[×] channel={self.idchannel} Error channelInfosURL {channelInfosURL} : {e}")
            self.writelog(f"[×] channel={self.idchannel} Error channelInfosURL {channelInfosURL} : {e}")
            self.exitProgram()

    # Used when errors/exceptions occured and when we want to exit right now
    def exitProgram(self):
        self.writelog("Execution had errors")
        self.writelog("Ending program")
        self.clean()
        #sys.exit(1)
        os._exit(1)
    
    # Used at the end of program without errors/exceptions and when errors/exception occured
    def clean(self):
        try:
            # Close Files
            self.loggingfile.close()
        except Exception as e:
            print("Error cleaning up : " + str(e))

    def recordChatInit(self, live):
        lastChat = None
        newfilenumber = None
        url = "https://www.youtube.com/watch?v=" + live['idVideo']

        if self.settings['record_chat']['enabled'] is True:
            try:
                db = Database(self.settings['params_database'])
                connection = db.getConnection()
            except Exception as e:
                print(f"[×] Error connecting to database : {e}")
                self.writelog(f"[×] Error connecting to database : {e}", 'normal')
                self.exitProgram()
            
            # Get last chat of live from chats table
            try:
                connection = db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                select_lastchat_query = """SELECT * FROM chats, lives
                WHERE lives.id_live = chats.id_live AND lives.idVideo=%(idVideo)s
                ORDER BY id_chat DESC LIMIT 1"""
                params = {"idVideo": live['idVideo']}
                cursor.execute(select_lastchat_query, params)
                result = cursor.fetchall()
                if len(result) > 0:
                    # Has been recorded at least once
                    lastChat = result[0]
                    print(lastChat)
                    print(f"id_live={live['id_live']} idVideo={live['idVideo']} Last id_chat=" + str(lastChat['id_chat']) + " with status_chat=" + str(lastChat['status_chat']))
                    self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Last id_chat=" + str(lastChat['id_chat']) + " with status_chat=" + str(lastChat['status_chat']), 'debug')

                cursor.close()
            except mysql.connector.Error as ex:
                print(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Get last chat of live from chats table : {ex}")
                self.writelog(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Get last chat of live from chats table : {ex}", 'normal')
                self.exitProgram()
            
            # Check if chat_pid stored in DB is still running and its commandline matchs char_downloader executable and url of stream (in case of same pid is reused by OS for another thing)
            procChatExists = False
            if lastChat is not None:
                if lastChat['chat_pid'] is not None and psutil.pid_exists(lastChat['chat_pid']) is True:
                    try:
                        proc = psutil.Process(lastChat['chat_pid'])
                        if proc.cmdline()[1] == self.settings['record_chat']['path_chat_downloader'] + 'chat_downloader' and url in proc.cmdline():
                            procChatExists = True                            
                    except Exception as e:
                        print(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Impossible to get Python process informations for chat recording : {e}")
                        self.writelog(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Impossible to get Python process informations for chat recording : {e}", 'normal')
                        # We continue normally            

            if procChatExists is False:
                print(f"id_live={live['id_live']} idVideo={live['idVideo']} We record a new chat file")
                self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} We record a new chat file", 'debug')
                
                if lastChat is None:
                    # No previous chat
                    newfilenumber = '001'
                else:
                    # Set filenumber + 1
                    newfilenumber = int(lastChat['filenumber']) + 1
                    newfilenumber = str(newfilenumber).rjust(3, '0')
                
                # Insert new chat in chats table
                dateNow = self.getDateNow()
                try:
                    connection = db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    insert_chat_query = """INSERT INTO chats
                    (id_live, filenumber, dateStart) VALUES (%(id_live)s, %(filenumber)s, %(dateStart)s)"""
                    params = {"id_live" : live["id_live"], "filenumber" : newfilenumber, "dateStart" : dateNow['dateDBString']}
                    cursor.execute(insert_chat_query, params)
                    connection.commit()
                    
                    # Set newChat that will serve in recordChat function
                    newChat = params                    
                    newChat["id_chat"] = cursor.lastrowid
                    cursor.close()
                except mysql.connector.Error as ex:
                    # Handles duplicate record when program tries to insert same (id_live, filenumber) at the same time from two different threads
                    if ex.errno == mysql.connector.errorcode.ER_DUP_ENTRY:
                        print(f"idVideo={live['videoId']} id_live={live['id_live']} filenumber={newfilenumber} Trying to insert duplicate key, exception : {ex}")
                        self.writelog(f"idVideo={live['videoId']} id_live={live['id_live']} filenumber={newfilenumber} Trying to insert duplicate key, exception : {ex}", 'normal')
                        return
                    else:
                        print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Insert new chat in chats table : {ex}")
                        self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Insert new chat in chats table : {ex}", 'normal')
                        self.exitProgram()    

                # Start a chat recording in a thread
                chatThread = threading.Thread(target=self.recordChat, args=(live, newChat))
                self.chatThreadList.append(chatThread)
                chatThread.start()
            else:
                print(f"id_live={live['id_live']} idVideo={live['idVideo']} We don't record chat as there's one currently ongoing, record=" + str(lastChat))
                self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} We don't record chat as there's one currently ongoing, record=" + str(lastChat), 'debug')

            # Close Mysql connection
            try:
                connection.close()
            except mysql.connector.Error as ex:
                pass
        else:
            print(f"id_live={live['id_live']} idVideo={live['idVideo']} Chat recording is disabled in settings, we skip it")
            self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Chat recording is disabled in settings, we skip it", 'debug')

    def recordLiveInit(self, live):
        lastRecord = None
        newfilenumber = None
        url = "https://www.youtube.com/watch?v=" + live['idVideo']
        
        if self.settings['record_video']['enabled'] is True:
            try:
                db = Database(self.settings['params_database'])
                connection = db.getConnection()
            except Exception as e:
                print(f"[×] Error connecting to database : {e}")
                self.writelog(f"[×] Error connecting to database : {e}", 'normal')
                self.exitProgram()
            
            # Get last record of live from records table
            try:
                connection = db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                select_lastrecord_query = """SELECT * FROM records, lives
                WHERE lives.id_live = records.id_live AND lives.idVideo=%(idVideo)s
                ORDER BY id_record DESC LIMIT 1"""
                params = {"idVideo": live['idVideo']}
                cursor.execute(select_lastrecord_query, params)
                result = cursor.fetchall()
                if len(result) > 0:
                    # Has been recorded at least once
                    lastRecord = result[0]
                    print(lastRecord)
                    print(f"id_live={live['id_live']} idVideo={live['idVideo']} Last id_record=" + str(lastRecord['id_record']) + " with status_recording=" + str(lastRecord['status_recording']))
                    self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Last id_record=" + str(lastRecord['id_record']) + " with status_recording=" + str(lastRecord['status_recording']), 'debug')
                    
                cursor.close()
            except mysql.connector.Error as ex:
                print(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Get last record of live from records table : {ex}")
                self.writelog(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Get last record of live from records table : {ex}", 'normal')
                self.exitProgram()
                                  
            # Check if recording_pid stored in DB is still running and its commandline matchs record_live_tool executable and url of stream (in case of same pid is reused by OS for another thing)
            proc_record_live_tool_exists = False
            if lastRecord is not None:
                if lastRecord['recording_pid'] is not None and psutil.pid_exists(lastRecord['recording_pid']) is True:
                    try:
                        proc = psutil.Process(lastRecord['recording_pid'])
                        if proc.cmdline()[1] == self.settings['record_video']['path_' + self.settings['record_video']['record_live_tool']] + self.settings['record_video']['record_live_tool'] and url in proc.cmdline():
                            proc_record_live_tool_exists = True
                    except Exception as e:
                        print(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Impossible to get {self.settings['record_video']['record_live_tool']} process informations for video recording : {e}")
                        self.writelog(f"[×] id_live={live['id_live']} idVideo={live['idVideo']} Impossible to get {self.settings['record_video']['record_live_tool']} process informations for video recording : {e}", 'normal')
                        # We continue normally
            
            if proc_record_live_tool_exists is False:
                print(f"id_live={live['id_live']} idVideo={live['idVideo']} We record a new video file")
                self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} We record a new video file", 'debug')

                if lastRecord is None:
                    # No previous record
                    newfilenumber = '001'
                else:
                    # Set filenumber + 1
                    newfilenumber = int(lastRecord['filenumber']) + 1
                    newfilenumber = str(newfilenumber).rjust(3, '0')
                
                # Insert new record in records table
                dateNow = self.getDateNow()
                try:
                    connection = db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    insert_record_query = """INSERT INTO records
                    (id_live, filenumber, recording_live_tool, dateStart) VALUES (%(id_live)s, %(filenumber)s, %(recording_live_tool)s, %(dateStart)s)"""
                    params = {"id_live" : live["id_live"], "filenumber" : newfilenumber, "recording_live_tool": self.settings['record_video']['record_live_tool'],
                    "dateStart" : dateNow['dateDBString']}
                    cursor.execute(insert_record_query, params)
                    connection.commit()
                    
                    # Set newRecord that will serve in recordLive function
                    newRecord = params                    
                    newRecord["id_record"] = cursor.lastrowid
                    cursor.close()
                except mysql.connector.Error as ex:
                    # Handles duplicate record when program tries to insert same (id_live, filenumber) at the same time from two different threads
                    if ex.errno == mysql.connector.errorcode.ER_DUP_ENTRY:
                        print(f"idVideo={live['videoId']} id_live={live['id_live']} filenumber={newfilenumber} Trying to insert duplicate key, exception : {ex}")
                        self.writelog(f"idVideo={live['videoId']} id_live={live['id_live']} filenumber={newfilenumber} Trying to insert duplicate key, exception : {ex}", 'normal')
                        return
                    else:
                        print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Insert new record in records table : {ex}")
                        self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error Insert new record in records table : {ex}", 'normal')
                        self.exitProgram()    

                # Start downloading stream
                recordThread = threading.Thread(target=self.recordLive, args=(live, newRecord))
                self.recordThreadList.append(recordThread)
                recordThread.start()
            else:
                print(f"id_live={live['id_live']} idVideo={live['idVideo']} We don't record video as there's one currently ongoing, record=" + str(lastRecord))
                self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} We don't record video as there's one currently ongoing, record=" + str(lastRecord), 'debug')

            # Close Mysql connection
            try:
                connection.close()
            except mysql.connector.Error as ex:
                pass
        else:
            print(f"id_live={live['id_live']} idVideo={live['idVideo']} Video recording is disabled in settings, we skip it")
            self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Video recording is disabled in settings, we skip it", 'debug')
        
    def process_logfile(self, process, filename):
        # Save stdout/stderr of process
        # See solutions here : https://stackoverflow.com/questions/2804543/read-subprocess-stdout-line-by-line
        logfile = open(filename, 'w', encoding="utf-8")
        for line in io.TextIOWrapper(process.stdout, encoding="utf-8"):
            dateNow = self.getDateNow()
            message = dateNow["dateString"] + " : " + line.rstrip() + "\n"
            logfile.write(message)
            # Write in real time
            logfile.flush()
        
        logfile.close()

    def recordLive(self, live, newRecord):
        url = "https://www.youtube.com/watch?v=" + live['idVideo']
        basefile = self.settings['folder_recording'] + 'video_' + self.idchannel + '.' + live['idVideo']
        basefile_new_record = basefile + '.' + newRecord['filenumber']      
        tsfile = basefile_new_record + '.ts'
        mp4file = basefile_new_record + '.mp4'
        outputfile = ''
        record_logfile = self.settings['folder_recording'] + self.settings['record_video']['record_live_tool']  + '_' + self.idchannel + '.' + live['idVideo'] + '.' + newRecord['filenumber'] + '.txt'
        
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} Starting recording live with with {self.settings['record_video']['record_live_tool']} basefile={basefile_new_record}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Starting recording live with {self.settings['record_video']['record_live_tool']} basefile={basefile_new_record}", 'normal')
        
        if self.settings['record_video']['record_live_tool'] == "streamlink":
            # Streamlink produces .ts file for each attempt then we convert them in .mp4
            outputfile = tsfile
            cmd_record = [self.settings['record_video']['path_streamlink'] + 'streamlink', "-o", outputfile]
            if len(settings['record_video']['streamlink_options']) > 0:
                cmd_record.extend(self.settings['record_video']['streamlink_options'])
            cmd_record.extend(['--logfile', record_logfile, '--loglevel', 'debug', '--logformat', '[{asctime}][{threadName}][{name}][{levelname}] {message}'])
            cmd_record.extend([url, self.settings['record_video']['streamlink_stream']])
        elif self.settings['record_video']['record_live_tool'] == "yt-dlp":
            # yt-dlp with --merge-output-format mp4 produces .mp4 files. So no need to convert them to .mp4
            outputfile = mp4file
            cmd_record = [self.settings['record_video']['path_yt-dlp'] + 'yt-dlp', "-o", outputfile,
            '--ffmpeg-location', self.settings['record_video']['path_ffmpeg'] + 'ffmpeg', *self.settings['record_video']['yt-dlp_options']]
            
            if self.settings['cookies']:
                cmd_record.extend(['--cookies', self.settings['cookies']])
                
            # We use '--live-from-start' only if no file has been recorded yet
            mp4files = glob.glob(basefile + '.*')
            if len(mp4files) == 0:
                cmd_record.append('--live-from-start')
            
            cmd_record.append(url)

        print(f"id_live={live['id_live']} idVideo={live['idVideo']} {self.settings['record_video']['record_live_tool']} commandline : {cmd_record}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} {self.settings['record_video']['record_live_tool']} commandline : {cmd_record}", 'normal')
        try:  
            recordProcess = subprocess.Popen(cmd_record, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            # Record yt-dlp stderr and stdout to file
            if self.settings['record_video']['record_live_tool'] == "yt-dlp":
                record_yt_dlp_logfile_thread = threading.Thread(target=self.process_logfile, args=(recordProcess, record_logfile))
                record_yt_dlp_logfile_thread.start()
        except Exception as e:
            print(f"id_live={live['id_live']} idVideo={live['idVideo']} Error with launching {self.settings['record_video']['record_live_tool']} recording live {outputfile} : exception={e}")
            self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Error with launching {self.settings['record_video']['record_live_tool']} recording live {outputfile} : exception={e}")
            return

        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()

        # UPDATE record in records table with status_recording = 'recording' and pid process
        newRecord['recording_pid'] = recordProcess.pid
        newRecord['status_recording'] = 'recording'
        try:
            print("Update status status_recording = 'recording' and pid process with newRecord :" + str(newRecord))
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = """UPDATE records SET recording_pid = %(recording_pid)s, status_recording = %(status_recording)s WHERE id_record = %(id_record)s"""
            params = {"id_record": newRecord["id_record"], "recording_pid": newRecord['recording_pid'], "status_recording": newRecord['status_recording']}
            cursor.execute(update_record_query, params)
            connection.commit()
            cursor.close()
        except mysql.connector.Error as ex:
            print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' and pid process : {ex}")
            self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' and pid process : {ex}", 'normal')
            self.exitProgram()

        # UPDATE dateFirstStartRecord in lives table if not already existing
        if live["dateFirstStartRecord"] is None:
            try:
                connection = db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                update_live_query = """UPDATE lives SET dateFirstStartRecord = %(dateFirstStartRecord)s
                WHERE id_live = %(id_live)s"""
                params = {"id_live" : live["id_live"], "dateFirstStartRecord": newRecord["dateStart"]}
                cursor.execute(update_live_query, params)
                connection.commit()
                cursor.close()
            except mysql.connector.Error as ex:
                print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE dateFirstStartRecord in lives table : {ex}")
                self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE dateFirstStartRecord in lives table : {ex}", 'normal')
                self.exitProgram()

        # We wait for end of recording
        recordProcess.wait()
        
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} record of stream has ended with returncode={recordProcess.returncode} : {outputfile}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} record of stream has ended with returncode={recordProcess.returncode} : {outputfile}", 'normal')
        
        # Get duration of output file : goal is to detect diff in official stream duration, records in DB and duration of outputfile, and duration of merged mp4
        # To get only duration with no other info : ffprobe -v error -show_entries format=duration -sexagesimal -of default=noprint_wrappers=1:nokey=1 <file>
        # cf https://trac.ffmpeg.org/wiki/FFprobeTips#Formatcontainerduration
        durationOutputFile = None
        processGetInfoOutputFile = subprocess.Popen([self.settings['record_video']['path_ffmpeg'] + 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-sexagesimal', '-of',
        'default=noprint_wrappers=1:nokey=1', outputfile],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = processGetInfoOutputFile.communicate()
        durationOutputFile = str(stdout.strip())
        
        status_recording_duration = durationOutputFile
        if processGetInfoOutputFile.returncode != 0:
            status_recording_duration = str(stderr.strip())
            
        newRecord["status_recording_duration"] = status_recording_duration
        newRecord["status_recording_duration_ffprobe"] = processGetInfoOutputFile.returncode
        
        # UPDATE sql in live/records table with status_recording = "finished" + duration of outputfile + Try to get actualEndTime from YTB API V3
        newRecord["status_recording"] = "finished"
        newRecord["status_recording_record_live_tool"] = recordProcess.returncode
        # Set date of end of this recording. Warning this date is influenced by --stream-timeout when recording has started, not influenced if not started.
        dateNow = self.getDateNow()
        dateEnd = dateNow['dateDBString']
                
        newRecord["dateEnd"] = dateEnd
        live["dateLastEndRecord"] = dateEnd
        
        # UPDATE record with new statuses, duration of outputfile and dateEnd
        try:
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = """UPDATE records SET status_recording = %(status_recording)s, status_recording_record_live_tool = %(status_recording_record_live_tool)s,
            status_recording_duration = %(status_recording_duration)s, status_recording_duration_ffprobe = %(status_recording_duration_ffprobe)s,
            dateEnd = %(dateEnd)s WHERE id_record = %(id_record)s"""
            params = {"id_record": newRecord["id_record"], "status_recording": newRecord['status_recording'],
            "status_recording_record_live_tool": newRecord["status_recording_record_live_tool"], "status_recording_duration": newRecord['status_recording_duration'],
            "status_recording_duration_ffprobe": newRecord['status_recording_duration_ffprobe'], "dateEnd": newRecord["dateEnd"]}
            cursor.execute(update_record_query, params)
            connection.commit()
            cursor.close()
        except mysql.connector.Error as ex:
            print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' : {ex}")
            self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' : {ex}", 'normal')
            self.exitProgram()

        # UPDATE live in lives table with dateEnd_YTB and dateLastEndRecord
        # Get stream endTime from YTB API V3
        dateEnd_YTB = None
        if not dateEnd_YTB in live or live['dateEnd_YTB'] is None:
            videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['YoutubeAPIV3']['youtubeKey'] + "&id=" + live['idVideo'] + \
            "&part=snippet,contentDetails,statistics,liveStreamingDetails"
            print(videosInfosURL)
            try:
                response = requests.get(videosInfosURL)
                videosInfosResponse = response.text
                if response.status_code == 200:
                    video_json = json.loads(videosInfosResponse)       
                    item = video_json.get('items')[0]
                    actualEndTime = item.get('liveStreamingDetails').get('actualEndTime')
                    # Convert datetime iso 2025-12-06T17:30:42Z to date with tz
                    actualEndTime_object = dateutil.parser.isoparse(actualEndTime)
                    dateEnd_YTB = actualEndTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
            except Exception as e:
                # Not a problem if something's wrong in this request
                print(f"id_live={live['id_live']} idVideo={live['idVideo']} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}")
                self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}", 'normal')
            
        # HOW TO : https://stackoverflow.com/questions/11517106/how-to-update-mysql-with-python-where-fields-and-entries-are-from-a-dictionary
        params = {'dateLastEndRecord': live["dateLastEndRecord"]}
        if dateEnd_YTB is not None:
            params['dateEnd_YTB'] = dateEnd_YTB        
            
        try:
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
            cursor.execute(update_record_query, list(params.values()))
            connection.commit()
            cursor.close()
        except mysql.connector.Error as ex:
            print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE live with new end dates : {ex}")
            self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE live with new end dates : {ex}", 'normal')
            self.exitProgram()
        
        # For streamlink record, convert .ts file to .mp4
        if self.settings['record_video']['record_live_tool'] == "streamlink":
            # Conversion with ffmpeg : ffmpeg -i out.ts -c copy out.mp4 & delete out.ts
            if os.path.isfile(outputfile):
                convertProcess = subprocess.Popen([self.settings['record_video']['path_ffmpeg'] + 'ffmpeg', "-i", outputfile, "-c", "copy", mp4file],
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

                # UPDATE record in records table with status_convert = 'converting'   
                newRecord["status_convert"] = "converting"
                try:
                    connection = db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    update_record_query = """UPDATE records SET status_convert = %(status_convert)s WHERE id_record = %(id_record)s"""
                    params = {"id_record" : newRecord["id_record"], "status_convert" : newRecord['status_convert']}
                    cursor.execute(update_record_query, params)
                    connection.commit()
                    cursor.close()
                except mysql.connector.Error as ex:
                    print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'converting' : {ex}")
                    self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'converting' : {ex}", 'normal')
                    self.exitProgram()    
                
                # We wait for end of conversion
                convertProcess.wait()
                
                # UPDATE record in records table with status_convert = 'finished'
                newRecord["status_convert"] = "finished"
                newRecord["status_convert_ffmpeg"] = convertProcess.returncode
                dateNow = self.getDateNow()
                newRecord["date_status_convert"] = dateNow['dateDBString']
                try:
                    connection = db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    update_record_query = """UPDATE records SET status_convert = %(status_convert)s, status_convert_ffmpeg = %(status_convert_ffmpeg)s,
                    date_status_convert = %(date_status_convert)s WHERE id_record = %(id_record)s"""
                    params = {"id_record" : newRecord["id_record"], "status_convert" : newRecord['status_convert'],
                    "status_convert_ffmpeg": newRecord["status_convert_ffmpeg"], "date_status_convert": newRecord["date_status_convert"]}
                    cursor.execute(update_record_query, params)
                    connection.commit()
                    cursor.close()
                except mysql.connector.Error as ex:
                    print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'finished' : {ex}")
                    self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'finished' : {ex}", 'normal')
                    self.exitProgram()
                
                if convertProcess.returncode == 0 and os.path.isfile(mp4file) is True:
                    print(f"id_live={live['id_live']} idVideo={live['idVideo']} Conversion in mp4 is OK : {mp4file}")
                    self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Conversion in mp4 is OK : {mp4file}", 'normal')
                    os.remove(outputfile)

        # Close Mysql connection
        try:
            connection.close()
        except mysql.connector.Error as ex:
            pass

        print(f"id_live={live['id_live']} idVideo={live['idVideo']} Recording of live ended")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Recording of live ended", 'normal')

    def recordChat(self, live, newChat):       
        url = "https://www.youtube.com/watch?v=" + live['idVideo']
        chatfile = self.settings['folder_recording'] + "chat_" + self.idchannel + '.' + live['idVideo'] + '.' + newChat['filenumber'] + '.txt'
        chat_downloader_log_filename = self.settings['folder_recording'] + 'chat_downloader_' + self.idchannel + '.' + live['idVideo'] + '.' + newChat['filenumber'] + '.txt'
        
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} Starting recording chat chatfile={chatfile}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Starting recording chat chatfile={chatfile}", 'normal')        

        # Start chat recording with chat_downloader cli
        # chat_downloader command is : chat_downloader [OPTIONS] <URL>
        cmd_record = [self.settings['record_chat']['path_chat_downloader'] + 'chat_downloader',
        "-o", chatfile, "--logging", "error"]
        if self.settings['cookies']:
                cmd_record.extend(['--cookies', self.settings['cookies']])
        
        cmd_record.append(url)
        
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} chat_downloader commandline : {cmd_record}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} chat_downloader commandline : {cmd_record}", 'normal')
            
        try:
            recordProcess = subprocess.Popen(cmd_record, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            # Trace errors of chat_downloader by recording stdout (contains chat messages) and stderr (errors)
            chat_downloader_logfileThread = threading.Thread(target=self.process_logfile, args=(recordProcess, chat_downloader_log_filename))
            chat_downloader_logfileThread.start()
        except Exception as e:
            print(f"id_live={live['id_live']} idVideo={live['idVideo']} Error with launching chat_downloader recording chat {chatfile} : exception={e}")
            self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Error with launching chat_downloader recording chat {chatfile} : exception={e}", 'normal')
        
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()
        
        # UPDATE chat in chats table with status_chat = 'recording' and pid process
        newChat['chat_pid'] = recordProcess.pid
        newChat['status_chat'] = 'recording'
        try:
            print("Update status status_chat = 'recording' with newChat :" + str(newChat))
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_chat_query = """UPDATE chats SET status_chat = %(status_chat)s, chat_pid = %(chat_pid)s WHERE id_chat = %(id_chat)s"""
            params = {"id_chat": newChat["id_chat"], "status_chat": newChat['status_chat'], "chat_pid": newChat['chat_pid']}
            cursor.execute(update_chat_query, params)
            connection.commit()
            cursor.close()
        except mysql.connector.Error as ex:
            print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE chat in chats table with status_chat = 'recording' : {ex}")
            self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE chat in chats table with status_chat = 'recording' : {ex}", 'normal')
            self.exitProgram()        
        
        # UPDATE dateFirstStartChat in lives table if not already existing
        if live["dateFirstStartChat"] is None:
            try:
                connection = db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                update_live_query = """UPDATE lives SET dateFirstStartChat = %(dateFirstStartChat)s
                WHERE id_live = %(id_live)s"""
                params = {"id_live" : live["id_live"], "dateFirstStartChat": newChat["dateStart"]}
                cursor.execute(update_live_query, params)
                connection.commit()
                cursor.close()
            except mysql.connector.Error as ex:
                print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE dateFirstStartChat in lives table : {ex}")
                self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE dateFirstStartChat in lives table : {ex}", 'normal')
                self.exitProgram()

        # Using python chat_downloader module directly :
        #try:
        #    chat = ChatDownloader().get_chat(url)       # create a generator
        #    for message in chat:                        # iterate over messages
        #        print(chat.format(message))
        #        fchat.write(chat.format(message))
        #        fchat.write("\n")
        #        fchat.flush()
        #except Exception as ex:
        #    fchat.write(str(ex))
        #    fchat.write("\n")
        #fchat.close()

        # We wait for end of recording
        recordProcess.wait()
       
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} record of chat .txt has ended with returncode={recordProcess.returncode} : {chatfile}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} record of chat .txt has ended with returncode={recordProcess.returncode} : {chatfile}", 'normal')

        # UPDATE sql in live/chats table with status_recording = "finished" + dateEnd + Try to get actualEndTime from YTB API V3
        
        dateNow = self.getDateNow()        
        dateEnd = dateNow["dateDBString"]
        newChat["dateEnd"] = dateEnd
        live["dateLastEndChat"] = dateEnd
        
        # UPDATE chat in chats table withn new statuses and dateEnd
        newChat['status_chat'] = 'finished'
        newChat["status_chat_downloader"] = recordProcess.returncode
        try:
            print("Update status status_chat = 'finished' with newChat :" + str(newChat))
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_chat_query = """UPDATE chats SET status_chat = %(status_chat)s, status_chat_downloader = %(status_chat_downloader)s, dateEnd = %(dateEnd)s
            WHERE id_chat = %(id_chat)s"""
            params = {"id_chat": newChat["id_chat"], "status_chat": newChat['status_chat'], "status_chat_downloader": newChat["status_chat_downloader"],
                      "dateEnd": newChat["dateEnd"]}
            cursor.execute(update_chat_query, params)
            connection.commit()
            cursor.close()
        except mysql.connector.Error as ex:
            print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE chat in chats table with status_chat = 'finished' : {ex}")
            self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE chat in chats table with status_chat = 'finished' : {ex}", 'normal')
            self.exitProgram()

        # UPDATE live in lives table with dateEnd_YTB and dateLastEndChat
        # Get stream endTime from YTB API V3
        dateEnd_YTB = None
        if not dateEnd_YTB in live or live['dateEnd_YTB'] is None:
            videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['YoutubeAPIV3']['youtubeKey'] + "&id=" + live['idVideo'] + \
            "&part=snippet,contentDetails,statistics,liveStreamingDetails"
            print(videosInfosURL)
            try:
                response = requests.get(videosInfosURL)
                videosInfosResponse = response.text
                if response.status_code == 200:
                    video_json = json.loads(videosInfosResponse)       
                    item = video_json.get('items')[0]
                    actualEndTime = item.get('liveStreamingDetails').get('actualEndTime')
                    # Convert datetime iso 2025-12-06T17:30:42Z to date with tz
                    actualEndTime_object = dateutil.parser.isoparse(actualEndTime)
                    dateEnd_YTB = actualEndTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
            except Exception as e:
                # Not a problem if something's wrong in this request
                print(f"id_live={live['id_live']} idVideo={live['idVideo']} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}")
                self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}", 'normal')
            
        # HOW TO : https://stackoverflow.com/questions/11517106/how-to-update-mysql-with-python-where-fields-and-entries-are-from-a-dictionary
        params = {'dateLastEndChat': live["dateLastEndChat"]}
        if dateEnd_YTB is not None:
            params['dateEnd_YTB'] = dateEnd_YTB        
            
        try:
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
            cursor.execute(update_record_query, list(params.values()))
            connection.commit()
            cursor.close()
        except mysql.connector.Error as ex:
            print(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE live with new end dates : {ex}")
            self.writelog(f"[x] id_live={live['id_live']} idVideo={live['idVideo']} Mysql Error UPDATE live with new end dates : {ex}", 'normal')
            self.exitProgram()

        # Close Mysql connection
        try:
            connection.close()
        except mysql.connector.Error as ex:
            pass

        print(f"id_live={live['id_live']} idVideo={live['idVideo']} Recording of chat ended")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Recording of chat ended", 'normal')

    def getVideoInfos(self, url):
        infosVideo = {"ytInitialPlayerResponse": None, "videoDetails": None}
        try:
            if self.settings['cookies']:
                cookie_jar = MozillaCookieJar(self.settings['cookies'])
                cookie_jar.load(ignore_discard=True)
                session = requests.Session()
                session.cookies = cookie_jar
                response = session.get(url)
            else:
                # To avoid consent popup showing off when calling response = requests.get(url), we set a cookie to "Accept all" :
                jar = requests.cookies.RequestsCookieJar()
                jar.set('SOCS', 'CAI', domain='.youtube.com', secure=True) # CAI means "accept all"
                response = requests.get(url, cookies=jar)
            
            if response.status_code == 200:
                ytInitialPlayerResponse = re.findall('ytInitialPlayerResponse\\s*=\\s*({.+?})\\s*;', response.text)
                if len(ytInitialPlayerResponse) == 1:
                    data = json.loads(ytInitialPlayerResponse[0])
                    infosVideo["ytInitialPlayerResponse"] = data                    
                    
                    videoDetails = data.get('videoDetails')
                    playabilityStatus = data.get('playabilityStatus')
                    if videoDetails is not None:
                        video = {"videoId": videoDetails.get('videoId'), "title": videoDetails.get('title'),
                        "is_live": videoDetails.get("isLive"), "playabilityStatus": playabilityStatus}
                        infosVideo["videoDetails"] = video
                    else:
                        print(f"{url} ytInitialPlayerResponse : videoDetails not found, status={playabilityStatus.get('status')} reason={playabilityStatus.get('reason')}")
                        self.writelog(f"{url} ytInitialPlayerResponse : videoDetails not found, status={playabilityStatus.get('status')} reason={playabilityStatus.get('reason')}", 'debug')
                else:
                    print(f"{url} ytInitialPlayerResponse not found")
                    self.writelog(f"{url} ytInitialPlayerResponse not found", 'debug')
            else:
                print(f"[×] Response of url {url} isn't OK : {response.status_code} {response.text}")
                self.writelog(f"[×] Response of url {url} isn't OK : {response.status_code} {response.text}", 'normal')
        except Exception as e:
            print(f"[×] Error url {url} : {e}")
            self.writelog(f"[×] Error url {url} : {e}", 'normal')

        return infosVideo
        
    def searchLives(self, discovery_method):
        # discovery_method can has value 'live_url' (hit /live page) or 'streams_url' (hit /streams page)
        # 'live_url' can only capture last ongoing live, 'streams_url' can capture all running lives
        # 'live_url' will detect a new live immediately and 'streams_url' will take at least 30 sec
        # Caution : 2 streams can be running at the same time for the same channel, that's why we can't rely only on /live page
        # So to be sure to not miss a new live (it's possible with discovery_method = 'live_url' if several lives are started in a small time frame),
        # we use both methods.

        print(f"Search ongoing lives with discovery_method = {discovery_method}")
        self.writelog(f"Search ongoing lives with discovery_method = {discovery_method}", 'debug')
        
        # Detect running streams. 
        # Note : we don't record Premiere videos (streamlink can't do it at the moment, see yt-dlp that can record them).
        # To record Premiere videos, we need to grab only videos that are currently on air.
        # Code to add :
        # in elif discovery_method == 'streams_url':, add :
        # videostypes = ["streams", "videos"]
        # for videotype in videostypes :
        #   videos = scrapetube.get_channel(channel_id=self.idchannel, content_type=videotype, sort_by="newest")
        #       for video in videos:
        #           if video['is_live'] is True
        
        streams = []
        if discovery_method == 'live_url':
            # Hit /live and get videoId.
            url_channel_live = f"https://www.youtube.com/channel/{self.idchannel}/live"
            stream = self.getVideoInfos(url_channel_live)
            
            if stream['videoDetails'] is not None and stream['videoDetails']['is_live'] is True:
                url = "https://www.youtube.com/watch?v=" + str(stream['videoDetails']['videoId'])
                print(f"{url} is live !")
                self.writelog(f"{url} is live !", 'debug')
                
                #print(f"Streams info from webpage : {stream}")
                #self.writelog(f"Streams info from webpage : {stream}", 'debug')
                
                streams.append(stream['videoDetails'])            
        elif discovery_method == 'streams_url':
            # Warning : browsing /streams can sometimes display ended streams as still running
            # scrapetube method can be replaced by :
            # - call to Youtube API V3 /videos : too much consuming to have same detection delay as scrapetube
            # - use push notifications via PubSubHubbub. Then check every video and see if it concerns a running live. 
            streams_scrapetube = scrapetube.get_channel(channel_id=self.idchannel, content_type="streams", limit=30, sort_by="newest")
            for stream in streams_scrapetube:
                url = "https://www.youtube.com/watch?v=" + str(stream['videoId'])
                print(url)
                self.writelog(url, 'debug')

                # Check if live is streaming right now and not a republish
                if stream['is_live'] is True:
                    print(f"{url} is live !")
                    self.writelog(f"{url} is live !", 'debug')
                    streams.append(stream)
        else:
            print(f"[×] idVideo={stream['videoId']} discovery_method must be live_url or streams_url, provided value={discovery_method}")
            self.writelog(f"[×] idVideo={stream['videoId']} discovery_method must be live_url or streams_url, provided value={discovery_method}", 'normal')
            return

        print(f"With discovery_method = {discovery_method}, found {len(streams)} running streams right now for this channel")
        self.writelog(f"With discovery_method = {discovery_method}, found {len(streams)} running streams right now for this channel", 'debug')
               
        if len(streams) == 0:
            return
        
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()

        # Browsing running streams
        print(f"Now browsing running streams")
        self.writelog(f"Now browsing running streams", 'debug')
        for stream in streams:
            url = "https://www.youtube.com/watch?v=" + str(stream['videoId'])
            print(url)
            self.writelog(url, 'debug')

            live = None
            # Get live infos from lives table
            try:
                connection = db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                select_live_query = """SELECT * FROM lives WHERE idVideo=%(idVideo)s""" 
                params = {"idVideo" : stream['videoId']}
                cursor.execute(select_live_query, params)
                result = cursor.fetchall()
                if len(result) > 0:
                    # Live was recorded before
                    live = result[0]
                    print(f"id_live={live['id_live']} idVideo={live['idVideo']} Ongoing live has already been recorded before")
                    self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Ongoing live has already been recorded before", 'debug')
                    
                    # Check if Youtube API V3 has given us actualEndTime
                    if live['dateEnd_YTB'] is not None:
                        print(f"id_live={live['id_live']} idVideo={live['idVideo']} live has ended actualEndTime={live['dateEnd_YTB']}")
                        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} live has ended actualEndTime={live['dateEnd_YTB']}", 'debug')
                        continue
                else:
                    # Live has never been recorded before
                    print(f"idVideo={stream['videoId']} Ongoing live has never been recorded before")
                    self.writelog(f"idVideo={stream['videoId']} Ongoing live has never been recorded before", 'debug')
                cursor.close()                
            except mysql.connector.Error as ex:
                print(f"[×] idVideo={stream['videoId']} Mysql Error Get live infos from lives table : {ex}")
                self.writelog(f"[×] idVideo={stream['videoId']} Mysql Error Get live infos from lives table : {ex}", 'normal')
                self.exitProgram()

            # Insert live in lives table if needed
            if live is None:
                # We only get handle channel from idchannel here and not at every start of the program
                # because Youtube API V3 quota is limited (10000 hits/day) and one hit every 5 sec would be too consuming
                # Other solution : get handle channel with another method such as hitting youtube.com/channel/id_channel and parse var ytInitialData
                self.initChannel()
                
                # We only gather official start datetime and title from YTB API V3 once
                # With discovery_method = 'streams_url', title can be auto-translated by Google, so we get it from YTB DATA API V3
                # With discovery_method = 'live_url' : title normally would be the original one and it would be possible to get start time in
                # microformat->playerMicroformatRenderer->liveBroadcastDetails->startTimestamp. But I didn't implement it.
                # So we hit YTB API V3 /videos in both cases.
                dateStart_YTB = None
                videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['YoutubeAPIV3']['youtubeKey'] + "&id=" + stream['videoId'] + \
                "&part=snippet,contentDetails,statistics,liveStreamingDetails"
                print(videosInfosURL)
                try:
                    response = requests.get(videosInfosURL)
                    videosInfosResponse = response.text
                    if response.status_code == 200:
                        video_json = json.loads(videosInfosResponse)       
                        item = video_json.get('items')[0]
                        snippet = item.get('snippet')
                        title = snippet.get('title')
                        stream['title'] = title
                        
                        actualStartTime = item.get('liveStreamingDetails').get('actualStartTime')
                        # Convert datetime iso 2025-12-06T17:30:42Z to date with tz
                        actualStartTime_object = dateutil.parser.isoparse(actualStartTime)
                        dateStart_YTB = actualStartTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
                except Exception as e:
                    # Not a problem if something's wrong in this request
                    print(f"idVideo={stream['videoId']} Error getting actualStartTime from YTB API V3 videosInfosURL {videosInfosURL} : {e}")
                    self.writelog(f"idVideo={stream['videoId']} Error getting actualStartTime from YTB API V3 videosInfosURL {videosInfosURL} : {e}")
                
                try:
                    connection = db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    insert_live_query = """INSERT INTO lives
                    (idchannel, handlechannel, idVideo, title, dateStart_YTB)
                    VALUES (%(idchannel)s, %(handlechannel)s, %(idVideo)s, %(title)s, %(dateStart_YTB)s)"""
                    params = {"idchannel" : self.idchannel, "handlechannel": self.handlechannel, "idVideo" : stream['videoId'],
                    "title": stream['title'], "dateStart_YTB": dateStart_YTB}
                    cursor.execute(insert_live_query, params)
                    connection.commit()

                    new_id_live = cursor.lastrowid
                    cursor.close()
                except mysql.connector.Error as ex:
                    # Handles duplicate record when program tries to insert same live at the same time from two different threads                    
                    if ex.errno == mysql.connector.errorcode.ER_DUP_ENTRY:
                        print(f"idVideo={stream['videoId']} Trying to insert duplicate key, exception : {ex}")
                        self.writelog(f"idVideo={stream['videoId']} Trying to insert duplicate key, exception : {ex}", 'normal')
                        return
                    else:
                        print(f"[x] idVideo={stream['videoId']} Mysql Error Insert live in lives table if needed : {ex}")
                        self.writelog(f"[x] idVideo={stream['videoId']} Mysql Error Insert live in lives table if needed : {ex}", 'normal')
                        self.exitProgram()
                    
                # Get created live from lives table
                try:
                    connection = db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    select_newlive_query = """SELECT * FROM lives WHERE id_live=%(new_id_live)s"""
                    params = {"new_id_live": new_id_live}
                    cursor.execute(select_newlive_query, params)
                    live = cursor.fetchone()
                    cursor.close()
                except mysql.connector.Error as ex:
                    print(f"[x] idVideo={stream['videoId']} Mysql Error get new live in lives table : {ex}")
                    self.writelog(f"[x] idVideo={stream['videoId']} Mysql Error get new live in lives table : {ex}", 'normal')
                    self.exitProgram()
                
                # Notifications of live started
                if self.settings['notifications']['mail'] is True:
                    print(f"Notification by mail needs to be sent")
                    self.writelog(f"Notification by mail needs to be sent", 'normal')
                        
                    # Log in to server using secure context and send email
                    # See : https://techoverflow.net/2021/03/23/how-to-send-email-with-file-attachment-via-smtp-in-python/
                    subject = f"Notification new live started for idchannel={self.idchannel} handlechannel={self.handlechannel}"
                    body = f"A new live has been started for :<br> idchannel={self.idchannel} urlchannel=<a href=\"{self.urlchannel}\">{self.urlchannel}</a> : <a href=\"{url}\">{url}</a><br>"
                    body += f"Title : {live['title']}"
                    sender_email = self.settings['mail']['username']
                    receiver_email = self.settings['mail']['to'] 

                    # Create message and set text content
                    mail = EmailMessage()
                    mail["From"] = sender_email
                    mail["To"] = receiver_email
                    mail["Subject"] = subject
                    # Set text content
                    mail.set_content(body, subtype='html')

                    try:
                        context = ssl.create_default_context()
                        with smtplib.SMTP_SSL(self.settings['mail']['server'], self.settings['mail']['port'], context=context) as server:
                            server.login(self.settings['mail']['username'], self.settings['mail']['password'])
                            mailsend = server.send_message(mail)
                            print(f"Notification by email for new live started, result={mailsend}")
                            self.writelog(f"Notification by email for new live started, result={mailsend}", "normal")
                    except Exception as e:
                        print(f"Error sending email for new live started : {e}")
                        self.writelog(f"Error sending email for new live started : {e}", 'normal')
                                        
            # Video and chat recording launched separatively at the same time in a thread
            recordVideoInitThread = threading.Thread(target=self.recordLiveInit, args=[live])
            recordVideoInitThread.start()
            recordChatInitThread = threading.Thread(target=self.recordChatInit, args=[live])
            recordChatInitThread.start()

            # Wait for threads to end
            recordVideoInitThread.join()
            recordChatInitThread.join()

        print("Search for livestreams done")
        self.writelog("Search for livestreams done", 'debug')

    def loopSearchLives(self, discovery_method, timestamp_first_start_script):
        index = 0
        while True:
            # Check if there's enough remaining time to launch searchLives()
            dateNow = self.getDateNow()
            second_of_now = dateNow["object"].second
            if second_of_now <= 60 - self.settings['searchlives_wait_before_retry'] - math.floor(self.settings['searchlives_wait_before_retry']) / 2 - self.settings['searchlives_seconds_security']:                
                if index > 0:
                    time.sleep(self.settings['searchlives_wait_before_retry'])

                # We launch searchLives
                self.searchLives(discovery_method)
            else:
                # Not enough time to launch a new searchLives(), we exit
                break
            
            index = index + 1

    # *************** Main program ***************
    def main(self):
        print("Starting program")
        self.writelog("Starting program")
        # self.initDatabase()
        
        self.writelog("Channel " + self.urlchannel + " id : " + self.idchannel)
        
        timestamp_first_start_script = time.perf_counter()

        # Make sure video recording or chat recording is enabled
        if not (self.settings['record_video']['enabled'] is False and self.settings['record_chat']['enabled'] is False):
            if len(self.settings['discovery_methods']) == 0:
                self.settings['discovery_methods'] = ["streams_url"]

            # Search lives with discovery_method == 'live_url' then wait then search lives with discovery_method == 'streams_url' OR
            # search lives with discovery_method == 'streams_url'
            loopSearchLives_threads = []
            for index, discover_meth in enumerate(self.settings['discovery_methods']):
                loopSearchLives_threads.append(threading.Thread(target=self.loopSearchLives, args=(self.settings['discovery_methods'][index], timestamp_first_start_script)))
                loopSearchLives_threads[index].start()
                if index < len(self.settings['discovery_methods']) - 1:
                    time.sleep(self.settings['searchlives_wait_before_retry'] / len(self.settings['discovery_methods']))
                            
            for loopSearchLives_t in loopSearchLives_threads:
                loopSearchLives_t.join()
            
            # Wait for recording threads to finish
            for recordThread in self.recordThreadList:
                recordThread.join()

            for chatThread in self.chatThreadList:
                chatThread.join()                
        else:
            print(f"Video recording and chat recording are disabled in settings, we exit program")
            self.writelog(f"Video recording and chat recording are disabled in settings, we exit program", 'normal')
                
        print("Execution was OK")
        self.writelog("Execution was OK")
        print("Ending program")
        self.writelog("Ending program")
        self.clean()

if __name__ == "__main__":
    urlchannel = "https://www.youtube.com/@your_channel"
    idchannel = '' # Found channel id on Youtube by clicking "Share channel" then "Copy channel ID"
    settings = {
        # Youtube
        'YoutubeAPIV3': { # Youtube Data API V3 can be used to get handle from idchannel, starttime / endtime of streams, but it's possible to not use it
            'enabled': True, # attribute not used, Youtube Data API V3 is always used right now
            'youtubeKey': '' # YouTube API Key from Google Cloud, see https://helano.github.io/help.html
        },
        'cookies' : os.path.dirname(os.path.realpath(__file__)) + '/cookiesYT.txt', # path of cookie file, or '' or None to disable
        # Format
        'tz': 'Europe/Paris', # Set tz also in chat_downloader/formatting/custom_formats.json to apply tz to chat messages date
        'dateFormats': {'dateString': '%d/%m/%Y %H:%M:%S', 'dateDBString': '%Y-%m-%d %H:%M:%S', 'dateFileString': '%d%m%Y%H%M%S'},
        # Recording
        'folder_recording': os.path.dirname(os.path.realpath(__file__)) + '/files/', # Add / at the end
        'searchlives_wait_before_retry': 5,
        'searchlives_seconds_security': 0,
        'discovery_methods' : ['streams_url'], # live_url or/and streams_url // calling live_url too often will lead to LOGIN_REQUIRED messages
        'record_video': {
            'enabled': True,
            'record_live_tool' : 'yt-dlp', # streamlink or yt-dlp
            'path_streamlink': '', # Add / at the end
            'path_yt-dlp' : '', # Add / at the end
            'path_ffmpeg': os.path.dirname(os.path.realpath(__file__)) + '/', # Add / at the end, same directory for ffmpeg and ffprobe
            'streamlink_options': ['--stream-sorting-excludes', '>480p,>480p30', '--stream-segmented-queue-deadline', '0', '--stream-timeout', '120'], # 120s of timeout is good
            'streamlink_stream': 'best,best-unfiltered', # With these streamlink_options and streamlink_stream settings : you will get 480p or just below if 480p is not found
            'yt-dlp_options': ['-S', 'res:480', '--remote-components', 'ejs:github', '--js-runtimes', 'deno:', # Put path of deno folder
            '--retries', '40', '--fragment-retries', '40', '--socket-timeout', '300',
            '-v', '-k',
            '--no-part', '--merge-output-format', 'mp4',
            '--extractor-args', 'youtube:player-client=default,web_embedded,mweb' #See https://github.com/yt-dlp/yt-dlp/issues/16862#issuecomment-4642619967
            ]
        },
        'record_chat': {
            'enabled': True,
            'path_chat_downloader': '' # Add / at the end
            },
        # Mail
        'mail': {
            "server": '',
            "port": ,
            "username": "",
            "password": "",
            "to": ''
        },
        'notifications': {
            'mail': False
        },
        # MySQL connection
        'params_database': {'mysql_host': '', 'mysql_database': '',
        'mysql_user': '',
        'mysql_pwd': ''},
        # Debug
        'level_debug_selected': 'debug' # 'debug' or 'normal' for minimal log
    }
    
    program = Program(idchannel, urlchannel, settings)
    program.main()
