#[derive(Debug)]
pub struct Song {
    pub compressed_print: String,
    pub print: Vec<i32>,
    pub duration: i32,
}

impl Song {
    pub fn new(line: &str) -> Song {
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

    pub fn decode_print(print: &str) -> Vec<i32> {
        chromaprint::Chromaprint::decode(print.as_bytes(), true).unwrap().0
    }
}
