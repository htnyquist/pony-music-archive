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

MIN_BITRATE_KBPS=128
QUEUE_SIZE = 128
NUM_THREADS = 12

#CMD="mediainfo --Output='Audio;%BitRate%' "
CMD='ffprobe -v error -select_streams a:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 '

mediaQueue = queue.Queue(QUEUE_SIZE)
threads = []

def checkBitrate(convertItem):
    srcPath = convertItem['srcPath']
    if srcPath.endswith('.flac'):
        mediaQueue.task_done()
        return
    try:
        escapedSrcPath = "'"+srcPath.replace("'", "'\\''")+"'"
        output = subprocess.check_output(CMD+escapedSrcPath, shell=True)
        bitrate = int(output.decode().strip())
        if bitrate < MIN_BITRATE_KBPS*1000:
            print('Bitrate of '+srcPath+': '+str(bitrate))
    except Exception as e:
        print('Failed to get bitrate of '+srcPath)
        print(e)
        pass
    mediaQueue.task_done()

def mediaLoop():
    while True:
        checkBitrate(mediaQueue.get())

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

for pathit in glob.iglob(srcDir+'/**', recursive=True):
    while mediaQueue.qsize() >= QUEUE_SIZE:
        sleep(0.1)

    srcPath = str(pathit)
    if not os.path.isfile(srcPath):
        continue

    mediaQueue.put({"srcPath": srcPath})
mediaQueue.join()

