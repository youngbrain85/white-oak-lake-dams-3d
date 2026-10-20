#!/usr/bin/env python3
"""Procedural PBR-ish textures for the White Oak Lake dam model (tileable)."""
import os, math
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
from scipy import ndimage

OUT = os.path.join(os.path.dirname(__file__), 'assets')
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(11)

def tile_noise(n, scales, seed=0, power=1.0):
    """tileable fractal noise in [0,1] (sum of upsampled random grids with wrap)"""
    r = np.random.default_rng(seed)
    acc = np.zeros((n, n), np.float32); wsum = 0
    for s, w in scales:
        g = r.random((s, s)).astype(np.float32)
        g = np.tile(g, (3, 3))                       # wrap for tileable bicubic
        im = Image.fromarray(g, 'F').resize((n * 3, n * 3), Image.BICUBIC)
        a = np.asarray(im)[n:2 * n, n:2 * n]
        acc += a * w; wsum += w
    acc /= wsum
    acc = (acc - acc.min()) / (acc.max() - acc.min() + 1e-6)
    return acc ** power

def to_normal(h, strength=2.0):
    gy, gx = np.gradient(h.astype(np.float32))
    nx = -gx * strength; ny = -gy * strength; nz = np.ones_like(h)
    l = np.sqrt(nx * nx + ny * ny + nz * nz)
    n = np.stack([nx / l, ny / l, nz / l], -1)
    return Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8))

def save(img, name, q=88):
    img.save(os.path.join(OUT, name), quality=q)

# ---------------------------------------------------------------- concrete
n = 512
base = tile_noise(n, [(4, 1.0), (8, 0.8), (32, 0.5), (128, 0.35), (256, 0.25)], seed=1)
spots = tile_noise(n, [(64, 1.0), (256, 0.6)], seed=2)
col = 150 + (base - 0.5) * 40 + (spots - 0.5) * 18
c = np.stack([col * 1.0, col * 0.99, col * 0.95], -1)
# subtle form-tie / aggregate speckle
spk = rng.random((n, n)) < 0.012
c[spk] *= 0.75
c = np.clip(c, 0, 255).astype(np.uint8)
save(Image.fromarray(c), 'concrete.jpg')
save(to_normal(base * 0.6 + spots * 0.4, 1.2), 'concrete_n.jpg')

# ------------------------------------------------- riprap (angular limestone)
n = 1024
rip = np.zeros((n, n), np.float32)
ids = np.zeros((n, n), np.int32)
# Voronoi-like rocks: random seed points, each with its own height dome
pts = rng.random((900, 2)) * n
yy, xx = np.mgrid[0:n, 0:n]
best = np.full((n, n), 1e9, np.float32)
for k, (px, py) in enumerate(pts):
    # wrap distance
    dx = np.abs(xx - px); dx = np.minimum(dx, n - dx)
    dy = np.abs(yy - py); dy = np.minimum(dy, n - dy)
    d = np.sqrt(dx * dx + dy * dy) * (0.8 + 0.5 * rng.random())
    m = d < best
    best[m] = d[m]; ids[m] = k
rock_scale = rng.uniform(0.6, 1.2, len(pts))
edge = best / (np.take(rock_scale, ids) * 28.0)
h = np.clip(1.0 - edge ** 3, 0, 1)
h += (tile_noise(n, [(128, 1.0), (512, 0.6)], seed=5) - 0.5) * 0.35
crev = np.clip(1.0 - edge, 0, 1) ** 0.5
rock_shade = np.take(rng.uniform(0.45, 1.0, len(pts)), ids)
grey = 70 + 110 * rock_shade * (0.45 + 0.55 * crev)
tint = tile_noise(n, [(64, 1)], seed=6)
r_ = grey * (0.98 + 0.08 * tint); g_ = grey * (0.97 + 0.04 * tint); b_ = grey * (0.90)
c = np.clip(np.stack([r_, g_, b_], -1), 0, 255).astype(np.uint8)
save(Image.fromarray(c), 'riprap.jpg')
save(to_normal(h, 6.0), 'riprap_n.jpg')
# roughness/AO-ish: crevices darker
ao = np.clip(h * 0.8 + 0.2, 0, 1)
save(Image.fromarray((ao * 255).astype(np.uint8)), 'riprap_ao.jpg')

