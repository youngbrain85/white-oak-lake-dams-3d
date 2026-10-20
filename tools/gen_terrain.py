#!/usr/bin/env python3
"""Generate terrain heightmap, albedo texture, masks and tree placements for the
White Oak Lake Dam 1 / Dam 2 3D model, from the 2005 aerial embedded in the bid set
(sheet 3, 1"=200' rendered at 200 dpi => 1 px = 1 ft) and the plan/contour data.

World frame (feet): X = east, Z = south (Three.js), Y = elevation (NAVD88 ft).
Local spillway frame: x = downstream along new spillway centerline, y = NNE along dam.
Origin = spillway centerline station 30+45 (center of the 40' semicircular weir).
"""
import json, math, os
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

Image.MAX_IMAGE_PIXELS = None
REF = os.path.join(os.path.dirname(__file__), '..', 'ref')
OUT = os.path.join(os.path.dirname(__file__), 'assets')
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- aerial crop
EXT = 2400                        # terrain extent in ft (square)
CX_FULL, CY_FULL = 3126, 2010     # spillway center C (sta 30+45) in full aerial px
aer = Image.open(os.path.join(REF, 'aerial-03.png')).convert('RGB')
x0, y0 = CX_FULL - EXT // 2, CY_FULL - EXT // 2
crop = aer.crop((x0, y0, x0 + EXT, y0 + EXT))
A = np.asarray(crop).astype(np.float32)   # [row(south), col(east), rgb], 1 px = 1 ft

