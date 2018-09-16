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

CMD='ffmpeg -f null -v fatal -xerror - -i '

mediaQueue = queue.Queue(QUEUE_SIZE)
threads = []

def checkFile(convertItem):
    srcPath = convertItem['srcPath']
    if not (srcPath.endswith('.flac') or srcPath.endswith('.mp3') or srcPath.endswith('.opus')):
        mediaQueue.task_done()
        return
    try:
        escapedSrcPath = "'"+srcPath.replace("'", "'\\''")+"'"
        subprocess.check_output(CMD+escapedSrcPath, shell=True)
    except Exception as e:
        print('Found potentially corrupt (or just weird) file: '+srcPath)
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


