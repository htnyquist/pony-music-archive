#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import tempfile

SRC = "Artists"
DST = "Processed"

FORMATS_SIGNATURES = {
    "WAVE audio": "wav",
    "MPEG ADTS, layer III": "mp3",
    "Audio file with ID3": "mp3",
    "Ogg data, Opus audio": "opus",
    "AAC-LC": "aac",
}
PREFERRED_FORMATS = ["wav", "mp3", "opus", "aac"]
LAME_VBR_QUAL = "3" # MP3 V3 (~175 kb/s VBR)

def convert_to_mp3(src_path, dst_path):
    if subprocess.call(["ffmpeg", '-loglevel', 'error', "-i", src_path, '-f', 'mp3', '-map_metadata', '0:s', '-q:a', LAME_VBR_QUAL, dst_path+'.part']):
        print("# Conversion returned an error for "+src_path+", ignoring!")
        return None
    else:
        os.rename(dst_path+'.part', dst_path)
        return dst_path

def repair_song_file(song_dir, src_path, fmt):
    song_name = song_dir[song_dir.rfind('/')+1:]
    dest_base_path = os.path.join(song_dir, song_name)
    if fmt == 'wav' or fmt == 'mp3':
        dest_path = dest_base_path+'.'+fmt
        print('Fixing filename for '+song_dir)
        shutil.copy(src_path, dest_path)
        return dest_path
    elif fmt == 'opus' or fmt == 'aac':
        dest_path = dest_base_path+'.mp3'
        print('Converting '+song_dir+' to MP3')
        convert_to_mp3(src_path, dest_path)
        return dest_path
    else:
        raise Exception('Unexpected format in repair_song_file')

def try_repair_song(song_dir):
    formats_found = [None, None, None, None]
    for entry in os.listdir(song_dir):
        if entry.endswith('.part'):
            continue
        entry_path = os.path.join(song_dir, entry)
        output = subprocess.check_output(["file", entry_path]).decode()
        for sig in FORMATS_SIGNATURES:
            if sig in output:
                fmt_index = PREFERRED_FORMATS.index(FORMATS_SIGNATURES[sig])
                formats_found[fmt_index] = entry_path
    
    for index, fmt_path in enumerate(formats_found):
        if fmt_path is not None:
            return repair_song_file(song_dir, fmt_path, PREFERRED_FORMATS[index])
    return None

def find_best_quality(song_dir):
    best_path = None
    with os.scandir(song_dir) as it:
        for entry in it:
            if not entry.is_file():
                continue
            path = entry.path
            if path.endswith(".wav"):
                return path
            elif path.endswith(".mp3"):
                # Some .mp3 filenames are actually video files ...
                output = subprocess.check_output(["file", path]).decode()
                if 'Audio file with ID3' in output or 'MPEG ADTS, layer III' in output:
                    if best_path is not None and os.stat(best_path).st_size > os.stat(path).st_size:
                        continue
                    best_path = path
                else:
                    print('# MP3 is not actually an MP3: '+path)
    if best_path is None:
        best_path = try_repair_song(song_dir)
    return best_path
                
def import_wav(artist, song, src_song, artwork_path):
    dst_path = os.path.join(DST, artist, song+'.flac')
    if os.path.exists(dst_path):
        return
    if subprocess.call(["ffmpeg", '-y', '-loglevel', 'error', "-i", src_song, dst_path]):
        print("# Conversion to FLAC failed for "+src_song)
        os.remove(dst_path)
        raise Exception("This is a bug. Giving up!")
    
    if os.path.exists(artwork_path):
        # Metaflac does not support unicode in image paths, so we make a copy
        tmp_dir=tempfile.mkdtemp(prefix='ponyfm-import-eqbeats-tmp')
        tmp_art=os.path.join(tmp_dir, 'artwork.png')
        shutil.copy(artwork_path, tmp_art)
        error = subprocess.call(['metaflac', '--import-picture-from', tmp_art, dst_path])
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if error:
            os.remove(dst_path)
            raise Exception("Failed to add cover art for "+dst_path)

def import_mp3(artist, song, src_song, artwork_path):
    dst_path = os.path.join(DST, artist, song+'.mp3')
    if os.path.exists(dst_path):
        return
    if not os.path.exists(artwork_path):
        shutil.copy(src_song, dst_path)
        return
    
    if subprocess.call(["ffmpeg", '-y', '-loglevel', 'error', "-i", src_song, '-i', artwork_path, '-f', 'mp3', '-map', '0:0', '-map', '1:0', '-c', 'copy',
                        '-id3v2_version', '3', '-metadata:s:v', 'title="Album cover"', '-metadata:s:v', 'comment="Cover (front)"', dst_path+'.part']):
        os.remove(dst_path+'.part')
        raise Exception("Adding album art to "+dst_path+" failed!")
    else:
        os.rename(dst_path+'.part', dst_path)

def find_artwork(song_dir):
    artwork_jpg = os.path.join(song_dir, 'artwork.jpg')
    if os.path.exists(artwork_jpg):
        return artwork_jpg
    artwork_png = os.path.join(song_dir, 'artwork.png')
    if 'JPEG image data' in subprocess.check_output(["file", artwork_png]).decode():
        shutil.copy(artwork_png, artwork_jpg)
        return artwork_jpg
    return artwork_png
    

def process_song(artist, song):
    target_base = os.path.join(DST, artist, song)
    # When debugging the script, it can be useful to skip over existing targets!
    #if os.path.exists(target_base+'.flac') or os.path.exists(target_base+'.mp3'):
        #print('! Skipping!')
        #return
    
    song_dir = os.path.join(SRC, artist, song)
    src_song = find_best_quality(song_dir)
    if src_song is None:
        print("# No good format for song: "+song_dir)
        return
    
    artwork_path = find_artwork(song_dir)
    
    print('Importing '+src_song)
    if src_song.endswith('.wav'):
        import_wav(artist, song, src_song, artwork_path)
    elif src_song.endswith('.mp3'):
        import_mp3(artist, song, src_song, artwork_path)
    else:
        raise Exception('Unexpected format for import')

def process_artist(name):
    artist_path = os.path.join(SRC, name)
    os.makedirs(os.path.join(DST, name), exist_ok=True)
    with os.scandir(artist_path) as it:
        for entry in it:
            if entry.is_dir():
                process_song(name, entry.name)

with os.scandir(SRC) as it:
    for entry in it:
        if entry.is_dir():
            process_artist(entry.name)

