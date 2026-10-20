#!/usr/bin/env python3
"""Build index.html (CDN) and index_local.html (local node_modules) from the template; copy photos."""
import os, shutil
S = os.path.dirname(os.path.abspath(__file__))
t = open(os.path.join(S, 'index_template.html')).read()
cdn = t.replace('__THREE__', 'https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js') \
       .replace('__ADDONS__', 'https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/') \
       .replace('__APP__', 'app.js')
open(os.path.join(S, 'index.html'), 'w').write(cdn)
loc = t.replace('__THREE__', './node_modules/three/build/three.module.js') \
       .replace('__ADDONS__', './node_modules/three/examples/jsm/') \
       .replace('__APP__', 'app.js')
open(os.path.join(S, 'index_local.html'), 'w').write(loc)
ref = os.path.join(S, '..', 'ref')
for i in (1, 2, 3):
    src = os.path.join(ref, f'photo{i}_view.jpg')
    shutil.copy(src, os.path.join(S, 'assets', f'photo{i}.jpg'))
import re
art = t.replace('__THREE__', 'https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js') \
       .replace('__ADDONS__', 'https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/') \
       .replace('__APP__', 'app.js')
# strip document skeleton: keep from <title> through </style> + importmap, then body inner
head = re.search(r'(<title>.*?</script>\s*)</head>', art, re.S).group(1)
body = re.search(r'<body>(.*?)</body>', art, re.S).group(1)
body = re.sub(r'\s*<button id="btnExport">.*?</button>', '', body, flags=re.S)
open(os.path.join(S, 'index_artifact.html'), 'w').write(head + body)
print('built')
