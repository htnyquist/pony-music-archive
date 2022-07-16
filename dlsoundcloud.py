#!/usr/bin/python3

import urllib.request
import os
import sys
import json
import queue
import threading
import subprocess
import glob
import re
import random
import tempfile
import shutil
import soundcloud
from time import sleep

tracks = []
localFiles = []

TMPDIR=tempfile.mkdtemp(prefix='ponyfm-dlsoundcloud-tmp')
CMD_HAS_COVER = 'ffprobe 2>/dev/null -show_streams '
CMD_COVER_DOWNLOAD = 'curl 2>/dev/null -o '+os.path.join(TMPDIR, 'cover.jpg')+' '
CMD_CVT_MP3_1 = 'ffmpeg 2>/dev/null -y -map 0 -map 1 -map_metadata 1 -c:a copy -c:v copy '+os.path.join(TMPDIR, 'tmpsong.mp3')+' -i '+os.path.join(TMPDIR, 'cover.jpg')+' -i '
CMD_CVT_MP3_2 = 'mv '+os.path.join(TMPDIR, 'tmpsong.mp3')+' '
CMD_CVT_FLAC = 'metaflac --import-picture-from='+os.path.join(TMPDIR, 'cover.jpg')+' '
SOUNDCLOUD_BORROWED_CLIENT_ID = '91f71f725804f4915f4cc95f69fff503' # First result for a public token on Github search!

def hasCoverArt(filePath):
    try:
        escapedSrcPath = "'"+filePath.replace("'", "'\\''")+"'"
        result = subprocess.check_output(CMD_HAS_COVER+escapedSrcPath, shell=True)
        return 'DISPOSITION:attached_pic=1' in result.decode()
    except Exception as e:
        print('Failed to check '+filePath+' for cover art!')
        print(e)
        return True

def downloadCoverArt(track):
    try:
        subprocess.check_output(CMD_COVER_DOWNLOAD+'"'+track['artUrl']+'"', shell=True)            
        return True
    except Exception as e:
        print('Failed to download cover art !')
        print(e)
        return False

def addCoverArt(songPath):
    try:
        if songPath.endswith('.mp3'):
            escapedSrcPath = "'"+songPath.replace("'", "'\\''")+"'"
            subprocess.check_output(CMD_CVT_MP3_1+escapedSrcPath, shell=True)
            subprocess.check_output(CMD_CVT_MP3_2+escapedSrcPath, shell=True)
        elif songPath.endswith('.flac'):
            escapedSrcPath = "'"+songPath.replace("'", "'\\''")+"'"
            subprocess.check_output(CMD_CVT_FLAC+escapedSrcPath, shell=True)
        else:
            print("Couldn't add cover art to "+songPath+", unsupported file type!")
    except Exception as e:
        print('Failed to add cover art for '+songPath+' !')
        print(e)

def listSoundcloudTracks(client, user):
    print('Getting Soundcloud track list...')
    trackList = []
    
    tracks = client.get('/users/'+str(user.id)+'/tracks')
    
    for track in tracks:
        title = track.title
        dlUrl = track.download_url if track.downloadable else track.stream_url
        artUrl = track.artwork_url or user.avatar_url
        trackList.append({
            'type': 'soundcloud',
            'fullTitle': title,
            'artUrl': artUrl,
            'downloadUrl': dlUrl,
            'streamUrl': track.stream_url,
        })
    
    return trackList

def convertWavToFlac(filename):
    escapedFilename = "'"+filename.replace("'", "'\\''")+"'"
    flacFilename = filename[:-4] + '.flac'
    escapedFlacFilename = "'"+flacFilename.replace("'", "'\\''")+"'"
    subprocess.check_output('ffmpeg 2>/dev/null -y -i '+escapedFilename+' '+escapedFlacFilename+' && rm '+escapedFilename, shell=True)

def downloadTrack(downloadUrl, fullTitle):
    reply = urllib.request.urlopen(downloadUrl+'?client_id='+SOUNDCLOUD_BORROWED_CLIENT_ID)
    disp = reply.getheader('Content-Disposition')
    if disp == None:
        ct = reply.getheader('Content-Type')
        mimeToExt = {'audio/mpeg': 'mp3', 'audio/x-wav': 'wav'}
        if ct in mimeToExt:
            filename = fullTitle+'.'+mimeToExt[ct]
        else:
            filename = fullTitle+'.???'
    else:
        filename = fullTitle + '.' + disp[disp.find('"')+1:disp.rfind('"')].rsplit('.', 1)[1]
    filename = filename.replace('/', '-')
    if filename.startswith(artistName+' - '):
        filename = filename[len(artistName+' - '):]
    flacFilename = baseFileName = os.path.basename(filename).rsplit('.', 1)[0] + '.flac'
    targetFilename = filename
    if filename.endswith('.wav') or os.path.exists(flacFilename):
        targetFilename = flacFilename
    if os.path.exists(targetFilename):
        print('File "'+targetFilename+'" already exists, skipping download')
    else:
        print('Downloading "'+filename+'"')
        with open(filename, 'wb+') as out:
            out.write(reply.read())
    
        if filename.endswith('.wav'):
            convertWavToFlac(filename)
    
    if not hasCoverArt(targetFilename):
        print('Downloading cover art for '+targetFilename)
        if downloadCoverArt(track):
            addCoverArt(targetFilename)

if len(sys.argv) != 2:
    print('Usage: '+sys.argv[0]+' <path>')
    sys.exit(-1)
srcDir = sys.argv[1]
webUrl = input('Soundcloud URL: ')

if not 'soundcloud.com/' in webUrl:
    print('Invalid URL.')
    sys.exit(-1)

client = soundcloud.Client(client_id=SOUNDCLOUD_BORROWED_CLIENT_ID)
user = client.get('/resolve', url=webUrl)
artistName = user.username
tracks = listSoundcloudTracks(client, user)

for track in tracks:
    try:
        downloadTrack(track['downloadUrl'], track['fullTitle'])
        continue
    except Exception as e:
        print('Failed to download track ('+str(e)+'), retrying with stream URL')
        pass
    
    try:
        downloadTrack(track['streamUrl'], track['fullTitle'])
    except Exception as e:
        print('Failed to download track "'+track['fullTitle']+'", giving up')

shutil.rmtree(TMPDIR, ignore_errors=True)
