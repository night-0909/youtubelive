# youtubelive
Automatic recording of youtube lives with chat

- record_channel.py : record stream and chat of lives of a Youtube channel with<br />
It uses streamlink to record stream. See https://github.com/streamlink/streamlink<br />
If streamlink has an issue, search on its github repository. yt-dlp can be used with small edits in my code.

- record_mergeall.py : merge all mp4 for each recorded live and do some files renaming<br />

- chat_downloader module : I made some changes, see https://github.com/night-0909/youtubecomments<br/>
When live is finished (not the case here), chat_downloader prints timecode (eg. 03:00) of each chat message.<br/>
But when live is ongoing (case here), chat_downloader prints datetime (2026-01-01 00:00:00) of each chat message.<br/>
To set your own datetime format, you need to set it in chat_downloader/formatting/custom_formats.json
using timestamp->format and timestamp->tz<br/>
For instance :
```{
    "default": {
        "template": "{time_text|timestamp}{author.badges}{money.text}{author.display_name|author.name} ({author.id}) {message}",
        "keys": {
            "time_text": "{} ",
            "timestamp": {
                "template": "{} : ",
                "format": "%d/%m/%Y %H:%M:%S",
                "tz": "Europe/Paris"
            },
```

**General principles :**
- **record_channel.py** : setup a cron every minute.<br />
This script check every 5 seconds (setting wait_before_retry) if there'a new live for a Youtube channel. If recording isn't done yet, it create 3 files :<br />
streamlink.001.log : log of streamlink in debug mode.<br />
video.001.ts : video stream.<br />
chat.001.txt : chat messages.<br />

At the end of the recording, I convert ts file to mp4.<br />
If there're some lagging/network connection problems, streamlink will exit after 120s timeout and record_channel.py will try every 5 sec to record stream/chat.<br />
So you can end up with multiple files : streamlink.001.log/video.001.mp4/chat.001.txt, streamlink.002.log/video.002.mp4/chat.002.txt, etc...<br />

It also gathers starttime and endtime of stream from Youtube API V3.<br />

- **record_mergeall.py** : setup a cron every 10 min or something.<br />
This script merges all mp4 for each recorded stream. If there's only one recording for a stream, it renames video.001.mp4 to video.mp4 and chat.001.txt to chat.txt<br />
It's up to you to manually check which chat files have all messages.<br />

- **recordytb.sql** : creation of tables (Mysql)

**How to detect problems ?**
See record_IDCHANNEL.log, streamlink_XXX.log and database records.
