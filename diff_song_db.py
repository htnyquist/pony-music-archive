#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import re
import sqlite3
from time import sleep

READONLY = False

if len(sys.argv) < 5:
    print('Usage: '+sys.argv[0]+' <source dir> <source db> <target dir> <target db>')
    sys.exit(-1)
SRC_DIR = sys.argv[1]
SRC_DB = sys.argv[2]
TARGET_DIR = sys.argv[3]
TARGET_DB = sys.argv[4]
if len(sys.argv) >= 6:
    READONLY = sys.argv[5] == '-n'

def process_song(artist, artist_path, albums_path, song_filename):
    song_path = os.path.join(artist_path, albums_path, song_filename)
    song_title = song_filename[:song_filename.rfind('.')]
    song_format = song_filename[song_filename.rfind('.')+1:]
    print("Processing "+artist+' - '+song_filename)

def process_artist(artist, rows):
    artist_path = os.path.join(SRC, artist)
    existing_db_entries = []
    for row in rows:
        row_albums_path, row_title, row_format = row
        existing_db_entries.append(os.path.join(row_albums_path, row_title)+'.'+row_format)
    for root, dirs, files in os.walk(artist_path):
        for song_file in files:
            albums_path = os.path.relpath(root, artist_path)
            rel_path = os.path.join(albums_path, song_file)
            if rel_path in existing_db_entries:
                continue
            process_song(artist, artist_path, albums_path, song_file)

class Song:
    def __init__(self, songs_root_path, artist, albums_path, song_title, song_format, duration, fingerprint, has_cover_art):
        self.artist = artist
        self.albums_path = albums_path
        self.title = song_title
        self.fmt = song_format
        self.duration = duration
        self.fingerprint = fingerprint.decode('utf-8')
        self.has_cover_art = has_cover_art
        self.rel_path = os.path.join(self.artist, self.albums_path, self.title+'.'+self.fmt)
        self.full_path = os.path.join(songs_root_path, self.artist, self.albums_path, self.title+'.'+self.fmt)
        self.match = None
        self.match_score = 0.0

def check_read_only_mode():
    if READONLY:
        print('! Read only mode is on, no change was made')
    return READONLY

def import_songs(db_path):
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    cur.execute("SELECT value FROM info WHERE tag == 'songs_rel_path'")
    songs_path = os.path.join(os.path.dirname(db_path), cur.fetchone()[0])
    cur.execute('SELECT DISTINCT * FROM songs')

    fingerprints = {}
    exact_dup_count = 0
    for row in cur.fetchall():
        song = Song(songs_path, *row)
        if song.fingerprint in fingerprints:
            exact_dup_count += 1
            #print(f'# Exact duplicate {song.full_path} --- {fingerprints[song.fingerprint].full_path}')
        fingerprints[song.fingerprint] = song
    print(f'{str(exact_dup_count)} duplicates found (exact fingerprint match)')

    cur.close()
    db.close()
    return fingerprints

def update_dst_db_song_cover_art(song):
    db = sqlite3.connect(TARGET_DB)
    db.execute('UPDATE songs SET has_cover_art=? WHERE artist==? AND albums_path==? AND title==? AND format==?', [song.has_cover_art, song.artist, song.albums_path, song.title, song.fmt])
    db.commit()
    db.close()

def remove_parens(title):
    depth = 0
    result = ''
    lastStart = 0
    for i, c in enumerate(title):
        if c in '([{':
            if depth == 0:
                result += title[lastStart:i]
            depth += 1
        if c in ')]}':
            depth -= 1
            if depth == 0:
                lastStart = i+1
    if depth == 0:
        result += title[lastStart:]
    return result.strip()

def simplify_charset(title):
    superfluous = "´'’!?*/⁄\\★-_:\"&.【】"
    result = title
    for c in superfluous:
        result = result.replace(c, ' ')
    return result

def remove_prefixes(title):
    fluff = ["mlp-fim", "mlp fim"]
    for prefix in fluff:
        if title.startswith(prefix):
            return title[len(prefix):]
    return title

def remove_feats(titleFragment):
    for feat in ['feat.', 'feat', 'ft.', 'ft']:
        spacedFeat = ' '+feat+' '
        pos = titleFragment.find(spacedFeat)
        if pos != -1:
            return titleFragment[:pos]
    return titleFragment

def canonicalize_title(title):
    title = re.sub("([^ ])'(s|ve|re)", '\\1\\2', title.lower())
    title = simplify_charset(title)
    title = remove_parens(title)
    title = remove_prefixes(title)
    return re.sub( '\s+', ' ', title).strip()

