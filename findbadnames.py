#!/usr/bin/python3

import urllib.request
import os
import sys
import re
import json
import queue
import threading
import subprocess
import glob
import numpy as np
from time import sleep

# This has false positives if the songs are numbered (i.e. Part 1/Part 2 or  No. I/No. II in title)
CHECK_MISSPELLINGS=False

if len(sys.argv) != 2:
    print('Usage: '+sys.argv[0]+' <path>')
    sys.exit(-1)
srcDir = sys.argv[1]

GOOD_NAMES_COUNT = 0
BAD_NAMES_COUNT = 0

TMP_COVER_PATH = '/tmp/pma-findbadnames-cover.jpg'
CMD_HAS_COVER = 'ffprobe 2>/dev/null -show_streams '
CMD_EXTRACT_COVER = 'ffmpeg 2>/dev/null -y -an '+TMP_COVER_PATH+' -i '
CMD_APPLY_FLAC_COVER = 'metaflac --import-picture-from='+TMP_COVER_PATH+' '

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

def hasCoverArt(filePath):
    try:
        escapedSrcPath = "'"+filePath.replace("'", "'\\''")+"'"
        result = subprocess.check_output(CMD_HAS_COVER+escapedSrcPath, shell=True)
        return 'DISPOSITION:attached_pic=1' in result.decode()
    except Exception as e:
        print('Failed to check '+filePath+' for cover art!')
        print(e)
        return True

def applyFlacCoverFromMp3(mp3_path, flac_path):
    try:
        esc_mp3_path = "'"+mp3_path.replace("'", "'\\''")+"'"
        esc_flac_path = "'"+flac_path.replace("'", "'\\''")+"'"
        subprocess.check_output(CMD_EXTRACT_COVER+esc_mp3_path, shell=True)
        subprocess.check_output(CMD_APPLY_FLAC_COVER+esc_flac_path, shell=True)
    except Exception as e:
        print('Failed to add cover art for '+flac_path+'!')
        print(e)

def existsDupe(path):
    basepath = os.path.basename(path)
    dirpath = os.path.dirname(path)
    songname = basepath.rsplit('.', 1)[0].lower()
    try:
        for entry in os.listdir(dirpath):
            entrypath = os.path.join(dirpath, entry)
            if not os.path.isfile(entrypath):
                continue
            if entry == basepath:
                continue
            entry_songname = entry.rsplit('.', 1)[0].lower()
            if entry_songname == songname:
                print('duplicate_name: '+path+' /// '+entry)
                if path.endswith('.mp3') and entry.endswith('.flac'):
                    if hasCoverArt(path) and not hasCoverArt(entrypath):
                        print('> IMPORTING COVER ART AND DELETING DUPLICATE MP3: '+path)
                        applyFlacCoverFromMp3(path, entrypath)
                        os.remove(path)
                        return True
                    else:
                        print('> DELETING DUPLICATE MP3: '+path)
                        os.remove(path)
                return True
            if CHECK_MISSPELLINGS and levenshtein(songname, entry_songname) < 2:
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
                return showError('duplicate_folder_reduced_name', path+' /// '+entry)
    except Exception as e:
        print(e)
    return True

def normalize_name(name):
    for c in '[](){}':
        name = name.replace(c, '')
    return name.lower()

def showError(errorName, path):
    global BAD_NAMES_COUNT
    BAD_NAMES_COUNT += 1
    print(errorName+': '+path)
    return False

def commonChecks(srcPath, baseName, baseFileName):
    for c in "><:?*|\"\\":
        if c in baseName:
            return showError('bad_character', srcPath)
    if baseName.startswith('.'):
        return showError('hidden_file', srcPath)
    if baseName.replace('[', '').replace('(', '').replace('{', '').lower().startswith('pony.fm exclusive'):
        return showError('startswith_ponyfm_exclusive', srcPath)
    if baseName.startswith(' ') or baseName.endswith(' '):
        return showError('extra_blank_spaces', '"'+srcPath+'"')
    if "\n" in baseName:
        return showError('newline_in_name', srcPath)

    return True

# Folders can't have autocorrect, that would break the next iterations
def folderChecks(srcPath, baseName, baseFileName):
    if srcPath.endswith('.'):
        return showError('dot_at_end', srcPath)
    if srcPath.endswith('Archive'):
        return showError('archive_artist', srcPath)
    if 'audiotool.com' in srcPath:
        return showError('audiotool.com', srcPath)
    if baseName.lower().startswith('newgrounds audio portal'):
        return showError('startswith_newgrounds', srcPath)
    if '  ' in baseName:
        return showError('double_space', srcPath)
    return checkFolderDupes(srcPath)

def fileChecks(srcPath, baseName, baseFileName):
    if existsDupe(srcPath):
        return False
    if not (srcPath.endswith('.mp3') or srcPath.endswith('.flac') or srcPath.endswith('.opus')):
        return showError('unexpected_extension', srcPath)
    if baseFileName.endswith(' '):
        showError('extra_blank_spaces', '"'+srcPath+'"')
        fixedPath = root+'/'+baseFileName[:-1]+baseName[baseName.rfind('.'):]
        print('> AUTO-CORRECTING TO: '+fixedPath)
        os.rename(srcPath, fixedPath)
        return False

    if '  ' in baseName:
        showError('double_space', srcPath)
        fixedPath = root+'/'+re.sub('\\s+', ' ', baseName)
        os.rename(srcPath, fixedPath)
        print('> AUTO-CORRECTING TO: '+fixedPath)
        return False

    if srcPath.endswith('.wav.flac'):
        showError('ends_in_.wav.flac', srcPath)
        fixedPath = srcPath[:-9]+'.flac'
        os.rename(srcPath, fixedPath)
        print('> AUTO-CORRECT .wav.flac: '+fixedPath)
        return False
    if srcPath.endswith('.mp3.mp3'):
        showError('ends_in_.mp3.mp3', srcPath)
        fixedPath = srcPath[:-4]
        os.rename(srcPath, fixedPath)
        print('> AUTO-CORRECT .mp3.mp3: '+fixedPath)
        return False

    if normalize_name(baseFileName).startswith('bonus track') and normalize_name(baseFileName) != 'bonus track':
        return showError('startswith_bonus_track', srcPath)
    if 'free download' in baseFileName.lower():
        return showError('free_download', srcPath)

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
    for char in '([{':
        if ' - '+char in baseFileName or ' -'+char in baseFileName or char+' - ' in baseFileName or char+'- ' in baseFileName:
            showError('redundant_punctuation', srcPath)
            fixedPath = root+'/'+baseName.replace(' - '+char, ' '+char).replace(' -'+char, ' '+char).replace(char+' - ', char+' ').replace(char+'- ', char+' ')
            print('> AUTO-CORRECTING TO: '+fixedPath)
            os.rename(srcPath, fixedPath)
            return False

    for elem in ['ft.', 'ft', 'feat.', 'feat']:
        if ' - '+elem+' ' in baseName.lower():
            return showError('feat_not_in_parens', srcPath)

    for dirname in os.path.dirname(srcPath).split(os.sep):
        if baseFileName.startswith(dirname+' -') or baseFileName.endswith('- '+dirname):
            return showError('dirname_in_filename', srcPath)

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
