# Pony Music Archive scripts

This is a collection of short scripts and helpful tools used to manage the Pony Music Archive, a collection of music over 600GB in size.
The archive is released every 6 months as torrents for the raw and different transcode qualities.

These tools help automate tasks like downloading new songs and album art, converting the archive to Opus, finding duplicates and naming issues, and looking for corrupt or low-quality tracks.
While those scripts are fully functional, they're primarily written to work on the author's purposes, so expect some lack of polish here and there!

## Requirements

Because they invoke other tools like FFmpeg and ImageMagick in complex ways, these scripts are primarily meant to be used on Linux and they require several dependencies.
Note that not all scripts need all these dependencies, but if you run into any problems make sure you have the following tools installed first:

- `ffmpeg` and `ffprobe` from FFmpeg (for audio and metadata processing in general)
- `youtube-dl` (downloading cover art)
- `convert` utility from ImageMagick (auto-cropping the cover art)
- `metaflac` (adding cover art to FLACs)
- `opusenc` (converting songs to Opus)
- The `sqlite3` and `acoustid` Python3 packages to build the song database
- An `audioread` package built from Git master, due to a crippling memory leak in the last release (2.1.6)...
- Basic unix tools: `grep`, `awk` and `file` (misc processing)

## Release scripts

### convert.py

Converts a raw archive containing FLACs and MP3s to an Opus archive.

Usage: `convert.py <source> <destination>`

## Content download

### dlcoverart.py

Tries to find album art on an artist's Bandcamp, Soundcloud, or Youtube channel that matches their songs in the music archive.
Will auto-crop the cover art to remove any black bars (for Youtube) and apply it to the songs.

This tries pretty hard to guess when slightly different titles are the same song, so these are all recognized as the same track:
- Hot Mixtape (Ft Real Person) [Bonus Track]
- MLP-FiM: Hot mixtape! {12 SUB SPECIAL}
- The Hot Mixtape Album - hot mixtape feat. realperson12 & friends

Usage: `dlcoverart.py <artist folder>` then input the track list URL when prompted.

### dlbandcamp.py

Downloads an artist's entire discography from Bandcamp in free stream-quality MP3.
This is useful only for tracks that are too expensive to purchase (or if no one likes the damn album).

Usage: `dlbandcamp.py <path> <bandcamp artist URL>`

### dlsoundcloud.py

Downloads an artist's tracks from Soundcloud in either original quality (if Download is available), or stream-quality MP3.
This will not overwrite existing files, but it will try to apply Soundcloud's cover art if the name matches.
For arists who do not have a Bandcamp.

Usage: `dlsoundcloud.py <path> <soundcloud artist URL>`

### scrape.py

Downloads songs from Pony.fm, in either FLAC or MP3.
Optionally converts songs to Opus on the fly (this feature is deprecated, use the convert.py script instead).

Usage: `scrape.py <destination folder>`

## Maintenance scripts

### findbadnames.py

Looks through every folder and files in the archive for incorrect names.
This script tries to find a wide variety of problems such as duplicate songs or artists, using characters that are invalid on Windows (no `/)^(\.mp3` is not a good song name, looking at you General Mumble...), files that are not music (often a forgotten "cover.png" or "Thanks for buying my album.txt"), files that start or end with a blank space, and several other common issues.

This is always run (and every problem fixed) before creating a torrent.

Usage: `findbadnames.py <archive folder>`


### findbitrate.py

Reads through every song in the archive to find tracks under a minimum bitrate.
This will generate a list of low quality songs that should be replaced with a better source, if any.

Usage: `findbitrate.py <archive folder>`

### findlength.py

Largely useless and impressively slow. Will look for songs of a certain duration.
I've needed this exactly once, probably no one ever will.

Usage: `findlength.py <archive folder>`

### findcorrupt.py

Reads through every song in the archive and reports tracks that FFmpeg doesn't like, either because they are hopelessly corrupt or because of some minor weirdness.
Very basic script and thoroughly prone to false positives for the time being.

Usage: `findcorrupt.py <archive folder>`

## Song database, bulk merging & import

### build_song_db.py

Builds an SQLite database of songs from a Pony Music Archive-compatible Artists folder (aproximately 150MB for the latest Pony Music Archive).
The DB keeps track of metadata for each song: the artist, albums, format, duration, bitrate, estimated frequency cutoff, presence or absence of cover art, and audio fingerprint (Chromaprint).
We use this database to help automate bulk import and merging of other music archives.

Creating the DB from scratch takes a couple hours (mostly for computing audio fingerprints and frequency cutoff), but incremental updates rarely take more than a minute.

Usage: `build_song_db.py <PMA compatible Artists folder> <database file>`

### process_eqbeats.py

This script was used to conver the EQ Beats archive into a format and layout compatible with the Pony Music Archive, to help with semi-automatic importing of music and cover art.
Due to some surprises in the EQ Beats archive data (truncated file names, MP4 videos passing as .mp3 files, or Paint.NET projects pretending to be a PNG) some manual intervention is necessary to handle the few edge cases, but otherwise the process is automated.

Usage: `process_eqbeats.py` in the root folder of the eqbeats archive.

### diff_song_db.py

Matches songs between the Pony Music Archive and another collection to help automatically import music.

The music archive to import must first be converted to a PMA-compatible layout, and then a song database has to be built so we can efficiently diff the contents.

This uses the Chromaprint Matcher to compare songs. Start with a high matching threshold, then reduce progressively while watching for any false positives.
Going below an 80% match is typically not worth it, there'll be too many false positives to sort through and few new legitimate matches.

The -n flag shows what work would be done (importing cover art, replacing MP3s with matching FLACs), but doesn't actually perform any change.

Usage: `diff_song_db.py <src_artists_dir> <src_song_db> <pma_artists_dir> <pma_song_db> [-n]`

