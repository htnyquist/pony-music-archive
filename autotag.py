#!/usr/bin/env python3 
import argparse
import os
import sys
import time
import json
import queue
import threading
import subprocess
import glob
import random
import tempfile
import shutil
from enum import Enum

TAGGING_QUEUE_SIZE = 1024
PARSE_QUEUE_SIZE = 1024
NUM_PARSE_THREADS = 16

taggingQueue = queue.Queue(TAGGING_QUEUE_SIZE)
parseQueue = queue.Queue(PARSE_QUEUE_SIZE)
parseThreads = []
parseQueueOpen = True # When the queue closes, we're done adding elements to it

metadataMap = {}
artistNameMap = {}

totalSongs = 0
totalAlbumSongs = 0
artistTags = 0
albumTags = 0
titleTags = 0

TaggingTaskType = Enum('TaggingTask', 'FILE FOLDER')

class TaggingTask:
    def __init__(self, taskType, metaUpdates, description, isComplexDecision):
        self.taskType = taskType
        self.metaUpdates = metaUpdates # Non null fields of those metadata objects mean tags to update!
        self.description = description
        self.isComplexDecision = isComplexDecision

class ParseJob:
    def __init__(self, artistPath, artist, folderRelPath):
        self.artistPath = artistPath
        self.artist = artist
        self.folderRelPath = folderRelPath

class Metadata:
    def __init__(self, path, artist, album, title):
        self.path = path
        self.artist = artist
        self.album = album
        self.title = title
        
    def makeUpdateObject(self, updatedField, updatedValue):
        new = Metadata(self.path, None, None, None)
        setattr(new, updatedField, updatedValue)
        return new
    
    def applyUpdate(self, update):
        new = Metadata(self.path, self.artist, self.album, self.title)
        if update.artist:
            new.artist = update.artist
        if update.album:
            new.album = update.album
        if update.title:
            new.title = update.title
        return new
        
class Folder:
    def __init__(self, artistPath, artist, folderRelPath, files):
        self.artistPath = artistPath
        self.artist = artist
        self.folderRelPath = folderRelPath
        self.files = files

def startThread(function):
    thread = threading.Thread(target=function)
    thread.daemon = True
    thread.start()
    return thread

def runShellCmd(cmd):
    devnull=open(os.devnull)
    output = subprocess.check_output(["sh", "-c", cmd], stdin=devnull).decode('utf-8', 'ignore')
    devnull.close()
    return output

def query_yes_no(question, default="no"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes", "no" (the default) or None (meaning
        an answer is required of the user).
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            print("Please answer'yes' or 'no' (or 'y' or 'n')")

