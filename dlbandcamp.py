#!/usr/bin/env python3

import os
import sys
import subprocess

if len(sys.argv) < 2:
    print('Usage: '+sys.argv[0]+' <output dir>')
    sys.exit(-1)
OUT_DIR = sys.argv[1]
URL = input('Bandcamp URL: ')

fetchCmd = "curl 2>/dev/null "+URL+" | egrep 'href=\"/(track|album)/' | sed 's@.*\\(/[^/]\+/.*\\)\".*@\\1@'"
titles = subprocess.check_output(["sh", "-c", fetchCmd]).decode().strip().split('\n')

track_base_url = URL.replace('/music', '')

print('Downloading '+str(len(titles))+' albums')

for title in titles:
    track_url = track_base_url+title
    subprocess.call(['python3', os.path.dirname(__file__)+'/bandcamp-dl/bandcamp_dl/__main__.py', '-eyr', '--template=%{artist}/%{album}/%{track}%{title}', track_url])