def import_cover_art(src_path, dst_path, dst_fmt):
    cover_path = os.path.join(os.path.dirname(dst_path), 'cover.jpg')
    subprocess.check_call(['ffmpeg', '-y', '-i', src_path, '-an', cover_path], stderr=subprocess.DEVNULL)
    if dst_fmt == 'mp3':
        subprocess.check_call('ffmpeg -f mp3 -y -map 0 -map 1 -map_metadata 1 -c:a copy -c:v copy'.split()+[dst_path+'.tmp', '-i', cover_path, '-i', dst_path], stderr=subprocess.DEVNULL)
        os.rename(dst_path+'.tmp', dst_path)
    elif dst_fmt == 'flac':
        subprocess.check_call(['metaflac', '--import-picture-from', cover_path, dst_path], stderr=subprocess.DEVNULL)
    else:
        print(f"Couldn't add cover art to {dst_path}, unsupported file format {dst_fmt}!")
    os.remove(cover_path)

def merge_best_of_songs(src_song, dst_song):    
    if not dst_song.has_cover_art and src_song.has_cover_art:
        print('> Importing cover art from '+src_song.rel_path+' to '+dst_song.rel_path)
        if check_read_only_mode():
            return
        import_cover_art(src_song.full_path, dst_song.full_path, dst_song.fmt)
        dst_song.has_cover_art = True
        update_dst_db_song_cover_art(dst_song)
        
    if src_song.fmt == 'flac' and dst_song.fmt == 'mp3':
        print(f'> Replacing MP3 {dst_song.rel_path}, with FLAC version {src_song.rel_path}')
        if check_read_only_mode():
            return
        flac_path = dst_song.full_path[:-3]+'flac'
        shutil.copy(src_song.full_path, flac_path)
        if not src_song.has_cover_art and dst_song.has_cover_art:
            import_cover_art(dst_song.full_path, flac_path, 'flac')
        os.remove(dst_song.full_path)

def process_fingerprint_match(src_song, dst_song):
    dst_canon_title = canonicalize_title(dst_song.title)
    
    src_title_elems = [src_song.title] + src_song.title.split('-')
    if dst_song.title != src_song.title:
        for elem in src_title_elems:
            canon_fragment = remove_feats(canonicalize_title(elem)).strip()
            if canon_fragment == dst_canon_title:
                break
        else:
            print('Fingerprints match, but canon titles are different: '+src_song.rel_path+' --- '+dst_song.rel_path)
            return
    
    merge_best_of_songs(src_song, dst_song)

print('Importing source database')
src_fingerprints = import_songs(SRC_DB)
print(str(len(src_fingerprints))+' source fingerprints')
print('Importing target database')
dst_fingerprints = import_songs(TARGET_DB)
print(str(len(dst_fingerprints))+' target fingerprints')

print('Running chromaprint matcher to generate diff')

matcher_stdout = None
with subprocess.Popen(['./chromaprint_matcher'], stderr=subprocess.PIPE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as matcher:
    for fingerprint in dst_fingerprints:
        song = dst_fingerprints[fingerprint]
        matcher.stdin.write(f'''{str(song.duration)} {song.fingerprint}\n''')
    matcher.stdin.write('\n')
    for fingerprint in src_fingerprints:
        song = src_fingerprints[fingerprint]
        matcher.stdin.write(f'''{str(song.duration)} {song.fingerprint}\n''')
    matcher_stdout, stderr = matcher.communicate()

print('Processing and importing matches')
count_matching = 0
for line in matcher_stdout.split('\n')[:-1]:
    count_matching += 1
    src_print, match_print, match_score = line.split(' ');
    src_song = src_fingerprints[src_print]
    dst_song = dst_fingerprints[match_print]
    src_song.match = dst_song
    src_song.match_score = match_score
    
    process_fingerprint_match(src_song, dst_song)
print('Found '+str(count_matching)+' matching fingerprints, '+str(len(src_fingerprints)-count_matching)+' unmatched')

print('Processing artist folders')

src_artists = {}
for src_print in src_fingerprints:
    src_song = src_fingerprints[src_print]
    if not src_song.artist in src_artists:
        src_artists[src_song.artist] = []
    src_artists[src_song.artist].append(src_song)

src_artists_without_matches = []
for artist in src_artists:
    songs = src_artists[artist]
    for song in songs:
        if song.match is not None:
            break
    else:
        src_artists_without_matches.append(artist)
        print(f'> Source artist {artist} has no matching songs, eligible for bulk import')
    
print(f'Found {str(len(src_artists))} source artists, {str(len(src_artists_without_matches))} without any matches')

for artist in src_artists:
    if artist in src_artists_without_matches:
        continue
    songs = src_artists[artist]
    for song in songs:
        if song.match is None:
            print(f'> Unmatched song to import: {song.rel_path}')
