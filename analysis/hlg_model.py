#!/usr/bin/env python3
"""Model of FilmCraft's HLG -> Rec.709 input transform (crates/color/src/transform.rs on main),
of PR 3312's BT.2446-1 Method A variant, and of a BT.2100 OOTF rendered for a 100 cd/m2 SDR
display, all evaluated on the handoff's test pattern and compared with out/results.json.
Run:  python3 -I analysis/hlg_model.py [repo_dir]
"""
import json, math, os, subprocess, sys

H = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
pat = json.load(open(f"{H}/sample/hlg_pattern.json"))
res = json.load(open(f"{H}/out/results.json"))
meas = {r['patch']: r for r in res['pattern']['patches']}

A, B, C = 0.17883277, 0.28466892, 0.55991073
def hlg_inv(e):
    e = min(max(e, 0.0), 1.0)
    return e*e/3.0 if e <= 0.5 else (math.exp((e-C)/A)+B)/12.0
def srgb_enc(v):
    v = min(max(v, 0.0), 1.0)
    return v*12.92 if v <= 0.0031308 else 1.055*v**(1/2.4)-0.055
def to8(v, enc='srgb'):
    e = srgb_enc(v) if enc == 'srgb' else min(max(v, 0.0), 1.0)**(1.0/float(enc))
    return int(round(e*255))

def inv3(m):
    (a,b,c),(d,e,f),(g,h,i) = m
    det = a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g); k = 1/det
    return [[(e*i-f*h)*k,(c*h-b*i)*k,(b*f-c*e)*k],[(f*g-d*i)*k,(a*i-c*g)*k,(c*d-a*f)*k],[(d*h-e*g)*k,(b*g-a*h)*k,(a*e-b*d)*k]]
def mul3(a,b): return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def mulv(m,v): return [sum(m[i][k]*v[k] for k in range(3)) for i in range(3)]
def npm(p, w):
    xyz = lambda c: [c[0]/c[1], 1.0, (1-c[0]-c[1])/c[1]]
    r,g,b = xyz(p[0]),xyz(p[1]),xyz(p[2])
    m = [[r[0],g[0],b[0]],[r[1],g[1],b[1]],[r[2],g[2],b[2]]]
    s = mulv(inv3(m), xyz(w))
    return [[m[i][j]*s[j] for j in range(3)] for i in range(3)]
D65 = [0.3127, 0.3290]
N709 = npm([[0.640,0.330],[0.300,0.600],[0.150,0.060]], D65)
N2020 = npm([[0.708,0.292],[0.170,0.797],[0.131,0.046]], D65)
M2020_709 = mul3(inv3(N709), N2020)
L2020, L709 = N2020[1], N709[1]
dot = lambda a,b: sum(x*y for x,y in zip(a,b))

# PQ and the BT.2390 EETF exactly as crates/color/src/transform.rs
m1, m2 = 0.1593017578125, 78.84375
c1, c2, c3 = 0.8359375, 18.8515625, 18.6875
def pq_inv(y):
    p = max(y,0.0)**m1; return ((c1+c2*p)/(1+c3*p))**m2
def pq_eotf(e):
    p = max(e,0.0)**(1/m2); return (max(p-c1,0.0)/(c2-c3*p))**(1/m1)
def eetf(nits, s, d):
    if d >= s or nits <= 0: return min(max(nits,0.0), max(s,d))
    pq = lambda n: pq_inv(min(max(n/10000.0,0.0),1.0))
    smax = pq(s); e1 = min(pq(nits)/smax, 1.0); max_lum = pq(d)/smax; ks = 1.5*max_lum-0.5
    if e1 < ks: e2 = e1
    else:
        t = (e1-ks)/(1-ks); t2, t3 = t*t, t*t*t
        e2 = (2*t3-3*t2+1)*ks + (t3-2*t2+t)*(1-ks) + (-2*t3+3*t2)*max_lum
    return pq_eotf(e2*smax)*10000.0
def tonemap2390(c, s, d):
    m = max(c)
    if m <= 0: return c
    nits = m*203.0
    k = (d/203.0)/m if nits >= s else eetf(nits, s, d)/nits
    return [v*k for v in c]
def desat(c, luma):
    mn = min(c)
    if mn >= 0: return c
    y = dot(luma, c)
    if y <= 0: return [0.0]*3
    t = y/(y-mn); return [max(y+(v-y)*t, 0.0) for v in c]
def clip(c, _luma=None): return [min(max(v,0.0),1.0) for v in c]

def ycbcr_to_rgb(ycc):
    Y, Cb, Cr = ycc
    y = (Y-64)/876.0; cb = (Cb-512)/896.0; cr = (Cr-512)/896.0
    kr, kb = 0.2627, 0.0593; kg = 1-kr-kb
    r = y + 2*(1-kr)*cr; b = y + 2*(1-kb)*cb; g = (y - kr*r - kb*b)/kg
    return [r,g,b]