def updateMetadata(meta):
    if meta.path.endswith('.mp3'):
        cmdline = ['eyeD3', meta.path]
        if meta.artist:
            cmdline.extend(['--artist', meta.artist])
        if meta.album:
            cmdline.extend(['--album', meta.album])
        if meta.title:
            cmdline.extend(['--title', meta.title])
    elif meta.path.endswith('.flac'):
        cmdline = ['metaflac', meta.path]
        if meta.artist:
            cmdline.extend(['--remove-tag', 'ARTIST', '--set-tag', 'ARTIST='+meta.artist])
        if meta.album:
            cmdline.extend(['--remove-tag', 'ALBUM', '--set-tag', 'ALBUM='+meta.album])
        if meta.title:
            cmdline.extend(['--remove-tag', 'TITLE', '--set-tag', 'TITLE='+meta.title])
    else:
        raise Exception(f'Cannot write metadata for unexpected file type {meta.path}')
    try:
        subprocess.run(cmdline, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError as e:
        print(f'# Error: Failed to update metadata for file {meta.path}')
        print(e)

def getMetadata(srcPath):
    global artistTags, albumTags, titleTags
    
    escapedSrcPath = "'"+srcPath.replace("'", "'\\''")+"'"
    metadataFlags = ''
    metadataCmd = 'ffmpeg -i '+escapedSrcPath+' 2>/dev/null -f ffmetadata -'
    try:
        ffmpegMetadata = runShellCmd(metadataCmd).strip()
        artist = ''
        album = ''
        title = ''
        for line in ffmpegMetadata.split('\n'):
            pair = line.split('=', 1)
            if len(pair) != 2: continue
            tagname = pair[0].lower()
            tagval = pair[1].replace('\\=', '=')
            if tagname == 'title':
                title = tagval
                titleTags += 1
            elif tagname == 'artist':
                artist = tagval
                artistTags += 1
            elif tagname == 'album':
                album = tagval
                albumTags += 1
        return Metadata(srcPath, artist, album, title)
    except subprocess.CalledProcessError as e:
        print("Failed to extract metadata for "+escapedSrcPath+", ignoring.")
        return None

def queueFileTagJob(currentMeta, updatedTagName, updatedTagValue, description, isComplexDecision):
    if not currentMeta.path in metadataMap:
        metadataMap[currentMeta.path] = currentMeta
    metaUpdates = [currentMeta.makeUpdateObject(updatedTagName, updatedTagValue)]
    taggingQueue.put(TaggingTask(TaggingTaskType.FILE, metaUpdates, description, isComplexDecision))
    
def queueFolderTagJob(filesCurrentMeta, metaUpdates, description, isComplexDecision):
    for meta in filesCurrentMeta:
        if not meta.path in metadataMap:
            metadataMap[meta.path] = meta
    taggingQueue.put(TaggingTask(TaggingTaskType.FOLDER, metaUpdates, description, isComplexDecision))

def processFolder(parseJob):
    global args, totalSongs, totalAlbumSongs
    
    folderFullPath = os.path.join(parseJob.artistPath, parseJob.folderRelPath)
    if args.verbose:
        print(f'Processing folder {folderFullPath}')
    filesMeta = []
    with os.scandir(folderFullPath) as it:
        for entry in it:
            srcPath = os.path.join(folderFullPath, entry.name)
            if not os.path.isfile(srcPath):
                continue
            totalSongs += 1
            if parseJob.folderRelPath:
                totalAlbumSongs += 1
            meta = getMetadata(srcPath)
            if not meta:
                continue
            filesMeta.append(meta)
            if not meta.title:
                newTitle = os.path.splitext(entry.name)[0]
                queueFileTagJob(meta, 'title', newTitle, f'Set title to "{newTitle}" based on file name', False)
                
    if filesMeta:
        albumTags = {}
        noAlbumTag = []
        for meta in filesMeta:
            if meta.album == '':
                noAlbumTag.append(meta)
                continue
            if meta.album in albumTags:
                albumTags[meta.album] += 1
            else:
                albumTags[meta.album] = 1
        if len(noAlbumTag) and parseJob.folderRelPath:
            # For nested folders, or in case there are multiple existing tags on other tracks, we're not sure what to use as the album name
            mostCommonAlbumTags = sorted(albumTags, key=albumTags.get, reverse=True)
            if mostCommonAlbumTags:
                newAlbumTag = mostCommonAlbumTags[0]
                isComplexDecision = len(mostCommonAlbumTags) > 1
                description = f'Use the most common tag in other tracks of this album: "{newAlbumTag}"'
            else:
                newAlbumTag = parseJob.folderRelPath.replace('/', ' - ')
                isComplexDecision = parseJob.folderRelPath.find('/') != -1 or parseJob.folderRelPath == 'Instrumentals' or parseJob.folderRelPath == 'A capellas'
                description = f'Set the album tag to the folder name: "{newAlbumTag}"'
                
            metaUpdates = [m.makeUpdateObject('album', newAlbumTag) for m in noAlbumTag]
            queueFolderTagJob(filesMeta, metaUpdates, description, isComplexDecision)
            
        # Doing artist names per-folder is okay. Some albums might be under a different or older alias, for example.
        artistTags = {}
        noArtistTag = []
        for meta in filesMeta:
            if meta.artist == '':
                noArtistTag.append(meta)
                continue
            if meta.artist in artistTags:
                artistTags[meta.artist] += 1
            else:
                artistTags[meta.artist] = 1
        if len(noArtistTag):
            # For nested folders, or in case there are multiple existing tags on other tracks, we're not sure what to use as the album name
            mostCommonArtistTags = sorted(artistTags, key=artistTags.get, reverse=True)
            isComplexDecision = len(mostCommonArtistTags) > 1 and mostCommonArtistTags[0] != parseJob.artist
            if mostCommonArtistTags:
                newArtistTag = mostCommonArtistTags[0]
                description = f'Use the most common artist tag in the folder: "{newArtistTag}"'
            else:
                newArtistTag = parseJob.artist
                description = f'Set the artist tag to the artist folder\'s name: "{newArtistTag}"'
                
            metaUpdates = [m.makeUpdateObject('artist', newArtistTag) for m in noArtistTag]
            queueFolderTagJob(filesMeta, metaUpdates, description, isComplexDecision)
        
    parseQueue.task_done()

def processArtistFolder(artistFolder, artist):
    parseQueue.put(ParseJob(artistFolder, artist, ''))
    for root, dirs, files in os.walk(artistFolder):
        for dirName in dirs:
            dirPath = os.path.join(root, dirName)
            parseQueue.put(ParseJob(artistFolder, artist, os.path.relpath(dirPath, artistFolder)))

def processArtists():
    global parseQueueOpen
    
    with os.scandir(SRC_DIR) as it:
        for entry in it:
            processArtistFolder(os.path.join(SRC_DIR, entry.name), entry.name)
    parseQueueOpen = False

def applyUpdates(metaUpdates):
    for update in metaUpdates:
        curMeta = metadataMap[update.path]
        newMeta = curMeta.applyUpdate(update)
        metadataMap[update.path] = newMeta
        updateMetadata(newMeta)

def processTaggingTask(args, task):
    if not task.metaUpdates:
        printf('# Error: Tagging task does not update anything!')
        return
    
    if task.isComplexDecision and args.no_complex:
        if args.verbose:
            print(f'Skipping complex decision: {task.description}')
        return
    
    if task.taskType == TaggingTaskType.FILE:
        prompt = f'Update file {task.metaUpdates[0].path}: {task.description}?'
    elif task.taskType == TaggingTaskType.FOLDER:
        folderPath = os.path.dirname(task.metaUpdates[0].path)
        prompt = f'Update {len(task.metaUpdates)} files in {folderPath}: {task.description}?'
    else:
        print(f'# Error: Unexpected tagging task type {task.taskType}')
        return
    
    if task.isComplexDecision or not args.auto_apply_simple:
        if args.do_nothing:
            print(f'{prompt} [skipping prompt]')
        elif not query_yes_no(prompt):
            return
    if args.do_nothing:
        if not args.quiet:
            print(f'Would have applied change: {task.description}')
            return
    elif not args.quiet:
        print(f'Applying change: {task.description}')
    applyUpdates(task.metaUpdates)
        
def parseLoop():
    while parseQueueOpen or not parseQueue.empty():
        processFolder(parseQueue.get())

parser = argparse.ArgumentParser(
    description='Pony Music Archive metadata tagger',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('folder', metavar='archive folder', type=str, help='The Pony Music Archive folder')
parser.add_argument('--do-nothing', action='store_true', help='Do not actually do any changes, just show what would happen')
parser.add_argument('--auto-apply-simple', action='store_true', help='Automatically fix missing tags in simple cases instead of prompting')
parser.add_argument('--no-complex', action='store_true', help='Ignore more complex tagging problems instead of prompting')
parser.add_argument('--verbose', action='store_true', help='Print every folder processed. Will not play well with interractive prompts!')
parser.add_argument('--quiet', action='store_true', help='Do not print every change applied')
args = parser.parse_args()

if args.verbose and args.quiet:
    print('Using both --verbose and --quiet may be a mistake. Comment this check if you\'re sure this is what you want...')
    sys.exit(-1)

SRC_DIR = os.path.join(args.folder, 'Artists')
if not os.path.exists(SRC_DIR):
    print('Not a valid archive folder')
    sys.exit(-1)

processArtistsThread = startThread(processArtists)
for i in range(NUM_PARSE_THREADS):
    parseThreads.append(startThread(parseLoop))

time.sleep(0.5)
while not parseQueue.empty():
    while not taggingQueue.empty():
        processTaggingTask(args, taggingQueue.get())
    time.sleep(0.01)
processArtistsThread.join()
parseQueue.join()
while not taggingQueue.empty():
    processTaggingTask(args, taggingQueue.get())

print(f'{totalSongs} songs found')
print(f'{artistTags} ({artistTags/totalSongs*100}%) artist tags')
print(f'{titleTags} ({titleTags/totalSongs*100}%) title tags')
print(f'{albumTags} ({albumTags/totalAlbumSongs*100}%) album tags')
