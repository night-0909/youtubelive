# -*- encoding: utf-8 -*-

import scrapetube
import requests, json, sys, os, psutil, io
from datetime import datetime
import dateutil.parser
import threading
import subprocess, glob
from zoneinfo import ZoneInfo
from mysql.connector import connect, Error

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
    def __init__(self, settings):
        self.settings = settings
        self.tzinfo = ZoneInfo(self.settings['tz'])
        self.initLoggingFile()
        self.initDebug()
                    
    def initLoggingFile(self):
        loggingfilename = os.path.dirname(os.path.realpath(__file__)) + "/record_process"
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

    def arrangeListRecords(self, listElements):
        # Put lives as parent and their records as children
        # DB records are sorted by id_live then id_record
        
        newlistElements = []

        last_live = None
        for el in listElements:
            if last_live is not None and el['id_live'] == last_live['id_live']:
                #live = searchInList(newlistElements, 'id_live', el['id_live'])
                live = last_live
            else:
                live = {'id_live': el['id_live'], 'idchannel': el['idchannel'], 'handlechannel': el['handlechannel'], 'idVideo': el['idVideo'], 'title': el['title'],
                'dateFirstStartRecord': el['dateFirstStartRecord'], 'dateFirstStartChat': el['dateFirstStartChat'],
                'dateLastEndRecord': el['dateLastEndRecord'], 'dateLastEndChat': el['dateLastEndChat'],
                'dateStart_YTB': el['dateStart_YTB'], 'dateEnd_YTB': el['dateEnd_YTB'],
                'status_merging_all': el['status_merging_all'], 'status_merging_all_ffmpeg': el['status_merging_all'],
                'date_status_merging_all': el['status_merging_all'], 'records': []}
                newlistElements.append(live)
            
            record = {'id_record': el['id_record'], 'filenumber': el['filenumber'], 'dateStart': el['dateStart'], 'dateEnd': el['dateEnd'],
            'recording_pid': el['recording_pid'], 'recording_live_tool': el['recording_live_tool'], 'status_recording': el['status_recording'],
            'status_recording_record_live_tool': el['status_recording_record_live_tool'],
            'status_recording_duration': el['status_recording_duration'], 'status_recording_duration_ffprobe': el['status_recording_duration_ffprobe'],
            'status_convert': el['status_convert'], 'status_convert_ffmpeg': el['status_convert_ffmpeg'], 'date_status_convert': el['date_status_convert']}
            live['records'].append(record)
            
            last_live = live
        
        return newlistElements
        
    def arrangeListChats(self, listElements):
        # Put lives as parent and their chats as children
        # DB records are sorted by id_live then id_chat
        
        newlistElements = []

        last_live = None
        for el in listElements:
            if last_live is not None and el['id_live'] == last_live['id_live']:
                #live = searchInList(newlistElements, 'id_live', el['id_live'])
                live = last_live
            else:
                live = {'id_live': el['id_live'], 'idchannel': el['idchannel'], 'handlechannel': el['handlechannel'], 'idVideo': el['idVideo'], 'title': el['title'],
                'dateFirstStartRecord': el['dateFirstStartRecord'], 'dateFirstStartChat': el['dateFirstStartChat'],
                'dateLastEndRecord': el['dateLastEndRecord'], 'dateLastEndChat': el['dateLastEndChat'],
                'dateStart_YTB': el['dateStart_YTB'], 'dateEnd_YTB': el['dateEnd_YTB'],
                'status_merging_all': el['status_merging_all'], 'status_merging_all_ffmpeg': el['status_merging_all'],
                'date_status_merging_all': el['status_merging_all'], 'chats': []}
                newlistElements.append(live)
            
            chat = {'id_chat': el['id_chat'], 'filenumber': el['filenumber'], 'dateStart': el['dateStart'], 'dateEnd': el['dateEnd'],
            'chat_pid': el['chat_pid'], 'status_chat': el['status_chat'], 'status_chat_downloader': el['status_chat_downloader']}
            live['chats'].append(chat)
            
            last_live = live
        
        return newlistElements

    def merge_mp4files(self, live, mp4files):   
        idVideo = live['idVideo']
        file_list = self.settings['folder_recording'] + 'filelist_' + live['idchannel'] + '.' + idVideo + '.txt'
        finalmp4file = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.mp4'

        print(f"id_live={live['id_live']} idVideo={idVideo} Starting merge of mp4 files...")
        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Starting merge of mp4 files...", 'normal')
        
        merge = subprocess.Popen([self.settings['video_tools']['path_ffmpeg'] + 'ffmpeg', "-f", "concat", "-safe", "0", "-i", file_list, "-c" , "copy", finalmp4file],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        merge.wait()
            
        # Get duration of final file : goal is to detect diff in official stream duration, records in DB and duration of temporary files, and duration of merged mp4
        # To get only duration with no other info : ffprobe -v error -show_entries format=duration -sexagesimal -of default=noprint_wrappers=1:nokey=1 <file>
        # cf https://trac.ffmpeg.org/wiki/FFprobeTips#Formatcontainerduration
        durationMP4 = None
        processGetInfoMP4 = subprocess.Popen([self.settings['video_tools']['path_ffmpeg'] + 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-sexagesimal', '-of',
        'default=noprint_wrappers=1:nokey=1', finalmp4file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = processGetInfoMP4.communicate()
        durationMP4 = str(stdout.strip())
        
        status_merging_all_duration = durationMP4
        if processGetInfoMP4.returncode != 0:
            status_merging_all_duration = str(stderr.strip())
            
        live["status_merging_all_duration"] = status_merging_all_duration
        live["status_merging_all_duration_ffprobe"] = processGetInfoMP4.returncode
        
        dateNow = self.getDateNow()
        live['status_merging_all_ffmpeg'] = merge.returncode
        live['date_status_merging_all'] = dateNow['dateDBString']

        if merge.returncode == 0 and os.path.isfile(finalmp4file) is True:
            print(f"id_live={live['id_live']} idVideo={idVideo} Merge was done without error")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Merge was done without error", 'normal')
            
            live['status_merging_all'] = "finished"
            os.remove(file_list)
            for mp4file in mp4files:
                if os.path.basename(mp4file) != os.path.basename(finalmp4file):
                    print("delete file " + mp4file)
                    os.remove(mp4file)
        else:
            # It would be nice to get stdout of merge command, see record_channel.py in recordLive() function
            print(f"id_live={live['id_live']} idVideo={idVideo} Merge had error : {merge.returncode}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Merge had error : {merge.returncode}", 'normal')
            live['status_merging_all'] = "error"

        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()

        # UPDATE live with new status of merging and duration of merged .mp4 file
        # HOW TO : https://stackoverflow.com/questions/11517106/how-to-update-mysql-with-python-where-fields-and-entries-are-from-a-dictionary
        params = {"status_merging_all": live["status_merging_all"], "status_merging_all_ffmpeg": live['status_merging_all_ffmpeg'],
        "date_status_merging_all": live["date_status_merging_all"], "status_merging_all_duration": live["status_merging_all_duration"],
        "status_merging_all_duration_ffprobe": live["status_merging_all_duration_ffprobe"]}

        try:
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_live_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
            cursor.execute(update_live_query, list(params.values()))
            connection.commit()
            cursor.close()
        except Error as ex:
            print(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with new status of merging : {ex}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with new status of merging : {ex}", 'normal')
            self.exitProgram()              
            
        # Close Mysql connection
        try:
            connection.close()
        except Error as ex:
            pass
        
    def update_live(self, db, live, params):
        idVideo = live['idVideo']
        try:
            print(f"Update live id_live={live['id_live']} idVideo={idVideo} with values : {params}")
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_live_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
            cursor.execute(update_live_query, list(params.values()))
            connection.commit()
            cursor.close()
        except Error as ex:
            print(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with new values {params} : {ex}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with new values {params} : {ex}", 'normal')
            self.exitProgram()                      

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

    def downloadVideosFiles(self, live):
        url = "https://www.youtube.com/watch?v=" + live['idVideo']
        cmd_download = [self.settings['video_tools']['path_yt-dlp'] + 'yt-dlp',
        '--ffmpeg-location', self.settings['video_tools']['path_ffmpeg'] + 'ffmpeg', *self.settings['download_files']['yt-dlp_options']]
        
        if self.settings['cookies']:
            cmd_download.extend(['--cookies', self.settings['cookies']])
                                    
        cmd_download.append(url)
        
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} yt-dlp commandline : {cmd_download}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} yt-dlp commandline : {cmd_download}", 'normal')
        try:
            downloadProcess = subprocess.Popen(cmd_download, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            # Record yt-dlp stderr and stdout to file
            logfile = self.settings['folder_recording'] + 'downloading_files_' + live['idVideo'] + '.log'
            dl_yt_dlp_logfile_thread = threading.Thread(target=self.process_logfile, args=(downloadProcess, logfile))
            dl_yt_dlp_logfile_thread.start()
        except Exception as e:
            print(f"id_live={live['id_live']} idVideo={live['idVideo']} Error launching yt-dlp to download files : exception={e}")
            self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Error launching yt-dlp to download files : exception={e}", 'normal')
            
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()        
        
        params = {'status_downloading_all': 'ongoing'}
        self.update_live(db, live, params)
        
        downloadProcess.wait()
        
        print(f"id_live={live['id_live']} idVideo={live['idVideo']} downloading files has ended with returncode={downloadProcess.returncode} : {logfile}")
        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} downloading files has ended with returncode={downloadProcess.returncode} : {logfile}", 'normal')
        
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()
            
        status_downloading_all = 'finished' if downloadProcess.returncode == 0 else 'error'
        params = {'status_downloading_all': status_downloading_all}
        self.update_live(db, live, params)
        
    def process_download_videos(self):
        # ************** Download live files from Youtube (video, audio, subs or infos that yt-dlp can save in a file (description, title, etc...)) *********
        # Downloading after end of live can be useful if : you use record_channel only to record chat, if live recording failed or missed some segments,
        # you prefer higher quality, you want to save title and description and other metadata accessible by yt-dlp, etc...)
        
        print("Downloading files after live has ended")
        
        if self.settings['download_files']['enabled'] is False:
            print(f"Downloading videos files is disabled")
            self.writelog(f"Downloading videos files is disabled", 'normal')
            return
        
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()        
        
        if self.settings['download_files']['enabled'] is True:
            downloadThreadList = []            
            try:
                select_livesD_query = """SELECT * FROM lives
                WHERE lives.status_downloading_all IS NULL
                ORDER BY lives.id_live ASC"""
                connection = db.getConnection()
                cursor = connection.cursor(prepared=True, dictionary=True)
                params = {}
                cursor.execute(select_livesD_query, params)
                lives_downloading_files_todo = cursor.fetchall()
                if len(lives_downloading_files_todo) == 0:
                    print("No live needs downloading video files")
                    self.writelog("No live needs downloading video files", 'normal')
                
                cursor.close()
            except Error as ex:
                print(f"Mysql Error SELECT lives with records where video files has to be checked : {ex}")
                self.writelog(f"Mysql Error SELECT lives with records where video files has to be checked : {ex}", 'normal')
                self.exitProgram()

            if len(lives_downloading_files_todo) > 0:
                print("Browse lives with downloading to do")
                self.writelog("Browse lives with downloading to do", 'normal')
                for live in lives_downloading_files_todo:
                    isRunning = False
                    try:
                        streams = scrapetube.get_channel(live['idchannel'], content_type="streams", limit=30, sort_by="newest")
                    except Exception as e:
                        print(f"[×] Error scrapetube /streams for idchannel={live['idchannel']} : {e}")
                        self.writelog(f"[×] Error scrapetube /streams for idchannel={live['idchannel']} : {e}", 'normal')
                        continue
                    
                    for stream in streams:
                        if live['idVideo'] == stream['videoId'] and stream['is_live'] is True:
                            isRunning = True
                            break
                
                    if isRunning is False:
                        # Start downloading files in a thread 
                        downloadThread = threading.Thread(target=self.downloadVideosFiles, args=[live])
                        downloadThreadList.append(downloadThread)
                        downloadThread.start()
                    else:
                        print(f"id_live={live['id_live']} idVideo={live['idVideo']} Stream is still up on Youtube, we skip downlading files")
                        self.writelog(f"id_live={live['id_live']} idVideo={live['idVideo']} Stream is still up on Youtube, we skip downloading files", 'normal')
                    
                # Wait for all threads to finish
                for t in downloadThreadList:
                    t.join()
            
    def process_videos(self):
        print("Process videos files")
        
        if self.settings['process_video']['enabled'] is False:
            print(f"Processing of videos files is disabled")
            self.writelog(f"Processing if videos files is disabled", 'normal')
            return
        
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()
        
        try:
            select_livesR_query = """SELECT * FROM lives, records WHERE lives.id_live = records.id_live
            AND lives.status_merging_all IS NULL
            ORDER BY lives.id_live, records.id_record ASC"""
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            params = {}
            cursor.execute(select_livesR_query, params)
            lives_records_todo = cursor.fetchall()
            if len(lives_records_todo) == 0:
                print("No live needs processing on video files")
                self.writelog("No live needs processing on video files", 'normal')
            else:
                # Assemble an array with lives as parents and records as children
                lives_records_todo = self.arrangeListRecords(lives_records_todo)
            cursor.close()
        except Error as ex:
            print(f"Mysql Error SELECT lives with records where video files has to be checked : {ex}")
            self.writelog(f"Mysql Error SELECT lives with records where video files has to be checked : {ex}", 'normal')
            self.exitProgram()

        if len(lives_records_todo) > 0:
            mergeThreadList = []
            print("Browse lives with operations to do on video files")
            self.writelog("Browse lives with operations to do on video files", 'normal')

            # Loop on lives where video files hasn't been processed
            for live in lives_records_todo:
                url = "https://www.youtube.com/watch?v=" + live['idVideo']
                idVideo = live['idVideo']
                isRunning = False
                
                print('\n')
                print(f"id_live={live['id_live']} idVideo={idVideo} Some video files hasn't been processed")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Some video files hasn't been processed", 'normal')

                # Get last record of live from DB
                lastRecord = live['records'][len(live['records']) - 1]
                print(f"id_live={live['id_live']} idVideo={idVideo} lastRecord : {lastRecord}")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastRecord : {lastRecord}", 'normal')
               
                # Debug info from last record
                lastfilenumbervideo = lastRecord['filenumber']
                lastmp4file = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.' + lastfilenumbervideo + '.mp4'
                resultmp4file = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.mp4'
                print(f"id_live={live['id_live']} idVideo={idVideo} lastmp4file : {lastmp4file}")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastmp4file : {lastmp4file}", 'normal')
                print(f"id_live={live['id_live']} idVideo={idVideo} resultmp4file : {resultmp4file}")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} resultmp4file : {resultmp4file}", 'normal')

                # Check if live is streaming right now from database. If info isn't available, we'll check on Youtube
                if live['dateEnd_YTB'] is None:
                    # Check if live is streaming right now from Youtube
                    # It can be replaced by a call to Youtube API V3 /videos or a call to YTB video url and get videoDetails->isLive
                    # 2 streams can be running at the same time on same channel
                    # Get last streams of channel
                    try:
                        streams = scrapetube.get_channel(live['idchannel'], content_type="streams", limit=30, sort_by="newest")
                    except Exception as e:
                        print(f"[×] Error scrapetube /streams for idchannel={live['idchannel']} : {e}")
                        self.writelog(f"[×] Error scrapetube /streams for idchannel={live['idchannel']} : {e}", 'normal')
                        continue
                    
                    for stream in streams:
                        if idVideo == stream['videoId'] and stream['is_live'] is True:
                            isRunning = True
                            break
                
                if isRunning is False:
                    # UPDATE live with dateEnd_YTB if empty
                    dateEnd_YTB = None
                    if live['dateEnd_YTB'] is None:
                        videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['YoutubeAPIV3']['youtubeKey'] + "&id=" + idVideo + \
                        "&part=snippet,contentDetails,statistics,liveStreamingDetails"
                        print(videosInfosURL)
                        try:
                            response = requests.get(videosInfosURL)
                            videosInfosResponse = response.text
                            if response.status_code == 200:
                                video_json = json.loads(videosInfosResponse)       
                                item = video_json.get('items')[0]
                                actualEndTime = item.get('liveStreamingDetails').get('actualEndTime')
                                # Convert datetime iso 2025-12-06T17:30:42Z to 2025-12-06 17:30:42
                                actualEndTime_object = dateutil.parser.isoparse(actualEndTime)
                                dateEnd_YTB = actualEndTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
                        except Exception as e:
                            # Not a problem if something's wrong in this request
                            print(f"id_live={live['id_live']} idVideo={idVideo} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}", 'normal')
                    
                        if dateEnd_YTB is not None:
                            params['dateEnd_YTB'] = dateEnd_YTB
                            try:
                                connection = db.getConnection()
                                cursor = connection.cursor(prepared=True, dictionary=True)
                                update_live_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
                                cursor.execute(update_live_query, list(params.values()))
                                connection.commit()
                                cursor.close()
                            except Error as ex:
                                print(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with dateEnd_YTB if empty : {ex}")
                                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with dateEnd_YTB if empty : {ex}", 'normal')
                                self.exitProgram()
    
                    # Check if record_live_tool process has terminated
                    proc_record_live_tool_exists = False
                    if lastRecord['recording_pid'] is not None and psutil.pid_exists(lastRecord['recording_pid']) is True:
                        try:
                            proc = psutil.Process(lastRecord['recording_pid'])
                            if proc.cmdline()[1] == self.settings['record_video']['path_' + lastRecord['recording_live_tool']] + lastRecord['recording_live_tool'] and url in proc.cmdline():
                                proc_record_live_tool_exists = True
                        except Exception as e:
                            print(f"[×] idVideo={stream['videoId']} Impossible to get {lastRecord['recording_live_tool']} process informations for video recording : {e}")
                            self.writelog(f"[×] idVideo={stream['videoId']} Impossible to get {lastRecord['recording_live_tool']} process informations for video recording : {e}", 'normal')
                            # We continue normally
                                            
                    # Before trying to merge mp4 files together, we make sure for streamlink records that all .ts are converted to .mp4 (case of crash of record_channel.py or error in conversion process in record_channel.py)
                    # and for yt-dlp that we have mp4 file
                    # We assure that live is not running + wait seconds_before_merge seconds before doing that, because otherwise a stream can be running at the time of the cron
                    # and a current .ts can wrongly be converted to .mp4
                    if proc_record_live_tool_exists is False:
                        tsfiles = []
                        mp4files = []
                        fragment_files_exists = False
                        
                        for record in live['records']:
                            basefile = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.' + record['filenumber']
                            tsfile = basefile + '.ts'
                            mp4file = basefile + '.mp4'
                            if lastRecord['recording_live_tool'] == 'streamlink':
                                # .ts files
                                if os.path.isfile(tsfile):
                                    print(f"id_live={live['id_live']} idVideo={idVideo} .ts file present : {tsfile}")
                                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} .ts file present : {tsfile}", 'normal')                        
                                
                                    # First, we convert remaining .ts file to .mp4, if success they will be added to mp4files list
                                    timestamp_now = datetime.now().timestamp()
                                    time_diff_seconds = timestamp_now - os.path.getmtime(tsfile)
                                    if time_diff_seconds > self.settings['process_video']['seconds_before_merge']:
                                        print(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is older than {self.settings['process_video']['seconds_before_merge']} seconds but still present : {tsfile}, we convert it to mp4")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is older than {self.settings['process_video']['seconds_before_merge']} seconds but still present : {tsfile}, we convert it to mp4", 'normal')
                                        new_mp4file = tsfile.replace('.ts', '.mp4')
                                        convert = subprocess.Popen([self.settings['video_tools']['path_ffmpeg'] + 'ffmpeg', "-i", tsfile, "-c", "copy", new_mp4file],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
                                        convert.wait()
                                        
                                        if convert.returncode == 0 and os.path.isfile(new_mp4file) is True:
                                            print(f"id_live={live['id_live']} idVideo={idVideo} Convert remaining .ts file to mp4 succeeded : {new_mp4file}")
                                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Convert remaining .ts file to mp4 succeeded : {new_mp4file}", 'normal')
                                            os.remove(tsfile)
                                        else:
                                            print(f"id_live={live['id_live']} idVideo={idVideo} Convert remaining .ts file to mp4 encountered a problem. convert.returncode={convert.returncode}, isfile={os.path.isfile(new_mp4file)} : {new_mp4file}")
                                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Convert remaining .ts file to mp4 encountered a problem. convert.returncode={convert.returncode}, isfile={os.path.isfile(new_mp4file)} : {new_mp4file}", 'normal')
                                            tsfiles.append(tsfile)
                                    else:
                                        print(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is younger than {self.settings['process_video']['seconds_before_merge']} seconds so we don't do anything : {tsfile}")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is younger than {self.settings['process_video']['seconds_before_merge']} seconds so we don't do anything : {tsfile}", 'normal')
                                        tsfiles.append(tsfile)

                                # .mp4 files
                                if os.path.isfile(mp4file):
                                    print(f"id_live={live['id_live']} idVideo={idVideo} .mp4 file present : {mp4file}")
                                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} .mp4 file present : {mp4file}", 'normal')
                                    mp4files.append(mp4file)
                            elif lastRecord['recording_live_tool'] == 'yt-dlp':
                                # .mp4 files
                                if os.path.isfile(mp4file):
                                    print(f"id_live={live['id_live']} idVideo={idVideo} .mp4 file present : {mp4file}")
                                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} .mp4 file present : {mp4file}", 'normal')
                                    mp4files.append(mp4file)
                                else:
                                    fragment_files = glob.glob(basefile + '.f*.*')
                                    if len(fragment_files) > 0:
                                        # If there's a least one file basefile.fXXX.YYY, we don't do the merge automatically. Merge of missing mp4 would have to be
                                        # done manually with basefile.fXXX.YYY files, then merge all .mp4 files
                                        print(f"id_live={live['id_live']} idVideo={idVideo} {mp4file} isn't present and there are fragment files ({fragment_files})")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} {mp4file} isn't present and there are fragment files ({fragment_files})", 'normal')
                                        fragment_files_exists = True
                        
                        # Check if there's still some fragment files
                        if lastRecord['recording_live_tool'] == 'yt-dlp':
                            if fragment_files_exists is True:
                                print(f"id_live={live['id_live']} idVideo={idVideo} There are fragment files, we don't merge files automatically.")
                                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} There are fragment files, we don't merge files automatically.", 'normal')
                                params = {'status_merging_all': 'need_to_fix'}
                                self.update_live(db, live, params)                            
                                continue
                        
                        # Check if there's still at leat one .ts file for this stream
                        # We let this script try again this stream in the future
                        if len(tsfiles) > 0:
                            print(f"id_live={live['id_live']} idVideo={idVideo} There's still at least one .ts file, we don't merge. tsfiles : {tsfiles}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} There's still at least one .ts file, we don't merge. tsfiles : {tsfiles}", 'normal')
                            continue
                        
                        # To merge mp4s, we need more than one mp4 file. If only one mp4, we only rename .001.mp4 to .mp4 and exit
                        # mp4 files are sorted by id_record ASC
                        if len(mp4files) == 0:
                            print(f"id_live={live['id_live']} idVideo={idVideo} No mp4 file found, we skip")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} No mp4 file found, we skip", 'normal')
                            params = {'status_merging_all': 'not_needed'}
                            self.update_live(db, live, params)
                            continue
                        # We rename the only 001.mp4 to .mp4 if it's older than seconds_before_merge seconds and live is not running
                        elif len(mp4files) == 1:
                            print(f"id_live={live['id_live']} idVideo={idVideo} One mp4 found {mp4files[0]}, we will see if we can rename it")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} One mp4 found {mp4files[0]}, we will see if we can rename it", 'normal')
                            
                            if os.path.isfile(mp4files[0]):
                                timestamp_now = datetime.now().timestamp()
                                time_diff_seconds = timestamp_now - os.path.getmtime(mp4files[0])
                                if time_diff_seconds > self.settings['process_video']['seconds_before_merge']:
                                    if not os.path.isfile(resultmp4file):                            
                                        print(f"id_live={live['id_live']} idVideo={idVideo} We rename mp4 file {mp4files[0]}")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} We rename mp4 file {mp4files[0]}", 'normal')
                                        os.rename(mp4files[0], resultmp4file)
                                        params = {'status_merging_all': 'finished'}
                                    else:
                                        print(f"id_live={live['id_live']} idVideo={idVideo} mp4 filename already exists, we don't rename mp4 file {mp4files[0]}")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} mp4 filename already exists, we don't rename mp4 file {mp4files[0]}", 'normal')
                                        params = {'status_merging_all': 'not_needed'}
                                    
                                    self.update_live(db, live, params)
                                else:
                                    print(f"id_live={live['id_live']} idVideo={idVideo} mp4 file is not older than {self.settings['process_video']['seconds_before_merge']} seconds, we do not rename mp4 file : {mp4files[0]}")
                                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} mp4 file is not older than {self.settings['process_video']['seconds_before_merge']} seconds, we do not rename mp4 file : {mp4files[0]}", 'normal')
                            continue

                        # Check if there's still a .ts file for this stream
                        if len(tsfiles) > 0:
                            print(f"id_live={live['id_live']} idVideo={idVideo} There's still at least one .ts file, we don't merge. tsfiles : {tsfiles}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} There's still at least one .ts file, we don't merge. tsfiles : {tsfiles}", 'normal')
                            continue
                        
                        # Check if merge of all mp4 hasn't been already done // To do it again clear status_merging_all field
                        if live['status_merging_all'] is not None:
                            print(f"id_live={live['id_live']} idVideo={idVideo} No merging to do, actual status_merging_all is : {live['status_merging_all']}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} No merging to do, actual status_merging_all is : {live['status_merging_all']}", 'normal')
                            continue
                            
                        # Check if there's not already a final .mp4 file present
                        if os.path.isfile(resultmp4file):
                            print(f"id_live={live['id_live']} idVideo={idVideo} one final .mp4 is already present, we don't merge. resultmp4file : {resultmp4file}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} one final .mp4 is already present, we don't merge. resultmp4file : {resultmp4file}", 'normal')
                            params = {'status_merging_all': 'not_needed'}                   
                            self.update_live(db, live, params)
                            continue

                        # Check if last filenumber mp4 is older than seconds_before_merge seconds
                        if os.path.isfile(lastmp4file):
                            timestamp_now = datetime.now().timestamp()
                            time_diff_seconds = timestamp_now - os.path.getmtime(lastmp4file)
                            if time_diff_seconds <= self.settings['process_video']['seconds_before_merge']:
                                print(f"id_live={live['id_live']} idVideo={idVideo} Last mp4 file is only {time_diff_seconds} seconds old, we skip")
                                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Last mp4 file is only {time_diff_seconds} seconds old, we skip", 'normal')
                                continue
                        
                        
                        # *************** Merging mp4 files ******************
                        # Everything is OK, we merge mp4 files
                        print(f"id_live={live['id_live']} idVideo={idVideo} Merge process is needed")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Merge process is needed", 'normal')
                        
                        file_list_string = ''
                        for mp4file in mp4files:
                            file_list_string = file_list_string + "file '" + mp4file + "'\n"

                        print(f"id_live={live['id_live']} idVideo={idVideo} file_list_string : {file_list_string}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} file_list_string : {file_list_string}", 'normal')

                        file_list = self.settings['folder_recording'] + 'filelist_' + live['idchannel'] + '.' + idVideo + '.txt'
                        f = open(file_list, "w", encoding="utf-8")
                        f.write(file_list_string)
                        f.close()

                        mergeThread = threading.Thread(target=self.merge_mp4files, args=(live, mp4files))
                        mergeThreadList.append(mergeThread)
                        mergeThread.start()                       
                    else:
                        print(f"id_live={live['id_live']} idVideo={idVideo} {lastRecord['recording_live_tool']} is still running, we skip video processing")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} {lastRecord['recording_live_tool']} is still running, we skip video processing", 'normal')
                else:
                    print(f"id_live={live['id_live']} idVideo={idVideo} Stream is still up on Youtube, we skip video processing")
                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Stream is still up on Youtube, we skip video processing", 'normal')

            # Wait for all mp4 merges to finish
            for mergeThread in mergeThreadList:
                mergeThread.join()
            
        # Close Mysql connection
        try:
            connection.close()
        except Error as ex:
            pass
        
    def process_chats(self):
        print("Process chat files")
        
        if self.settings['process_chat']['enabled'] is False:
            print(f"Processing of chat files is disabled")
            self.writelog(f"Processing of chat files is disabled", 'normal')
            return
        
        try:
            db = Database(self.settings['params_database'])
            connection = db.getConnection()
        except Exception as e:
            print(f"[×] Error connecting to database : {e}")
            self.writelog(f"[×] Error connecting to database : {e}", 'normal')
            self.exitProgram()
            
        try:
            connection = db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            select_livesC_query = """SELECT * FROM lives, chats WHERE lives.id_live = chats.id_live
            AND lives.status_rename_chat IS NULL
            ORDER BY lives.id_live, chats.id_chat ASC"""
            params = {}
            cursor.execute(select_livesC_query, params)
            lives_chats_todo = cursor.fetchall()
            if len(lives_chats_todo) == 0:
                print("No live needs processing on chat files")
                self.writelog("No live needs processing on chat files", 'normal')
            else:
                # Assemble an array with lives as parents and chats as children
                lives_chats_todo = self.arrangeListChats(lives_chats_todo)
            cursor.close()
        except Error as ex:
            print(f"Mysql Error SELECT lives with chats with renaming to check : {ex}")
            self.writelog(f"Mysql Error SELECT lives with chats with renaming to check : {ex}", 'normal')
            self.exitProgram()

        if len(lives_chats_todo) > 0:
            print("Browse lives with operations to do on chat files")
            self.writelog("Browse lives with operations to do on chat files", 'normal')

            # Loop on lives where chat files hasn't been processed
            for live in lives_chats_todo:
                url = "https://www.youtube.com/watch?v=" + live['idVideo']
                idVideo = live['idVideo']
                isRunning = False
                
                print('\n')
                print(f"id_live={live['id_live']} idVideo={idVideo} Some chat files hasn't been processed")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Some chat files hasn't been processed", 'normal')

                # Get last chat of live from DB
                lastChat = live['chats'][len(live['chats']) - 1]
                print(f"id_live={live['id_live']} idVideo={idVideo} lastChat : {lastChat}")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastChat : {lastChat}", 'normal')            
                
                # Debug info from last chat
                lastfilenumberchat = lastChat['filenumber']
                lastchatfile = self.settings['folder_recording'] + 'chat_' + live['idchannel'] + '.' + idVideo + '.' + lastfilenumberchat + '.txt'
                resultchatfile = self.settings['folder_recording'] + 'chat_' + live['idchannel'] + '.' + idVideo + '.txt'
                print(f"id_live={live['id_live']} idVideo={idVideo} lastchatfile : {lastchatfile}")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastchatfile : {lastchatfile}", 'normal')
                print(f"id_live={live['id_live']} idVideo={idVideo} resultchatfile : {resultchatfile}")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} resultchatfile : {resultchatfile}", 'normal')

                # Check if live is streaming right now from database. If info isn't available, we'll check on Youtube
                if live['dateEnd_YTB'] is None:
                    # Check if live is streaming right now from Youtube
                    # It can be replaced by a call to Youtube API V3 /videos or a call to YTB video url and get videoDetails->isLive
                    # 2 streams can be running at the same time on same channel
                    # Get last streams of channel
                    streams = scrapetube.get_channel(live['idchannel'], content_type="streams", limit=30, sort_by="newest")
                    for stream in streams:
                        if idVideo == stream['videoId'] and stream['is_live'] is True:
                            isRunning = True
                            break   

                if isRunning is False:
                    # UPDATE live with dateEnd_YTB if empty
                    dateEnd_YTB = None
                    if live['dateEnd_YTB'] is None:
                        videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['YoutubeAPIV3']['youtubeKey'] + "&id=" + idVideo + \
                        "&part=snippet,contentDetails,statistics,liveStreamingDetails"
                        print(videosInfosURL)
                        try:
                            response = requests.get(videosInfosURL)
                            videosInfosResponse = response.text
                            if response.status_code == 200:
                                video_json = json.loads(videosInfosResponse)       
                                item = video_json.get('items')[0]
                                actualEndTime = item.get('liveStreamingDetails').get('actualEndTime')
                                # Convert datetime iso 2025-12-06T17:30:42Z to 2025-12-06 17:30:42
                                actualEndTime_object = dateutil.parser.isoparse(actualEndTime)
                                dateEnd_YTB = actualEndTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
                        except Exception as e:
                            # Not a problem if something's wrong in this request
                            print(f"id_live={live['id_live']} idVideo={idVideo} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}", 'normal')
                    
                        if dateEnd_YTB is not None:
                            params['dateEnd_YTB'] = dateEnd_YTB
                            try:
                                connection = db.getConnection()
                                cursor = connection.cursor(prepared=True, dictionary=True)
                                update_live_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
                                cursor.execute(update_live_query, list(params.values()))
                                connection.commit()
                                cursor.close()
                            except Error as ex:
                                print(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with dateEnd_YTB if empty : {ex}")
                                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with dateEnd_YTB if empty : {ex}", 'normal')
                                self.exitProgram()

                    # Check if chat_downloader process has terminated
                    procChatExists = False
                    if lastChat['chat_pid'] is not None and psutil.pid_exists(lastChat['chat_pid']) is True:
                        try:
                            proc = psutil.Process(lastChat['chat_pid'])
                            if proc.cmdline()[1] == self.settings['process_chat']['path_chat_downloader'] + 'chat_downloader' and url in proc.cmdline():
                                procChatExists = True                            
                        except Exception as e:
                            print(f"[×] idVideo={stream['videoId']} Impossible to get Python process informations for chat recording : {e}")
                            self.writelog(f"[×] idVideo={stream['videoId']} Impossible to get Python process informations for chat recording : {e}", 'normal')
                            # We continue normally            

                    # We assure that live is not running + wait seconds_before_rename_chat before doing something
                    if procChatExists is False:
                        chatfiles = []
                        for chat in live['chats']:
                            chatfile = self.settings['folder_recording'] + 'chat_' + live['idchannel'] + '.' + idVideo + '.' + chat['filenumber'] + '.txt'
                            if os.path.isfile(chatfile):
                                print(f"id_live={live['id_live']} idVideo={idVideo} chat file present : {chatfile}")
                                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} chat file present : {chatfile}", 'normal')
                                chatfiles.append(chatfile)
                        
                        update_status_rename_chat = False
                        params = {}                
                        # Warning, dont't rename chat file too soon as viewers can still write message after stream ended on YTB (5 minutes or so)
                        # If we have only one chat file, we rename it without filenumber
                        if len(chatfiles) == 0:
                            print(f"id_live={live['id_live']} idVideo={idVideo} no chat file has been found")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} no chat file has been found", 'normal')
                            update_status_rename_chat = True
                            params['status_rename_chat'] = 'not_needed'
                        
                        elif len(chatfiles) == 1:
                            print(f"id_live={live['id_live']} idVideo={idVideo} One chat file found : {chatfiles[0]}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} One chat file found : {chatfiles[0]}", 'normal')
                            if os.path.isfile(lastchatfile):
                                timestamp_now = datetime.now().timestamp()
                                time_diff_seconds = timestamp_now - os.path.getmtime(lastchatfile)
                                if time_diff_seconds > self.settings['process_chat']['seconds_before_rename_chat']:
                                    if not os.path.isfile(resultchatfile):
                                        print(f"id_live={live['id_live']} idVideo={idVideo} We rename chat file : {lastchatfile}")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} We rename chat file : {lastchatfile}", 'normal')
                                        os.rename(lastchatfile, resultchatfile)
                                        update_status_rename_chat = True
                                        params['status_rename_chat'] = 'finished'
                                    else:
                                        print(f"id_live={live['id_live']} idVideo={idVideo} Chat filename already exists, we don't rename chat file : {lastchatfile}")
                                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Chat filename already exists, we don't rename chat file : {lastchatfile}", 'normal')
                                        update_status_rename_chat = True
                                        params['status_rename_chat'] = 'not_needed'
                                else:
                                    print(f"id_live={live['id_live']} idVideo={idVideo} Chat file is not older than {self.settings['process_chat']['seconds_before_rename_chat']} seconds, we do not rename chat file : {lastchatfile}")
                                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Chat file is not older than {self.settings['process_chat']['seconds_before_rename_chat']} seconds, we do not rename chat file : {lastchatfile}", 'normal')
                                    update_status_rename_chat = False
                        
                        # If more than one chat file, we don't rename and let the user check manually where are all chat messages
                        elif len(chatfiles) > 1:
                            print(f"id_live={live['id_live']} idVideo={idVideo} More than one chat file, we don't do anything")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} More than one chat file, we don't do anything", 'normal')
                            update_status_rename_chat = True
                            params['status_rename_chat'] = 'not_needed'
                            
                        # UPDATE status_rename_chat
                        if update_status_rename_chat is True:
                            self.update_live(db, live, params)
                    else:
                        print(f"id_live={live['id_live']} idVideo={idVideo} chat_downloader is still running, we skip chat processing")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} chat_downloader is still running, we skip chat processing", 'normal')
                else:
                    print(f"id_live={live['id_live']} idVideo={idVideo} Stream is still up on Youtube, we skip chat processing")
                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Stream is still up on Youtube, we skip chat processing", 'normal')
                            
        # Close Mysql connection
        try:
            connection.close()
        except Error as ex:
            pass
        
    # *************** Main program ******************
    def main(self):
        print("Starting program")
        self.writelog("Starting program")
        self.initDatabase()
        
        # SELECT lives where no video and chat operations has been done
        # If you want to do again a treatment on a live, clear "status_" fields in lives table
        
        # Possible cases :
        #   1- if "record_video" in settings is enabled :
        #       a- convert remaining .ts files in .mp4
        #       b- merge .mp4 files in one .mp4
        #       c- rename the only video_idVideo_XXX.mp4 to video_idVideo.mp4
        #       d- no renaming, no convert of .ts->.mp4, no merging of .mp4 to do

        #   2- if "record_chat" in settings is enabled :
        #       e- rename the only chat_idVideo_XXX.txt to chat_idVideo.txt
        #       f- no rename to do as no chat files at all or presence of several chat files (in this case, it's up to you to determine manually what to keep/merge)
        
        #   3- if "download_files" in settings is enabled :
        #       g- download files of video
        
        process_videos_Thread = threading.Thread(target=self.process_videos)
        process_videos_Thread.start()
        process_chats_Thread = threading.Thread(target=self.process_chats)
        process_chats_Thread.start()
        process_download_videos_Thread = threading.Thread(target=self.process_download_videos)
        process_download_videos_Thread.start()               
        
        process_videos_Thread.join()
        process_chats_Thread.join()
        process_download_videos_Thread.join()
                
        print("Execution was OK")
        self.writelog("Execution was OK")
        print("Ending program")
        self.writelog("Ending program")
        self.clean()

