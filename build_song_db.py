#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import queue
import threading
import sqlite3
import acoustid
from time import sleep

from audioread import rawread
from audioread import gstdec

QUEUE_SIZE = 128
NUM_THREADS = 16

artist_queue = queue.Queue(QUEUE_SIZE)
results_queue = queue.Queue(QUEUE_SIZE)
threads = []

if len(sys.argv) < 3:
    print('Usage: '+sys.argv[0]+' <artists dir> <db file>')
    sys.exit(-1)
SRC = sys.argv[1]
DB_FILENAME = sys.argv[2]

def has_cover_art_async(path):
    return subprocess.Popen(['ffprobe', '-show_streams', path], stderr=subprocess.DEVNULL, stdout=subprocess.PIPE)

def process_song(artist, artist_path, albums_path, song_filename):
    song_path = os.path.join(artist_path, albums_path, song_filename)
    song_title = song_filename[:song_filename.rfind('.')]
    song_format = song_filename[song_filename.rfind('.')+1:]
    
    print("Processing "+artist+' - '+song_filename)
    has_cover_art_process = has_cover_art_async(song_path)
    duration, fingerprint = acoustid.fingerprint_file(song_path)
    
    out, err = has_cover_art_process.communicate()
    has_cover_art = 'DISPOSITION:attached_pic=1' in out.decode()
    results_queue.put([artist, albums_path, song_title, song_format, int(duration), fingerprint, has_cover_art])

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

def worker():
    while True:
        process_artist(*artist_queue.get())
        artist_queue.task_done()

def finish_processing_results():
    db = sqlite3.connect(DB_FILENAME)
    while True:
        process_results(db)
        sleep(2)

def start_thread(function):
    thread = threading.Thread(target=function)
    thread.daemon = True
    thread.start()
    return thread

def process_results(db):
    result_list = []
    while True:
        try:
            result_list.append(results_queue.get_nowait())
        except queue.Empty:
            break
    db.executemany('''INSERT INTO songs VALUES (?, ?, ?, ?, ?, ?, ?)''', result_list)
    db.commit()
    for i in range(len(result_list)):
        results_queue.task_done()
        
def process_removed_songs(db):
    db_cur = db.cursor()
    db_cur.execute('SELECT artist, albums_path, title, format FROM songs')
    to_remove = []
    rows = db_cur.fetchall()
    for row in rows:
        artist, albums_path, title, fmt = row
        song_path = os.path.join(SRC, artist, albums_path, title+'.'+fmt)
        if not os.path.exists(song_path):
            print('Removing deleted song from DB: '+song_path)
            to_remove.append(row)
    db_cur.executemany('DELETE FROM songs WHERE artist == ? AND albums_path == ? AND title == ? AND format == ?', to_remove)
    db_cur.close()
    db.commit()

db = sqlite3.connect(DB_FILENAME)
db.execute('''CREATE TABLE IF NOT EXISTS songs (artist text, albums_path text, title text, format text, duration integer, fingerprint text, has_cover_art integer)''')
db.execute('''CREATE TABLE IF NOT EXISTS info (tag text UNIQUE, value text)''')
db.execute('''INSERT OR REPLACE INTO info VALUES ('songs_rel_path', ?)''', [os.path.relpath(SRC, os.path.dirname(DB_FILENAME))])

print('Looking for removed songs')
process_removed_songs(db)

print('Looking for new songs')

for i in range(NUM_THREADS):
    threads.append(start_thread(worker))

with os.scandir(SRC) as it:
    db_cur = db.cursor()
    for entry in it:
        while artist_queue.qsize() >= QUEUE_SIZE:
            process_results(db)
            sleep(2)
        if entry.is_dir():
            db_cur.execute('SELECT albums_path, title, format FROM songs WHERE artist=?', [entry.name])
            rows = db_cur.fetchall()
            artist_queue.put([entry.name, rows])

db.commit()
db.close()

start_thread(finish_processing_results)
artist_queue.join()
results_queue.join()
