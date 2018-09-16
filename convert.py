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

CONV_QUEUE_SIZE = 128
NUM_CONVERSION_THREADS = 14
BITRATE = 96
TMP_DIR=tempfile.mkdtemp(prefix='ponyfm-convert-tmp')

conversionQueue = queue.Queue(CONV_QUEUE_SIZE)
conversionThreads = []

if len(sys.argv) < 3:
    print('Usage: '+sys.argv[0]+' <src> <dst>')
    sys.exit(-1)
SRC_DIR = sys.argv[1]
DST_DIR = sys.argv[2]

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

def convertToOpus(convertItem):
    srcPath = convertItem['srcPath']
    dstPath = convertItem['dstPath']
    print("Converting "+srcPath)
    try:
        escapedSrcPath = "'"+srcPath.replace("'", "'\\''")+"'"
        escapedDstPath = "'"+dstPath.replace("'", "'\\''")+".part'"

        coverPath = os.path.join(TMP_DIR, str(random.randint(0, 2**64))+'.png')
        coverCmd = 'ffmpeg -i '+escapedSrcPath+' -an -vcodec copy 2> /dev/null '+coverPath+' && file -b --mime-type '+coverPath
        convCmd = ''
        try:
            coverMimetype = subprocess.check_output(["sh", "-c", coverCmd]).decode().strip()
            convCmd = 'ffmpeg -i '+escapedSrcPath+' -f wav - 2> /dev/null | opusenc --picture \|'+coverMimetype+'\|\|\|'+coverPath+' --bitrate '+str(BITRATE)+' --vbr - '+escapedDstPath+' > /dev/null 2>&1; rm -f '+coverPath
        except subprocess.CalledProcessError as e:
            convCmd = 'ffmpeg -i '+escapedSrcPath+' -f wav - 2> /dev/null | opusenc --bitrate '+str(BITRATE)+' --vbr - '+escapedDstPath+' > /dev/null 2>&1'

        if subprocess.call(["sh", "-c", convCmd]):
            print("Conversion returned an error for "+escapedSrcPath+", ignoring!")
        else:
            os.rename(dstPath+'.part', dstPath)
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

for pathit in glob.iglob(os.path.join(SRC_DIR, '**'), recursive=True):
    while conversionQueue.qsize() >= CONV_QUEUE_SIZE:
        sleep(0.1)

    srcPath = str(pathit)
    basepath = srcPath[len(SRC_DIR):].rsplit('.', 1)[0]
    dstPath = DST_DIR + basepath + '.opus'
    if os.path.exists(dstPath) or not os.path.isfile(srcPath):
        continue
    
    if srcPath.endswith('.mp3') and existsIgnoreCase(SRC_DIR+basepath+'.flac'):
        continue
    
    createFolder(os.path.dirname(dstPath))
    conversionQueue.put({"srcPath": srcPath, "dstPath": dstPath})
conversionQueue.join()
shutil.rmtree(TMP_DIR, ignore_errors=True)