# --------------------------------------------------------- grass detail (tileable)
n = 512
g1 = tile_noise(n, [(8, 0.6), (32, 0.8), (128, 1.0), (512, 0.9)], seed=21)
g2 = tile_noise(n, [(256, 1.0)], seed=22)
v = 0.72 + (g1 - 0.5) * 0.55 + (g2 - 0.5) * 0.25
c = np.stack([v * 255 * 0.95, v * 255 * 1.0, v * 255 * 0.86], -1)
save(Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)), 'grass_detail.jpg')
save(to_normal(g1, 1.5), 'grass_n.jpg')

# ------------------------------------------------------------ gravel / stone path
n = 512
gv = tile_noise(n, [(64, 0.7), (128, 1.0), (256, 0.9), (512, 0.5)], seed=31)
pebbles = ndimage.gaussian_filter((rng.random((n, n)) < 0.02).astype(np.float32), 2.0)
pebbles = pebbles / (pebbles.max() + 1e-6)
v = 0.62 + (gv - 0.5) * 0.4 + pebbles * 0.35
c = np.stack([v * 255 * 0.92, v * 255 * 0.88, v * 255 * 0.80], -1)
save(Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)), 'gravel.jpg')
save(to_normal(gv * 0.5 + pebbles, 3.0), 'gravel_n.jpg')

# ------------------------------------------------------------ wood planks
n = 512
img = Image.new('RGB', (n, n))
d = ImageDraw.Draw(img)
plank_w = 64
grain = tile_noise(n, [(2, 0.3), (8, 0.6), (64, 1.0), (512, 0.4)], seed=41)
arr = np.zeros((n, n, 3), np.float32)
for i in range(n // plank_w):
    shade = rng.uniform(0.75, 1.1)
    y0, y1 = i * plank_w, (i + 1) * plank_w
    base_c = np.array([150, 118, 80]) * shade
    strip = grain[y0:y1]
    arr[y0:y1] = base_c[None, None, :] * (0.75 + strip[..., None] * 0.5)
    arr[y0:y0 + 2] *= 0.55; arr[y1 - 2:y1] *= 0.6
# streaks along x
streak = tile_noise(n, [(4, 1.0), (256, 0.5)], seed=42)
arr *= (0.85 + 0.3 * streak[..., None])
save(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), 'wood.jpg')
save(to_normal(grain * 0.3 + (np.arange(n)[:, None] % plank_w < 3) * 0.5, 2.0), 'wood_n.jpg')

# ------------------------------------------------------------ bark
n = 256
bk = tile_noise(n, [(4, 0.8), (16, 1.0), (64, 0.7), (256, 0.4)], seed=51)
v = 0.35 + (bk - 0.5) * 0.5
c = np.stack([v * 255 * 0.72, v * 255 * 0.62, v * 255 * 0.52], -1)
save(Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)), 'bark.jpg')

# ------------------------------------------------------------ weathering steel
n = 256
rs = tile_noise(n, [(8, 0.8), (32, 1.0), (128, 0.7), (256, 0.5)], seed=61)
v = 0.55 + (rs - 0.5) * 0.5
c = np.stack([v * 255 * 0.62, v * 255 * 0.36, v * 255 * 0.22], -1)
save(Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)), 'corten.jpg')