if __name__ == "__main__":
    settings = {
        # Youtube
        'YoutubeAPIV3': { # Youtube Data API V3 can be used to get endtime of streams
            'enabled': True, # attribute not used, Youtube Data API V3 is always used right now
            'youtubeKey': '' # YouTube API Key from Google Cloud, see https://helano.github.io/help.html
        },
        'cookies' : '', # path of cookie file, or '' or None to disable
        # Format
        'tz': 'Europe/Paris',
        'dateFormats': {'dateString': '%d/%m/%Y %H:%M:%S', 'dateDBString': '%Y-%m-%d %H:%M:%S', 'dateFileString': '%d%m%Y%H%M%S'},
        # Converting and renaming
        'folder_recording': os.path.dirname(os.path.realpath(__file__)) + '/files/', # Add / at the end
        'video_tools':
            {'path_streamlink': '', # Add / at the end
            'path_yt-dlp' : '', # Add / at the end
            'path_ffmpeg': os.path.dirname(os.path.realpath(__file__)) + '/' # Add / at the end, same directory for ffmpeg and ffprobe
        },
        'process_video': {
            'enabled' : True,
            'seconds_before_merge': 60*5 # 5 minutes // Must be > "stream-timeout" from record_channel.py, plus let record_channel.py the time to to convert .ts in mp4
        },
        'process_chat': {
            'enabled' : True,
            'seconds_before_rename_chat': 60*10, # 10 minutes
            "path_chat_downloader": '' # Add / at the end
        },
        'download_files' : {
            'enabled' : True,
            'yt-dlp_options': ['-S', 'res:480', '--remote-components', 'ejs:github', '--js-runtimes', 'deno:',  # Put path of deno folder
            '--retries', '40', '--fragment-retries', '40', '--socket-timeout', '300',
            '-v', '-k', '-o', os.path.dirname(os.path.realpath(__file__)) + '/files/' + '%(id)s %(title)s.%(ext)s',
            '--no-part', '--merge-output-format', 'mp4',
            '--extractor-args', 'youtube:player-client=default,web_embedded,mweb' #See https://github.com/yt-dlp/yt-dlp/issues/16862#issuecomment-4642619967
            ]
        },        
        # MySQL connection
        'params_database': {'mysql_host': '', 'mysql_database': '',
        'mysql_user': '',
        'mysql_pwd': ''},
        # Debug
        'level_debug_selected': 'debug' # 'debug' or 'normal' for minimal log
    }
    
    program = Program(settings)
    program.main()
