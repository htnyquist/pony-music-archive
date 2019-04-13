# Chromaprint Matcher

This compares every song between two music archives and finds matches. The threshold for matches can be adjusted with the constants at the top of the source.  
Originally, the audio matching was done in Python and could not complete in 15 minutes. The Rust code happily compares tens of thousand of files on each side in a second or two.

An important gotcha: The AcoustID Python library we use for generating audio fingerprints really only compares the first 2 minutes of audio, so songs `Foo.mp3` and `Foo (Extended).mp3` would look like an exact match.  
We have multiple sanity checks in place to make sure we don't accidentally replace a good file with a false positive:
- We check the duration, less than 5 seconds difference is OK (turns out musicians aren't super precise when rendering), above we consider those two different tracks
- Even if the audio fingerprints match, if there's no fragment of the song titles that are remotely similar the Python code will reject the fingerprint match downstream

The other really nice use-case for the Chromaprint Matcher is that it will gladly find all duplicates in the current Pony Music Archive (just temporarily lower the threshold and safeguards until satisfied!).  
It has already helped eliminate several hundred dups and track down new aliases for some musicians (turns out they sometimes upload a couple of the same songs under two different names).

