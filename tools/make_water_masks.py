#!/usr/bin/env python3
"""Water-plane masks for the viewer and the Blender scene.
Lake 1: the plane at EL 476.6 covers everything upstream of the dam crest (local x < 17 ft) except the spillway box,
so the shoreline is the true terrain/plane intersection. Lake 2: the aerial outline dilated 12 ft (the shore was
raised above EL 491 within 25 ft of it), again hidden by terrain at the edge."""
import os, math, numpy as np
from PIL import Image, ImageFilter
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'viewer', 'assets')
EXT = 2400
U = (-0.9666, 0.2563); V = (0.2563, 0.9666)
jj, ii = np.meshgrid(np.arange(EXT), np.arange(EXT)); E = jj - EXT / 2; N = EXT / 2 - ii
LX = E * U[0] + N * U[1]; LY = E * V[0] + N * V[1]
cut = np.asarray(Image.open(os.path.join(A, 'cutmask.png')).convert('L')) > 127
box = np.asarray(Image.fromarray((cut * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
w1 = (LX < 17.0) & ~box
w1 = np.asarray(Image.fromarray((w1 * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0)))
Image.fromarray(w1).save(os.path.join(A, 'water1.png'))
old2 = np.asarray(Image.open(os.path.join(A, 'water2.png')).convert('L')) > 127
w2 = np.asarray(Image.fromarray((old2 * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(25)).filter(ImageFilter.GaussianBlur(1.0)))
Image.fromarray(w2).save(os.path.join(A, 'water2.png'))
print('water1 coverage', (w1 > 127).mean().round(3), 'water2 coverage', (w2 > 127).mean().round(3))
