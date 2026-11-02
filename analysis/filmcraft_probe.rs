// Integration-test probe: runs FilmCraft's real `InputTransform` (HLG -> Rec. 709 working space,
// auto tone map on) on the test pattern's patches and prints the 8-bit sRGB result.
//
// Use: copy this file to `crates/color/tests/filmcraft_probe.rs` inside a FilmCraft checkout, then
//   cargo test -p filmcraft-color --test filmcraft_probe -- --nocapture | grep PROBE
// and delete it afterwards. `analysis/probe_main_output.txt` and `analysis/probe_pr3312_output.txt`
// are its output on main 8c171a0a and on PR 3312 head aaded55a (2026-11-01).
use filmcraft_color::{ColorPipeline, ColorSpace, InputTransform, Matrix, Range, linear_to_srgb, normalize_c, normalize_y, ycbcr_to_rgb};

fn decode(ycc: [u32; 3]) -> [f32; 3] {
    ycbcr_to_rgb(normalize_y(ycc[0], 10, Range::Limited), normalize_c(ycc[1], 10, Range::Limited), normalize_c(ycc[2], 10, Range::Limited), Matrix::Bt2020Ncl)
}

#[test]
fn probe() {
    let t = InputTransform::new(ColorSpace::Rec2100Hlg, Range::Limited, &ColorPipeline::REC709, None);
    let patches: &[(&str, [u32; 3])] = &[
        ("grey10", [152, 512, 512]), ("grey20", [239, 512, 512]), ("grey30", [327, 512, 512]), ("grey40", [414, 512, 512]), ("grey50", [502, 512, 512]),
        ("grey60", [590, 512, 512]), ("grey70", [677, 512, 512]), ("grey80", [765, 512, 512]), ("grey90", [852, 512, 512]), ("grey100", [940, 512, 512]),
        ("red75", [237, 418, 848]), ("green75", [509, 270, 203]), ("blue75", [103, 848, 485]), ("skin", [572, 460, 573]), ("foliage", [480, 428, 466]),
        ("denim", [336, 578, 494]), ("lit_skin", [701, 432, 562]), ("bark", [721, 493, 518]), ("warm_hilite", [830, 448, 552]),
    ];
    for (name, ycc) in patches {
        let sig = decode(*ycc);
        let lin = t.convert(sig);
        let e = lin.map(|v| (linear_to_srgb(v.clamp(0.0, 1.0)) * 255.0).round() as u8);
        println!("PROBE {name:<12} signal {:.4?} -> working {:.4?} -> sRGB8 {:?}", sig, lin, e);
    }
}
