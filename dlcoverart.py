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

TMPDIR=tempfile.mkdtemp(prefix='ponyfm-dlcoverart-tmp')
CMD_HAS_COVER = 'ffprobe 2>/dev/null -show_streams '
CMD_YT_DOWNLOAD = 'youtube-dl --write-thumbnail --skip-download -o '+os.path.join(TMPDIR, 'coverpre.jpg')+' '
CMD_YT_CROP = 'convert '+os.path.join(TMPDIR, 'coverpre.jpg')+' -fuzz 5% -trim '+os.path.join(TMPDIR, 'cover.jpg')
CMD_GENERIC_DOWNLOAD = 'curl 2>/dev/null -o '+os.path.join(TMPDIR, 'cover.jpg')+' '
CMD_CVT_MP3_1 = 'ffmpeg 2>/dev/null -y -map 0 -map 1 -map_metadata 1 -c:a copy -c:v copy '+os.path.join(TMPDIR, 'tmpsong.mp3')+' -i '+os.path.join(TMPDIR, 'cover.jpg')+' -i '
CMD_CVT_MP3_2 = 'mv '+os.path.join(TMPDIR, 'tmpsong.mp3')+' '
CMD_CVT_FLAC = 'metaflac --import-picture-from='+os.path.join(TMPDIR, 'cover.jpg')+' '
LIST_VIDEOS_CMD='youtube-dl --skip-download --youtube-skip-dash-manifest -i 2>/dev/null --get-filename -o "%(id)s %(title)s" '
VIDEO_BASE_URL = 'https://www.youtube.com/watch?v='
SOUNDCLOUD_BORROWED_CLIENT_ID = '91f71f725804f4915f4cc95f69fff503' # First result for a public token on Github search!

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

def downloadCoverArt(track):
    try:
        if track['type'] == 'youtube':
            subprocess.check_output(CMD_YT_DOWNLOAD+'"'+VIDEO_BASE_URL+track['id']+'"', shell=True)
            subprocess.check_output(CMD_YT_CROP, shell=True)
            return True
        elif track['type'] == 'bandcamp' or track['type'] == 'soundcloud':
            subprocess.check_output(CMD_GENERIC_DOWNLOAD+'"'+track['artUrl']+'"', shell=True)            
            return True
        else:
            print('Unknown track type! ('+track['type']+')')
            sys.exit(-1)
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

def processMatchingTrack(track, localFile):
    localPath = localFile['path']
    baseName = localFile['baseName']
    if hasCoverArt(localPath):
        print('Already have cover art for '+baseName)
        return
    print('Downloading cover art for '+baseName)
    if not downloadCoverArt(track):
        return
    addCoverArt(localFile)        

def findMatch(localFile, tracks):
    for track in tracks:
        videoTitleElems = [track['fullTitle']] + track['fullTitle'].split('-') + track['fullTitle'].split('~')
        for videoTitleElem in videoTitleElems:
            canonFragment = removeFeats(canonicalizeTitle(videoTitleElem)).strip()
            if canonFragment == localFile['canonTitle']:
                processMatchingTrack(track, localFile)
                return True
    return False

def listYoutubeVideos(url):
    print('Getting channel videos list...')
    ytVideos = []
    try:
        output = subprocess.check_output(LIST_VIDEOS_CMD+'"'+webUrl+'" || true', shell=True).decode()
        for line in output.split('\n'):
            elems = line.split(' ', 1)
            if len(elems) == 2:
                ytVideos.append({
                    'type': 'youtube',
                    'id': elems[0],
                    'fullTitle': elems[1],
                    'canonTitle': canonicalizeTitle(elems[1])
                })
        return ytVideos
    except Exception as e:
        print('Failed to channel video list')
        print(e)
        sys.exit(-1)

def getBandcampAlbumTitles(albumUrl):
    html = urllib.request.urlopen(albumUrl).read().decode('utf-8')
    titles = []
    curpos = 0
    while True:
        curpos = html.find('<span itemprop="name">', curpos)
        if curpos == -1:
            break
        curpos += len('<span itemprop="name">')
        titles.append(html[curpos:html.find('<', curpos)])
    return titles

def listBandcampTracks(url):
    print('Getting Bandcamp track list...')
    baseUrl = url.replace('/music', '')
    trackList = []
    html = urllib.request.urlopen(url).read().decode('utf-8')
    curpos = 0
    while True:
        curpos = html.find('href="/', curpos)
        if curpos == -1:
            break
        curpos += len('href="')
        linkUrl = html[curpos:html.find('"', curpos)]
        trackTitles = []
        if linkUrl.startswith('/track'):
            titlePos = html.find('class="title">', curpos) + len('class="title">')
            if titlePos == -1:
                print('Failed to get title of track '+linkUrl)
                continue
            title = html[titlePos:html.find('<', titlePos)].strip()
            trackTitles.append(title)
        elif linkUrl.startswith('/album'):
            trackTitles.extend(getBandcampAlbumTitles(baseUrl+linkUrl))
        else:
            continue
        
        artClassPos = html.find('class="art', curpos)
        if artClassPos == -1:
            print('Failed to find album art tag! Is our cheap-ass parser broken?')
            sys.exit(-1)
        curpos = artClassPos + len('class="art')
        if html[curpos:curpos+6] == ' empty':
            print('No album art for '+linkUrl)
            continue
        artUrlPos = html.find('src="', curpos) + len('src="')
        artUrl = html[artUrlPos:html.find('"', artUrlPos)]
        if artUrl == '/img/0.gif':
            # Lazy loading
            artUrlPos = html.find('data-original="', curpos) + len('data-original="')
            artUrl = html[artUrlPos:html.find('"', artUrlPos)]
        
        for title in trackTitles:
            trackList.append({
                'type': 'bandcamp',
                'fullTitle': title,
                'canonTitle': canonicalizeTitle(title),
                'artUrl': artUrl,
            })
    return trackList

def listSoundcloudTracks(url):
    print('Getting Soundcloud track list...')
    trackList = []
    client = soundcloud.Client(client_id=SOUNDCLOUD_BORROWED_CLIENT_ID)
    user = client.get('/resolve', url=url)
    tracks = client.get('/users/'+str(user.id)+'/tracks')
    
    for track in tracks:
        title = track.title
        trackList.append({
            'type': 'soundcloud',
            'fullTitle': title,
            'canonTitle': canonicalizeTitle(title),
            'artUrl': track.artwork_url,
        })
    
    return trackList

if len(sys.argv) != 2:
    print('Usage: '+sys.argv[0]+' <path>')
    sys.exit(-1)
srcDir = sys.argv[1]
webUrl = input('Track list URL: ')

if 'www.youtube.com/' in webUrl:
    tracks = listYoutubeVideos(webUrl)
elif '.bandcamp.com/' in webUrl:
    tracks = listBandcampTracks(webUrl)
elif 'soundcloud.com/' in webUrl:
    tracks = listSoundcloudTracks(webUrl)
else:
    print('Invalid URL. Youtube, Bandcamp and Soundcloud are supported.')
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

noMatchCount = 0
for localFile in localFiles:
    if not findMatch(localFile, tracks):
        noMatchCount += 1

if noMatchCount != 0:
    print('No match found for '+str(noMatchCount)+' local files')

shutil.rmtree(TMPDIR, ignore_errors=True)
