use std::io::{self, BufRead};
use std::error::Error;
use std::cmp::min;
use rayon::prelude::*;
use chromaprint;

const MAX_MATCH_DURATION_DIFF: i32 = 5;
const MATCH_IMMEDIATE_TRESHOLD: f32 = 0.98;
const MATCH_PARTIAL_TRESHOLD: f32 = 0.97;

#[derive(Debug)]
struct Song {
    pub compressed_print: String,
    pub print: Vec<i32>,
    pub duration: i32,
}

impl Song {
    fn new(line: &str) -> Song {
        let words: Vec<_> = line.split(' ').collect();
        assert_eq!(words.len(), 2);
        let duration = words[0].parse().unwrap();
        let compressed_print = words[1].to_owned();
        let print = Song::decode_print(&compressed_print);
        Song {
            compressed_print,
            print,
            duration,
        }
    }

    fn decode_print(print: &str) -> Vec<i32> {
        chromaprint::Chromaprint::decode(print.as_bytes(), true).unwrap().0
    }
}

fn find_fingerprint_match<'a>(song: &'a Song, dst_songs: &'a [Song]) -> (Option<&'a Song>, f32) {
    let mut best_score = 0.0;
    let mut best_match: Option<&Song> = None;

    for dst_song in dst_songs.iter() {
        if (song.duration - dst_song.duration).abs() > MAX_MATCH_DURATION_DIFF {
            continue;
        }

        let mut error = 0f32;
        for (x, y) in song.print.iter().zip(dst_song.print.iter()) {
            error += (x ^ y).count_ones() as f32;
        }
        let min_len = min(song.print.len(), dst_song.print.len()).max(1);
        let score = 1.0 - error / 32.0 / min_len as f32;
        if score >= MATCH_IMMEDIATE_TRESHOLD {
            return (Some(dst_song), score);
        } else if score >= MATCH_PARTIAL_TRESHOLD && score > best_score {
            best_score = score;
            best_match = Some(dst_song);
        }
    }

    return (best_match, best_score)
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut dst_songs: Vec<String> = Vec::new();
    let mut src_songs: Vec<String> = Vec::new();

    let stdin = io::stdin();
    let mut end_of_dst = false;
    for line in stdin.lock().lines() {
        let line = line?.trim().to_owned();
        if line.is_empty() {
            end_of_dst = true;
            continue
        }
        if !end_of_dst {
            dst_songs.push(line);
        } else {
            src_songs.push(line);
        }
    }
    let dst_songs: Vec<_> = dst_songs.par_iter().map(|ref s| Song::new(s)).collect();
    let src_songs: Vec<_> = src_songs.par_iter().map(|ref s| Song::new(s)).collect();

    src_songs.par_iter().for_each(|song| {
        if let (Some(song_match), score) = find_fingerprint_match(&song, &dst_songs) {
            println!("{} {} {}", song.compressed_print, song_match.compressed_print, score.to_string());
        }
    });
    Ok(())
}