# ---- A. FilmCraft main: HLG inverse OETF -> BT.2100 OOTF (Lw 1000, gamma 1.2) / 203 -> BT.2020->709 -> BT.2390 1000->203 -> desaturate
def fc_main(sig):
    c = [hlg_inv(v) for v in sig]
    ys = max(dot(L2020, c), 0.0); g = (1000.0/203.0)*ys**0.2
    c = [v*g for v in c]
    c = mulv(M2020_709, c)
    c = tonemap2390(c, 1000.0, 203.0)
    return desat(c, L709)

# ---- B. PR 3312 / 1273: same OOTF, then BT.2446-1 Method A in BT.2020, then the matrix
def bt2446a(c):
    rgb = [min(max(v*(203.0/1000.0),0.0),1.0)**(1/2.4) for v in c]
    y = 0.2627*rgb[0]+0.6780*rgb[1]+0.0593*rgb[2]
    if y <= 0: return [0.0]*3
    yp = math.log(1+12.259798*y)/2.5847368
    yc = 1.0770*yp if yp <= 0.7399 else (-1.1510*yp*yp+2.7811*yp-0.6302 if yp < 0.9909 else 0.5*yp+0.5)
    sdr = (math.exp(yc*1.7399323)-1)/4.696958
    scale = sdr/(1.1*y)
    cb = scale*(rgb[2]-y)/1.8814; cr = scale*(rgb[0]-y)/1.4746
    luma = sdr - max(0.1*cr, 0.0)
    r = luma+1.4746*cr; b = luma+1.8814*cb; g = (luma-0.2627*r-0.0593*b)/0.6780
    return [max(v,0.0)**2.4 for v in (r,g,b)]
def fc_pr3312(sig):
    c = [hlg_inv(v) for v in sig]
    ys = max(dot(L2020, c), 0.0); g = (1000.0/203.0)*ys**0.2
    c = [v*g for v in c]
    c = bt2446a(c)
    c = mulv(M2020_709, c)
    return desat(c, L709)

# ---- C. BT.2100 HLG OOTF rendered for an SDR display: HLG 100 % = SDR white, system gamma g
def bt2390_gamma(lw): return 1.2 * 1.111 ** math.log2(lw/1000.0)
def ootf_sdr(sig, gamma, gm=desat):
    c = [hlg_inv(v) for v in sig]
    ys = dot(L2020, c)
    k = ys**(gamma-1.0) if ys > 0 else 0.0
    c = [v*k for v in c]
    c = mulv(M2020_709, c)
    return gm(c, L709)

greys = [p for p in pat['patches'] if p['name'].startswith('grey') and p['name'] != 'grey0']
colours = [p for p in pat['patches'] if not p['name'].startswith('grey')]
real = ['skin', 'foliage', 'denim', 'lit_skin', 'bark', 'warm_hilite']
apple_mean = lambda n: sum(meas[n]['apple'])/3.0
fmt = lambda v: "(" + ",".join(f"{x:3d}" for x in v) + ")"
G100 = bt2390_gamma(100.0)

