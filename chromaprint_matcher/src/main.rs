mod song;
use song::*;
mod matcher;
use matcher::*;

use std::io::{self, BufRead};
use std::error::Error;
use rayon::prelude::*;
use structopt::StructOpt;

#[derive(StructOpt)]
struct Opt
{
    #[structopt(short, long)]
    duration_diff: Option<i32>,

    #[structopt(short, long)]
    immediate_threshold: Option<f32>,

    #[structopt(short, long)]
    partial_threshold: Option<f32>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let opt = Opt::from_args();
    let mut params = MatchParams::default();
    if let Some(duration_diff) = opt.duration_diff {
        params.max_match_duration_diff = duration_diff;
    }
    if let Some(immediate_threshold) = opt.immediate_threshold {
        params.match_immediate_threshold = immediate_threshold;
    }
    if let Some(partial_threshold) = opt.partial_threshold {
        params.match_partial_threshold = partial_threshold;
    }

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
        if let (Some(song_match), score) = find_fingerprint_match(&song, &dst_songs, &params) {
            println!("{} {} {}", song.compressed_print, song_match.compressed_print, score.to_string());
        }
    });
    Ok(())
}
