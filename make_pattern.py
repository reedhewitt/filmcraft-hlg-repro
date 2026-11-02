"""Write sample/hlg_pattern.mov: 1920x1080, 60 fps, 1 s, 10-bit ProRes 422 HQ tagged
BT.2020 primaries / HLG (arib-std-b67) / BT.2020 non-constant-luminance, limited range.
Top row: 11 neutral grey steps at HLG signal 0%,10%..100%.
Bottom row: colour patches given as HLG R'G'B' signal values (BT.2020).
Patch layout is printed to sample/hlg_pattern.json."""
import json, struct, subprocess, os
W, H = 1920, 1080
greys = [i / 10 for i in range(11)]
colours = {"red75": (0.75, 0, 0), "green75": (0, 0.75, 0), "blue75": (0, 0, 0.75),
           "cyan75": (0, 0.75, 0.75), "magenta75": (0.75, 0, 0.75), "yellow75": (0.75, 0.75, 0),
           "skin": (0.68, 0.55, 0.47), "foliage": (0.40, 0.52, 0.30), "denim": (0.28, 0.31, 0.45),
           "lit_skin": (0.81, 0.71, 0.56), "bark": (0.76, 0.75, 0.71), "warm_hilite": (0.94, 0.86, 0.74)}
KR, KB = 0.2627, 0.0593  # BT.2020 NCL
def ycc(r, g, b):
    y = KR * r + (1 - KR - KB) * g + KB * b
    cb = (b - y) / (2 * (1 - KB)); cr = (r - y) / (2 * (1 - KR))
    return round(64 + 876 * y), round(512 + 896 * cb), round(512 + 896 * cr)
patches, cells = [], []
gw = W // len(greys)
for i, v in enumerate(greys):
    patches.append({"name": f"grey{int(v*100)}", "hlg_rgb": [v, v, v], "box": [i * gw, 0, gw, H // 2]})
cw = W // len(colours)
for i, (n, c) in enumerate(colours.items()):
    patches.append({"name": n, "hlg_rgb": list(c), "box": [i * cw, H // 2, cw, H // 2]})
planes = [bytearray(W * H * 2) for _ in range(3)]
for p in patches:
    x0, y0, w, h = p["box"]; code = ycc(*p["hlg_rgb"]); p["ycbcr10"] = code
    for k in range(3):
        row = struct.pack("<H", code[k]) * w
        for y in range(y0, y0 + h):
            o = (y * W + x0) * 2; planes[k][o:o + 2 * w] = row
os.makedirs("sample", exist_ok=True)
raw = b"".join(planes)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv444p10le", "-s", f"{W}x{H}",
    "-r", "60", "-i", "-", "-vf", "loop=59:1:0,setparams=range=tv:color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc", "-frames:v", "60", "-c:v", "prores_ks", "-profile:v", "3",
    "-pix_fmt", "yuv422p10le", "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
    "-colorspace", "bt2020nc", "-color_range", "tv", "sample/hlg_pattern.mov"], input=raw, check=True)
json.dump({"size": [W, H], "patches": patches}, open("sample/hlg_pattern.json", "w"), indent=1)
print("wrote sample/hlg_pattern.mov,", len(patches), "patches")
