#!/usr/bin/env python3
"""Extra textures for the Blender/Cycles version: leaf-cluster cards, grass clumps, bark, rock albedo.
All procedural (PIL + numpy), tileable where it matters. Output: blender/tex/"""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tex')
os.makedirs(OUT, exist_ok=True)

def tile_noise(n, scales, seed=0):
    r = np.random.default_rng(seed)
    acc = np.zeros((n, n), np.float32); wsum = 0
    for s, w in scales:
        g = np.tile(r.random((s, s)).astype(np.float32), (3, 3))
        a = np.asarray(Image.fromarray(g, 'F').resize((n * 3, n * 3), Image.BICUBIC))[n:2 * n, n:2 * n]
        acc += a * w; wsum += w
    acc /= wsum
    return (acc - acc.min()) / (acc.max() - acc.min() + 1e-6)

def to_normal(h, strength):
    gy, gx = np.gradient(h.astype(np.float32))
    nx, ny, nz = -gx * strength, -gy * strength, np.ones_like(h)
    l = np.sqrt(nx * nx + ny * ny + nz * nz)
    return Image.fromarray(((np.stack([nx / l, ny / l, nz / l], -1) * 0.5 + 0.5) * 255).astype(np.uint8))

# ---------------------------------------------------------------- leaf cluster cards (RGBA), 3 variants
def leaf_card(seed, base, W=1024):
    """irregular cluster of small leaves: 5-7 sub-clusters with gaps, so cards don't read as discs"""
    r = np.random.default_rng(seed)
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, W / 2
    subs = []
    for k in range(r.integers(5, 8)):
        a = r.uniform(0, 2 * math.pi); rad = r.uniform(0.1, 0.42) * W
        subs.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad * 0.9, r.uniform(0.12, 0.24) * W))
    for (sx, sy, sr) in subs:
        d.line([(cx, cy), (sx, sy)], fill=(60, 48, 36, 255), width=int(r.uniform(2, 5)))
    for (sx, sy, sr) in subs:
        n = int(sr * sr / 900)
        for k in range(n):
            a = r.uniform(0, 2 * math.pi); rad = r.uniform(0, 1) ** 0.5
            x = sx + math.cos(a) * rad * sr; y = sy + math.sin(a) * rad * sr
            s = r.uniform(W * 0.022, W * 0.04)
            rot = r.uniform(0, math.pi)
            shade = r.uniform(0.55, 1.3)
            col = tuple(int(min(255, c * shade)) for c in base)
            leaf = Image.new('RGBA', (int(s * 2.4), int(s * 2.4)), (0, 0, 0, 0))
            ld = ImageDraw.Draw(leaf)
            w2 = s * 0.5
            ld.ellipse([s * 1.2 - w2, s * 1.2 - s, s * 1.2 + w2, s * 1.2 + s], fill=col + (255,))
            ld.line([(s * 1.2, s * 0.3), (s * 1.2, s * 2.1)], fill=tuple(int(c * 0.65) for c in col) + (255,), width=max(1, int(s * 0.07)))
            leaf = leaf.rotate(math.degrees(rot), resample=Image.BILINEAR, expand=False)
            img.alpha_composite(leaf, (int(x - s * 1.2), int(y - s * 1.2)))
    return img

for i, base in enumerate([(78, 118, 42), (96, 138, 48), (66, 100, 40)]):
    leaf_card(100 + i, base).save(os.path.join(OUT, f'leafcard{i}.png'))

# ---------------------------------------------------------------- grass clump card
def grass_card(seed, W=1024):
    r = np.random.default_rng(seed)
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k in range(150):
        x0 = r.uniform(W * 0.22, W * 0.78); top = r.uniform(W * 0.1, W * 0.6)
        bend = r.uniform(-W * 0.22, W * 0.22)
        g = r.uniform(0.75, 1.3)
        col = (int(74 * g), int(112 * g), int(38 * g), 255)
        pts = []
        for t in np.linspace(0, 1, 8):
            pts.append((x0 + bend * t * t, W - (W - top) * t))
        wdt = int(r.uniform(4, 10))
        for j in range(len(pts) - 1):
            ww = max(1, int(wdt * (1 - j / len(pts))))
            d.line([pts[j], pts[j + 1]], fill=col, width=ww)
    # dry blades
    for k in range(10):
        x0 = r.uniform(W * 0.3, W * 0.7); top = r.uniform(W * 0.1, W * 0.5); bend = r.uniform(-W * 0.2, W * 0.2)
        pts = [(x0 + bend * t * t, W - (W - top) * t) for t in np.linspace(0, 1, 8)]
        d.line(pts, fill=(170, 150, 90, 255), width=3)
    return img

grass_card(5).save(os.path.join(OUT, 'grassclump.png'))

# ---------------------------------------------------------------- bark (tileable) + normal
n = 1024
b1 = tile_noise(n, [(3, 0.6), (12, 1.0), (48, 0.6), (256, 0.35)], seed=31)
# vertical furrows: stretch noise in y
r = np.random.default_rng(32)
fur = np.tile(r.random((64, 8)).astype(np.float32), (3, 3))
fur = np.asarray(Image.fromarray(fur, 'F').resize((n * 3, n * 3), Image.BICUBIC))[n:2 * n, n:2 * n]
h = b1 * 0.55 + fur * 0.45
v = 0.28 + (h - 0.5) * 0.4
c = np.stack([v * 255 * 0.78, v * 255 * 0.64, v * 255 * 0.52], -1)
Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'bark.jpg'), quality=90)
to_normal(h, 4.0).save(os.path.join(OUT, 'bark_n.jpg'), quality=90)

