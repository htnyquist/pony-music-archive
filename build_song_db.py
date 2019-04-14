#!/usr/bin/env python3
import os
import sys
import uuid
import shutil
import subprocess
import queue
import threading
import sqlite3
import scipy
import numpy
import acoustid
import tempfile
from time import sleep
from scipy import signal
from scipy.io import wavfile

from audioread import rawread
from audioread import gstdec

QUEUE_SIZE = 128
NUM_THREADS = 24

# Cutoff frequency search parameters
FFT_LENGTH = 1024
CUTOFF_SEARCH_START_FREQ = 5000 # There's no sense looking for a cutoff lower than 5kHz, if there's a song that poorly encoded I can only hope it's "artistic choice"
CUTOFF_SEARCH_SEGMENT_WIDTH = 50 # Distance to lookahead for the drop, as a fraction of the frequency (search space)
CUTOFF_MIN_DB_DROP = 15 # If we see a drop this many dB tall in a segment, we found the cutoff
CUTOFF_LOWEST_LEVEL = +15 # If we reach a level this many dB above the floor, there must not have been a sharp drop, so we cutoff here.

artist_queue = queue.Queue(QUEUE_SIZE)
results_queue = queue.Queue(QUEUE_SIZE)
threads = []
tempfile.tempdir = '.'
tmpdir = tempfile.mkdtemp(prefix='pma-build-song-db-tmp')

if len(sys.argv) < 3:
    print('Usage: '+sys.argv[0]+' <artists dir> <db file>')
    sys.exit(-1)
SRC = sys.argv[1]
DB_FILENAME = sys.argv[2]

def has_cover_art_async(path):
    return subprocess.Popen(['ffprobe', '-show_streams', path], stderr=subprocess.DEVNULL, stdout=subprocess.PIPE)

def find_bitrate_in_ffprobe_output(output):
    for line in output.split('\n'):
        if line.startswith('bit_rate=') and not line.endswith('N/A'):
            return int(line[len('bit_rate='):])
    return None

def frequency_cutoff_search(power_db, freq, dx, db_drop, lowest_level):
    start_pos = int(CUTOFF_SEARCH_START_FREQ * len(power_db) / freq)
    pos_to_freq = freq/len(power_db)/2
    for i in range(start_pos, len(power_db)-dx):
        if power_db[i] - power_db[i+dx] > db_drop:
            return int(i+dx/2) * pos_to_freq
        if power_db[i] - power_db[-1] < lowest_level:
            break
    return freq

def find_song_cutoff_frequency(song_path):
    temp_file = os.path.join(tmpdir, uuid.uuid4().hex+'.wav')
    subprocess.check_call(['ffmpeg', '-i', song_path, '-acodec', 'pcm_f32le', temp_file], stderr=subprocess.DEVNULL)
    freq, audio = wavfile.read(temp_file)
    os.remove(temp_file)
    
    if len(audio.shape) > 1 and audio.shape[1] > 1:
        graph_freqs, powerL = scipy.signal.welch(audio[:, 0], freq, nperseg=FFT_LENGTH, average='median')
        graph_freqs, powerR = scipy.signal.welch(audio[:, 1], freq, nperseg=FFT_LENGTH, average='median')
        power = powerL + powerR
    else:
        graph_freqs, power = scipy.signal.welch(audio, freq, nperseg=FFT_LENGTH, average='median')
    max_power = numpy.max(power)
    if max_power == 0: # Some songs are mostly empty (e.g. acapellas), we can't meaningfully look for a cutoff
        return None
    power_db = 10*scipy.log10(power/max_power)

    return frequency_cutoff_search(power_db, freq, int(len(power)/CUTOFF_SEARCH_SEGMENT_WIDTH), CUTOFF_MIN_DB_DROP, CUTOFF_LOWEST_LEVEL)

def process_song(artist, artist_path, albums_path, song_filename):
    song_path = os.path.join(artist_path, albums_path, song_filename)
    song_title = song_filename[:song_filename.rfind('.')]
    song_format = song_filename[song_filename.rfind('.')+1:]
    
    print("Processing "+artist+' - '+song_filename)
    has_cover_art_process = has_cover_art_async(song_path)
    duration, fingerprint = acoustid.fingerprint_file(song_path)
    
    ffprobe_out, err = has_cover_art_process.communicate()
    ffprobe_out = ffprobe_out.decode()
    has_cover_art = 'DISPOSITION:attached_pic=1' in ffprobe_out
    bitrate = find_bitrate_in_ffprobe_output(ffprobe_out)
    freq_cutoff = find_song_cutoff_frequency(song_path)
    
    results_queue.put([artist, albums_path, song_title, song_format, int(duration), bitrate, freq_cutoff, has_cover_art, fingerprint])

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
            retry = 0
            while retry < 3:
                try:
                    process_song(artist, artist_path, albums_path, song_file)
                    break
                except Exception as e:
                    retry += 1
                    print(e)

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
    db.executemany('''INSERT INTO songs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', result_list)
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
db.execute('''CREATE TABLE IF NOT EXISTS songs (
    artist TEXT NOT NULL,
    albums_path TEXT NOT NULL,
    title TEXT NOT NULL,
    format TEXT NOT NULL,
    duration INTEGER NOT NULL,
    bitrate INTEGER,
    freq_cutoff REAL,
    has_cover_art INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    UNIQUE(artist, albums_path, title)
    )''')
db.execute('''CREATE INDEX IF NOT EXISTS idx_artist ON songs(artist)''')
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

shutil.rmtree(tmpdir, ignore_errors=True)
