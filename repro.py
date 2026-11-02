#!/usr/bin/env python3
"""Reproduce FilmCraft's HLG -> Rec.709 conversion and compare it with ffmpeg references.

Usage:  python3 repro.py            (needs filmcraft-cli and ffmpeg on PATH)

For each sample in sample/, builds a headless FilmCraft project (Rec.709 working space,
auto tone map ON, i.e. the defaults), places the clip, exports one PNG frame, and renders
the same frame with ffmpeg (zscale + tonemap). Writes everything to out/ and prints
per-patch RGB for the synthetic pattern plus whole-frame luma/saturation for the iPhone clip.

The real-footage step runs only if sample/iphone_hlg_dv_4s.mov is present (any iPhone HLG clip,
shot in portrait, will do; it is not part of this repository). The synthetic pattern alone
carries the grey-ramp and colour-patch measurements.
"""
import json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SAMPLE = os.path.join(HERE, "sample")
FPS = 60

# ffmpeg references. Both linearise HLG with the HLG inverse OETF + OOTF (zscale, nominal
# peak 203 cd/m2 per BT.2408 reference white) and convert BT.2020 -> BT.709 primaries.
REFS = {
    "ffmpeg_hable": "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
                    "zscale=t=bt709:m=bt709:r=tv,format=rgb24",
    "ffmpeg_clip": "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=clip,"
                   "zscale=t=bt709:m=bt709:r=tv,format=rgb24",
}

# boxes (x, y, w, h) on the 1080x1920 iPhone frame; mean of the middle 50% of each box
IPHONE_REGIONS = {"cheek": (400, 540, 80, 80), "forehead": (470, 260, 120, 60), "shirt": (450, 1050, 160, 160),
                  "foliage": (100, 250, 160, 160), "bark": (900, 650, 160, 160),
                  "tablet": (300, 1450, 160, 80), "ground": (60, 1700, 120, 120)}

