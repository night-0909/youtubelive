# youtubelive
Automatic recording of youtube lives with chat with Mysql database

- recordytb.sql : creation of Mysql tables.<br />
- record_channel.py : record stream and chat of lives of a Youtube channel.<br />
For video, it uses yt-dlp (recommended) or streamlink to record stream. See https://github.com/yt-dlp/yt-dlp and  https://github.com/streamlink/streamlink<br />
For chat, it uses chat_downloader. See https://github.com/xenova/chat-downloader<br />

Read documentation of these two softwares and if an issue occurs search in their Github repository.<br />
yt-dlp and chat_downloader can use Youtube cookies.<br />
Procedure to export cookies from Youtube : read https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies and https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp

- record_process.py : merge all mp4 for each recorded live and do some files renaming<br />
**Warning :** this script may mess up things in edgy cases, so be cautious using it.
If you don't use it, you'll need to merge manually all .mp4 files with ffmpeg for instance.

- chat_downloader module : I made some changes, see my version https://github.com/night-0909/chat-downloader<br/>
Timezone and date format can be set in chat_downloader\formatting\custom_formats.json and at the end of record_channel.py and record_process.py<br />

- scrapetube module : I made some changes, see my version https://github.com/night-0909/scrapetube<br/>

**General principles :**
- **record_channel.py** : setup a cron every minute.<br />
This script checks every 5 seconds (setting wait_before_retry) if there'a new live for a Youtube channel.<br/>
It handles the case where more than streams are running at the same time by using two method to detect streams :
- scrape https://youtube.com/{idchannel}/live : it detect only last started stream. Delay in detection is low (0 sec to 10-15) as Youtube is quick.<br>
- scrape https://youtube.com/{idchannel}/streams : it detect all started streams. Delay in detection is more than 30 sec as Youtube has this latency
to mark a stream as running in https://youtube.com/{idchannel}/streams url.

If recording hasn't started yet, it creates :<br />
- for chat recording : chat.idchannel.idvideo.XXX.txt (contains messages), chat_downloader.idchannel.idvideo.XXX.txt (contains exceptions and messages)<br />
- for video recording :<br />
streamlink : video.idchannel.idvideo.XXX.ts, streamlink.idchannel.idvideo.XXX.txt<br />
yt-dlp : video.idchannel.idvideo.XXX.fYYY.mp4, yt-dlp.idchannel.idvideo.XXX.txt<br />

At the end of the recording, for streamlink I convert ts file to mp4.<br />
If there're some lagging/network connection problems, streamlink will exit after 120s timeout and record_channel.py will try every 5 sec to record stream/chat.
yt-dlp has some retries too.<br />
So you can end up with multiple files : video.idchannel.idvideo.001.ts, streamlink.idchannel.idvideo.001.txt, video.idchannel.idvideo.002.ts, streamlink.idchannel.idvideo.002.txt, etc...<br />
 streamlink.001.log/video.001.mp4/chat.001.txt, streamlink.002.log/video.002.mp4/chat.002.txt, etc...<br />

It also gathers starttime and endtime of stream from Youtube API V3.<br />

- **record_process.py** : setup a cron every 10 min or something.<br />
For lives recorded with streamlink, this script first converts remaining .ts files in .mp4 files.
Then it merges all mp4 in one mp4 for each recorded stream. If there's only one recording for a stream,
it renames video.idchannel.idvideo.001.mp4 to video.idchannel.idvideo.mp4 and same thing for chat file<br />
If there's more than one chat file, it's up to you to manually check and rebuild all messages.<br />

For lives recorded with yt-dlp, format files (fYYY.mp4) are not deleted by security, letting user verify/try to merge again format files in case of problems.

**How to reprocess a live ?**<br />
If you want to reprocess chat processing, clear status_rename_chat field in lives table.<br />
For video processing, clear status_merging_all fields in same table.

**How to detect problems ?**<br />
See record_idchannel.log, yt-dlp_XXX.log, streamlink_XXX.log, chat_downloader_XXX.log, record_process.log and database records.

**Limitations :**<br />
- If you are too agressive (eg. using live_url discovery_method too often), Youtube can detect you as a bot and you'll need to wait, change IP address,
or use cookies from a Youtube account.
- streamlink can't use Youtube cookies at the moment, so use yt-dlp. With cookies, you can bypass bot detection more easily and access
to members-only streams and +18y streams.


