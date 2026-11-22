//! rAJIT render-path benchmark: times the script (`run_frame`) and display-tree walk +
//! command generation (`render`, null renderer: no GPU) of synthetic tile-game scenes.
//! Generate the SWFs with `python3 tools/rajit/gen_tiles.py`.

use ruffle_core::swf::{self, Tag};
use ruffle_core::tag_utils::movie_from_path;
use ruffle_core::PlayerBuilder;
use std::time::{Duration, Instant};

fn bench(name: &str, path: &str, frames: u32, expect: &[(u16, usize)]) {
    // Sanity check with Ruffle's own SWF reader: each layer sprite must hold the expected tiles.
    let data = std::fs::read(path).expect("read swf");
    let buf = swf::decompress_swf(&data[..]).expect("decompress");
    let parsed = swf::parse_swf(&buf).expect("parse");
    let mut tiles = 0;
    for &(id, count) in expect {
        let placed = parsed
            .tags
            .iter()
            .find_map(|t| match t {
                Tag::DefineSprite(sprite) if sprite.id == id => Some(
                    sprite.tags.iter().filter(|t| matches!(t, Tag::PlaceObject(_))).count(),
                ),
                _ => None,
            })
            .unwrap_or_else(|| panic!("{name}: sprite {id} missing"));
        assert_eq!(placed, count, "{name}: unexpected tile count in sprite {id}");
        tiles += placed;
    }

    let movie = movie_from_path(path, None).expect("load swf");
    let player = PlayerBuilder::new()
        .with_movie(movie)
        .with_autoplay(true)
        .with_viewport_dimensions(550, 400, 1.0)
        .build();
    let mut p = player.lock().unwrap();

    for _ in 0..10 {
        p.run_frame();
        p.render();
    }

    let (mut script, mut render) = (Duration::ZERO, Duration::ZERO);
    for _ in 0..frames {
        let t = Instant::now();
        p.run_frame();
        script += t.elapsed();
        let t = Instant::now();
        p.render();
        render += t.elapsed();
    }
    println!(
        "BENCH {name}: tiles={tiles} script={:.1}us/frame render={:.1}us/frame",
        script.as_secs_f64() * 1e6 / frames as f64,
        render.as_secs_f64() * 1e6 / frames as f64
    );
}

#[test]
#[ignore]
fn tiles_visible() {
    bench("tiles_visible", "rajit_bench_assets/tiles_visible.swf", 400, &[(3, 1200)]);
}

#[test]
#[ignore]
fn tiles_scroll() {
    bench("tiles_scroll", "rajit_bench_assets/tiles_scroll.swf", 400, &[(3, 1200)]);
}

#[test]
#[ignore]
fn layers_cached() {
    bench("layers_cached", "rajit_bench_assets/layers_cached.swf", 400, &[(3, 3000), (4, 1500), (5, 300)]);
}

#[test]
#[ignore]
fn layers_plain() {
    bench("layers_plain", "rajit_bench_assets/layers_plain.swf", 400, &[(3, 3000), (4, 1500), (5, 300)]);
}