def sh(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"failed: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout

def fc_build(name, media, seq_w, seq_h, fit):
    proj = os.path.join(OUT, f"{name}.fcproj")
    lines = [
        {"id": "file.newProject", "params": {"name": name}},
        {"id": "file.import", "params": {"paths": [media]}},
        {"id": "file.newSequence", "params": {"name": "repro", "width": seq_w, "height": seq_h,
                                               "fps": FPS, "video": 1, "audio": 1}},
    ]
    jl = os.path.join(OUT, f"{name}_build.jsonl")
    open(jl, "w").write("\n".join(json.dumps(l) for l in lines) + "\n")
    res = [json.loads(l) for l in sh(["filmcraft-cli", "run", jl, "--save-as", proj]).splitlines() if l.startswith("{")]
    item = res[1]["result"]["items"][0]
    place = [{"id": "timeline.place", "params": {"item": item, "track": "V1", "audioTrack": "A1", "frame": 0,
                                                  "insert": False, "sourceIn": {"frame": 0}, "duration": {"frame": 60}}}]
    open(jl, "w").write(json.dumps(place[0]) + "\n")
    res = [json.loads(l) for l in sh(["filmcraft-cli", "--project", proj, "--save", "run", jl]).splitlines() if l.startswith("{")]
    if fit:
        clip = res[0]["result"]["clips"][0]
        sh(["filmcraft-cli", "--project", proj, "--save", "exec", "clip.fitToFrame", json.dumps({"clips": [clip]})])
    color = json.loads(sh(["filmcraft-cli", "--project", proj, "exec", "sequence.colorSettings", "{}"]))
    return proj, color

def fc_frame(proj, name, t):
    base = os.path.join(OUT, f"{name}_filmcraft.png")
    sh(["filmcraft-cli", "--project", proj, "export", base, "--format", "png",
        "--start", str(t), "--end", str(t + 1 / FPS)])
    seq_png = base[:-4] + "000.png"          # the PNG exporter numbers frames
    os.replace(seq_png, base)
    return base

def ref_frame(media, name, t, w, h, fit):
    outs = {}
    for k, vf in REFS.items():
        p = os.path.join(OUT, f"{name}_{k}.png")
        scale = f",scale={w}:{h}:flags=lanczos" if fit else ""
        sh(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", media, "-frames:v", "1", "-vf", vf + scale, p])
        outs[k] = p
    # Apple's own HDR -> SDR conversion (AVFoundation, macOS only): what Photos/QuickTime show
    # and what an iPhone user expects. avconvert's H.264 presets tone-map HLG to Rec.709 SDR.
    if shutil.which("avconvert"):
        mov = os.path.join(OUT, f"{name}_apple.mov")
        sh(["avconvert", "-s", media, "-p", "Preset1920x1080", "-o", mov, "--duration", str(t + 1), "--replace"])
        p = os.path.join(OUT, f"{name}_apple.png")
        sh(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", mov, "-frames:v", "1",
            "-vf", f"scale={w}:{h}:flags=lanczos:in_color_matrix=bt709,format=rgb24", p])
        os.remove(mov)
        outs["apple"] = p
    return outs

def mean_rgb(png, box):
    x, y, w, h = box
    # sample the middle 50% of the patch to stay clear of chroma-subsampled edges
    cx, cy, cw, ch = x + w // 4, y + h // 4, w // 2, h // 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", png, "-vf",
                          f"crop={cw}:{ch}:{cx}:{cy},scale=1:1:flags=area,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return list(raw[:3])

def frame_stats(png):
    out = subprocess.run(["ffmpeg", "-i", png, "-vf", "signalstats,metadata=print", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    get = lambda k: float(out.split(f"lavfi.signalstats.{k}=")[1].split()[0])
    return {"YAVG": get("YAVG"), "SATAVG": get("SATAVG"), "YHIGH": get("YHIGH")}

def main():
    os.makedirs(OUT, exist_ok=True)
    report = {}

    # 1. synthetic pattern: 1920x1080 sequence, clip at 100% (same size, no scaling)
    pat = os.path.join(SAMPLE, "hlg_pattern.mov")
    layout = json.load(open(os.path.join(SAMPLE, "hlg_pattern.json")))
    proj, color = fc_build("pattern", pat, 1920, 1080, fit=False)
    imgs = {"filmcraft": fc_frame(proj, "pattern", 0.5)}
    imgs.update(ref_frame(pat, "pattern", 0.5, 1920, 1080, fit=False))
    rows = []
    for p in layout["patches"]:
        rows.append({"patch": p["name"], "hlg_rgb_signal": p["hlg_rgb"],
                     **{k: mean_rgb(v, p["box"]) for k, v in imgs.items()}})
    report["pattern"] = {"sequenceColor": color, "patches": rows}

    # 2. real iPhone clip: 1080x1920 sequence, clip fit to frame (as in the real projects)
    clip = os.path.join(SAMPLE, "iphone_hlg_dv_4s.mov")
    have_clip = os.path.exists(clip)
    if have_clip:
        proj, color = fc_build("iphone", clip, 1080, 1920, fit=True)
        imgs = {"filmcraft": fc_frame(proj, "iphone", 0.5)}
        imgs.update(ref_frame(clip, "iphone", 0.5, 1080, 1920, fit=True))
        regions = {k: v for k, v in IPHONE_REGIONS.items()}
        report["iphone"] = {"sequenceColor": color,
                            "frameStats": {k: frame_stats(v) for k, v in imgs.items()},
                            "regions": {n: {k: mean_rgb(v, b) for k, v in imgs.items()} for n, b in regions.items()}}
    else:
        print("note: sample/iphone_hlg_dv_4s.mov not found, skipping the real-footage comparison", file=sys.stderr)

    json.dump(report, open(os.path.join(OUT, "results.json"), "w"), indent=1)

    # side-by-side images: FilmCraft | Apple (or ffmpeg hable when avconvert is missing)
    ref = "apple" if "apple" in imgs else "ffmpeg_hable"
    for name, w, h in [("pattern", 960, 540)] + ([("iphone", 540, 960)] if have_clip else []):
        sh(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(OUT, f"{name}_filmcraft.png"),
            "-i", os.path.join(OUT, f"{name}_{ref}.png"), "-filter_complex",
            f"[0]scale={w}:{h}[a];[1]scale={w}:{h}[b];[a][b]hstack", os.path.join(OUT, f"compare_{name}.png")])
    cols = [k for k in ("filmcraft", "apple", "ffmpeg_clip", "ffmpeg_hable") if k in imgs]
    print(f"{'patch':<12}{'HLG signal':<20}" + "".join(f"{c:<17}" for c in cols))
    for r in rows:
        print(f"{r['patch']:<12}{str(r['hlg_rgb_signal']):<20}" + "".join(f"{str(r[c]):<17}" for c in cols))
    if have_clip:
        print(f"\niPhone frame regions (RGB 0-255)\n{'region':<12}" + "".join(f"{c:<17}" for c in cols))
        for n, v in report["iphone"]["regions"].items():
            print(f"{n:<12}" + "".join(f"{str(v[c]):<17}" for c in cols))
        print("\niPhone whole-frame stats (signalstats, 8-bit):")
        for k, v in report["iphone"]["frameStats"].items():
            print(f"  {k:<13} {v}")
    print(f"\nwrote {OUT}/results.json and PNGs")

if __name__ == "__main__":
    main()
