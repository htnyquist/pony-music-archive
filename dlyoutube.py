#!/usr/bin/env python3

import os
import sys
import subprocess
import dlcoverart

if len(sys.argv) < 2:
    print('Usage: '+sys.argv[0]+' <output dir>')
    sys.exit(-1)
OUT_DIR = sys.argv[1]
URL = input('Youtube URL: ')

downloadCmd = "youtube-dl -i -f bestaudio --extract-audio --audio-format mp3 --audio-quality 2 -o '%(title)s.%(ext)s' '"+URL+"'"
subprocess.check_output(["sh", "-c", downloadCmd]).decode().strip().split('\n')
dlcoverart.dlCoverArt(OUT_DIR, URL)
