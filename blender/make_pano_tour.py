#!/usr/bin/env python3
"""Turn the Cycles equirectangular renders (blender/out/panos/*.png + panos.json) into the web tour:
   pano/<name>.jpg (3072x1536, q86), pano/<name>_s.jpg (1536x768 for phones) and pano/tour.json with hotspots.

   Hotspot maths: image u = 0.5 + (bearing to the right of the view direction) / 2pi, v = 0.5 + elevation / pi.
"""
import json, math, os, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, 'out', 'panos'); DST = os.path.join(ROOT, 'pano')
os.makedirs(DST, exist_ok=True)
meta = json.load(open(os.path.join(SRC, 'panos.json')))

LINKS = {   # which panos are reachable from which (both ways)
    ('bridge', 'walkway'), ('bridge', 'crest'), ('bridge', 'shore'), ('bridge', 'outlet'),
    ('walkway', 'shore'), ('walkway', 'outlet'), ('crest', 'dam2'), ('shore', 'dam2'),
}
ORDER = ['bridge', 'walkway', 'shore', 'outlet', 'crest', 'dam2']
DESC = {
    'bridge': 'Mid-span on the 46 ft steel truss bridge (deck EL 482): weir and Lake No. 1 ahead, stilling basin below, dam crest to the left, stone walkway to the right.',
    'walkway': 'On the 8 ft stone walkway where it leaves the bridge and bends toward the asphalt access drive.',
    'shore': 'Lake No. 1 shoreline south-west of the weir, looking across the water at the semicircular overflow crest (EL 477.0).',
    'outlet': 'Standing in the riprap outlet channel (24 in. Class I riprap on broken concrete) looking back up at the end sills and baffles.',
    'crest': 'On the regraded crest of Dam No. 1 (EL 480), 130 ft north-east of the bridge.',
    'dam2': 'On the paved access drive along the crest of Dam No. 2 (EL 495), Lake No. 2 to the south.',
}

def uv_from_to(a, b):
    pe, pn, pz = a['pos']; fe, fn = a['forward']; te, tn, tz = b['pos']
    de, dn = te - pe, tn - pn; horiz = math.hypot(de, dn) or 1e-6
    right = (fn, -fe)
    ang = math.atan2(de * right[0] + dn * right[1], de * fe + dn * fn)      # + = to the right
    elev = math.atan2(tz - pz, horiz)
    return 0.5 + ang / (2 * math.pi), 0.5 + elev / math.pi, horiz

tour = {'scenes': []}
for name in ORDER:
    if name not in meta: continue
    src = os.path.join(SRC, name + '.png')
    if not os.path.exists(src): continue
    im = Image.open(src).convert('RGB')
    im.save(os.path.join(DST, name + '.jpg'), quality=86, optimize=True, progressive=True)
    im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(os.path.join(DST, name + '_s.jpg'), quality=84, optimize=True)
    hs = []
    for other in ORDER:
        if other == name or other not in meta: continue
        if (name, other) in LINKS or (other, name) in LINKS:
            u, v, d = uv_from_to(meta[name], meta[other])
            hs.append({'to': other, 'u': round(u % 1.0, 4), 'v': round(v, 4), 'dist_ft': round(d), 'label': meta[other]['title']})
    tour['scenes'].append({'id': name, 'title': meta[name]['title'], 'desc': DESC.get(name, ''), 'image': name + '.jpg', 'image_small': name + '_s.jpg',
                           'pos': [round(x, 1) for x in meta[name]['pos']], 'hotspots': hs})
json.dump(tour, open(os.path.join(DST, 'tour.json'), 'w'), indent=1)
print('scenes:', [s['id'] for s in tour['scenes']])
for s in tour['scenes']:
    print(' ', s['id'], [(h['to'], h['u'], h['v']) for h in s['hotspots']])