# ---------------------------------------------------------------- limestone rock albedo (tileable) + normal
n = 1024
r1 = tile_noise(n, [(4, 0.5), (16, 1.0), (64, 0.8), (256, 0.5), (1024, 0.3)], seed=41)
spots = tile_noise(n, [(128, 1.0), (512, 0.7)], seed=42)
v = 0.62 + (r1 - 0.5) * 0.35 + (spots - 0.5) * 0.18
tint = tile_noise(n, [(32, 1.0)], seed=43)
c = np.stack([v * 255 * (0.92 + 0.1 * tint), v * 255 * (0.90 + 0.05 * tint), v * 255 * 0.82], -1)
Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'limestone.jpg'), quality=90)
to_normal(r1 * 0.7 + spots * 0.3, 3.0).save(os.path.join(OUT, 'limestone_n.jpg'), quality=90)

# ---------------------------------------------------------------- concrete (tileable, higher res) + normal + roughness
n = 2048
c1 = tile_noise(n, [(4, 1.0), (16, 0.8), (64, 0.6), (256, 0.4), (1024, 0.3)], seed=51)
streak = tile_noise(n, [(6, 1.0), (24, 0.5)], seed=52)
streak_v = np.repeat(np.asarray(Image.fromarray(streak[:, :64].astype(np.float32), 'F').resize((n, n), Image.BICUBIC)), 1, axis=1)
form = ((np.arange(n)[:, None] // 256) % 2 == 0).astype(np.float32) * 0.03   # formwork panel bands
v = 0.58 + (c1 - 0.5) * 0.22 + (streak_v - 0.5) * 0.08 - form
spk = np.random.default_rng(53).random((n, n)) < 0.004
v[spk] *= 0.7
c = np.stack([v * 255 * 1.0, v * 255 * 0.99, v * 255 * 0.95], -1)
Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'concrete.jpg'), quality=90)
to_normal(c1 * 0.5 + streak_v * 0.2 + spk * 0.6, 1.6).save(os.path.join(OUT, 'concrete_n.jpg'), quality=90)
rough = np.clip(0.72 + (c1 - 0.5) * 0.3 + (streak_v - 0.5) * 0.15, 0, 1)
Image.fromarray((rough * 255).astype(np.uint8)).save(os.path.join(OUT, 'concrete_r.jpg'), quality=85)

# ---------------------------------------------------------------- grass ground detail (tileable), 2048
n = 2048
g1 = tile_noise(n, [(8, 0.5), (32, 0.8), (128, 1.0), (512, 0.9), (2048, 0.6)], seed=61)
g2 = tile_noise(n, [(256, 1.0)], seed=62)
v = 0.62 + (g1 - 0.5) * 0.6 + (g2 - 0.5) * 0.25
c = np.stack([v * 255 * 0.78, v * 255 * 0.98, v * 255 * 0.5], -1)
Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'grass_detail.jpg'), quality=88)
to_normal(g1, 2.0).save(os.path.join(OUT, 'grass_n.jpg'), quality=88)

# ---------------------------------------------------------------- wood planks (tileable along x)
n = 1024
grain = tile_noise(n, [(2, 0.3), (8, 0.6), (64, 1.0), (512, 0.4)], seed=71)
arr = np.zeros((n, n, 3), np.float32)
pw = 128
r = np.random.default_rng(72)
for i in range(n // pw):
    shade = r.uniform(0.75, 1.1)
    strip = grain[i * pw:(i + 1) * pw]
    arr[i * pw:(i + 1) * pw] = np.array([150, 118, 80]) * shade * (0.75 + strip[..., None] * 0.5)
    arr[i * pw:i * pw + 3] *= 0.5; arr[(i + 1) * pw - 3:(i + 1) * pw] *= 0.55
streak = tile_noise(n, [(4, 1.0), (256, 0.5)], seed=73)
arr *= (0.85 + 0.3 * streak[..., None])
Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'wood.jpg'), quality=90)
to_normal(grain * 0.3 + ((np.arange(n)[:, None] % pw) < 4) * 0.6, 2.5).save(os.path.join(OUT, 'wood_n.jpg'), quality=90)

# ---------------------------------------------------------------- chain link (RGBA, tileable)
n = 512
img = Image.new('RGBA', (n, n), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
cell = 64
for i in range(-1, n // cell + 2):
    for j in range(-1, n // cell + 2):
        x = i * cell + (cell // 2 if j % 2 else 0); y = j * cell
        pts = [(x, y + cell // 2), (x + cell // 2, y), (x + cell, y + cell // 2), (x + cell // 2, y + cell)]
        d.line(pts + [pts[0]], fill=(175, 180, 185, 255), width=9)
img.save(os.path.join(OUT, 'chainlink.png'))

# ---------------------------------------------------------------- rusted/weathering steel
n = 1024
rs = tile_noise(n, [(8, 0.8), (32, 1.0), (128, 0.7), (512, 0.5)], seed=81)
v = 0.5 + (rs - 0.5) * 0.5
c = np.stack([v * 255 * 0.70, v * 255 * 0.40, v * 255 * 0.24], -1)
Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'corten.jpg'), quality=90)
to_normal(rs, 1.5).save(os.path.join(OUT, 'corten_n.jpg'), quality=88)

# ---------------------------------------------------------------- asphalt
n = 1024
asf = tile_noise(n, [(8, 0.3), (64, 0.6), (256, 1.0), (1024, 0.8)], seed=91)
v = 0.26 + (asf - 0.5) * 0.16
c = np.stack([v * 255, v * 255 * 1.0, v * 255 * 1.03], -1)
Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'asphalt.jpg'), quality=88)

print('textures written to', OUT)
