#!/usr/bin/python3

import urllib.request
import os
import sys
import json
import queue
import threading
import subprocess
from time import sleep

API_TRACK = "https://pony.fm/api/web/tracks/"
SRC_FORMATS = [{"name": "FLAC", "ext": "flac"}, {"name": "MP3", "ext": "mp3"}]
DL_QUEUE_SIZE = 50
CONV_QUEUE_SIZE = 25
CONVERT_TO_OPUS = False
NUM_CONVERSION_THREADS = 0
NUM_DOWNLOAD_THREADS = 8

if len(sys.argv) < 2:
    print('Usage: '+sys.argv[0]+' <data dir>')
    sys.exit(-1)
DATA_DIR = sys.argv[1]

conversionQueue = queue.Queue(CONV_QUEUE_SIZE)
downloadQueue = queue.Queue()
conversionThreads = []
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

def getDownloadUrl(id, format):
    return "https://pony.fm/t"+str(id)+"/dl."+format['ext']

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

def findDownloadableFormat(metadata):
    for format in SRC_FORMATS:
        try:
            req = urllib.request.Request(getDownloadUrl(metadata['id'], format), method="HEAD")
            urllib.request.urlopen(req).read()
            return format
        except urllib.error.HTTPError as err:
            pass
    return None

def downloadTrack(metadata):
    id = metadata['id']

    format = findDownloadableFormat(metadata)
    if format is None:
        print("Couldn't find a good download format for track "+str(metadata['id'])+", skipping!")
        writeResumeState(id)
        return

    size = None
    try:
        for available_format in metadata['formats']:
            if available_format['name'] == format['name']:
                size = available_format['size']
                break
    except:
        pass

    artist = sanitize(metadata['user']['name'])
    album = None
    try:
        album = sanitize(metadata['album']['title'])
    except:
        pass
    title = removeExtraPrefixes(sanitize(metadata['title']), artist)
    
    basedir = snapToExistingIgnoreCase(DATA_DIR, artist)
    if album != None and not isUselessAlbum(album):
        basedir = snapToExistingIgnoreCase(basedir, album)
    basepath = os.path.join(basedir, title)
    path = basepath+'.'+format['ext']
    part_path = path+'.part'

    if existsIgnoreCase(basepath+'.'+format['ext']):
        if CONVERT_TO_OPUS:
            print("Track "+str(id)+" already downloaded, but needs conversion")
            conversionQueue.put({"basepath": basepath, "srcFormat": format})
        else:
            print("Track "+str(id)+" already downloaded")
        writeResumeState(id)
        return

    if CONVERT_TO_OPUS and existsIgnoreCase(basepath+'.opus'):
        print("Track "+str(id)+" already downloaded, skipping")
        writeResumeState(id)
        return

    createFolder(basedir)
    if size is None:
        print("Downloading "+str(id)+": "+artist+" - "+title+" ("+format['name']+")")
    else:
        print("Downloading "+str(id)+": "+artist+" - "+title+" ("+format['name']+" "+size+")")
        
    data = None
    try:
        data = urllib.request.urlopen(getDownloadUrl(id, format)).read()
    except Exception as err:
        print("Track "+str(id)+" couldn't be downloaded ("+str(err)+"), skipping");
        writeResumeState(id)
        return

    if len(data) < 8192:
        print("Track "+str(id)+" seems to be corrupted, skipping");
        return

    if existsIgnoreCase(basepath+'.'+format['ext']) or existsIgnoreCase(basepath+'.opus'):
        print("Track "+str(id)+" already downloaded, skipping")
        return
    
    with open(part_path, 'wb') as file:
        file.write(data)
    try:
        os.rename(part_path, path)
    except:
        print("Couldn't complete a download for track "+str(id)+", did we accidentally download it twice at the same time?")
        
    if CONVERT_TO_OPUS:
        conversionQueue.put({"basepath": basepath, "srcFormat": format})
    writeResumeState(id)

def fetchMetadata(id):
    metadata = ''
    try:
        metadata = urllib.request.urlopen(API_TRACK+str(id)).read()
    except urllib.error.HTTPError as err:
        try:
            replyJson = json.loads(err.fp.read().decode("utf-8"))
            if replyJson['message'] == 'Track not found!':
                print("Track "+str(id)+" doesn't exist")
                return
        except:
            pass
        print("Track "+str(id)+" can't be downloaded ("+str(err)+"), skipping!")
        return
    metadata = json.loads(metadata.decode("utf-8"))
    metadata = metadata['track']
    downloadQueue.put(metadata)

def convertToOpus(convertItem):
    fileBasePath = convertItem['basepath']
    srcFormat = convertItem['srcFormat']
    try:
        escapedPath = "'"+fileBasePath.replace("'", "'\\''")+"'"
        if not os.path.exists(fileBasePath+'.'+srcFormat['ext']):
            return
        cmd = 'ffmpeg -i '+escapedPath+'.'+srcFormat['ext']+' -f wav - 2> /dev/null | opusenc - ' \
                +escapedPath+'.opus  > /dev/null 2>&1'
        if subprocess.call(["sh", "-c", cmd]):
            print("Conversion returned an error for \""+os.path.basename(fileBasePath)+"\", ignoring!")
        if os.path.exists(fileBasePath+'.opus'):
            try:
                os.remove(fileBasePath+'.'+srcFormat['ext'])
            except:
                pass
    except KeyboardInterrupt:
        os.remove(fileBasePath+'.opus')

def conversionLoop():
    if not CONVERT_TO_OPUS:
        return
    while True:
        convertToOpus(conversionQueue.get())

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
if CONVERT_TO_OPUS:
    for i in range(NUM_CONVERSION_THREADS):
        conversionThreads.append(startThread(conversionLoop))
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