# ------------------------------------------------- remove white labels/arrows
mn = A.min(axis=2)
label = mn > 190
lab_img = Image.fromarray((label * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))
label = np.asarray(lab_img) > 0
# iterative inpaint: blur the image, copy blurred values into label area, repeat
inp = A.copy()
for it in range(12):
    bl = np.asarray(Image.fromarray(inp.astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
    inp[label] = bl[label]
A = inp

R, G, B = A[..., 0], A[..., 1], A[..., 2]
bright = (R + G + B) / 3.0

# ------------------------------------------------------------------- water masks
Ab = np.asarray(Image.fromarray(A.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))).astype(np.float32)
Rb, Gb, Bb = Ab[..., 0], Ab[..., 1], Ab[..., 2]
brightb = (Rb + Gb + Bb) / 3.0
lake1 = (Gb > Rb + 11) & (Gb > Bb + 7) & (brightb > 33) & (brightb < 120)
lake2 = (brightb < 34) & (Bb >= Gb - 3)
def clean(mask, open_r=5, close_r=9, min_keep=None):
    im = Image.fromarray((mask * 255).astype(np.uint8))
    im = im.filter(ImageFilter.MinFilter(open_r)).filter(ImageFilter.MaxFilter(open_r))
    im = im.filter(ImageFilter.MaxFilter(close_r)).filter(ImageFilter.MinFilter(close_r))
    return np.asarray(im) > 0
lake1 = clean(lake1, 7, 15)
lake2 = clean(lake2, 7, 15)

# keep only the connected component containing a known seed (flood fill)
def keep_component(mask, seed):
    im = Image.fromarray((mask * 255).astype(np.uint8)).copy()
    ImageDraw.floodfill(im, seed, 128)
    return np.asarray(im) == 128
lake1 = keep_component(lake1, (EXT // 2 + 330, EXT // 2 - 60))   # inside lake 1
lake2 = keep_component(lake2, (EXT // 2 - 560, EXT // 2 + 120))  # inside lake 2

def dist_to_edge_inside(mask):
    """approx distance (ft) from each inside pixel to the mask boundary"""
    from scipy import ndimage
    return ndimage.distance_transform_edt(mask)
try:
    from scipy import ndimage
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False

def edt(mask):
    if HAVE_SCIPY:
        return ndimage.distance_transform_edt(mask)
    # fallback: coarse multi-radius erosion
    d = np.zeros(mask.shape, np.float32)
    cur = mask.copy()
    for r in range(1, 40):
        im = Image.fromarray((cur * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))
        nxt = np.asarray(im) > 0
        d[cur & ~nxt] = r
        cur = nxt
        if not cur.any():
            break
    d[cur] = 40
    return d

d1_in = edt(lake1); d1_out = edt(~lake1)
d2_in = edt(lake2); d2_out = edt(~lake2)

# ------------------------------------------------------------ local frame helpers
# local x axis (downstream) in world (E, N): u = (-0.967, 0.256); local y axis: v = (0.256, 0.967)
U = np.array([-0.9666, 0.2563]); V = np.array([0.2563, 0.9666])
jj, ii = np.meshgrid(np.arange(EXT), np.arange(EXT))      # ii=row (south), jj=col (east)
E = (jj - EXT / 2).astype(np.float32)                      # east of C
N = -(ii - EXT / 2).astype(np.float32)                     # north of C
LX = E * U[0] + N * U[1]                                   # local x (downstream)
LY = E * V[0] + N * V[1]                                   # local y (along dam, NNE)

# ------------------------------------------------------------ base ground (RBF)
ctrl = [  # (east, north) of C in ft, elevation
    (-70, -90, 490), (-150, -150, 493), (-200, -50, 492), (-250, 50, 493),
    (-100, 100, 472), (-200, 200, 470), (-300, 350, 468), (0, 500, 471), (200, 700, 476),
    (0, 1000, 490), (-600, 1000, 492), (600, 1050, 488), (1000, 900, 485),
    (220, 760, 485), (300, 780, 488), (400, 600, 487), (600, 400, 486),
    (700, -100, 492), (1000, -400, 495), (400, -400, 495), (150, -300, 494),
    (-500, -500, 500), (-900, -300, 505), (-1000, -1000, 505), (0, -1000, 500), (1000, -1000, 498),
    (-500, 200, 474), (-700, 250, 476), (-900, -100, 498), (-300, -40, 494),
    (-1100, 100, 495), (-1100, 600, 490), (-350, 150, 480),
    (-1100, -600, 503), (1100, 100, 487), (1100, 600, 486), (-650, 650, 485),
]
cp = np.array([[c[0], c[1]] for c in ctrl], np.float32)
cz = np.array([c[2] for c in ctrl], np.float32)
# thin-plate-ish RBF (multiquadric) solved exactly
def rbf(r):
    return np.sqrt(r * r + 80.0 ** 2)
Dm = np.linalg.norm(cp[:, None, :] - cp[None, :, :], axis=2)
K = rbf(Dm)
P = np.hstack([np.ones((len(cp), 1)), cp])            # linear polynomial part
Aug = np.block([[K, P], [P.T, np.zeros((3, 3))]])
rhs = np.concatenate([cz, np.zeros(3)])
w = np.linalg.solve(Aug, rhs)
# evaluate on a coarse grid then upsample (speed)
step = 8
ge = (np.arange(0, EXT, step) - EXT / 2).astype(np.float32)
gn = -(np.arange(0, EXT, step) - EXT / 2).astype(np.float32)
GE, GN = np.meshgrid(ge, gn)
pts = np.stack([GE.ravel(), GN.ravel()], 1)
r = np.linalg.norm(pts[:, None, :] - cp[None, :, :], axis=2)
zc = rbf(r) @ w[:len(cp)] + w[len(cp)] + pts[:, 0] * w[len(cp) + 1] + pts[:, 1] * w[len(cp) + 2]
zc = zc.reshape(GE.shape)
base = np.asarray(Image.fromarray(zc.astype(np.float32), 'F').resize((EXT, EXT), Image.BICUBIC))
# gentle natural undulation
rng = np.random.default_rng(7)
noise = np.asarray(Image.fromarray(rng.random((60, 60)).astype(np.float32), 'F').resize((EXT, EXT), Image.BICUBIC))
noise2 = np.asarray(Image.fromarray(rng.random((240, 240)).astype(np.float32), 'F').resize((EXT, EXT), Image.BICUBIC))
base = base + (noise - 0.5) * 3.0 + (noise2 - 0.5) * 0.8

H = base.copy()

# ------------------------------------------------------------------- lakes
POOL1_OLD, POOL1_NEW = 482.4, 477.0
POOL2 = 490.4
bed1 = POOL1_OLD - np.minimum(d1_in * 0.33, 13.0)
bed2 = POOL2 - np.minimum(d2_in * 0.4, 14.0)
H = np.where(lake1, np.minimum(H, bed1), H)
H = np.where(lake2, np.minimum(H, bed2), H)
# shore just outside the water should sit slightly above old pool
shore1 = (~lake1) & (d1_out < 25)
H = np.where(shore1, np.maximum(H, POOL1_OLD + 0.6 + d1_out * 0.15), H)
shore2 = (~lake2) & (d2_out < 25)
H = np.where(shore2, np.maximum(H, POOL2 + 0.6 + d2_out * 0.15), H)

# ------------------------------------------------------------------ Dam No. 1
# centerline: local x = 11 (sta 30+56 of spillway = sta 21+34.5 of dam), y from -135 to +665
DAM1_X = 11.0
dx = LX - DAM1_X                     # + = downstream (NW), - = upstream (lake)
along1 = LY                          # + toward sta 28+00
crest1 = np.full(H.shape, 480.0, np.float32)
# crest rises back to existing ground 485 between sta 27+00 (y=565) and 28+00 (y=665)
t = np.clip((along1 - 565) / 100.0, 0, 1)
crest1 = 480.0 + 5.0 * t
prof1 = np.where(dx >= 6, crest1 - (dx - 6) / 10.0,
         np.where(dx <= -6, crest1 - (-dx - 6) / 3.0, crest1))
zone1 = (along1 > 20) & (along1 < 700) & (dx > -120) & (dx < 110)
prof1_cut = np.where(dx < -6, np.maximum(prof1, 468.5), prof1)
H = np.where(zone1 & (dx < 20), np.minimum(H, prof1_cut), H)       # cut old crest / lake lip (floor 468.5)
H = np.where(zone1, np.maximum(H, prof1), H)                          # fill to new grade
# downstream toe: smooth transition handled by max()

# ------------------------------------------------------------------ Dam No. 2
# crest 495, runs roughly E-W ~420 ft, north shore of lake 2.  In world coords (E,N of C):
D2A = np.array([-690.0, 70.0]); D2B = np.array([-300.0, 72.0])
d2v = D2B - D2A; L2 = np.linalg.norm(d2v); d2u = d2v / L2; d2n = np.array([-d2u[1], d2u[0]])  # normal (north-ish)
rel_e = E - D2A[0]; rel_n = N - D2A[1]
along2 = rel_e * d2u[0] + rel_n * d2u[1]
off2 = rel_e * d2n[0] + rel_n * d2n[1]       # + = north (downstream), - = south (lake 2)
crest2 = 495.0
prof2 = np.where(off2 >= 8, crest2 - (off2 - 8) / 3.0,
         np.where(off2 <= -8, crest2 - (-off2 - 8) / 3.0, crest2))
zone2 = (along2 > -10) & (along2 < L2 + 10) & (off2 > -70) & (off2 < 90)
H = np.where(zone2 & (off2 > -30) & (off2 < 20), np.minimum(H, prof2), H)
H = np.where(zone2, np.maximum(H, prof2), H)

# ------------------------------------------------------- new spillway walls (tops)
# polylines in local frame (x downstream, y lateral; left wall y<0, right wall y>0), inside face
def arc(cx, cy, r, a0, a1, n):
    a = np.linspace(a0, a1, n)
    return [(cx + r * math.cos(t), cy + r * math.sin(t)) for t in a]
weir = arc(0, 0, 20.5, math.pi / 2, 3 * math.pi / 2, 40)      # from (0,+20.5) through apex (-20.5,0) to (0,-20.5)
left_pts = [(0, -20.5, 477), (1, -20.5, 477), (13, -20.5, 480), (54.7, -20.5, 480), (78.4, -11.4, 477), (82.7, -6.9, 477), (88.1, 0.1, 477), (96.9, 11.4, 476), (105.9, 4.2, 476)]
right_pts = [(0, 20.5, 477), (1, 20.5, 477), (13, 20.5, 480), (58.7, 20.5, 480), (80.3, 28.5, 476), (72.4, 36.8, 476)]
wall_segs = []
for pts in (left_pts, right_pts):
    for a, b in zip(pts[:-1], pts[1:]):
        wall_segs.append((a, b))
for a, b in zip(weir[:-1], weir[1:]):
    wall_segs.append(((a[0], a[1], 477.0), (b[0], b[1], 477.0)))

# compute nearest wall top for pixels within 60 ft of spillway (local box)
near = (LX > -80) & (LX < 170) & (LY > -90) & (LY < 90)
idx = np.where(near)
px = LX[idx]; py = LY[idx]
best_d = np.full(px.shape, 1e9, np.float32); best_z = np.zeros(px.shape, np.float32)
for (a, b) in wall_segs:
    ax, ay, az = a; bx, by, bz = b
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    tt = np.clip(((px - ax) * vx + (py - ay) * vy) / max(L, 1e-6), 0, 1)
    qx = ax + tt * vx; qy = ay + tt * vy
    d = np.hypot(px - qx, py - qy)
    z = az + tt * (bz - az)
    m = d < best_d
    best_d[m] = d[m]; best_z[m] = z[m]
# blend ground to wall top within 30 ft of wall
blend = np.clip(1.0 - best_d / 30.0, 0, 1)
blend = blend * blend * (3 - 2 * blend)
cur = H[idx]
# upstream of weir (lake side) the ground is lake bed/riprap, do not pull it up to 477
rr = np.hypot(px, py)
upstream = (px < 0) & (rr > 20.5)
feather = np.clip((rr - 36.0) / 30.0, 0, 1)
ups_target = np.minimum(cur, 477.0 - np.clip((rr - 21) / 2.0, 0, 8))
ups_target = ups_target * (1 - feather) + cur * feather
target = np.where(upstream, ups_target, best_z)
H[idx] = np.where(upstream, target, cur * (1 - blend) + target * blend)

# inside the spillway box: push terrain well below slab (it is discarded anyway)
# polygon of the box (wall centerlines) for mask drawing
box_poly = [(x, y) for (x, y, z) in right_pts[:5]] + [(80.3, 28.5), (96.9, 11.4)] + [(x, y) for (x, y, z) in left_pts[:8]][::-1] + [(x, y) for (x, y) in weir[::-1]]
# (weir goes from (0,20.5) around to (0,-20.5); reversed so polygon closes from left wall start back to right)

# outlet riprap channel: from outlet line, 54 ft long, bottom 470 -> 466, widening 23 -> 40 ft, 2:1 sides
out_c = np.array([(96.9 + 80.3) / 2, (11.4 + 28.5) / 2])   # outlet center (88.6, 19.95)
out_dir = np.array([math.cos(math.radians(47)), math.sin(math.radians(47))])
out_nrm = np.array([-out_dir[1], out_dir[0]])
ox = (LX - out_c[0]) * out_dir[0] + (LY - out_c[1]) * out_dir[1]
oy = (LX - out_c[0]) * out_nrm[0] + (LY - out_c[1]) * out_nrm[1]
chan = (ox > -2) & (ox < 60)
half_w = 11.5 + np.clip(ox, 0, 54) * 0.16
bedz = 470.0 - np.clip(ox, 0, 54) * (4.0 / 54.0)
side = np.clip(np.abs(oy) - half_w, 0, None)
chan_z = bedz + side / 2.0
in_chan = chan & (np.abs(oy) < half_w + 30)
H = np.where(in_chan, np.minimum(H, chan_z), H)

# existing outlet channel continues downstream to the creek (NW) as a shallow swale
sw = (ox > 54) & (ox < 400) & (np.abs(oy) < 25)
swz = 466.0 - (ox - 54) * 0.01 + np.abs(oy) * 0.25
H = np.where(sw, np.minimum(H, swz), H)

# stone walkway from SW bridge abutment up to access drive: 8' wide, from (52,-24) heading -y, climbing 482->490 over 60 ft
# (handled by geometry in JS; terrain gets a gentle ramp here)
ramp = (LX > 44) & (LX < 60) & (LY < -22) & (LY > -95)
rz = 482.0 + np.clip((-LY - 24) / 60.0, 0, 1) * 8.0
H = np.where(ramp, np.where(H < rz, rz, np.minimum(H, rz + 0.5)), H)

# ------------------------------------------------------------------ smoothing
from scipy import ndimage as _nd
Hs = _nd.gaussian_filter(H.astype(np.float32), 1.2)
# keep sharp near walls
H = np.where(near, H, Hs)

# ------------------------------------------------------------------ cut mask (terrain discard)
cut = Image.new('L', (EXT, EXT), 0)
dr = ImageDraw.Draw(cut)
def to_px(x, y):
    e = x * U[0] + y * V[0]; n = x * U[1] + y * V[1]
    return (EXT / 2 + e, EXT / 2 - n)
dr.polygon([to_px(x, y) for (x, y) in box_poly], fill=255)
# riprap ring around weir (upstream) and channel footprint
cut_np = np.asarray(cut).copy()
ring = (LX < 2) & (np.hypot(LX, LY) < 36.5)
cut_np[ring] = 255
cut_np[chan & (np.abs(oy) < half_w + 16.5)] = 255
Image.fromarray(cut_np).save(os.path.join(OUT, 'cutmask.png'))

# ------------------------------------------------------------------ heightmap export (16-bit)
HMIN, HMAX = 440.0, 540.0
h16 = np.clip((H - HMIN) / (HMAX - HMIN) * 65535, 0, 65535).astype(np.uint16)
# store as raw little-endian uint16 (fast to load)
H2 = np.asarray(Image.fromarray(H.astype(np.float32), 'F').resize((EXT // 2 + 1, EXT // 2 + 1), Image.BILINEAR))
h16 = np.clip((H2 - HMIN) / (HMAX - HMIN) * 65535, 0, 65535).astype('<u2')
h16.tofile(os.path.join(OUT, 'height.u16'))
with open(os.path.join(OUT, 'height.json'), 'w') as f:
    json.dump({'size': EXT // 2 + 1, 'spacing': 2.0, 'extent': EXT, 'hmin': HMIN, 'hmax': HMAX}, f)

# ------------------------------------------------------------------ albedo texture
alb = A.copy()
# water areas: flat murky colour (water is a separate mesh)
alb[lake1] = np.array([70, 92, 60])
alb[lake2] = np.array([48, 60, 48])
# new pool is lower: exposed shore band gets muddy/grassy colour
newshore1 = lake1 & (H > POOL1_NEW - 0.3)
alb[newshore1] = np.array([172, 158, 124])
# construction / regraded areas: fresh grass
grass = np.array([96, 118, 52], np.float32)
regrade1 = zone1 & (dx > -40) & (dx < 75)
regrade2 = zone2 & (off2 > -35) & (off2 < 85)
spill_area = (LX > -60) & (LX < 150) & (LY > -100) & (LY < 100) & (H > POOL1_NEW)
for m in (regrade1, regrade2, spill_area):
    k = m & ~lake1 & ~lake2
    alb[k] = grass * (0.85 + 0.3 * noise2[k][:, None])
# riprap channel colour
rip = (chan & (np.abs(oy) < half_w + 2)) | ring
alb[rip] = np.array([150, 148, 140]) * (0.8 + 0.4 * noise2[rip][:, None])
# Dam 2 road (asphalt) and parking: keep aerial (already grey).  Dam 2 crest fresh grass flanks
alb = np.clip(alb, 0, 255).astype(np.uint8)
Image.fromarray(alb).save(os.path.join(OUT, 'albedo.jpg'), quality=86)

# water masks (alpha for water planes): lake1 minus spillway box, dilated slightly inward of old shore not needed
w1 = lake1.copy()
# water reaches the new weir: add upstream pocket around the semicircle (local x<2, R<70)
pocket = (LX < 2) & (np.hypot(LX, LY) < 70)
w1 |= pocket
w1[np.asarray(cut) > 0] = False
# but never inside the spillway box: also remove ring interior (R<21)
w1[(np.hypot(LX, LY) < 21.0)] = False
w1 = np.asarray(Image.fromarray((w1 * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)))
Image.fromarray(w1).save(os.path.join(OUT, 'water1.png'))
w2 = np.asarray(Image.fromarray((lake2 * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)))
Image.fromarray(w2).save(os.path.join(OUT, 'water2.png'))

# ------------------------------------------------------------------ trees
_I = bright
_m1 = ndimage.gaussian_filter(_I, 4); _m2 = ndimage.gaussian_filter(_I * _I, 4)
_std = np.sqrt(np.maximum(_m2 - _m1 * _m1, 0))
woods = (brightb > 16) & (brightb < 118) & (_std > 9.0) & (np.abs(Rb - Gb) < 18) & (np.abs(Gb - Bb) < 18) & ~lake1 & ~lake2 & ~label
woods = clean(woods, 5, 9)
# exclude cleared/constructed zones and water shores
excl = regrade1 | regrade2 | (spill_area & (LX > -40)) | lake1 | lake2 | (d1_out < 12) | (d2_out < 12) | ring | chan
# road exclusion: bright grey pixels (asphalt) in the aerial
road = (bright > 140) & (np.abs(R - G) < 18) & (np.abs(G - B) < 18)
road = np.asarray(Image.fromarray((road * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))) > 0
woods &= ~excl & ~road
trees = []
rng = np.random.default_rng(3)
SP = 17
for yy in range(10, EXT - 10, SP):
    for xx in range(10, EXT - 10, SP):
        jx = xx + rng.uniform(-7, 7); jy = yy + rng.uniform(-7, 7)
        ix, iy = int(jx), int(jy)
        if woods[iy, ix]:
            e = jx - EXT / 2; n = -(jy - EXT / 2)
            hgt = rng.uniform(28, 55);
            trees.append([round(e, 1), round(n, 1), round(float(H[iy, ix]), 2), round(hgt, 1), int(rng.integers(0, 3)), round(rng.uniform(0, 6.28), 2)])
# a few specimen trees in the mown park area SW of spillway (visible in aerial), keep sparse
park = (LX > -200) & (LX < 120) & (LY > -260) & (LY < -40) & ~road & ~lake1 & (H > 483)
for k in range(60):
    for _ in range(50):
        xx = int(rng.uniform(0, EXT)); yy = int(rng.uniform(0, EXT))
        if park[yy, xx] and not woods[yy, xx]:
            e = xx - EXT / 2; n = -(yy - EXT / 2)
            trees.append([e, n, round(float(H[yy, xx]), 2), round(rng.uniform(35, 60), 1), int(rng.integers(0, 3)), round(rng.uniform(0, 6.28), 2)])
            break
with open(os.path.join(OUT, 'trees.json'), 'w') as f:
    json.dump(trees, f)

# grass tuft candidates near spillway (dense) : grid 3 ft
tufts = []
gm = (LX > -70) & (LX < 160) & (LY > -110) & (LY < 160) & ~lake1 & (np.asarray(cut) == 0) & ~road & (H > POOL1_NEW + 0.2)
for yy in range(0, EXT, 3):
    for xx in range(0, EXT, 3):
        if gm[yy, xx] and rng.random() < 0.55:
            e = xx - EXT / 2 + rng.uniform(-1.5, 1.5); n = -(yy - EXT / 2) + rng.uniform(-1.5, 1.5)
            tufts.append([round(e, 1), round(n, 1), round(float(H[yy, xx]), 2)])
with open(os.path.join(OUT, 'tufts.json'), 'w') as f:
    json.dump(tufts, f)

print('trees', len(trees), 'tufts', len(tufts))
print('H range', float(H.min()), float(H.max()), 'at C', float(H[EXT // 2, EXT // 2]))
# debug previews
Image.fromarray(np.clip((H - 460) / 50 * 255, 0, 255).astype(np.uint8)).resize((800, 800)).save(os.path.join(OUT, '..', '..', 'ref', 'dbg_height.png'))
Image.fromarray(alb).resize((800, 800)).save(os.path.join(OUT, '..', '..', 'ref', 'dbg_albedo.png'))
tm = np.zeros((EXT, EXT), np.uint8); tm[woods] = 255
Image.fromarray(tm).resize((800, 800)).save(os.path.join(OUT, '..', '..', 'ref', 'dbg_woods.png'))
