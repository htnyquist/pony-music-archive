# Releasing the archive

Those are the general steps used to release a new version of the archive.

## Making the torrent

- Run findbadnames.py on the Raw version to look for problems
    - In particular make sure there are no special characters in file names, or windows users will get stuck downloading
    - Also make sure there aren't two different folders for the same artist with different case: eg "Dudebro" and "DUDEBRO", because that will cause the torrent to get stuck!
- When the raw version is ready, start the conversion in the background.
- After it's done, start it again a couple time to make sure an opusenc thread didn't segfault in the middle...
- Run findbadnames.py on the Opus version to look for leftover issues before making the torrent
- Install mktorrent and use it like below:

`mktorrent -a 'udp://tracker.coppersurfer.tk:6969,udp://tracker.leechers-paradise.org:6969,udp://exodus.desync.com:6969,udp://tracker.opentrackr.org:1337/announce,udp://tracker.kamigami.org:2710/announce,udp://tracker.uw0.xyz:6969/announce' -l 22 -n "Pony.fm archive (raw) - September 2018" Pony.fm\ archive\ \(raw\)\ -\ September\ 2018`

## Setting up a suitable temporary seedbox

- Create a C2S server on Scaleway with 4 150GB LSSD volumes
- Use LVM2 to create one logical volume with these
- Install deluged/deluge-console on the server, and set them up (add user to auth, allow remote connections)
- Add the torrent to deluge throught the remote interface, and let it download, then seed!
