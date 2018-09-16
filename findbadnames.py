#!/usr/bin/python3

import urllib.request
import os
import sys
import json
import queue
import threading
import subprocess
import glob
import numpy as np
from time import sleep

if len(sys.argv) != 2:
    print('Usage: '+sys.argv[0]+' <path>')
    sys.exit(-1)
srcDir = sys.argv[1]

GOOD_NAMES_COUNT = 0
BAD_NAMES_COUNT = 0

def levenshtein(seq1, seq2):
    size_x = len(seq1) + 1
    size_y = len(seq2) + 1
    matrix = np.zeros((size_x, size_y))
    for x in range(size_x):
        matrix[x, 0] = x
    for y in range(size_y):
        matrix[0, y] = y

    for x in range(1, size_x):
        for y in range(1, size_y):
            if seq1[x-1] == seq2[y-1]:
                matrix [x,y] = min(
                    matrix[x-1, y] + 1,
                    matrix[x-1, y-1],
                    matrix[x, y-1] + 1
                )
            else:
                matrix [x,y] = min(
                    matrix[x-1,y] + 1,
                    matrix[x-1,y-1] + 1,
                    matrix[x,y-1] + 1
                )
    return (matrix[size_x - 1, size_y - 1])

def existsDupe(path):
    basepath = os.path.basename(path)
    dirpath = os.path.dirname(path)
    songname = basepath.rsplit('.', 1)[0].lower()
    try:
        for entry in os.listdir(dirpath):
            if not os.path.isfile(entry):
                continue
            if entry == basepath:
                continue
            entry_songname = entry.rsplit('.', 1)[0].lower()
            if entry_songname == songname:
                print('duplicate_name: '+path+' /// '+entry)
                if path.endswith('.mp3') and entry.endswith('.flac'):
                    print('> DELETING DUPLICATE MP3: '+path)
                    os.remove(path)
                return True
            if levenshtein(songname, entry_songname) < 2:
                # This has false positives if the songs are numbered (i.e. Part 1/Part 2 or  No. I/No. II in title)
                print('possible_duplicate_misspelling: '+path+' /// '+entry)
                return True
    except Exception as e:
        print(e)
    return False

def checkFolderDupes(path):
    basepath = os.path.basename(path)
    dirpath = os.path.dirname(path)
    reducedName = basepath.replace(' ', '').replace('.', '').lower()
    try:
        for entry in os.listdir(dirpath):
            if os.path.isfile(entry):
                continue
            if entry == basepath:
                continue
            entryReducedName = entry.replace(' ', '').replace('.', '').lower()
            if entryReducedName == reducedName:
                return showError('duplicate_folder_reduced_name: '+path+' /// '+entry)
    except Exception as e:
        print(e)
    return True

def showError(errorName, path):
    global BAD_NAMES_COUNT
    BAD_NAMES_COUNT += 1
    print(errorName+': '+path)
    return False

def commonChecks(srcPath, baseName, baseFileName):
    for c in "><:?*|\\":
        if c in baseName:
            return showError('bad_character', srcPath)
    if baseName.startswith('.'):
        return showError('hidden_file', srcPath)
    if baseName.replace('[', '').replace('(', '').replace('{', '').lower().startswith('pony.fm exclusive'):
        return showError('startswith_ponyfm_exclusive', srcPath)
    if baseName.startswith(' ') or baseName.endswith(' ') or srcPath.endswith(' '):
        return showError('extra_blank_spaces', '"'+srcPath+'"')
    return True

def folderChecks(srcPath, baseName, baseFileName):
    if srcPath.endswith('Archive'):
        return showError('archive_artist', srcPath)
    if 'audiotool.com' in srcPath:
        return showError('audiotool.com', srcPath)
    if baseName.lower().startswith('newgrounds audio portal'):
        return showError('startswith_newgrounds', srcPath)
    return checkFolderDupes(srcPath)

def fileChecks(srcPath, baseName, baseFileName):
    if existsDupe(srcPath):
        return False
    if not (srcPath.endswith('.mp3') or srcPath.endswith('.flac') or srcPath.endswith('.opus')):
        return showError('unexpected_extension', srcPath)

    if baseName.replace('[', '').replace('(', '').replace('{', '').lower().startswith('bonus track'):
        return showError('startswith_bonus_track', srcPath)

    if baseFileName.startswith(os.path.basename(os.path.dirname(srcPath))+' -'):
        return showError('artist_in_filename', srcPath)

    if baseFileName.endswith('-'):
        showError('ends_with_dash', srcPath)
        if not '-' in baseFileName[:-1]:
            fixedPath = root+'/'+baseName.replace('-', '')
            print('> AUTO-CORRECTING TO: '+fixedPath)
            os.rename(srcPath, fixedPath)
        elif baseFileName.count('-') == 2:
            pos1 = baseName.find('-')
            pos2 = baseName.rfind('-')
            fixedPath = root+'/'+baseName[:pos1]+'['+baseName[pos1+1:pos2]+']'+baseName[pos2+1:]
            print('> AUTO-CORRECT DASH TO BRACKETS: '+fixedPath)
            os.rename(srcPath, fixedPath)
        return False

    if '20- ' in baseName:
        return showError('twenty_percent_broken', srcPath)

    for elem in ['ft.', 'ft', 'feat.', 'feat']:
        if ' - '+elem+' ' in baseName.lower():
            return showError('feat_not_in_parens', srcPath)
    return True

for root, dirs, files in os.walk(srcDir, topdown=False):
    entries = files + dirs
    for filename in entries:
        srcPath = root+'/'+filename
        baseName = os.path.basename(srcPath)
        baseFileName = os.path.basename(srcPath).rsplit('.', 1)[0]

        if not commonChecks(srcPath, baseName, baseFileName):
            continue

        if os.path.isfile(srcPath):
            if not fileChecks(srcPath, baseName, baseFileName):
                continue
        else:
            if not folderChecks(srcPath, baseName, baseFileName):
                continue
        
        GOOD_NAMES_COUNT += 1

print('Checked '+str(GOOD_NAMES_COUNT+BAD_NAMES_COUNT)+' file names, found '+str(BAD_NAMES_COUNT)+' issues!')
