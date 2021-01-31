use super::song::Song;
use std::cmp::min;

const DEFAULT_MAX_MATCH_DURATION_DIFF: i32 = 5;
const DEFAULT_MATCH_IMMEDIATE_THRESHOLD: f32 = 0.98;
const DEFAULT_MATCH_PARTIAL_THRESHOLD: f32 = 0.98;

pub struct MatchParams
{
    pub max_match_duration_diff: i32,
    pub match_immediate_threshold: f32,
    pub match_partial_threshold: f32,
}

impl Default for MatchParams {
    fn default() -> Self {
        Self {
            max_match_duration_diff: DEFAULT_MAX_MATCH_DURATION_DIFF,
            match_immediate_threshold: DEFAULT_MATCH_IMMEDIATE_THRESHOLD,
            match_partial_threshold: DEFAULT_MATCH_PARTIAL_THRESHOLD,
        }
    }
}

pub fn find_fingerprint_match<'a>(song: &'a Song, dst_songs: &'a [Song], params: &MatchParams) -> (Option<&'a Song>, f32) {
    let mut best_score = 0.0;
    let mut best_match: Option<&Song> = None;

    for dst_song in dst_songs.iter() {
        if (song.duration - dst_song.duration).abs() > params.max_match_duration_diff {
            continue;
        }

        let mut error = 0f32;
        for (x, y) in song.print.iter().zip(dst_song.print.iter()) {
            error += (x ^ y).count_ones() as f32;
        }
        let min_len = min(song.print.len(), dst_song.print.len()).max(1);
        let score = 1.0 - error / 32.0 / min_len as f32;
        if score >= params.match_immediate_threshold {
            return (Some(dst_song), score);
        } else if score >= params.match_partial_threshold && score > best_score {
            best_score = score;
            best_match = Some(dst_song);
        }
    }

    (best_match, best_score)
}
