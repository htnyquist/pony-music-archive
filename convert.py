#!/usr/bin/python3

import urllib.request
import os
import sys
import json
import queue
import threading
import subprocess
import glob
import random
import tempfile
import shutil
from time import sleep

CONV_QUEUE_SIZE = 64
NUM_CONVERSION_THREADS = 12
BITRATES = {'phone': 60, 'high': 96}
COMPLEXITY = 10
TMP_DIR=tempfile.mkdtemp(prefix='ponyfm-convert-tmp')

conversionQueue = queue.Queue(CONV_QUEUE_SIZE)
conversionThreads = []

if len(sys.argv) < 4:
    print('Usage: '+sys.argv[0]+' <quality> <src> <dst>')
    sys.exit(-1)
BITRATE = BITRATES[sys.argv[1]]
SRC_DIR = sys.argv[2]+os.path.sep
DST_DIR = sys.argv[3]+os.path.sep

if SRC_DIR == DST_DIR:
    print('Source and destination probably shouldn\'t be equal...')
    sys.exit(-1)

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

def singleQuoted(s):
    return "'"+s.replace("'", "'\\''")+"'"

def createMetadataFlags(ffmpegMetadata):
    metadataFlags = ' '
    # Those tags are better dropped (we're re-encoding here)
    ignored_tags = ['encoder', 'encoded_by', 'encoded by', 'encoded-by', 'software', 'minor_version', 'tlen',  \
                    'itunnorm', 'itunsmpb', 'itunpgap']
    
    for line in ffmpegMetadata.split('\n'):
        pair = line.split('=')
        if len(pair) != 2: continue
        tagname = pair[0].lower()
        tagval = singleQuoted(pair[1])
        if tagname == 'title':
            metadataFlags += "--title "+tagval+' '
        elif tagname == 'artist':
            metadataFlags += "--artist "+tagval+' '
        elif tagname == 'album':
            metadataFlags += "--album "+tagval+' '
        elif tagname == 'genre':
            metadataFlags += "--genre "+tagval+' '
        elif tagname == 'date' or tagname == 'year' or tagname == 'origdate':
            metadataFlags += "--date "+tagval+' '
        elif tagname == 'tyer':
            fields = pair[1].split('.')
            if len(fields) == 3:
                metadataFlags += "--date "+singleQuoted(str(fields[2])+'-'+str(fields[1])+'-'+str(fields[0]))+' '
            elif len(fields) == 1:
                metadataFlags += "--date "+tagval+' '
            else:
                print("Couldn't understand TYER date value: "+pair[1]+" for "+escapedSrcPath)
        elif tagname == 'album_artist':
            metadataFlags += "--comment "+singleQuoted('ALBUMARTIST='+pair[1])+' '
        elif tagname == 'compilation':
            metadataFlags += "--comment "+singleQuoted('COMPILATION='+pair[1])+' '
        elif tagname == 'contentgroup':
            metadataFlags += "--comment "+singleQuoted('GROUPING='+pair[1])+' '
        elif tagname == 'author':
            metadataFlags += "--comment "+singleQuoted('AUTHOR='+pair[1])+' '
        elif tagname == 'composer':
            metadataFlags += "--comment "+singleQuoted('COMPOSER='+pair[1])+' '
        elif tagname == 'performer':
            metadataFlags += "--comment "+singleQuoted('PERFORMER='+pair[1])+' '
        elif tagname == 'publisher':
            metadataFlags += "--comment "+singleQuoted('PUBLISHER='+pair[1])+' '
        elif tagname == 'engineer' or tagname == 'ieng':
            metadataFlags += "--comment "+singleQuoted('ENGINEER='+pair[1])+' '
        elif tagname == 'copyright' or tagname == 'copyright message':
            metadataFlags += "--comment "+singleQuoted('COPYRIGHT='+pair[1])+' '
        elif tagname == 'license':
            metadataFlags += "--comment "+singleQuoted('LICENSE='+pair[1])+' '
        elif tagname == 'track':
            metadataFlags += "--comment "+singleQuoted('TRACKNUMBER='+pair[1])+' '
        elif tagname == 'tracktotal' or tagname == 'totaltracks':
            metadataFlags += "--comment "+singleQuoted('TRACKTOTAL='+pair[1])+' '
        elif tagname == 'disc':
            metadataFlags += "--comment "+singleQuoted('DISCNUMBER='+pair[1])+' '
        elif tagname == 'disctotal':
            metadataFlags += "--comment "+singleQuoted('DISCTOTAL='+pair[1])+' '
        elif tagname == 'isrc':
            metadataFlags += "--comment "+singleQuoted('ISRC='+pair[1])+' '
        elif tagname == 'lyrics' or tagname == 'lyric' or tagname == 'unsyncedlyrics' or tagname.startswith('lyrics-'):
            metadataFlags += "--comment "+singleQuoted('LYRICS='+pair[1])+' '
        elif tagname == 'bpm' or tagname == 'tbpm' or tagname == 'bpm (beats per minute)':
            metadataFlags += "--comment "+singleQuoted('BPM='+pair[1])+' '
        elif tagname == 'comment' or tagname == 'comments':
            metadataFlags += "--comment "+singleQuoted('COMMENT='+pair[1])+' '
        elif tagname.startswith('id3v2_priv') or tagname in ignored_tags:
            pass
        else:
            metadataFlags += "--comment "+singleQuoted(pair[0]+'='+pair[1])+' '
    return metadataFlags

