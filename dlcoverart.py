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
import binascii
from html import unescape
from time import sleep

tracks = []
localFiles = []

TMPDIR=tempfile.mkdtemp(prefix='ponyfm-dlcoverart-tmp')
CMD_HAS_COVER = 'ffprobe 2>/dev/null -show_streams '
CMD_YT_DOWNLOAD = 'youtube-dl -i --write-thumbnail --skip-download -o '+os.path.join(TMPDIR, 'coverpre.jpg')+' '
CMD_YT_CROP = 'convert '+os.path.join(TMPDIR, 'coverpre.jpg')+' -fuzz 5%% -trim '+os.path.join(TMPDIR, 'cover%s.jpg')
CMD_GENERIC_DOWNLOAD = 'curl 2>/dev/null -o '+os.path.join(TMPDIR, 'cover%s.jpg')+' '
CMD_CVT_MP3_1 = 'ffmpeg 2>/dev/null -y -map 0 -map 1 -map_metadata 1 -c:a copy -c:v copy '+os.path.join(TMPDIR, 'tmpsong.mp3')+' -i '+os.path.join(TMPDIR, 'cover%s.jpg')+' -i '
CMD_CVT_MP3_2 = 'mv '+os.path.join(TMPDIR, 'tmpsong.mp3')+' '
CMD_CVT_FLAC = 'metaflac --import-picture-from='+os.path.join(TMPDIR, 'cover%s.jpg')+' '
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
            subprocess.check_output(CMD_YT_CROP % track['id'], shell=True)
            return True
        elif track['type'] == 'bandcamp' or track['type'] == 'soundcloud' or track['type'] == 'generic':
            subprocess.check_output((CMD_GENERIC_DOWNLOAD % track['id'])+'"'+track['artUrl']+'"', shell=True)            
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
            subprocess.check_output((CMD_CVT_MP3_1 % localFile['id'])+escapedSrcPath, shell=True)
            subprocess.check_output(CMD_CVT_MP3_2+escapedSrcPath, shell=True)
        elif songPath.endswith('.flac'):
            escapedSrcPath = "'"+songPath.replace("'", "'\\''")+"'"
            subprocess.check_output((CMD_CVT_FLAC % localFile['id'])+escapedSrcPath, shell=True)
        else:
            print("Couldn't add cover art to "+songPath+", unsupported file type!")
    except Exception as e:
        print('Failed to add cover art for '+songPath+' !')
        print(e)

def processMatchingTrack(track, localFile):
    localPath = localFile['path']
    baseName = localFile['baseName']
    if 'id' not in track:
        track['id'] = binascii.b2a_hex(os.urandom(15)).decode()
    localFile['id'] = track['id']
    
    if hasCoverArt(localPath):
        print('Already have cover art for '+baseName)
        return
    print('Downloading cover art for '+baseName)
    if not downloadCoverArt(track):
        return
    addCoverArt(localFile)        

def findMatch(localFile, tracks):
    for track in tracks:
        videoTitleElems = [track['fullTitle']] + track['fullTitle'].split('-') + track['fullTitle'].split('—') + track['fullTitle'].split('~')
        for videoTitleElem in videoTitleElems:
            canonFragment = canonicalizeTitle(videoTitleElem).strip()
            featlessCanonFragment = removeFeats(canonFragment).strip()
            if canonFragment == localFile['canonTitle'] or featlessCanonFragment == localFile['canonTitle']:
                processMatchingTrack(track, localFile)
                return True
    return False

def listYoutubeVideos(url):
    print('Getting channel videos list...')
    ytVideos = []
    try:
        output = subprocess.check_output(LIST_VIDEOS_CMD+'"'+url+'" || true', shell=True).decode()
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

def findBandcampArtUrl(html, pos):
    artClassPos = html.find('id="tralbumArt', pos) # If we are on an album page, this is the only cover art
    if artClassPos != -1:
        pos = artClassPos + len('id="tralbumArt')
    else:
        artClassPos = html.find('class="art', pos)
        pos = artClassPos + len('class="art')
    if artClassPos == -1:
        print('Failed to find album art tag! Is our cheap-ass parser broken?')
        sys.exit(-1)
    if html[pos:pos+6] == ' empty':
        print('No album art for '+linkUrl)
        return None
    artUrlPos = html.find('src="', pos) + len('src="')
    artUrl = html[artUrlPos:html.find('"', artUrlPos)]
    if artUrl == '/img/0.gif':
        # Lazy loading
        artUrlPos = html.find('data-original="', pos) + len('data-original="')
        artUrl = html[artUrlPos:html.find('"', artUrlPos)]
    return artUrl

def getBandcampAlbumTracks(albumUrl):
    html = urllib.request.urlopen(albumUrl).read().decode('utf-8')
    tracks = []
    curpos = 0
    artUrl = findBandcampArtUrl(html, curpos)
    if artUrl is None:
        return tracks
    while True:
        curpos = html.find('<span class="track-title" itemprop="name">', curpos)
        if curpos == -1:
            break
        curpos += len('<span class="track-title" itemprop="name">')
        title = unescape(html[curpos:html.find('<', curpos)])
        tracks.append({
            'type': 'bandcamp',
            'fullTitle': title,
            'canonTitle': canonicalizeTitle(title),
            'artUrl': artUrl,
        })
    return tracks

def listBandcampTracks(url):
    print('Getting Bandcamp track list...')
    baseUrl = url[:url.find('bandcamp.com/')+len('bandcamp.com/')]
    trackList = []
    if 'bandcamp.com/album/' in url:
        return getBandcampAlbumTracks(url)
    
    html = urllib.request.urlopen(url).read().decode('utf-8')
    curpos = 0
    while True:
        curpos = html.find('href="/', curpos)
        if curpos == -1:
            break
        curpos += len('href="')
        linkUrl = html[curpos:html.find('"', curpos)]
        if linkUrl.startswith('/track'):
            titlePos = html.find('class="title">', curpos) + len('class="title">')
            if titlePos == -1:
                print('Failed to get title of track '+linkUrl)
                continue
            title = unescape(html[titlePos:html.find('<', titlePos)].strip())
            artUrl = findBandcampArtUrl(html, curpos)
            if artUrl is None:
                continue
            trackList.append({
                'type': 'bandcamp',
                'fullTitle': title,
                'canonTitle': canonicalizeTitle(title),
                'artUrl': artUrl,
            })
        elif linkUrl.startswith('/album'):
            trackList.extend(getBandcampAlbumTracks(baseUrl+linkUrl))
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

def dlCoverArt(srcDir, webUrl):
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


if __name__ == '__main__':
	if len(sys.argv) != 2:
		print('Usage: '+sys.argv[0]+' <path>')
		sys.exit(-1)
	srcDir = sys.argv[1]
	webUrl = input('Track list URL: ')
	dlCoverArt(srcDir, webUrl)
