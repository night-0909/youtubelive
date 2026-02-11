# -*- encoding: utf-8 -*-

from chat_downloader import ChatDownloader
import scrapetube
import requests, json, sys, os, time, psutil
from datetime import datetime, timedelta
import dateutil.parser
import streamlink
import threading
import subprocess
from zoneinfo import ZoneInfo
from mysql.connector import connect, Error

# Database class
class Database():
    def __init__(self, params_database):
        self.params_database = params_database
        self.connection = None
        self.connect()

    def connect(self):
        self.connection = connect(
                host=self.params_database['mysql_host'],
                user=self.params_database['mysql_user'],
                password=self.params_database['mysql_pwd'],
                database=self.params_database['mysql_database'],
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
        self.initStreamTimeout()
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

    def initStreamTimeout(self):
        # Get value next to --stream-timeout in streamlink_options settings
        self.stream_timeout = 0
        if "--stream-timeout" in self.settings['streamlink_options']:
            try:
                self.stream_timeout = int(self.settings['streamlink_options'][self.settings['streamlink_options'].index("--stream-timeout") + 1])
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
        channelInfosURL = "https://www.googleapis.com/youtube/v3/channels?key=" + self.settings['youtubeKey'] + "&id=" + self.idchannel + "&part=snippet"
        print(channelInfosURL)
        try:
            response = requests.get(channelInfosURL)
            if response.status_code == 200:
                channelInfosResponse = response.text
                channel_json = json.loads(channelInfosResponse)       
                
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

    def recordLive(self, live, newRecord):
        url = "https://www.youtube.com/watch?v=" + live['idVideo']
        tsfile = self.settings['folder_recording'] + 'video_' + self.idchannel + '.' + live['idVideo'] + '.' + newRecord['filenumber'] + '.ts'
        mp4file = self.settings['folder_recording'] + 'video_' + self.idchannel + '.' + live['idVideo'] + '.' + newRecord['filenumber'] + '.mp4'
        streamlinklogfile = self.settings['folder_recording'] + 'streamlink_' + self.idchannel + '.' + live['idVideo'] + '.' + newRecord['filenumber'] + '.txt'
        
        print(f"idVideo={live['idVideo']} Starting recording live " + tsfile)
        self.writelog(f"idVideo={live['idVideo']} Starting recording live " + tsfile, 'normal')
        
        # streamlink command args is : streamlink [OPTIONS] <URL> [STREAM] so here you can use *streamlink_options for [OPTIONS] and streamlink_stream for [STREAM]
        # To prevent early recording stoppages happening with streamlink (default 6 seconds), we exit after 120 seconds of retries with this setting :
        # --stream-segmented-queue-deadline=0 and --stream-timeout=120
        # This setup will result in an exit of streamlink with error code = 1 and an error message "error: Error when reading from stream: Read timeout, exiting",
        # at the end of the stream. If you prefer the default behavior of Streamlink (early exit after 6 seconds), remove "--stream-segmented-queue-deadline", "0", "--stream-timeout", "120"
        recordProcess = subprocess.Popen([self.settings['path_streamlink'] + 'streamlink', "-o", tsfile, *self.settings['streamlink_options'],
        '--logfile', streamlinklogfile, '--loglevel', 'debug', '--logformat', '[{asctime}][{threadName}][{name}][{levelname}] {message}',
        url, self.settings['streamlink_stream']],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

        # UPDATE record in records table with status_recording = 'recording' and pid process
        newRecord['recording_pid'] = recordProcess.pid
        newRecord['status_recording'] = 'recording'
        try:
            print("Update status status_recording = 'recording' and pid process with newRecord :" + str(newRecord))
            connection = self.db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = """UPDATE records SET recording_pid = %(recording_pid)s, status_recording = %(status_recording)s WHERE id_record = %(id_record)s"""
            params = {"id_record": newRecord["id_record"], "recording_pid": newRecord['recording_pid'], "status_recording": newRecord['status_recording']}
            cursor.execute(update_record_query, params)
            connection.commit()
            cursor.close()
        except Error as ex:
            print(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' and pid process : {ex}")
            self.writelog(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' and pid process : {ex}", 'normal')
            self.exitProgram()

        # We wait for end of recording
        recordProcess.wait()
        
        print(f"idVideo={live['idVideo']} record of stream .ts has ended with returncode=" + str(recordProcess.returncode) + " : " + tsfile)
        self.writelog(f"idVideo={live['idVideo']} record of stream .ts has ended with returncode=" + str(recordProcess.returncode) + " : " + tsfile, 'normal')
        
        # Get duration of .ts file : goal is to detect diff in official stream duration, records in DB and duration of .ts file, and duration of merged mp4
        # To get only duration with no other info : ffprobe -v error -show_entries format=duration -sexagesimal -of default=noprint_wrappers=1:nokey=1 <file>
        # cf https://trac.ffmpeg.org/wiki/FFprobeTips#Formatcontainerduration
        durationTS = None
        processGetInfoTS = subprocess.Popen([self.settings['path_ffmpeg'] + 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-sexagesimal', '-of',
        'default=noprint_wrappers=1:nokey=1', tsfile],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = processGetInfoTS.communicate()
        durationTS = str(stdout.strip())
        
        status_recording_duration = durationTS
        if processGetInfoTS.returncode != 0:
            status_recording_duration = str(stderr.strip())
            
        newRecord["status_recording_duration"] = status_recording_duration
        newRecord["status_recording_duration_ffprobe"] = processGetInfoTS.returncode
        
        # UPDATE sql in live/records table with status_recording = "finished" + duration of .ts file + Try to get actualEndTime from YTB API V3
        newRecord["status_recording"] = "finished"
        newRecord["status_recording_streamlink"] = recordProcess.returncode
        # Set date of end of this recording. Warning this date is influenced by --stream-timeout, so I substract --stream-timeout to dateNow
        dateNow = self.getDateNow()
        dateNow_object = dateNow['object']
        dateEnd_object = dateNow_object - timedelta(seconds=self.stream_timeout)
        dateEnd = dateEnd_object.strftime(self.settings['dateFormats']['dateDBString'])
                
        newRecord["dateEnd"] = dateEnd
        live["dateLastEnd"] = dateEnd
        
        # Get stream endTime from YTB API V3
        dateEnd_YTB = None
        if not dateEnd_YTB in live or live['dateEnd_YTB'] is None:
            videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['youtubeKey'] + "&id=" + live['idVideo'] + \
            "&part=snippet,contentDetails,statistics,liveStreamingDetails"
            print(videosInfosURL)
            try:
                response = requests.get(videosInfosURL)
                if response.status_code == 200:
                    videosInfosResponse = response.text
                    video_json = json.loads(videosInfosResponse)       
                    item = video_json.get('items')[0]
                    actualEndTime = item.get('liveStreamingDetails').get('actualEndTime')
                    # Convert datetime iso 2025-12-06T17:30:42Z to date with tz
                    actualEndTime_object = dateutil.parser.isoparse(actualEndTime)
                    dateEnd_YTB = actualEndTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
            except Exception as e:
                # Not a problem if something's wrong in this request
                print(f"idVideo={live['idVideo']} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}")
                self.writelog(f"idVideo={live['idVideo']} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}", 'normal')
            
        # HOW TO : https://stackoverflow.com/questions/11517106/how-to-update-mysql-with-python-where-fields-and-entries-are-from-a-dictionary
        params = {'dateLastEnd': live["dateLastEnd"]}
        if dateEnd_YTB is not None:
            params['dateEnd_YTB'] = dateEnd_YTB        
            
        try:
            connection = self.db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
            cursor.execute(update_record_query, list(params.values()))
            connection.commit()
            cursor.close()
        except Error as ex:
            print(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE live with new end dates : {ex}")
            self.writelog(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE live with new end dates : {ex}", 'normal')
            self.exitProgram()

        # UPDATE record with new status, duration of .ts file and dates
        try:
            connection = self.db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_record_query = """UPDATE records SET status_recording = %(status_recording)s, status_recording_streamlink = %(status_recording_streamlink)s,
            status_recording_duration = %(status_recording_duration)s, status_recording_duration_ffprobe = %(status_recording_duration_ffprobe)s,
            dateEnd = %(dateEnd)s WHERE id_record = %(id_record)s"""
            params = {"id_record": newRecord["id_record"], "status_recording": newRecord['status_recording'],
            "status_recording_streamlink": newRecord["status_recording_streamlink"], "status_recording_duration": newRecord['status_recording_duration'],
            "status_recording_duration_ffprobe": newRecord['status_recording_duration_ffprobe'], "dateEnd": newRecord["dateEnd"]}
            cursor.execute(update_record_query, params)
            connection.commit()
            cursor.close()
        except Error as ex:
            print(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' : {ex}")
            self.writelog(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_recording = 'recording' : {ex}", 'normal')
            self.exitProgram()
        
        # Convertion with ffmpeg : ffmpeg -i out.ts -c copy out.mp4 & delete out.ts
        if os.path.isfile(tsfile):
            convertProcess = subprocess.Popen([self.settings['path_ffmpeg'] + 'ffmpeg', "-i", tsfile, "-c", "copy", mp4file],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

            # UPDATE record in records table with status_convert = 'converting'   
            newRecord["status_convert"] = "converting"
            try:
                connection = self.db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                update_record_query = """UPDATE records SET status_convert = %(status_convert)s WHERE id_record = %(id_record)s"""
                params = {"id_record" : newRecord["id_record"], "status_convert" : newRecord['status_convert']}
                cursor.execute(update_record_query, params)
                connection.commit()
                cursor.close()
            except Error as ex:
                print(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'converting' : {ex}")
                self.writelog(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'converting' : {ex}", 'normal')
                self.exitProgram()    
            
            # We wait for end of convertion
            convertProcess.wait()
            
            # UPDATE record in records table with status_convert = 'finished'
            newRecord["status_convert"] = "finished"
            newRecord["status_convert_ffmpeg"] = convertProcess.returncode
            dateNow = self.getDateNow()
            newRecord["date_status_convert"] = dateNow['dateDBString']
            try:
                connection = self.db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                update_record_query = """UPDATE records SET status_convert = %(status_convert)s, status_convert_ffmpeg = %(status_convert_ffmpeg)s,
                date_status_convert = %(date_status_convert)s WHERE id_record = %(id_record)s"""
                params = {"id_record" : newRecord["id_record"], "status_convert" : newRecord['status_convert'],
                "status_convert_ffmpeg": newRecord["status_convert_ffmpeg"], "date_status_convert": newRecord["date_status_convert"]}
                cursor.execute(update_record_query, params)
                connection.commit()
                cursor.close()
            except Error as ex:
                print(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'finished' : {ex}")
                self.writelog(f"[x] idVideo={live['idVideo']} Mysql Error UPDATE record in records table with status_convert = 'finished' : {ex}", 'normal')
                self.exitProgram()
            
            if convertProcess.returncode == 0 and os.path.isfile(mp4file) is True:
                print(f"idVideo={live['idVideo']} Convertion in mp4 is OK : {mp4file}")
                self.writelog(f"idVideo={live['idVideo']} Convertion in mp4 is OK : {mp4file}", 'normal')
                os.remove(tsfile)

        print(f"idVideo={live['idVideo']} Recording of live ended")
        self.writelog(f"idVideo={live['idVideo']} Recording of live ended", 'normal')

    def saveChat(self, live, newRecord):
        url = "https://www.youtube.com/watch?v=" + live['idVideo']
        print(f"idVideo={live['idVideo']} Starting recording chat")
        self.writelog(f"idVideo={live['idVideo']} Starting recording chat", 'normal')
        
        filechat = self.settings['folder_recording'] + "chat_" + self.idchannel + '.' + live['idVideo'] + '.' + newRecord['filenumber'] + '.txt'
        fchat = open(filechat, "w", encoding="utf-8")
        fchat.write("Chaine " + self.urlchannel + " id : " + self.idchannel + " Vidéo : https://www.youtube.com/watch?v=" + live['idVideo'])
        fchat.write("\n\n")
        fchat.flush()

        try:
            chat = ChatDownloader().get_chat(url)       # create a generator
            for message in chat:                        # iterate over messages
                print(chat.format(message))
                fchat.write(chat.format(message))
                fchat.write("\n")
                fchat.flush()
        except Exception as ex:
            fchat.write(str(ex))
            fchat.write("\n")

        fchat.close()
        
        print(f"idVideo={live['idVideo']} Recording of chat ended")
        self.writelog(f"idVideo={live['idVideo']} Recording of chat ended", 'normal')

    def searchLives(self):   
        print("Search ongoing lives")
        self.writelog("Search ongoing lives", 'debug')
        
        streams = scrapetube.get_channel(channel_id=self.idchannel, content_type="streams", limit=30, sort_by="newest")

        for stream in streams:
            streamRecord = None
            url = "https://www.youtube.com/watch?v=" + str(stream['videoId'])
            print(url)
            self.writelog(url, 'debug')

            # Check is live is streaming right now and not a republish // can be replaced by call to Youtube API V3 /videos
            # Caution : 2 streams can be running at the same time for the same channel
            if 'runs' in stream['thumbnailOverlays'][0]['thumbnailOverlayTimeStatusRenderer']['text']:
                print(f"{url} is live !")
                self.writelog(f"{url} is live !", 'debug')

                dateNow = self.getDateNow()
                actualfilenumber = None
                newfilenumber = None
                lasttsfile = None
                live = None
                lastRecord = None
                
                # Get live infos from lives table
                try:
                    connection = self.db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    select_live_query = """SELECT * FROM lives WHERE idVideo=%(idVideo)s"""
                    params = {"idVideo" : stream['videoId']}
                    cursor.execute(select_live_query, params)
                    result = cursor.fetchall()
                    if len(result) > 0:
                        # Live was recorded before
                        print(f"idVideo={stream['videoId']} Ongoing live has already been recorded before")
                        self.writelog(f"idVideo={stream['videoId']} Ongoing live has already been recorded before", 'debug')
                        live = result[0]
                    else:
                        # Live has never been recorded before
                        print(f"idVideo={stream['videoId']} Ongoing live has never been recorded before")
                        self.writelog(f"idVideo={stream['videoId']} Ongoing live has never been recorded before", 'debug')
                    cursor.close()                
                except Error as ex:
                    print(f"[×] idVideo={stream['videoId']} Mysql Error Get live infos from lives table : {ex}")
                    self.writelog(f"[×] idVideo={stream['videoId']} Mysql Error Get live infos from lives table : {ex}", 'normal')
                    self.exitProgram()
                
                # Get last record of live from records table
                try:
                    connection = self.db.getConnection()
                    cursor = connection.cursor(prepared=True, dictionary=True)
                    select_lastecord_query = """SELECT * FROM records, lives
                    WHERE lives.id_live = records.id_live AND lives.idVideo=%(idVideo)s
                    ORDER BY id_record DESC LIMIT 1"""
                    params = {"idVideo": stream['videoId']}
                    cursor.execute(select_lastecord_query, params)
                    result = cursor.fetchall()
                    if len(result) > 0:
                        # Has been recorded at least once
                        lastRecord = result[0]
                        print(lastRecord)
                        print(f"idVideo={stream['videoId']} Last id_record=" + str(lastRecord['id_record']) + " with status_recording=" + str(lastRecord['status_recording']))
                        self.writelog(f"idVideo={stream['videoId']} Last id_record=" + str(lastRecord['id_record']) + " with status_recording=" + str(lastRecord['status_recording']), 'debug')
                        
                        actualfilenumber = lastRecord['filenumber']
                        lasttsfile = self.settings['folder_recording'] + 'video_' + self.idchannel + '.' + stream['videoId'] + '.' + actualfilenumber + '.ts'
                    cursor.close()
                except Error as ex:
                    print(f"[×] idVideo={stream['videoId']} Mysql Error Get last record of live from records table : {ex}")
                    self.writelog(f"[×] idVideo={stream['videoId']} Mysql Error Get last record of live from records table : {ex}", 'normal')
                    self.exitProgram()
               
                # Check if recording_pid stored in DB is still running and its commandline matchs url of stream (in case of same pid is reused by OS for another thing)
                procStreamlinkExists = False
                if lastRecord is not None:
                    if lastRecord['recording_pid'] is not None and psutil.pid_exists(lastRecord['recording_pid']) is True:
                        try:
                            proc = psutil.Process(lastRecord['recording_pid'])
                            if url in proc.cmdline():
                                procStreamlinkExists = True
                        except Exception as e:
                            print(f"[×] idVideo={stream['videoId']} Impossible to get streamlink process informations : {e}")
                            self.writelog(f"[×] idVideo={stream['videoId']} Impossible to get streamlink process informations : {e}", 'normal')
                            # We continue normally
                
                if procStreamlinkExists is False:
                    print(f"idVideo={stream['videoId']} We record a new file")
                    self.writelog(f"idVideo={stream['videoId']} We record a new file", 'debug')

                    # Insert live in lives table if needed
                    if live is None:
                        # We only get handle channel from idchannel here and not at every start of the program.
                        # Because Youtube API V3 quota is limited (10000 hits/day) and one hit every 5 sec would be too consuming
                        # Other solution : get handle channel with another method such as hitting youtube.com/channel/id_channel and parse var ytInitialData
                        self.initChannel()
                        
                        # We only gather official start datetime from YTB API V3 once
                        dateStart_YTB = None
                        videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['youtubeKey'] + "&id=" + stream['videoId'] + \
                        "&part=snippet,contentDetails,statistics,liveStreamingDetails"
                        print(videosInfosURL)
                        try:
                            response = requests.get(videosInfosURL)
                            if response.status_code == 200:
                                videosInfosResponse = response.text
                                video_json = json.loads(videosInfosResponse)       
                                item = video_json.get('items')[0]
                                actualStartTime = item.get('liveStreamingDetails').get('actualStartTime')
                                # Convert datetime iso 2025-12-06T17:30:42Z to date with tz
                                actualStartTime_object = dateutil.parser.isoparse(actualStartTime)
                                dateStart_YTB = actualStartTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
                        except Exception as e:
                            # Not a problem if something's wrong in this request
                            print(f"idVideo={stream['videoId']} Error getting actualStartTime from YTB API V3 videosInfosURL {videosInfosURL} : {e}")
                            self.writelog(f"idVideo={stream['videoId']} Error getting actualStartTime from YTB API V3 videosInfosURL {videosInfosURL} : {e}")
                        
                        try:
                            connection = self.db.getConnection()
                            cursor = connection.cursor(prepared=True, dictionary=True)
                            insert_live_query = """INSERT INTO lives
                            (idchannel, handlechannel, idVideo, dateFirstStart, dateStart_YTB)
                            VALUES (%(idchannel)s, %(handlechannel)s, %(idVideo)s, %(dateFirstStart)s, %(dateStart_YTB)s)"""
                            params = {"idchannel" : self.idchannel, "handlechannel": self.handlechannel, "idVideo" : stream['videoId'],
                            "dateFirstStart" : dateNow['dateDBString'], "dateStart_YTB": dateStart_YTB}
                            cursor.execute(insert_live_query, params)
                            connection.commit()

                            live = params
                            live["id_live"] = cursor.lastrowid
                            cursor.close()
                        except Error as ex:
                            print(f"[x] idVideo={stream['videoId']} Mysql Error Insert live in lives table if needed : {ex}")
                            self.writelog(f"[x] idVideo={stream['videoId']} Mysql Error Insert live in lives table if needed : {ex}", 'normal')
                            self.exitProgram()

                    if lastRecord is None:
                        # No previous record
                        newfilenumber = '001'
                    else:
                        # Set filenumber + 1
                        newfilenumber = int(lastRecord['filenumber']) + 1
                        newfilenumber = str(newfilenumber).rjust(3, '0')
                    
                    # Insert new record in records table
                    try:
                        connection = self.db.getConnection()
                        cursor = connection.cursor(prepared=True, dictionary=True)
                        insert_record_query = """INSERT INTO records
                        (id_live, filenumber, dateStart, title) VALUES (%(id_live)s, %(filenumber)s, %(dateStart)s, %(title)s)"""
                        params = {"id_live" : live["id_live"], "filenumber" : newfilenumber, "dateStart" : dateNow['dateDBString'],
                        "title": stream['title']['runs'][0]['text']}
                        cursor.execute(insert_record_query, params)
                        connection.commit()
                        
                        # Set newRecord that will serve in record and chat function
                        newRecord = params                    
                        newRecord["id_record"] = cursor.lastrowid
                        cursor.close()
                    except Error as ex:
                        print(f"[x] idVideo={stream['videoId']} Mysql Error Insert new record in records table : {ex}")
                        self.writelog(f"[x] idVideo={stream['videoId']} Mysql Error Insert new record in records table : {ex}", 'normal')
                        self.exitProgram()    

                    # Start downloading stream and chat in a separate thread
                    recordThread = threading.Thread(target=self.recordLive, args=(live, newRecord))
                    self.recordThreadList.append(recordThread)
                    recordThread.start()

                    chatThread = threading.Thread(target=self.saveChat, args=(live, newRecord))
                    self.chatThreadList.append(chatThread)
                    chatThread.start()                
                else:
                    print(f"idVideo={stream['videoId']} We don't do anything as a record is currently ongoing, record=" + str(lastRecord))
                    self.writelog(f"idVideo={stream['videoId']} We don't do anything as a record is currently ongoing, record=" + str(lastRecord), 'debug')
            else:
                print(f"idVideo={stream['videoId']} Stream is not running")
                self.writelog(f"idVideo={stream['videoId']} Stream is not running", 'debug')

        print("Search for livestreams done")
        self.writelog("Search for livestreams done", 'debug')

    # *************** Main program ***************
    def main(self):
        print("Starting program")
        self.writelog("Starting program")
        self.initDatabase()
        
        self.writelog("Chaine " + self.urlchannel + " id : " + self.idchannel)
        
        timestamp_start_script = time.perf_counter()
        timestamp_first_start_script = timestamp_start_script

        # ********* First searchLives() **********
        self.searchLives()
        timestamp_end_script = time.perf_counter()
            
        # TRY maximum searchLives() in one minute : 5 seconds pause after each try is working.
        # Didn't test if issue happens if self.settings['wait_before_retry'] is too low (eg. 3 or less)
        number_runs = int(60 // self.settings['wait_before_retry'])

        # ********* Nexts searchLives() **********
        for index in range(2, number_runs, 1):
            # Check if there's enough time to launch searchLives()
            elapsed_seconds_from_start = time.perf_counter() - timestamp_first_start_script            
            if elapsed_seconds_from_start <= 60 - self.settings['wait_before_retry'] - self.settings['seconds_security']:
                time.sleep(self.settings['wait_before_retry'])
                # We launch searchLives another time
                timestamp_start_script = time.perf_counter()
                self.searchLives()
                timestamp_end_script = time.perf_counter()
            else:
                # Not enough time to launch a new searchLives(), we exit
                break

        # Wait for threads to finish
        for recordThread in self.recordThreadList:
            recordThread.join()

        for chatThread in self.chatThreadList:
            chatThread.join()

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
        'youtubeKey': '', # YouTube API Key from Google Cloud, see https://helano.github.io/help.html
        # Format
        'tz': 'Europe/Paris',
        'dateFormats': {'dateString': '%d/%m/%Y %H:%M:%S', 'dateDBString': '%Y-%m-%d %H:%M:%S', 'dateFileString': '%d%m%Y%H%M%S'},
        # Recording
        'wait_before_retry': 5,
        'seconds_security': 0,
        'path_streamlink': '', # Add / at the end
        'path_ffmpeg': os.path.dirname(os.path.realpath(__file__)) + '/', # Add / at the end, same directory for ffmpeg and ffprobe
        'folder_recording': os.path.dirname(os.path.realpath(__file__)) + '/files/', # Add / at the end
        'streamlink_options': ['--stream-sorting-excludes', '>480p', '--stream-segmented-queue-deadline', '0', '--stream-timeout', '120'], # 120s of timeout is good
        'streamlink_options': 'best,best-unfiltered', # With these streamlink_options and streamlink_options : will get 480p or just below if 480p is not found
        # MySQL connection
        'params_database': {'mysql_host': '', 'mysql_database': '',
        'mysql_user': '',
        'mysql_pwd': ''},
        # Debug
        'level_debug_selected': 'debug' # 'debug' or 'normal' for minimal log
    }
    
    program = Program(idchannel, urlchannel, settings)
    program.main()