def runShellCmd(cmd):
    devnull=open(os.devnull)
    output = subprocess.check_output(["sh", "-c", cmd], stdin=devnull).decode('utf-8', 'ignore')
    devnull.close()
    return output

def convertToOpus(convertItem):
    srcPath = convertItem['srcPath']
    dstPath = convertItem['dstPath']
    print("Converting "+srcPath)
    try:
        escapedSrcPath = "'"+srcPath.replace("'", "'\\''")+"'"
        escapedDstPath = "'"+dstPath.replace("'", "'\\''")+".part'"

        metadataFlags = ''
        metadataCmd = 'ffmpeg -i '+escapedSrcPath+' 2>/dev/null -f ffmetadata -'
        try:
            metaOutput = runShellCmd(metadataCmd).strip()
            metadataFlags = createMetadataFlags(metaOutput)
        except subprocess.CalledProcessError as e:
            print("Failed to extract metadata for "+escapedSrcPath+", ignoring.")
            print(e)
            pass

        coverPath = os.path.join(TMP_DIR, str(random.randint(0, 2**64))+'.png')
        coverCmd = 'ffmpeg -i '+escapedSrcPath+' -an -c:v copy 2> /dev/null '+coverPath+' && file -b --mime-type '+coverPath
        convCmd = ''
        try:
            coverMimetype = runShellCmd(coverCmd).strip()
            convCmd = 'ffmpeg -i '+escapedSrcPath+' -f wav - 2> /dev/null | opusenc --picture \|'+coverMimetype+'\|\|\|'+coverPath+metadataFlags \
                    +' --bitrate '+str(BITRATE)+' --comp '+str(COMPLEXITY)+' --vbr - '+escapedDstPath+' > /dev/null 2>&1; rm -f '+coverPath
        except subprocess.CalledProcessError as e:
            convCmd = 'ffmpeg -i '+escapedSrcPath+' -f wav - 2> /dev/null | opusenc --bitrate ' \
                    +str(BITRATE)+metadataFlags+' --comp '+str(COMPLEXITY)+' --vbr - '+escapedDstPath+' > /dev/null 2>&1'

        devnull=open(os.devnull)
        if subprocess.call(["sh", "-c", convCmd], stdin=devnull):
            print(coverCmd)
            print(convCmd)
            print("Conversion returned an error for "+escapedSrcPath+", ignoring!")
        else:
            os.rename(dstPath+'.part', dstPath)
        devnull.close()
    except KeyboardInterrupt:
        os.remove(dstPath+'.part')
    conversionQueue.task_done()

def conversionLoop():
    while True:
        convertToOpus(conversionQueue.get())

def startThread(function):
    thread = threading.Thread(target=function)
    thread.daemon = True
    thread.start()
    return thread

createFolder(DST_DIR)
for i in range(NUM_CONVERSION_THREADS):
    conversionThreads.append(startThread(conversionLoop))

for pathit in glob.iglob(os.path.join(glob.escape(SRC_DIR), '**'), recursive=True):
    while conversionQueue.qsize() >= CONV_QUEUE_SIZE:
        sleep(0.1)

    srcPath = str(pathit)
    basepath = srcPath[len(SRC_DIR)-1:].rsplit('.', 1)[0]
    dstPath = DST_DIR + basepath + '.opus'
    if os.path.exists(dstPath) or not os.path.isfile(srcPath):
        continue
    
    if srcPath.endswith('.mp3') and existsIgnoreCase(SRC_DIR+basepath+'.flac'):
        continue
    
    if not srcPath.endswith('.mp3') and not srcPath.endswith('.flac'):
        continue
    
    createFolder(os.path.dirname(dstPath))
    conversionQueue.put({"srcPath": srcPath, "dstPath": dstPath})
conversionQueue.join()
shutil.rmtree(TMP_DIR, ignore_errors=True)
