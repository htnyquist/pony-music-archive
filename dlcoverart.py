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
from time import sleep

videos = []
localFiles = []

TMPDIR=tempfile.mkdtemp(prefix='ponyfm-dlcoverart-tmp')
CMD_HAS_COVER = 'ffprobe 2>/dev/null -show_streams '
CMD_DOWNLOAD = 'youtube-dl --write-thumbnail --skip-download -o '+os.path.join(TMPDIR, 'coverpre.jpg')+' '
CMD_CROP = 'convert '+os.path.join(TMPDIR, 'coverpre.jpg')+' -fuzz 5% -trim '+os.path.join(TMPDIR, 'cover.jpg')
CMD_CVT_MP3_1 = 'ffmpeg 2>/dev/null -y -map 0 -map 1 -map_metadata 1 -c:a copy -c:v copy '+os.path.join(TMPDIR, 'tmpsong.mp3')+' -i '+os.path.join(TMPDIR, 'cover.jpg')+' -i '
CMD_CVT_MP3_2 = 'mv '+os.path.join(TMPDIR, 'tmpsong.mp3')+' '
CMD_CVT_FLAC = 'metaflac --import-picture-from='+os.path.join(TMPDIR, 'cover.jpg')+' '
LIST_VIDEOS_CMD='youtube-dl --skip-download --youtube-skip-dash-manifest -i 2>/dev/null --get-filename -o "%(id)s %(title)s" '
VIDEO_BASE_URL = 'https://www.youtube.com/watch?v='

def removeParens(title):
    depth = 0
    result = ''
    lastStart = 0
    for i, c in enumerate(title):
        if c in '([{':
            if depth == 0:
                result += title[lastStart:i]
            depth += 1
        if c in ')]}':
            depth -= 1
            if depth == 0:
                lastStart = i+1
    if depth == 0:
        result += title[lastStart:]
    return result.strip()

def simplifyCharset(title):
    superfluous = "´'’!?*/⁄\\★-_:\"&"
    result = title
    for c in superfluous:
        result = result.replace(c, ' ')
    return result

def removePrefixes(title):
    fluff = ["mlp-fim"]
    for prefix in fluff:
        if title.startswith(prefix):
            return title[len(prefix):]
    return title

def canonicalizeTitle(title):
    title = simplifyCharset(title.lower())
    title = removeParens(title)
    title = removePrefixes(title)
    return re.sub( '\s+', ' ', title).strip()

def removeFeats(titleFragment):
    for feat in ['feat.', 'feat', 'ft.', 'ft']:
        spacedFeat = ' '+feat+' '
        pos = titleFragment.find(spacedFeat)
        if pos != -1:
            return titleFragment[:pos]
    return titleFragment

def hasCoverArt(filePath):
    try:
        escapedSrcPath = "'"+filePath.replace("'", "'\\''")+"'"
        result = subprocess.check_output(CMD_HAS_COVER+escapedSrcPath, shell=True)
        return 'DISPOSITION:attached_pic=1' in result.decode()
    except Exception as e:
        print('Failed to check '+filePath+' for cover art!')
        print(e)
        return True

def downloadCoverArt(video):
    try:
        subprocess.check_output(CMD_DOWNLOAD+'"'+VIDEO_BASE_URL+video['id']+'"', shell=True)
        subprocess.check_output(CMD_CROP, shell=True)
        return True
    except Exception as e:
        print('Failed to download cover art !')
        print(e)
        return False

def addCoverArt(localFile):
    songPath = localFile['path']
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

def processMatchingVideo(video, localFile):
    localPath = localFile['path']
    baseName = localFile['baseName']
    if hasCoverArt(localPath):
        print('Already have cover art for '+baseName)
        return
    print('Downloading cover art for '+baseName)
    if not downloadCoverArt(video):
        return
    addCoverArt(localFile)        

def findMatch(localFile, videos):
    for video in videos:
        videoTitleElems = [video['fullTitle']] + video['fullTitle'].split('-') + video['fullTitle'].split('~')
        for videoTitleElem in videoTitleElems:
            canonFragment = removeFeats(canonicalizeTitle(videoTitleElem)).strip()
            if canonFragment == localFile['canonTitle']:
                processMatchingVideo(video, localFile)
                return
    print('No matching video found for '+localFile['baseName'])

if len(sys.argv) != 2:
    print('Usage: '+sys.argv[0]+' <path>')
    sys.exit(-1)
srcDir = sys.argv[1]
channelUrl = input('Channel URL: ')

print('Getting channel videos list...')
try:
    output = subprocess.check_output(LIST_VIDEOS_CMD+'"'+channelUrl+'" || true', shell=True).decode()
    for line in output.split('\n'):
        elems = line.split(' ', 1)
        if len(elems) == 2:
            videos.append({
                'id': elems[0],
                'fullTitle': elems[1],
                'canonTitle': canonicalizeTitle(elems[1])
            })
except Exception as e:
    print('Failed to channel video list')
    print(e)
    sys.exit(-1)

for pathit in glob.iglob(srcDir+'/**', recursive=True):
    srcPath = str(pathit)
    if not os.path.isfile(srcPath):
        continue

    baseName = os.path.basename(srcPath).rsplit('.', 1)[0]
    canonTitle = canonicalizeTitle(baseName)
    
    localFiles.append({
        'path': srcPath,
        'baseName': baseName,
        'canonTitle': canonTitle,
    })

for localFile in localFiles:
    findMatch(localFile, videos)

shutil.rmtree(TMPDIR, ignore_errors=True)