# ------------------------------------------------------------ chain link (RGBA)
n = 256
img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
cell = 32
for i in range(-1, n // cell + 2):
    for j in range(-1, n // cell + 2):
        x = i * cell + (cell // 2 if j % 2 else 0); y = j * cell
        pts = [(x, y + cell // 2), (x + cell // 2, y), (x + cell, y + cell // 2), (x + cell // 2, y + cell)]
        d.line(pts + [pts[0]], fill=(200, 205, 210, 255), width=3)
img = img.filter(ImageFilter.GaussianBlur(0.4))
save(img, 'chainlink.png')

# ------------------------------------------------------------ leaf canopy sprites (atlas 3 x 1)
W = 512; H = 512
atlas = Image.new('RGBA', (W * 3, H), (0, 0, 0, 0))
for v_ in range(3):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = np.random.default_rng(100 + v_)
    cx, cy = W / 2, H * 0.40
    rx, ry = W * 0.42, H * 0.36
    # trunk
    tw = 22
    d.polygon([(cx - tw, H), (cx + tw, H), (cx + tw * 0.55, cy + ry * 0.2), (cx - tw * 0.55, cy + ry * 0.2)], fill=(78, 62, 48, 255))
    for k in range(5):  # branches
        ang = r.uniform(-1.0, 1.0)
        bx = cx + math.sin(ang) * rx * 0.6; by = cy - math.cos(ang) * ry * 0.5 + ry * 0.3
        d.line([(cx, cy + ry * 0.25), (bx, by)], fill=(70, 56, 44, 255), width=int(r.uniform(5, 9)))
    # leaf clusters: several overlapping lobes for an irregular silhouette
    base_g = np.array([[66, 104, 38], [84, 124, 44], [58, 92, 36]][v_])
    lobes = [(cx, cy, rx * 0.78, ry * 0.8)]
    for k in range(6):
        a = r.uniform(0, 2 * math.pi); dd = r.uniform(0.35, 0.7)
        lobes.append((cx + math.cos(a) * rx * dd, cy + math.sin(a) * ry * dd * 0.9, rx * r.uniform(0.35, 0.55), ry * r.uniform(0.35, 0.55)))
    for (lx, ly, lrx, lry) in lobes:
        for k in range(650):
            a = r.uniform(0, 2 * math.pi); rad = math.sqrt(r.uniform(0, 1))
            x = lx + math.cos(a) * lrx * rad; y = ly + math.sin(a) * lry * rad
            if rad > 0.8 and r.random() < (rad - 0.8) / 0.2 * 0.85:
                continue
            s = r.uniform(5, 13)
            vert = (y - (cy - ry)) / (2 * ry)
            light = 0.55 + 0.75 * (1 - vert) + r.uniform(-0.18, 0.18)
            # leaves nearer the outline are lit, inner/lower ones dark
            if rad < 0.5: light *= 0.85
            col = tuple(int(min(255, cc * light)) for cc in base_g) + (255,)
            d.ellipse([x - s, y - s * 0.65, x + s, y + s * 0.65], fill=col)
    atlas.paste(im, (v_ * W, 0))
save(atlas, 'leaves.png')

# ------------------------------------------------------------ grass tuft sprite
W = 256; H = 256
im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
r = np.random.default_rng(7)
for k in range(140):
    x0 = r.uniform(W * 0.2, W * 0.8); top = r.uniform(H * 0.05, H * 0.5)
    bend = r.uniform(-50, 50)
    gcol = (int(r.uniform(90, 140)), int(r.uniform(130, 175)), int(r.uniform(40, 70)), 255)
    pts = [(x0, H), (x0 + bend * 0.3, (H + top) / 2), (x0 + bend, top)]
    d.line(pts, fill=gcol, width=int(r.uniform(2, 5)), joint='curve')
save(im, 'grass_tuft.png')

# ------------------------------------------------------------ water normal (tileable)
n = 512
w1 = tile_noise(n, [(16, 0.8), (64, 1.0), (256, 0.6)], seed=71)
save(to_normal(w1, 2.5), 'water_n.jpg')

# ------------------------------------------------------------ asphalt
n = 256
asf = tile_noise(n, [(8, 0.3), (64, 0.6), (256, 1.0)], seed=81)
v = 0.28 + (asf - 0.5) * 0.18
c = np.stack([v * 255, v * 255 * 1.0, v * 255 * 1.02], -1)
save(Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)), 'asphalt.jpg')

print('textures done')