def main():
    print("== 1. Model of main vs the measured FilmCraft column (G channel; patches decoded from their Y'CbCr codes) ==")
    print(f"{'patch':<12}{'measured':>10}{'model':>8}{'diff':>6}")
    worst = 0
    for p in pat['patches'][1:]:
        sig = ycbcr_to_rgb(p['ycbcr10']); m = [to8(v) for v in fc_main(sig)]; a = meas[p['name']]['filmcraft']
        d = max(abs(x-y) for x,y in zip(m,a)); worst = max(worst, d)
        print(f"{p['name']:<12}{fmt(a):>16}{fmt(m):>16}  max|diff| {d}")
    print(f"largest per-channel difference over all patches: {worst}")

    print("\n== 2. Fit of model C to Apple's grey ramp (mean RGB): best system gamma per display encode ==")
    for enc in ('srgb', '2.4', '2.2'):
        best = None
        for i in range(600, 1301, 5):
            gamma = i/1000.0
            err = sum((to8(ootf_sdr(ycbcr_to_rgb(p['ycbcr10']), gamma)[1], enc) - apple_mean(p['name']))**2 for p in greys)
            if best is None or err < best[1]: best = (gamma, err)
        print(f"  encode {enc:<5} best gamma {best[0]:.3f}  rms {math.sqrt(best[1]/len(greys)):.2f} codes")
    print(f"  BT.2390 extended system gamma 1.2*1.111^log2(Lw/1000) at Lw = 100 cd/m2: {G100:.4f}")

    print("\n== 3. Grey ramp, 8-bit sRGB, vs Apple (mean RGB) ==")
    cands = [("main", fc_main), ("PR3312", fc_pr3312), (f"C g={G100:.3f}", lambda s: ootf_sdr(s, G100)), ("C g=0.78", lambda s: ootf_sdr(s, 0.78)), ("inv OETF only", lambda s: ootf_sdr(s, 1.0))]
    print(f"{'HLG':<6}{'Apple':>7}{'hable':>7}" + "".join(f"{n:>16}" for n,_ in cands))
    tot = {n: 0.0 for n,_ in cands}; worst = {n: 0 for n,_ in cands}
    for p in greys:
        sig = ycbcr_to_rgb(p['ycbcr10']); a = apple_mean(p['name']); hb = sum(meas[p['name']]['ffmpeg_hable'])/3.0
        row = f"{p['name'][4:]+'%':<6}{a:>7.0f}{hb:>7.0f}"
        for n,f in cands:
            v = to8(f(sig)[1]); tot[n] += (v-a)**2; worst[n] = max(worst[n], abs(round(v-a)))
            row += f"{v:>11}({v-a:+.0f})"
        print(row)
    print("rms vs Apple:   ", {n: round(math.sqrt(t/len(greys)),1) for n,t in tot.items()})
    print("worst vs Apple: ", worst, " (handoff threshold: 6)")

    print(f"\n== 4. Colour patches, 8-bit sRGB, vs Apple; d = largest per-channel difference (handoff threshold for real colours: 8) ==")
    rows = [("main", fc_main), ("PR3312", fc_pr3312), (f"C g={G100:.3f} desat", lambda s: ootf_sdr(s, G100)), (f"C g={G100:.3f} clip", lambda s: ootf_sdr(s, G100, clip))]
    worst = {n: 0 for n,_ in rows}
    for p in colours:
        sig = ycbcr_to_rgb(p['ycbcr10']); a = meas[p['name']]['apple']
        line = f"{p['name']:<12} apple {fmt(a)}"
        for n,f in rows:
            m = [to8(v) for v in f(sig)]; d = max(abs(x-y) for x,y in zip(m,a))
            if p['name'] in real: worst[n] = max(worst[n], d)
            line += f"  | {n} {fmt(m)} d{d:>3}"
        print(line)
    print("worst over the six real-world colours:", worst)

    print("\n== 5. HLG reference white (75 % signal, 203 cd/m2 on a 1000 cd/m2 display) in working-linear and 8-bit sRGB ==")
    for n,f in cands:
        l = f([0.75]*3)[1]; print(f"  {n:<14} linear {l:.3f}  8-bit {to8(l)}")
    ks = 1.5*pq_inv(203/10000)/pq_inv(1000/10000)-0.5
    print(f"  BT.2390 knee (1000 -> 203 cd/m2) starts at {pq_eotf(ks*pq_inv(1000/10000))*10000:.0f} cd/m2 = {pq_eotf(ks*pq_inv(1000/10000))*10000/203:.2f} working")

    # ---- 7. real footage: raw HLG R'G'B' of the repro's iPhone regions through the models
    clip_path = f"{H}/sample/iphone_hlg_dv_4s.mov"
    regions = {"cheek": (400, 540, 80, 80), "forehead": (470, 260, 120, 60), "shirt": (450, 1050, 160, 160), "foliage": (100, 250, 160, 160),
               "bark": (900, 650, 160, 160), "tablet": (300, 1450, 160, 80), "ground": (60, 1700, 120, 120)}
    if os.path.exists(clip_path):
        print("\n== 6. iPhone frame regions: raw HLG R'G'B' (ffmpeg, no tone map, 1080x1920 as repro.py) through the models vs measured ==")
        print("   (mean of the signal then transform, so textured regions are only approximate)")
        print(f"{'region':<10}{'raw HLG signal':>22}{'FC measured':>16}{'model main':>16}{'Apple':>16}{'model C':>16}{'PR3312':>16}")
        for name, (x,y,w,h) in regions.items():
            cx, cy, cw, ch = x + w//4, y + h//4, w//2, h//2
            vf = f"zscale=w=1080:h=1920:f=lanczos,format=rgb48le,crop={cw}:{ch}:{cx}:{cy},scale=1:1:flags=area,format=rgb48le"
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", clip_path, "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"], capture_output=True)
            if r.returncode or len(r.stdout) < 6:
                print(f"{name:<10} ffmpeg failed: {r.stderr.decode()[:200]}"); continue
            raw = [int.from_bytes(r.stdout[i:i+2], 'little')/65535.0 for i in (0,2,4)]
            mm = res['iphone']['regions'][name]
            out = lambda f: fmt([to8(v) for v in f(raw)])
            print(f"{name:<10}{'(' + ','.join(f'{v:.3f}' for v in raw) + ')':>22}{fmt(mm['filmcraft']):>16}{out(fc_main):>16}{fmt(mm['apple']):>16}{out(lambda s: ootf_sdr(s, G100)):>16}{out(fc_pr3312):>16}")

if __name__ == "__main__":
    main()
