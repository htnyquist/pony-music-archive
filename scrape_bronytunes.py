#!/usr/bin/python3

import urllib.request
import os
import sys
import json
import queue
import threading
import subprocess
import dlcoverart
from time import sleep

DL_URL = "https://bronytunes.com/retrieve_song.php?client_type=web&song_id="
META_URL = "https://bronytunes.com/retrieve_songs.php?client_type=web&song_id="
ART_URL = "https://bronytunes.com/retrieve_artwork.php?size=512&song_id="
SRC_FORMATS = [{"name": "FLAC", "ext": "flac"}, {"name": "MP3", "ext": "mp3"}]
DL_QUEUE_SIZE = 2
NUM_DOWNLOAD_THREADS = 5
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:86.0) Gecko/20100101 Firefox/86.0'}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

if len(sys.argv) < 2:
    print('Usage: '+sys.argv[0]+' <data dir>')
    sys.exit(-1)
DATA_DIR = sys.argv[1]

downloadQueue = queue.Queue()
downloadThreads = []
resumeFile = None
resumeFileLock = threading.Lock()

def createFolder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

def existsIgnoreCase(path):
    dirpath = os.path.dirname(path)
    lowfile = os.path.basename(path).lower()
    try:
        for entry in os.listdir(dirpath):
            if entry.lower() == lowfile:
                return True
    except:
        pass
    return False


def snapToExistingIgnoreCase(basepath, elem):
    """If the path already exists ignoring case, returns the existing path. 
    Otherwise returns the path with the case of the arguments
    """
    try:
        for entry in os.listdir(basepath):
            if entry.lower() == elem.lower():
                return os.path.join(basepath, entry)
    except:
        pass
    return os.path.join(basepath, elem)

def writeResumeState(id):
    global resumeFile
    global resumeFileLock
    resumeFileLock.acquire()
    try:
        resumeFile.seek(0)
        resumeFile.truncate(0)
        resumeFile.write(str(id))
        resumeFile.flush()
    except Exception as err:
        print('Failed to write resume state at '+str(id)+': '+str(err))
    resumeFileLock.release()

def sanitize(string):
    return string.replace('/', '').replace("\\", "").replace(':', '')

def removeExtraPrefixes(title, artist):
    if title.startswith(artist+' - '):
        return title[len(artist+' - '):]
    elif title.startswith(artist+'- '):
        return title[len(artist+'- '):]
    else:
        return title

# Those really add nothing, they just make it harder to find the song you're looking for most of the time
def isUselessAlbum(album):
    return album in ['My Little Medleys', 'My Little Mashups', 'My Little DJ Tunes', 'My Little Pixels', 'My Little YTPMVs', 'Rocking is Magic', 'Rapping is Magic']

def hasCoverArt(song_id):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        req = urllib.request.Request(ART_URL+str(song_id), method="HEAD", headers = HEADERS)
        res = opener.open(req)
    except urllib.error.HTTPError as e:
        res = e
    
    location = res.getheader('location')
    return not location.endswith('song-white-512.png')

def downloadTrack(metadata):
    id = metadata['song_id']

    artist = sanitize(metadata['artist_name'])
    album = None
    try:
        album = sanitize(metadata['album'])
    except:
        pass
    title = removeExtraPrefixes(sanitize(metadata['name']), artist)
    
    basedir = snapToExistingIgnoreCase(DATA_DIR, artist)
    if album != None and not isUselessAlbum(album):
        basedir = snapToExistingIgnoreCase(basedir, album)
    basepath = os.path.join(basedir, title)
    path = basepath+'.mp3'
    part_path = path+'.part'

    if existsIgnoreCase(basepath+'.mp3'):
        print("Track "+str(id)+" already downloaded")
        writeResumeState(id)
        return

    createFolder(basedir)
    print("Downloading "+str(id)+": "+artist+" - "+title)
    
    data = None
    try:
        req = urllib.request.Request(DL_URL+str(id), headers = HEADERS)
        data = urllib.request.urlopen(req).read()
    except Exception as err:
        print("Track "+str(id)+" couldn't be downloaded ("+str(err)+"), skipping");
        writeResumeState(id)
        return

    if len(data) < 8192:
        print("Track "+str(id)+" seems to be corrupted, skipping");
        return

    if existsIgnoreCase(basepath+'.mp3'):
        print("Track "+str(id)+" already downloaded, skipping")
        return
    
    with open(part_path, 'wb') as file:
        file.write(data)
    try:
        os.rename(part_path, path)
    except:
        print("Couldn't complete a download for track "+str(id)+", did we accidentally download it twice at the same time?")
    
    if hasCoverArt(id):
        if not dlcoverart.hasCoverArt(path):
            dlcoverart.downloadCoverArt({
                'id': id,
                'type': 'generic',
                'artUrl': ART_URL+id,
            })
            dlcoverart.addCoverArt({ 'id': id, 'path': path })
    
    writeResumeState(id)

def fetchMetadata(id):
    metadata = ''
    try:
        req = urllib.request.Request(META_URL+str(id), headers = HEADERS)
        metadata = urllib.request.urlopen(req).read()
    except urllib.error.HTTPError as err:
        print("Track "+str(id)+" metadata can't be downloaded ("+str(err)+"), skipping!")
        return
    metadata = json.loads(metadata.decode("utf-8"))
    metadata = metadata[0]
    if metadata is None:
        print("Track "+str(id)+" doesn't exist")
        return
    downloadQueue.put(metadata)

def downloadLoop():
    try:
        while True:
            downloadTrack(downloadQueue.get())
    except Exception as e:
        print("Download failed unexpectedly, exiting ("+str(e)+")")
        resumeFileLock.acquire()
        resumeFile.close()
        os._exit(1)

def startThread(function):
    thread = threading.Thread(target=function)
    thread.daemon = True
    thread.start()
    return thread

createFolder(DATA_DIR)
for i in range(NUM_DOWNLOAD_THREADS):
    downloadThreads.append(startThread(downloadLoop))
try:
    with open(os.path.join(DATA_DIR, "scraper-resume"), "r") as resumeFile:
        id = max(int(str(resumeFile.read())) - DL_QUEUE_SIZE, 1);
except:
    id = 1
resumeFile = open(os.path.join(DATA_DIR, "scraper-resume"), "a+")
resumeFile.seek(0)
while True:
    try:
        while downloadQueue.qsize() >= DL_QUEUE_SIZE:
            sleep(0.1)
        fetchMetadata(id)
        id += 1
    except KeyboardInterrupt:
        resumeFileLock.acquire()
        resumeFile.close()
        sys.exit(0)

