# -*- encoding: utf-8 -*-

import scrapetube
import requests, json, sys, os
from datetime import datetime
import dateutil.parser
import threading, glob
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
    def __init__(self, settings):
        self.settings = settings
        self.tzinfo = ZoneInfo(self.settings['tz'])
        self.initLoggingFile()
        self.initDebug()
            
    def initLoggingFile(self):
        loggingfilename = os.path.dirname(os.path.realpath(__file__)) + "/record_mergeall"
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
                live = {'id_live': el['id_live'], 'idchannel': el['idchannel'], 'handlechannel': el['handlechannel'], 'idVideo': el['idVideo'],
                'dateFirstStart': el['dateFirstStart'], 'dateLastEnd': el['dateLastEnd'], 'dateStart_YTB': el['dateStart_YTB'], 'dateEnd_YTB': el['dateEnd_YTB'],
                'status_merging_all': el['status_merging_all'], 'status_merging_all_ffmpeg': el['status_merging_all'],
                'date_status_merging_all': el['status_merging_all'], 'records': []}
                newlistElements.append(live)
            
            record = {'id_record': el['id_record'], 'filenumber': el['filenumber'], 'dateStart': el['dateStart'], 'dateEnd': el['dateEnd'],
            'title': el['title'], 'status_recording': el['status_recording'], 'status_recording_streamlink': el['status_recording_streamlink'],
            'status_convert': el['status_convert'], 'status_convert_ffmpeg': el['status_convert_ffmpeg'], 'date_status_convert': el['date_status_convert']}
            live['records'].append(record)
            
            last_live = live
        
        return newlistElements

    def merge_mp4files(self, live, mp4files):   
        idVideo = live['idVideo']
        file_list = self.settings['folder_recording'] + 'filelist_' + live['idchannel'] + '.' + idVideo + '.txt'
        finalmp4file = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.mp4'

        print(f"id_live={live['id_live']} idVideo={idVideo}) Starting merge of mp4 files...")
        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Starting merge of mp4 files...", 'normal')
        
        merge = subprocess.Popen([self.settings['path_ffmpeg'] + 'ffmpeg', "-f", "concat", "-safe", "0", "-i", file_list, "-c" , "copy", finalmp4file],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        merge.wait()
            
        # Get duration of .ts file : goal is to detect diff in official stream duration, records in DB and duration of .ts file, and duration of merged mp4
        # To get only duration with no other info : ffprobe -v error -show_entries format=duration -sexagesimal -of default=noprint_wrappers=1:nokey=1 <file>
        # cf https://trac.ffmpeg.org/wiki/FFprobeTips#Formatcontainerduration
        durationMP4 = None
        processGetInfoMP4 = subprocess.Popen([self.settings['path_ffmpeg'] + 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-sexagesimal', '-of',
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
            print(f"id_live={live['id_live']} idVideo={idVideo}) Merge was done without error")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo}) Merge was done without error")
            
            live['status_merging_all'] = "finished"
            os.remove(file_list)
            for mp4file in mp4files:
                if os.path.basename(mp4file) != os.path.basename(finalmp4file):
                    print("delete file " + mp4file)
                    os.remove(mp4file)
        else:
            # It would be nice to get stdout of merge command, see record_channel.py in recordLive() function around line stdout, stderr = processGetInfoTS.communicate()
            print(f"id_live={live['id_live']} idVideo={idVideo}) Merge had error : {merge.returncode}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo}) Merge had error : {merge.returncode}", 'normal')
            live['status_merging_all'] = "error"

        # UPDATE live with new status of merging and duration of merge .mp4 file
        # HOW TO : https://stackoverflow.com/questions/11517106/how-to-update-mysql-with-python-where-fields-and-entries-are-from-a-dictionary
        params = {"status_merging_all": live["status_merging_all"], "status_merging_all_ffmpeg": live['status_merging_all_ffmpeg'],
        "date_status_merging_all": live["date_status_merging_all"], "status_merging_all_duration": live["status_merging_all_duration"],
        "status_merging_all_duration_ffprobe": live["status_merging_all_duration_ffprobe"]}

        try:
            connection = self.db.getConnection()
            cursor = connection.cursor(prepared=True, dictionary=True)
            update_live_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
            cursor.execute(update_live_query, list(params.values()))
            connection.commit()
            cursor.close()
        except Error as ex:
            print(f"id_live={live['id_live']} idVideo={idVideo}) Mysql Error UPDATE live with new status of merging : {ex}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo}) Mysql Error UPDATE live with new status of merging : {ex}", 'normal')
            self.exitProgram()              
        
        # *************** Main program ******************
    def main(self):
        print("Starting program")
        self.writelog("Starting program")
        self.initDatabase()
        
        # SELECT lives not merges yet, having finished records // We also want .ts not converted to mp4, to try to convert .ts here
        # If one merge for a stream had a problem, to get another attempt manually delete status_merging* columns in lives table

        lives_notmerged = []
        mergeThreadList = []
        try:
            connection = self.db.getConnection()
            select_lives_query = """SELECT * FROM lives, records WHERE lives.id_live = records.id_live
            AND lives.status_merging_all_ffmpeg IS NULL
            ORDER BY lives.id_live, records.id_record ASC"""
            cursor = connection.cursor(prepared=True, dictionary=True)
            params = {}
            cursor.execute(select_lives_query, params)
            lives_notmerged = cursor.fetchall()
            if len(lives_notmerged) == 0:
                print("No live with no merging attempt found")
                self.writelog("No live with no merging attempt found", 'normal')
                self.exitProgram()
            else:
                # Assemble an array with lives as parents and records as children
                lives_notmerged = self.arrangeListRecords(lives_notmerged)
            cursor.close()
        except Error as ex:
            print(f"Mysql Error SELECT lives where ffmpeg process has been recorded in database : {ex}")
            self.writelog(f"Mysql Error SELECT lives where ffmpeg process has been recorded in database : {ex}", 'normal')
            self.exitProgram()

        print("Browse lives to merge")
        self.writelog("Browse lives to merge", 'normal')

        # Loop on lives not merged
        for live in lives_notmerged:
            idVideo = live['idVideo']
            
            print('\n')
            print(f"id_live={live['id_live']} idVideo={idVideo} Live is not merged")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Live is not merged", 'normal')

            # Get last streams of channel
            streams = scrapetube.get_channel(live['idchannel'], content_type="streams", limit=30, sort_by="newest")

            # Get last record of live from DB
            lastRecord = live['records'][len(live['records']) - 1]
            print(f"id_live={live['id_live']} idVideo={idVideo} lastRecord : {lastRecord}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastRecord : {lastRecord}", 'normal')
            
            # Debug info from last record
            lastfilenumber = lastRecord['filenumber'] 
            lastmp4file = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.' + lastfilenumber + '.mp4'
            lastchatfile = self.settings['folder_recording'] + 'chat_' + live['idchannel'] + '.' + idVideo + '.' + lastfilenumber + '.txt'
            print(f"id_live={live['id_live']} idVideo={idVideo} lastmp4file : {lastmp4file}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastmp4file : {lastmp4file}", 'normal')
            print(f"id_live={live['id_live']} idVideo={idVideo} lastchatfile : {lastchatfile}")
            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} lastchatfile : {lastchatfile}", 'normal')

            # Check if live is streaming right now and not a republish // can be replaced by call to Youtube API V3 /videos
            # and check "liveStreamingDetails"->"liveBroadcastContent" == "live", see chat.py
            # 2 streams can be running at the same time on same channel
            isRunning = False
            for stream in streams:
                if idVideo == stream['videoId'] and 'runs' in stream['thumbnailOverlays'][0]['thumbnailOverlayTimeStatusRenderer']['text']:
                    isRunning = True
                    break    

            # Before trying to merge mp4 together, we make sure all .ts are converted to .mp4 (case of crash of record.py or error in merge process in record.py)
            # We assure that live is not running + wait seconds_before_merge seconds before doing that, because otherwise a stream can be running at the time of the cron
            # and a current .ts can wrongly be converted to .mp4
            if isRunning is False:
                tsfiles = []
                mp4files = []
                chatfiles = []
                for record in live['records']:
                    tsfile = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.' + record['filenumber'] + '.ts'
                    if os.path.isfile(tsfile):
                        print(f"id_live={live['id_live']} idVideo={idVideo} .ts file present : {tsfile}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} .ts file present : {tsfile}", 'normal')                        
                        tsfiles.append(tsfile)
                        
                    mp4file = self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.' + record['filenumber'] + '.mp4'
                    if os.path.isfile(mp4file):
                        print(f"id_live={live['id_live']} idVideo={idVideo} .mp4 file present : {mp4file}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} .mp4 file present : {mp4file}", 'normal')
                        mp4files.append(mp4file)
                    
                    chatfile = self.settings['folder_recording'] + 'chat_' + live['idchannel'] + '.' + idVideo + '.' + record['filenumber'] + '.txt'
                    if os.path.isfile(chatfile):
                        print(f"id_live={live['id_live']} idVideo={idVideo} .txt file present : {chatfile}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} .txt file present : {chatfile}", 'normal')
                        chatfiles.append(chatfile)
                
                # UPDATE live with dateEnd_YTB if empty
                dateEnd_YTB = None
                if live['dateEnd_YTB'] is None:
                    videosInfosURL = "https://www.googleapis.com/youtube/v3/videos?key=" + self.settings['youtubeKey'] + "&id=" + idVideo + \
                    "&part=snippet,contentDetails,statistics,liveStreamingDetails"
                    print(videosInfosURL)
                    try:
                        response = requests.get(videosInfosURL)
                        if response.status_code == 200:
                            videosInfosResponse = response.text
                            video_json = json.loads(videosInfosResponse)       
                            item = video_json.get('items')[0]
                            actualEndTime = item.get('liveStreamingDetails').get('actualEndTime')
                            # Convert datetime iso 2025-12-06T17:30:42Z to 2025-12-06 17:30:42
                            actualEndTime_object = dateutil.parser.isoparse(actualEndTime)
                            dateEnd_YTB = actualEndTime_object.astimezone(self.tzinfo).strftime(self.settings['dateFormats']['dateDBString'])
                    except Exception as e:
                        # Not a problem if something's wrong in this request
                        print(f"id_live={live['id_live']} idVideo={idVideo} Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo}Error getting actualEndTime from Youtube API V3 videosInfosURL {videosInfosURL} : {e}", 'normal')                        
                
                    if dateEnd_YTB is not None:
                        params['dateEnd_YTB'] = dateEnd_YTB
                        try:
                            connection = self.db.getConnection()
                            cursor = connection.cursor(prepared=True, dictionary=True)
                            update_live_query = 'UPDATE lives SET {values} WHERE id_live = {id_live}'.format(values=', '.join('{}=%s'.format(keys) for keys in params), id_live=live["id_live"])
                            cursor.execute(update_live_query, list(params.values()))
                            connection.commit()
                            cursor.close()
                        except Error as ex:
                            print(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with dateEnd_YTB if empty : {ex}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Mysql Error UPDATE live with dateEnd_YTB if empty : {ex}", 'normal')
                            self.exitProgram()
                
                # Convert remaining .ts to .mp4
                for tsfile in tsfiles:
                    timestamp_now = datetime.now().timestamp()
                    time_diff_seconds = timestamp_now - os.path.getmtime(tsfile)
                    if time_diff_seconds > self.settings['seconds_before_merge']:
                        print(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is older than {self.settings['seconds_before_merge']} seconds but still present : {tsfile}, we convert it to mp4")
                        log(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is older than {self.settings['seconds_before_merge']} seconds but still present : {tsfile}, we convert it to mp4", 'normal')
                        mp4file = tsfile.replace('.ts', '.mp4')
                        merge = subprocess.Popen([dirnameWorking + '/ffmpeg', "-i", tsfile, "-c", "copy", mp4file],
                        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
                        merge.wait()
                        
                        if merge.returncode == 0 and os.path.isfile(mp4file) is True:
                            os.remove(tsfile)
                    else:
                        print(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is younger than {self.settings['seconds_before_merge']} seconds so we don't do anything : {tsfile}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Live is not running, .ts is younger than {self.settings['seconds_before_merge']} seconds so we don't do anything : {tsfile}", 'normal')
                    
                # Warning, dont't rename chat file too soon as viewers can still write message after stream ended on YTB
                # If we have only one chat file, we rename it without filenumber
                if len(chatfiles) == 1 and os.path.isfile(lastchatfile):
                    print(f"id_live={live['id_live']} idVideo={idVideo} One chat file found : {chatfiles[0]}")
                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} One chat file found : {chatfiles[0]}", 'normal')
                    
                    timestamp_now = datetime.now().timestamp()
                    time_diff_seconds = timestamp_now - os.path.getmtime(lastchatfile)
                    if time_diff_seconds > self.settings['seconds_before_rename_chat']:
                        print(f"id_live={live['id_live']} idVideo={idVideo} We rename chat file : {lastchatfile}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} We rename chat file : {lastchatfile}")
                        os.rename(lastchatfile, self.settings['folder_recording'] + 'chat_' + live['idchannel'] + '.' + idVideo + '.txt')
                    else:
                        print(f"id_live={live['id_live']} idVideo={idVideo} Chat file is not older than {self.settings['seconds_before_rename_chat']} seconds, we do not rename chat file : {lastchatfile}")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Chat file is not older than {self.settings['seconds_before_rename_chat']} seconds, we do not rename chat file : {lastchatfile}", 'normal')
               
                # To merge mp4s, we need more than one mp4 file. If only one mp4, we only rename .001.mp4 to .mp4 and exit
                # mp4 files are sorted by id_record ASC
                if len(mp4files) == 0:
                    print(f"id_live={live['id_live']} idVideo={idVideo} No mp4 file found, we skip")
                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} No mp4 file found, we skip")
                    continue
                # We rename the only 001.mp4 (no check in DB, we use filesystem) to .mp4 if it's older than seconds_before_merge seconds and live is not running
                # We don't use records in DB because there are cases where it's not accurate rely on DB, such as
                # stream is still up but is "circling" without audio/video and people still send messages in chat
                elif len(mp4files) == 1:
                    print(f"id_live={live['id_live']} idVideo={idVideo} One mp4 found {mp4files[0]}, we try to rename and skip")
                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} One mp4 found {mp4files[0]}, we try to rename and skip", 'normal')
                    
                    if os.path.isfile(mp4files[0]):
                        timestamp_now = datetime.now().timestamp()
                        time_diff_seconds = timestamp_now - os.path.getmtime(mp4files[0])
                        if time_diff_seconds > self.settings['seconds_before_merge']:
                            print(f"id_live={live['id_live']} idVideo={idVideo} We rename mp4 file {mp4files[0]}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} We rename mp4 file {mp4files[0]}")
                            os.rename(mp4files[0], self.settings['folder_recording'] + 'video_' + live['idchannel'] + '.' + idVideo + '.mp4')
                        else:
                            print(f"id_live={live['id_live']} idVideo={idVideo} mp4 file is not older than {self.settings['seconds_before_merge']} seconds, we do not rename mp4 file : {mp4files[0]}")
                            self.writelog(f"id_live={live['id_live']} idVideo={idVideo} mp4 file is not older than {self.settings['seconds_before_merge']} seconds, we do not rename mp4 file : {mp4files[0]}", 'normal')
                    continue

                # Check if merge of all mp4 is not ongoing or finished
                if live['status_merging_all'] is not None:
                    print(f"id_live={live['id_live']} idVideo={idVideo} No merging to do, actual status_merging_all is : {live['status_merging_all']}")
                    self.writelog(f"id_live={live['id_live']} idVideo={idVideo} No merging to do, actual status_merging_all is : {live['status_merging_all']}", 'normal')
                    continue

                # Check if last filenumber mp4 is older than seconds_before_merge seconds, to make sure stream has ended and mp4 convert had the time
                if os.path.isfile(lastmp4file):
                    timestamp_now = datetime.now().timestamp()
                    time_diff_seconds = timestamp_now - os.path.getmtime(lastmp4file)
                    if time_diff_seconds <= self.settings['seconds_before_merge']:
                        print(f"id_live={live['id_live']} idVideo={idVideo} Last mp4 file is only {time_diff_seconds} seconds old, we skip")
                        self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Last mp4 file is only {time_diff_seconds} seconds old, we skip")
                        continue
                            
                # *************** Merging mp4 ******************
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
                print(f"id_live={live['id_live']} idVideo={idVideo} Stream is still up on Youtube, we skip")
                self.writelog(f"id_live={live['id_live']} idVideo={idVideo} Stream is still up on Youtube, we skip", 'normal')
                continue

        # Wait for all mp4 merges to finish
        for mergeThread in mergeThreadList:
            mergeThread.join()

        print("Execution was OK")
        self.writelog("Execution was OK")
        print("Ending program")
        self.writelog("Ending program")
        self.clean()

if __name__ == "__main__":
    settings = {
        # Youtube
        'youtubeKey': '', # YouTube API Key from Google Cloud, see https://helano.github.io/help.html
        # Format
        'tz': 'Europe/Paris',
        'dateFormats': {'dateString': '%d/%m/%Y %H:%M:%S', 'dateDBString': '%Y-%m-%d %H:%M:%S', 'dateFileString': '%d%m%Y%H%M%S'},
        # Converting and renaming
        'path_ffmpeg': os.path.dirname(os.path.realpath(__file__)) + '/', # Add / at the end, same directory for ffmpeg and ffprobe
        'folder_recording': os.path.dirname(os.path.realpath(__file__)) + '/files/', # Add / at the end
        'seconds_before_rename_chat': 60*10, # 10 minutes
        'seconds_before_merge': 60*5, # 5 minutes
        # MySQL connection
        'params_database': {'mysql_host': '', 'mysql_database': '',
        'mysql_user': '',
        'mysql_pwd': ''},
        # Debug
        'level_debug_selected': 'debug' # 'debug' or 'normal' for minimal log
    }
    
    program = Program(settings)
    program.main()
