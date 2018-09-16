#!/usr/bin/python3

import urllib.request
import os
import sys
import json
import queue
import threading
import subprocess
import glob
from time import sleep

QUEUE_SIZE = 128
NUM_THREADS = 12

mediaQueue = queue.Queue(QUEUE_SIZE)
threads = []

def checkFile(convertItem):
    srcPath = convertItem['srcPath']
    if not (srcPath.endswith('.flac') or srcPath.endswith('.mp3') or srcPath.endswith('.opus')):
        mediaQueue.task_done()
        return
    try:
        escapedSrcPath = "'"+srcPath.replace("'", "'\\''")+"'"
        CMD="ffprobe "+escapedSrcPath+" 2>&1 | grep Duration | awk '{ print $2 }' | awk -F ':' '{ print $2*60+$3 }'"
        out = float(subprocess.check_output(CMD, shell=True).decode().strip())
        if out >= 363 and out <= 367:
            print(srcPath+': '+str(out))
    except Exception as e:
        print(e)
        pass
    mediaQueue.task_done()

def mediaLoop():
    while True:
        checkFile(mediaQueue.get())

def startThread(function):
    thread = threading.Thread(target=function)
    thread.daemon = True
    thread.start()
    return thread

for i in range(NUM_THREADS):
    threads.append(startThread(mediaLoop))

if len(sys.argv) < 2:
    print('Usage: '+sys.argv[0]+' <path>')
    sys.exit(-1)
srcDir = sys.argv[1]

for pathit in glob.iglob(os.path.join(srcDir, '**'), recursive=True):
    while mediaQueue.qsize() >= QUEUE_SIZE:
        sleep(0.1)

    srcPath = str(pathit)
    if not os.path.isfile(srcPath):
        continue

    mediaQueue.put({"srcPath": srcPath})
mediaQueue.join()


