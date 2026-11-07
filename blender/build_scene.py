#!/usr/bin/env python3
"""
White Oak Lake Dams (IDNR E015001L) – Blender / Cycles reconstruction.

Rebuilds the whole scene (terrain, lakes, Dam No.1 drop spillway, pedestrian bridge, riprap,
Dam No.2, vegetation) from the same data the Three.js viewer uses (viewer/assets/*), but with
physically based materials, real 3D trees, scattered grass and rocks, a Nishita sky and Cycles.

Usage (needs the `bpy` PyPI module, Blender 5.x):
    python3 blender/build_scene.py --build                # build scene, save blender/out/white_oak.blend
    python3 blender/build_scene.py --render preview        # quick low-res renders of every preset
    python3 blender/build_scene.py --render final [names]  # full quality renders
    python3 blender/build_scene.py --export                # GLB for the web viewer

Units: feet (1 BU = 1 ft, scene unit scale 0.3048). World X = east, Y = north, Z = elevation (NAVD88 ft).
"""
import sys, os, math, json, time, argparse, random
import numpy as np
from PIL import Image

import bpy, bmesh
from mathutils import Vector, Matrix, Euler

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, 'viewer', 'assets')
TEX = os.path.join(HERE, 'tex')
OUT = os.path.join(HERE, 'out')
os.makedirs(OUT, exist_ok=True)
BLEND = os.path.join(OUT, 'white_oak.blend')

# ----------------------------------------------------------------------------- frames
# local spillway frame: x downstream (WNW), y lateral toward the right wall (NNE)
U = (-0.9666, 0.2563)
V = (0.2563, 0.9666)
def L2W(x, y, z=0.0):
    return (x * U[0] + y * V[0], x * U[1] + y * V[1], z)
def W2L(e, n):
    # inverse of the (orthonormal, reflecting) 2x2
    return (e * U[0] + n * U[1], e * V[0] + n * V[1])

# ----------------------------------------------------------------------------- data
HJ = json.load(open(os.path.join(ASSETS, 'height.json')))
_h = np.asarray(Image.open(os.path.join(ASSETS, 'height.png')).convert('RGB'))
HGT = HJ['hmin'] + ((_h[..., 0].astype(np.uint32) << 8) | _h[..., 1]).astype(np.float64) * (HJ['hmax'] - HJ['hmin']) / 65535.0
HS = HJ['size']; HSP = HJ['spacing']; HEXT = HJ['extent']
CUT = np.asarray(Image.open(os.path.join(ASSETS, 'cutmask.png')).convert('L')) > 127
W1 = np.asarray(Image.open(os.path.join(ASSETS, 'water1.png')).convert('L')) > 127
W2 = np.asarray(Image.open(os.path.join(ASSETS, 'water2.png')).convert('L')) > 127

def terrain_h(e, n):
    fx = (e + HEXT / 2) / HSP; fy = (HEXT / 2 - n) / HSP
    x0 = int(min(max(math.floor(fx), 0), HS - 2)); y0 = int(min(max(math.floor(fy), 0), HS - 2))
    tx = min(1, max(0, fx - x0)); ty = min(1, max(0, fy - y0))
    return (HGT[y0, x0] * (1 - tx) + HGT[y0, x0 + 1] * tx) * (1 - ty) + (HGT[y0 + 1, x0] * (1 - tx) + HGT[y0 + 1, x0 + 1] * tx) * ty
def terrain_h_local(x, y):
    e, n, _ = L2W(x, y); return terrain_h(e, n)
def in_mask(mask, e, n):
    px = int(round(e + 1200)); py = int(round(1200 - n))
    if px < 0 or py < 0 or px >= 2400 or py >= 2400: return False
    return bool(mask[py, px])

# ----------------------------------------------------------------------------- blender helpers
def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'IMPERIAL'; sc.unit_settings.scale_length = 0.3048; sc.unit_settings.length_unit = 'FEET'
    return sc

COLS = {}
def coll(name):
    if name in COLS: return COLS[name]
    c = bpy.data.collections.new(name); bpy.context.scene.collection.children.link(c); COLS[name] = c; return c

def mesh_from_arrays(name, V, F, UV=None, col='Structures', mat=None, smooth=False):
    """V: (n,3) float, F: (m,k) int (all faces same size k) or list of lists, UV: per-loop (sum k, 2)."""
    me = bpy.data.meshes.new(name)
    V = np.asarray(V, dtype=np.float64)
    if isinstance(F, np.ndarray):
        nf, k = F.shape
        loops = F.ravel()
        loop_start = np.arange(nf, dtype=np.int32) * k
    else:
        loops = np.fromiter((v for f in F for v in f), dtype=np.int32)
        sizes = np.fromiter((len(f) for f in F), dtype=np.int32)
        nf = len(F); loop_start = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int32)
    me.vertices.add(len(V)); me.vertices.foreach_set('co', V.ravel())
    me.loops.add(len(loops)); me.loops.foreach_set('vertex_index', loops.astype(np.int32))
    me.polygons.add(nf); me.polygons.foreach_set('loop_start', loop_start)
    me.update(calc_edges=True); me.validate(verbose=False)
    if UV is not None:
        uv = me.uv_layers.new(name='UVMap'); uv.data.foreach_set('uv', np.asarray(UV, dtype=np.float32).ravel())
    if smooth: me.shade_smooth()
    ob = bpy.data.objects.new(name, me); coll(col).objects.link(ob)
    if mat is not None: me.materials.append(mat)
    return ob

def box_uv(V, F, scale):
    """per-loop box-projected UVs for faces F over verts V (world coords)."""
    V = np.asarray(V); out = []
    for f in F:
        p = V[list(f)]
        n = np.cross(p[1] - p[0], p[2] - p[0]); a = int(np.argmax(np.abs(n)))
        i, j = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[a]
        for q in p: out.append((q[i] * scale, q[j] * scale))
    return np.asarray(out, dtype=np.float32)

def solid_from_profile(name, pts2d, bottom, top, col='Structures', mat=None, uvscale=0.1):
    """closed polygon (list of (x,y) world) extruded between bottom and top elevations."""
    n = len(pts2d)
    V = [(x, y, bottom) for x, y in pts2d] + [(x, y, top) for x, y in pts2d]
    F = [list(range(n))[::-1], list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n; F.append([i, j, n + j, n + i])
    UV = box_uv(V, F, uvscale)
    return mesh_from_arrays(name, V, F, UV, col, mat)

def box_obj(name, cx, cy, cz, sx, sy, sz, rot_z=0.0, col='Structures', mat=None, uvscale=0.1):
    c, s = math.cos(rot_z), math.sin(rot_z)
    corners = []
    for dx, dy in ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2)):
        corners.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return solid_from_profile(name, corners, cz - sz / 2, cz + sz / 2, col, mat, uvscale)

def cylinder_between(name, a, b, r, mat, col='Structures', seg=10, uvscale=0.2):
    a = Vector(a); b = Vector(b); d = b - a; L = d.length
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L)
    q = d.normalized().to_track_quat('Z', 'Y')
    M = Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=M, verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    uv = me.uv_layers.new(name='UVMap')
    V = np.array([v.co for v in me.vertices]); F = [p.vertices[:] for p in me.polygons]
    uv.data.foreach_set('uv', box_uv(V, F, uvscale).ravel())
    me.shade_smooth()
    ob = bpy.data.objects.new(name, me); coll(col).objects.link(ob); me.materials.append(mat); return ob

def curve_cable(name, pts, r, mat, col='Structures'):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r; cu.bevel_resolution = 3; cu.resolution_u = 8
    sp = cu.splines.new('NURBS'); sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts): sp.points[i].co = (p[0], p[1], p[2], 1.0)
    sp.use_endpoint_u = True; sp.order_u = 3
    ob = bpy.data.objects.new(name, cu); coll(col).objects.link(ob); cu.materials.append(mat); return ob

# ----------------------------------------------------------------------------- materials
IMG = {}
def img(path, srgb=True):
    if path in IMG: return IMG[path]
    im = bpy.data.images.load(path, check_existing=True)
    im.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'
    IMG[path] = im; return im

def pbr(name, albedo=None, normal=None, rough_img=None, color=(0.8, 0.8, 0.8, 1), rough=0.8, metal=0.0,
        nstrength=0.5, alpha_from_albedo=False, translucent=0.0, tint=None, detail=None, detail_scale=1.0,
        uv_scale=1.0, bump_noise=0.0, wet_below=None, spec_ior=1.45, instance_var=0.0, slope_soil=False, desat=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nodes = nt.nodes; links = nt.links
    for n in list(nodes): nodes.remove(n)
    out = nodes.new('ShaderNodeOutputMaterial'); out.location = (900, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (600, 0)
    bsdf.inputs['Roughness'].default_value = rough; bsdf.inputs['Metallic'].default_value = metal
    bsdf.inputs['Base Color'].default_value = color; bsdf.inputs['IOR'].default_value = spec_ior
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    tc = nodes.new('ShaderNodeTexCoord'); tc.location = (-900, 0)
    mapn = nodes.new('ShaderNodeMapping'); mapn.location = (-700, 0); mapn.inputs['Scale'].default_value = (uv_scale, uv_scale, uv_scale)
    links.new(tc.outputs['UV'], mapn.inputs['Vector'])
    col_out = None
    if albedo:
        t = nodes.new('ShaderNodeTexImage'); t.image = img(albedo); t.location = (-400, 200); t.name = 'ALBEDO'
        links.new(mapn.outputs['Vector'], t.inputs['Vector'])
        col_out = t.outputs['Color']
        if alpha_from_albedo:
            links.new(t.outputs['Alpha'], bsdf.inputs['Alpha'])
    if tint is not None and col_out is not None:
        mx = nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'; mx.location = (-150, 200)
        mx.inputs['Factor'].default_value = 1.0; mx.inputs[7].default_value = tint
        links.new(col_out, mx.inputs[6]); col_out = mx.outputs[2]
    if detail is not None and col_out is not None:
        mp2 = nodes.new('ShaderNodeMapping'); mp2.location = (-700, -300); mp2.inputs['Scale'].default_value = (detail_scale,) * 3
        links.new(tc.outputs['UV'], mp2.inputs['Vector'])
        t2 = nodes.new('ShaderNodeTexImage'); t2.image = img(detail); t2.location = (-400, -300)
        links.new(mp2.outputs['Vector'], t2.inputs['Vector'])
        mx = nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'OVERLAY'; mx.location = (0, 100)
        mx.inputs['Factor'].default_value = 0.6
        links.new(col_out, mx.inputs[6]); links.new(t2.outputs['Color'], mx.inputs[7]); col_out = mx.outputs[2]
    # large scale procedural variation (dirt / moisture)
    if bump_noise or wet_below is not None:
        nz = nodes.new('ShaderNodeTexNoise'); nz.location = (-400, -600); nz.inputs['Scale'].default_value = 0.08; nz.inputs['Detail'].default_value = 6
        links.new(tc.outputs['Object'], nz.inputs['Vector'])
        if col_out is not None:
            mx = nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'; mx.location = (200, 100)
            ramp = nodes.new('ShaderNodeValToRGB'); ramp.location = (-100, -600)
            ramp.color_ramp.elements[0].position = 0.35; ramp.color_ramp.elements[0].color = (0.72, 0.70, 0.66, 1)
            ramp.color_ramp.elements[1].position = 0.65; ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
            links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
            mx.inputs['Factor'].default_value = 1.0
            links.new(col_out, mx.inputs[6]); links.new(ramp.outputs['Color'], mx.inputs[7]); col_out = mx.outputs[2]
    if wet_below is not None and col_out is not None:
        # darker + glossier below an elevation (standing water / damp concrete)
        sep = nodes.new('ShaderNodeSeparateXYZ'); sep.location = (-400, -900)
        geo = nodes.new('ShaderNodeNewGeometry'); geo.location = (-600, -900)
        links.new(geo.outputs['Position'], sep.inputs['Vector'])
        mr = nodes.new('ShaderNodeMapRange'); mr.location = (-200, -900)
        mr.inputs['From Min'].default_value = wet_below - 0.6; mr.inputs['From Max'].default_value = wet_below + 0.6
        mr.inputs['To Min'].default_value = 1.0; mr.inputs['To Max'].default_value = 0.0
        links.new(sep.outputs['Z'], mr.inputs['Value'])
        mx = nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'; mx.location = (350, 100)
        mx.inputs[7].default_value = (0.45, 0.45, 0.42, 1)
        links.new(mr.outputs['Result'], mx.inputs['Factor']); links.new(col_out, mx.inputs[6]); col_out = mx.outputs[2]
        rmix = nodes.new('ShaderNodeMix'); rmix.data_type = 'FLOAT'; rmix.location = (350, -300)
        rmix.inputs[2].default_value = rough; rmix.inputs[3].default_value = 0.15
        links.new(mr.outputs['Result'], rmix.inputs['Factor']); links.new(rmix.outputs[0], bsdf.inputs['Roughness'])
    if desat is not None and col_out is not None:
        hs = nodes.new('ShaderNodeHueSaturation'); hs.location = (380, 250)
        hs.inputs['Saturation'].default_value = desat[0]; hs.inputs['Value'].default_value = desat[1]
        links.new(col_out, hs.inputs['Color']); col_out = hs.outputs['Color']
    if instance_var > 0 and col_out is not None:
        oi = nodes.new('ShaderNodeObjectInfo'); oi.location = (0, 500)
        hs = nodes.new('ShaderNodeHueSaturation'); hs.location = (400, 400)
        mr = nodes.new('ShaderNodeMapRange'); mr.location = (200, 500)
        mr.inputs['To Min'].default_value = 0.5 - 0.06 * instance_var; mr.inputs['To Max'].default_value = 0.5 + 0.06 * instance_var
        links.new(oi.outputs['Random'], mr.inputs['Value']); links.new(mr.outputs['Result'], hs.inputs['Hue'])
        mv = nodes.new('ShaderNodeMapRange'); mv.location = (200, 650)
        mv.inputs['To Min'].default_value = 1.0 - 0.3 * instance_var; mv.inputs['To Max'].default_value = 1.0 + 0.25 * instance_var
        links.new(oi.outputs['Random'], mv.inputs['Value']); links.new(mv.outputs['Result'], hs.inputs['Value'])
        links.new(col_out, hs.inputs['Color']); col_out = hs.outputs['Color']
    if slope_soil and col_out is not None:
        geo = nodes.new('ShaderNodeNewGeometry'); geo.location = (-200, 700)
        sep = nodes.new('ShaderNodeSeparateXYZ'); sep.location = (0, 700)
        links.new(geo.outputs['Normal'], sep.inputs['Vector'])
        mr = nodes.new('ShaderNodeMapRange'); mr.location = (200, 800)
        mr.inputs['From Min'].default_value = 0.80; mr.inputs['From Max'].default_value = 0.93; mr.inputs['To Min'].default_value = 1.0; mr.inputs['To Max'].default_value = 0.0
        links.new(sep.outputs['Z'], mr.inputs['Value'])
        soil = nodes.new('ShaderNodeTexNoise'); soil.location = (0, 900); soil.inputs['Scale'].default_value = 0.4
        links.new(tc.outputs['Object'], soil.inputs['Vector'])
        sc_ = nodes.new('ShaderNodeValToRGB'); sc_.location = (200, 1000)
        sc_.color_ramp.elements[0].color = (0.26, 0.20, 0.14, 1); sc_.color_ramp.elements[1].color = (0.42, 0.35, 0.25, 1)
        links.new(soil.outputs['Fac'], sc_.inputs['Fac'])
        mx = nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.location = (450, 600)
        links.new(mr.outputs['Result'], mx.inputs['Factor']); links.new(col_out, mx.inputs[6]); links.new(sc_.outputs['Color'], mx.inputs[7]); col_out = mx.outputs[2]
    if col_out is not None: links.new(col_out, bsdf.inputs['Base Color'])
    if rough_img:
        tr = nodes.new('ShaderNodeTexImage'); tr.image = img(rough_img, srgb=False); tr.location = (-400, -100)
        links.new(mapn.outputs['Vector'], tr.inputs['Vector']); links.new(tr.outputs['Color'], bsdf.inputs['Roughness'])
    if normal:
        tn = nodes.new('ShaderNodeTexImage'); tn.image = img(normal, srgb=False); tn.location = (-400, -400)
        links.new(mapn.outputs['Vector'], tn.inputs['Vector'])
        nm = nodes.new('ShaderNodeNormalMap'); nm.location = (200, -400); nm.inputs['Strength'].default_value = nstrength
        links.new(tn.outputs['Color'], nm.inputs['Color']); links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    if translucent > 0:
        tr = nodes.new('ShaderNodeBsdfTranslucent'); tr.location = (600, -300)
        if col_out is not None: links.new(col_out, tr.inputs['Color'])
        mix = nodes.new('ShaderNodeMixShader'); mix.location = (800, 0); mix.inputs['Fac'].default_value = translucent
        links.new(bsdf.outputs['BSDF'], mix.inputs[1]); links.new(tr.outputs['BSDF'], mix.inputs[2])
        if alpha_from_albedo:
            # alpha has to wrap the whole mix for Cycles
            tp = nodes.new('ShaderNodeBsdfTransparent'); tp.location = (800, -200)
            mix2 = nodes.new('ShaderNodeMixShader'); mix2.location = (950, -100)
            links.new(nodes['ALBEDO'].outputs['Alpha'], mix2.inputs['Fac'])
            links.new(tp.outputs['BSDF'], mix2.inputs[1]); links.new(mix.outputs['Shader'], mix2.inputs[2])
            links.new(mix2.outputs['Shader'], out.inputs['Surface'])
            for l in list(bsdf.inputs['Alpha'].links): nt.links.remove(l)
        else:
            links.new(mix.outputs['Shader'], out.inputs['Surface'])
    m['export_albedo'] = albedo or ''; m['export_normal'] = normal or ''; m['export_rough'] = rough
    return m

def make_materials():
    M = {}
    M['concrete'] = pbr('Concrete', os.path.join(TEX, 'concrete.jpg'), os.path.join(TEX, 'concrete_n.jpg'), os.path.join(TEX, 'concrete_r.jpg'),
                        nstrength=0.6, bump_noise=1.0, uv_scale=1.0)
    M['concrete_slab'] = pbr('ConcreteSlab', os.path.join(TEX, 'concrete.jpg'), os.path.join(TEX, 'concrete_n.jpg'), os.path.join(TEX, 'concrete_r.jpg'),
                             nstrength=0.5, bump_noise=1.0, wet_below=470.6, tint=(0.82, 0.82, 0.80, 1))
    M['limestone'] = pbr('Limestone', os.path.join(TEX, 'limestone.jpg'), os.path.join(TEX, 'limestone_n.jpg'), rough=0.92, nstrength=0.8, bump_noise=1.0, tint=(0.95, 0.9, 0.82, 1), instance_var=0.8)
    M['gravel'] = pbr('Gravel', os.path.join(ASSETS, 'gravel.jpg'), os.path.join(ASSETS, 'gravel_n.jpg'), rough=0.95, nstrength=0.6, tint=(0.85, 0.82, 0.76, 1))
    M['wood'] = pbr('WoodDeck', os.path.join(TEX, 'wood.jpg'), os.path.join(TEX, 'wood_n.jpg'), rough=0.7, nstrength=0.6, tint=(0.95, 0.88, 0.78, 1))
    M['wood_post'] = pbr('WoodPost', os.path.join(TEX, 'wood.jpg'), os.path.join(TEX, 'wood_n.jpg'), rough=0.85, nstrength=0.6, tint=(0.6, 0.52, 0.42, 1))
    M['corten'] = pbr('WeatheringSteel', os.path.join(TEX, 'corten.jpg'), os.path.join(TEX, 'corten_n.jpg'), rough=0.72, metal=0.35, nstrength=0.4)
    M['galv'] = pbr('Galvanized', color=(0.55, 0.57, 0.58, 1), rough=0.42, metal=0.9)
    M['galv_dark'] = pbr('GalvanizedDark', color=(0.28, 0.29, 0.3, 1), rough=0.55, metal=0.85)
    M['chain'] = pbr('ChainLink', os.path.join(TEX, 'chainlink.png'), rough=0.45, metal=0.85, alpha_from_albedo=True, tint=(0.75, 0.78, 0.8, 1))
    M['asphalt'] = pbr('Asphalt', os.path.join(TEX, 'asphalt.jpg'), rough=0.9, tint=(0.8, 0.8, 0.8, 1))
    M['bark'] = pbr('Bark', os.path.join(TEX, 'bark.jpg'), os.path.join(TEX, 'bark_n.jpg'), rough=0.95, nstrength=1.0)
    for i in range(3):
        M[f'leaf{i}'] = pbr(f'Leaves{i}', os.path.join(TEX, f'leafcard{i}.png'), rough=0.55, alpha_from_albedo=True, translucent=0.3, spec_ior=1.4, instance_var=1.0)
    M['grass_clump'] = pbr('GrassClump', os.path.join(TEX, 'grassclump.png'), rough=0.8, alpha_from_albedo=True, translucent=0.1, tint=(0.55, 0.72, 0.42, 1))
    M['mud'] = pbr('Mud', color=(0.32, 0.27, 0.19, 1), rough=0.75)
    M['track'] = pbr('MownTrack', os.path.join(ASSETS, 'gravel.jpg'), os.path.join(ASSETS, 'gravel_n.jpg'), rough=0.95, nstrength=0.4, tint=(0.62, 0.66, 0.45, 1))
    # terrain
    m = pbr('Terrain', os.path.join(ASSETS, 'albedo.jpg'), os.path.join(TEX, 'grass_n.jpg'), rough=0.95, nstrength=0.35,
            detail=os.path.join(TEX, 'grass_detail.jpg'), detail_scale=260.0, tint=(1.0, 1.0, 1.0, 1), slope_soil=True, desat=(0.72, 0.85))
    # the normal map must tile too: re-link its mapping to the detail scale
    nt = m.node_tree
    for n in nt.nodes:
        if n.type == 'TEX_IMAGE' and n.image and n.image.filepath.endswith('grass_n.jpg'):
            mp = nt.nodes.new('ShaderNodeMapping'); mp.inputs['Scale'].default_value = (260.0,) * 3
            tc = [x for x in nt.nodes if x.type == 'TEX_COORD'][0]
            nt.links.new(tc.outputs['UV'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], n.inputs['Vector'])
    M['terrain'] = m
    # water
    w = bpy.data.materials.new('LakeWater'); w.use_nodes = True
    nt = w.node_tree; nodes = nt.nodes; links = nt.links
    for n in list(nodes): nodes.remove(n)
    out = nodes.new('ShaderNodeOutputMaterial'); out.location = (800, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (400, 0)
    bsdf.inputs['Base Color'].default_value = (0.06, 0.095, 0.05, 1); bsdf.inputs['Roughness'].default_value = 0.12
    bsdf.inputs['IOR'].default_value = 1.33; bsdf.inputs['Coat Weight'].default_value = 0.3
    tc = nodes.new('ShaderNodeTexCoord'); tc.location = (-800, 0)
    n1 = nodes.new('ShaderNodeTexNoise'); n1.location = (-500, -200); n1.inputs['Scale'].default_value = 0.35; n1.inputs['Detail'].default_value = 8; n1.inputs['Roughness'].default_value = 0.55
    links.new(tc.outputs['Object'], n1.inputs['Vector'])
    bump = nodes.new('ShaderNodeBump'); bump.location = (0, -200); bump.inputs['Strength'].default_value = 0.08; bump.inputs['Distance'].default_value = 0.3
    links.new(n1.outputs['Fac'], bump.inputs['Height']); links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    alpha = nodes.new('ShaderNodeTexImage'); alpha.location = (-500, 300); alpha.name = 'MASK'; alpha.interpolation = 'Linear'
    links.new(tc.outputs['UV'], alpha.inputs['Vector'])
    tp = nodes.new('ShaderNodeBsdfTransparent'); tp.location = (400, 300)
    mix = nodes.new('ShaderNodeMixShader'); mix.location = (650, 0)
    links.new(alpha.outputs['Color'], mix.inputs['Fac']); links.new(tp.outputs['BSDF'], mix.inputs[1]); links.new(bsdf.outputs['BSDF'], mix.inputs[2])
    links.new(mix.outputs['Shader'], out.inputs['Surface'])
    w['export_albedo'] = ''; w['export_rough'] = 0.06
    M['water'] = w
    return M

# ----------------------------------------------------------------------------- terrain / water
BOX = None
def make_box_mask():
    """mask of the spillway box bounded by the walls' OUTER faces (no dilation); terrain faces whose
    centre falls inside are dropped, so the terrain reaches into the wall thickness but never past
    the inner face, and there is no slot along the outside of the walls."""
    from PIL import ImageDraw
    left, left_wing, right, right_wing = wall_polylines()
    def offset(pts, sign, thick=1.0):
        out = []
        for i, p in enumerate(pts):
            a = pts[max(0, i - 1)]; b = pts[min(len(pts) - 1, i + 1)]
            tx, ty = b[0] - a[0], b[1] - a[1]; l = math.hypot(tx, ty) or 1; tx /= l; ty /= l
            out.append((p[0] - ty * sign * thick, p[1] + tx * sign * thick))
        return out
    weir_pts = [(x, y, 477) for x, y in arc(0, 0, 20.5, 90 * D, 270 * D, 48)]
    poly = offset(right, +1) + offset(left, -1)[::-1] + offset(weir_pts, -1)[::-1]
    im = Image.new('L', (2400, 2400), 0)
    ImageDraw.Draw(im).polygon([(L2W(x, y)[0] + 1200, 1200 - L2W(x, y)[1]) for x, y in poly], fill=255)
    return np.asarray(im) > 127

def build_terrain(M):
    global BOX
    BOX = make_box_mask()
    half = HEXT / 2
    def grid(step, lo, hi, skip_inner=None, name='Terrain', smooth_sigma=0.0):
        xs = np.arange(lo, hi + 1e-6, step); ys = np.arange(hi, lo - 1e-6, -step)
        E, N = np.meshgrid(xs, ys)
        # bilinear sample heightmap
        fx = (E + half) / HSP; fy = (half - N) / HSP
        x0 = np.clip(np.floor(fx).astype(int), 0, HS - 2); y0 = np.clip(np.floor(fy).astype(int), 0, HS - 2)
        tx = np.clip(fx - x0, 0, 1); ty = np.clip(fy - y0, 0, 1)
        Z = (HGT[y0, x0] * (1 - tx) + HGT[y0, x0 + 1] * tx) * (1 - ty) + (HGT[y0 + 1, x0] * (1 - tx) + HGT[y0 + 1, x0 + 1] * tx) * ty
        ny, nx = E.shape
        if smooth_sigma:
            from scipy import ndimage
            px_ = np.clip(np.round(E + 1200).astype(int), 0, 2399); py_ = np.clip(np.round(1200 - N).astype(int), 0, 2399)
            near = ndimage.binary_dilation(CUT, iterations=3)[py_, px_]
            Zs = ndimage.gaussian_filter(Z, smooth_sigma)
            Z = np.where(near, Z, Zs)
        Vv = np.stack([E.ravel(), N.ravel(), Z.ravel()], 1)
        idx = np.arange(ny * nx).reshape(ny, nx)
        a = idx[:-1, :-1]; b = idx[:-1, 1:]; c = idx[1:, 1:]; d = idx[1:, :-1]
        F = np.stack([a.ravel(), d.ravel(), c.ravel(), b.ravel()], 1)   # CCW seen from above
        # masks
        px = np.clip(np.round(E + 1200).astype(int), 0, 2399); py = np.clip(np.round(1200 - N).astype(int), 0, 2399)
        cxe = (Vv[F[:, 0], 0] + Vv[F[:, 2], 0]) / 2; cyn = (Vv[F[:, 0], 1] + Vv[F[:, 2], 1]) / 2
        pcx = np.clip(np.round(cxe + 1200).astype(int), 0, 2399); pcy = np.clip(np.round(1200 - cyn).astype(int), 0, 2399)
        keep = ~CUT[pcy, pcx] & ~BOX[pcy, pcx]
        if skip_inner is not None:
            ins = ((np.abs(E) < skip_inner) & (np.abs(N) < skip_inner)).ravel()
            keep &= ~(ins[F[:, 0]] & ins[F[:, 1]] & ins[F[:, 2]] & ins[F[:, 3]])
        F = F[keep]
        UVv = np.stack([(Vv[:, 0] + 1200) / 2400, (Vv[:, 1] + 1200) / 2400], 1)
        UV = UVv[F.ravel()]
        ob = mesh_from_arrays(name, Vv, F, UV, 'Terrain', M['terrain'], smooth=True)
        return ob, Vv, F
    inner, Vi, Fi = grid(2.0, -500, 500, None, 'TerrainInner', smooth_sigma=2.4)
    outer, _, _ = grid(6.0, -1200, 1200, 498, 'TerrainOuter')
    # far ground
    far = mesh_from_arrays('FarGround', [(-9000, -9000, 466), (9000, -9000, 466), (9000, 9000, 466), (-9000, 9000, 466)], [[0, 1, 2, 3]],
                           [(0, 0), (1, 0), (1, 1), (0, 1)], 'Terrain', M['terrain'])
    # water planes
    for name, level, mask in (('Lake1', 476.6, 'water1.png'), ('Lake2', 490.4, 'water2.png')):
        wm = M['water'].copy(); wm.name = 'Water_' + name
        wm.node_tree.nodes['MASK'].image = img(os.path.join(ASSETS, mask), srgb=False)
        ob = mesh_from_arrays(name, [(-1200, -1200, level), (1200, -1200, level), (1200, 1200, level), (-1200, 1200, level)], [[0, 1, 2, 3]],
                              [(0, 0), (1, 0), (1, 1), (0, 1)], 'Water', wm)
        ob.visible_shadow = False
    return inner, Vi, Fi

# ----------------------------------------------------------------------------- spillway (local frame)
def arc(cx, cy, r, a0, a1, n):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
D = math.pi / 180
BX0, BX1 = 8.0, 16.0            # pedestrian bridge (8 ft wide) centred on the Dam No.1 centreline, sta 30+56
WALK_SW = [(12, -24.5), (12, -38)] + [(52 - 40 * math.cos(math.radians(a)), -38 - 40 * math.sin(math.radians(a))) for a in range(6, 55, 6)]
DRIVE1 = [(-230, -190), (-140, -150), (-70, -123), (0, -95), (40, -62), (80, -34), (116, -23)]       # existing asphalt access drive (from the 2005 aerial)
DRIVE2 = [(-90, -305), (-20, -255), (20, -243), (60, -232), (100, -207), (140, -199), (250, -190), (410, -178)]  # lake access drive
CREST = [(12, 24.5), (12, 48), (11.5, 120), (11, 300), (11, 560)]                                   # mown track along the Dam No.1 crest
def dist_to_polyline(x, y, pts):
    best = 1e9
    for a, b in zip(pts[:-1], pts[1:]):
        vx, vy = b[0] - a[0], b[1] - a[1]; L2 = vx * vx + vy * vy or 1e-6
        t = max(0.0, min(1.0, ((x - a[0]) * vx + (y - a[1]) * vy) / L2))
        best = min(best, math.hypot(x - a[0] - t * vx, y - a[1] - t * vy))
    return best
def dist_to_drives(x, y):
    return min(dist_to_polyline(x, y, DRIVE1), dist_to_polyline(x, y, DRIVE2))

def slab_elev(x, y):
    if x < 0: return 473.46 + 0.54 * min(1.0, -x / 20.5)
    tbl = [(0, 473.46), (13, 473.12), (15, 472.81), (50, 472.0), (60, 472.0), (75, 471.25), (90, 470.85), (110, 470.0), (140, 469.0)]
    s = x
    if x > 54.7:
        ang = math.atan2(y - 15, x - 54.7); sweep = ang + math.pi / 2
        s = 54.7 + max(0.0, sweep) * 35.5
        end = 54.7 + (52 * D) * 35.5
        if s > end:
            dx = x - 82.7; dy = y + 6.9; s = end + dx * math.cos(52 * D) + dy * math.sin(52 * D)
    for i in range(len(tbl) - 1):
        if tbl[i][0] <= s <= tbl[i + 1][0]:
            t = (s - tbl[i][0]) / (tbl[i + 1][0] - tbl[i][0]); return tbl[i][1] + (tbl[i + 1][1] - tbl[i][1]) * t
    return 473.46 if s < 0 else 469.0

def wall_polylines():
    left = [(0, -20.5, 477), (1, -20.5, 477), (13, -20.5, 480), (54.7, -20.5, 480)]
    arcL = arc(54.7, 15, 35.5, -90 * D, -38 * D, 26)
    for i in range(1, len(arcL)):
        f = i / (len(arcL) - 1); sArc = f * 52 * D * 35.5
        top = 480 - 3 * (sArc / 25.7) if sArc < 25.7 else 477
        left.append((arcL[i][0], arcL[i][1], top))
    left += [(88.1, 0.0, 477), (96.9, 11.4, 476)]
    left_wing = [(96.9, 11.4, 476), (105.9, 4.2, 476)]
    right = [(0, 20.5, 477), (1, 20.5, 477), (13, 20.5, 480), (58.7, 20.5, 480)]
    arcR = arc(58.7, 52, 31.5, -90 * D, -49 * D, 22)
    for i in range(1, len(arcR)):
        f = i / (len(arcR) - 1); right.append((arcR[i][0], arcR[i][1], 480 - 4 * f))
    right_wing = [(80.3, 28.5, 476), (72.4, 36.8, 476)]
    return left, left_wing, right, right_wing

def build_wall(name, pts, thick, bottom, outward_sign, mat):
    inner = []; outer = []
    for i, p in enumerate(pts):
        a = pts[max(0, i - 1)]; b = pts[min(len(pts) - 1, i + 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]; l = math.hypot(tx, ty) or 1; tx /= l; ty /= l
        nx, ny = -ty * outward_sign, tx * outward_sign
        inner.append((p[0], p[1], p[2])); outer.append((p[0] + nx * thick, p[1] + ny * thick, p[2]))
    V = []; F = []
    n = len(pts)
    for i in range(n):
        V += [L2W(inner[i][0], inner[i][1], bottom), L2W(inner[i][0], inner[i][1], inner[i][2]),
              L2W(outer[i][0], outer[i][1], outer[i][2]), L2W(outer[i][0], outer[i][1], bottom)]
    for i in range(n - 1):
        a = i * 4; b = (i + 1) * 4
        F.append([a, b, b + 1, a + 1]); F.append([a + 1, b + 1, b + 2, a + 2]); F.append([a + 2, b + 2, b + 3, a + 3])
    F.append([0, 1, 2, 3]); e = (n - 1) * 4; F.append([e + 3, e + 2, e + 1, e])
    UV = box_uv(V, F, 0.1)
    return mesh_from_arrays(name, V, F, UV, 'Structures', mat)

def build_spillway(M):
    left, left_wing, right, right_wing = wall_polylines()
    build_wall('WallLeft', left, 1.0, 466, -1, M['concrete'])
    build_wall('WallLeftWing', left_wing, 1.0, 466, -1, M['concrete'])
    build_wall('WallRight', right, 1.0, 466, +1, M['concrete'])
    build_wall('WallRightWing', right_wing, 1.0, 466, +1, M['concrete'])
    # weir: semicircle inner R 20.5, outer 21.5, top 477, bottom 470 (sits on slab)
    pts = [(x, y, 477) for x, y in arc(0, 0, 20.5, 90 * D, 270 * D, 48)]
    build_wall('Weir', pts, 1.0, 470, -1, M['concrete'])
    # slab: half disk + ribbon
    V = []; F = []
    rim = arc(0, 0, 21.0, 90 * D, 270 * D, 48)
    V.append(L2W(0, 0, slab_elev(0, 0)))
    for p in rim: V.append(L2W(p[0], p[1], slab_elev(p[0], p[1])))
    for i in range(len(rim) - 1): F.append([0, 2 + i, 1 + i])
    def poly_len(P):
        return sum(math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]) for i in range(1, len(P)))
    def at_frac(P, f):
        L = poly_len(P); t = f * L
        for i in range(1, len(P)):
            seg = math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1])
            if t <= seg or i == len(P) - 1:
                u = max(0, min(1, t / seg)) if seg else 0
                return (P[i - 1][0] + (P[i][0] - P[i - 1][0]) * u, P[i - 1][1] + (P[i][1] - P[i - 1][1]) * u)
            t -= seg
        return P[-1][:2]
    lp = [(p[0], p[1] + 0.5) for p in left]; rp = [(p[0], p[1] - 0.5) for p in right]
    lp[0] = (-0.5, lp[0][1]); rp[0] = (-0.5, rp[0][1])
    N = 90; base = len(V)
    for i in range(N + 1):
        f = i / N; l = at_frac(lp, f); r = at_frac(rp, f)
        V.append(L2W(l[0], l[1], slab_elev(l[0], l[1]))); V.append(L2W(r[0], r[1], slab_elev(r[0], r[1])))
    for i in range(N):
        a = base + i * 2; F.append([a, a + 1, a + 3, a + 2])
    UV = box_uv(V, F, 0.1)
    mesh_from_arrays('Slab', V, F, UV, 'Structures', M['concrete_slab'])
    # baffle blocks
    for yc in (-11.3, 0.0, 11.3):
        z0 = slab_elev(50, yc) - 0.02
        prof = [(60, yc - 2.5), (62.8, yc - 2.5), (62.8, yc + 2.5), (60, yc + 2.5)]
        # trapezoid in x-z: build as two solids: lower box 2.8 wide, upper slope approximated by 3 slices
        Vb = []; Fb = []
        for (x0, x1, zz) in ((50, 52.8, 0), (50, 51.6, 2.0), (50, 50.75, 3.75)):
            Vb += [L2W(x0, yc - 2.5, z0 + zz), L2W(x1, yc - 2.5, z0 + zz), L2W(x1, yc + 2.5, z0 + zz), L2W(x0, yc + 2.5, z0 + zz)]
        for k in range(2):
            a = k * 4; b = a + 4
            for (i0, i1) in ((0, 1), (1, 2), (2, 3), (3, 0)):
                Fb.append([a + i0, a + i1, b + i1, b + i0])
        Fb.append([8, 9, 10, 11]); Fb.append([3, 2, 1, 0])
        mesh_from_arrays(f'Baffle_{yc:+.0f}', Vb, Fb, box_uv(Vb, Fb, 0.1), 'Structures', M['concrete'])
    # end sill blocks along the outlet line
    ax, ay = 96.9, 11.4; bx, by = 80.3, 28.5
    L = math.hypot(bx - ax, by - ay); dx, dy = (bx - ax) / L, (by - ay) / L
    for i in range(6):
        t = (i + 0.5) / 6 * L; px, py = ax + dx * t, ay + dy * t
        c, s = math.cos(math.atan2(dy, dx)), math.sin(math.atan2(dy, dx))
        corners = []
        for ox, oy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            lx = px + ox * c - oy * s; ly = py + ox * s + oy * c
            e, n, _ = L2W(lx, ly); corners.append((e, n))
        solid_from_profile(f'EndSill_{i}', corners, 469.6, 471.75, 'Structures', M['concrete'])
    # bridge abutments behind the walls
    for sgn in (-1, 1):
        corners = [L2W(BX0 - 2, sgn * 23 - 1.5)[:2], L2W(BX1 + 2, sgn * 23 - 1.5)[:2], L2W(BX1 + 2, sgn * 23 + 1.5)[:2], L2W(BX0 - 2, sgn * 23 + 1.5)[:2]]
        solid_from_profile(f'Abutment_{sgn:+d}', corners, 475.0, 481.75, 'Structures', M['concrete'])
    build_bridge(M)
    fenceL = [(p[0], p[1] - 0.5, p[2]) for p in left if p[0] >= 19.5] + [(100.5, 8.5, 476), (105.9, 4.2, 476)]
    fenceR = [(p[0], p[1] + 0.5, p[2]) for p in right if p[0] >= 19.5] + [(76.3, 32.6, 476), (72.4, 36.8, 476)]
    build_chainlink('FenceLeft', fenceL, M); build_chainlink('FenceRight', fenceR, M)
    build_outlet_channel(M)
    build_weir_riprap(M)
    build_walkway(M)
    for i, line in enumerate(([(7.0, -25.5), (7.0, -46.5)], [(17.0, -25.5), (17.0, -46.5)], [(6.0, 25.5), (6.0, 46.5)], [(16.0, 25.5), (16.0, 46.5)], [(60.0, -25.0), (81.0, -25.0)])):
        build_post_cable(f'PostCable{i}', line, M)

def build_bridge(M):
    x0, x1, yA, yB = BX0, BX1, -23.5, 23.5
    deck, bot, top = 482.0, 481.6, 485.6
    # deck planks: 2x6 across the bridge, laid along y, 0.46' wide with 1/4" gaps
    V = []; F = []; y = yA
    while y < yB - 0.01:
        w = min(0.46, yB - y)
        for (lx, ly, z) in ((x0, y, deck - 0.14), (x1, y, deck - 0.14), (x1, y + w, deck - 0.14), (x0, y + w, deck - 0.14),
                            (x0, y, deck), (x1, y, deck), (x1, y + w, deck), (x0, y + w, deck)):
            V.append(L2W(lx, ly, z))
        b = len(V) - 8
        F += [[b + 4, b + 5, b + 6, b + 7], [b + 3, b + 2, b + 1, b], [b, b + 1, b + 5, b + 4], [b + 1, b + 2, b + 6, b + 5], [b + 2, b + 3, b + 7, b + 6], [b + 3, b, b + 4, b + 7]]
        y += 0.49
    mesh_from_arrays('BridgeDeck', V, F, box_uv(V, F, 0.12), 'Bridge', M['wood'])
    # stringers
    for x in (x0 + 0.6, (x0 + x1) / 2, x1 - 0.6):
        cyl = box_obj  # noqa
        corners = [L2W(x - 0.15, yA)[:2], L2W(x + 0.15, yA)[:2], L2W(x + 0.15, yB)[:2], L2W(x - 0.15, yB)[:2]]
        solid_from_profile(f'Stringer_{x:.1f}', corners, deck - 0.95, deck - 0.15, 'Bridge', M['corten'])
    panels = 8; pw = (yB - yA) / panels
    for x in (x0 + 0.2, x1 - 0.2):
        for z in (bot, top):
            corners = [L2W(x - 0.17, yA - 0.5)[:2], L2W(x + 0.17, yA - 0.5)[:2], L2W(x + 0.17, yB + 0.5)[:2], L2W(x - 0.17, yB + 0.5)[:2]]
            solid_from_profile(f'Chord_{x:.1f}_{z:.0f}', corners, z - 0.17, z + 0.17, 'Bridge', M['corten'])
        for i in range(panels + 1):
            y = yA + i * pw
            corners = [L2W(x - 0.125, y - 0.125)[:2], L2W(x + 0.125, y - 0.125)[:2], L2W(x + 0.125, y + 0.125)[:2], L2W(x - 0.125, y + 0.125)[:2]]
            solid_from_profile(f'Post_{x:.1f}_{i}', corners, bot, top, 'Bridge', M['corten'])
            if i < panels:
                a = (x, bot, y); b = (x, top, y + pw)
                if i % 2 == 1: a = (x, bot, y + pw); b = (x, top, y)
                cylinder_between(f'Diag_{x:.1f}_{i}', L2W(a[0], a[2], a[1]), L2W(b[0], b[2], b[1]), 0.1, M['corten'], 'Bridge', seg=8)
        # pickets as one mesh
        Vp = []; Fp = []
        yy = yA + 0.2
        while yy < yB:
            for (lx, ly, z) in ((x - 0.03, yy - 0.03, bot + 0.2), (x + 0.03, yy - 0.03, bot + 0.2), (x + 0.03, yy + 0.03, bot + 0.2), (x - 0.03, yy + 0.03, bot + 0.2),
                                (x - 0.03, yy - 0.03, top - 0.2), (x + 0.03, yy - 0.03, top - 0.2), (x + 0.03, yy + 0.03, top - 0.2), (x - 0.03, yy + 0.03, top - 0.2)):
                Vp.append(L2W(lx, ly, z))
            b = len(Vp) - 8
            Fp += [[b, b + 1, b + 5, b + 4], [b + 1, b + 2, b + 6, b + 5], [b + 2, b + 3, b + 7, b + 6], [b + 3, b, b + 4, b + 7], [b + 4, b + 5, b + 6, b + 7]]
            yy += 0.333
        mesh_from_arrays(f'Pickets_{x:.1f}', Vp, Fp, box_uv(Vp, Fp, 0.3), 'Bridge', M['galv_dark'])
        corners = [L2W(x - 0.1, yA - 0.5)[:2], L2W(x + 0.1, yA - 0.5)[:2], L2W(x + 0.1, yB + 0.5)[:2], L2W(x - 0.1, yB + 0.5)[:2]]
        solid_from_profile(f'Handrail_{x:.1f}', corners, top + 0.18, top + 0.33, 'Bridge', M['corten'])

def build_chainlink(name, poly, M):
    H = 3.5
    pts = []
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]; seg = math.hypot(b[0] - a[0], b[1] - a[1]); n = max(1, round(seg / 6))
        for k in range(n):
            t = k / n; pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t))
    pts.append(poly[-1])
    for i, p in enumerate(pts):
        cylinder_between(f'{name}_post{i}', L2W(p[0], p[1], p[2] - 0.2), L2W(p[0], p[1], p[2] + H + 0.1), 0.1, M['galv'], 'Fence', seg=8)
    V = []; F = []; UV = []; s = 0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        cylinder_between(f'{name}_rail{i}', L2W(a[0], a[1], a[2] + H), L2W(b[0], b[1], b[2] + H), 0.07, M['galv'], 'Fence', seg=6)
        cylinder_between(f'{name}_brail{i}', L2W(a[0], a[1], a[2] + 0.15), L2W(b[0], b[1], b[2] + 0.15), 0.05, M['galv'], 'Fence', seg=6)
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        base = len(V)
        V += [L2W(a[0], a[1], a[2] + 0.1), L2W(b[0], b[1], b[2] + 0.1), L2W(b[0], b[1], b[2] + H), L2W(a[0], a[1], a[2] + H)]
        F.append([base, base + 1, base + 2, base + 3])
        UV += [(s / 2, 0), ((s + seg) / 2, 0), ((s + seg) / 2, H / 2), (s / 2, H / 2)]
        s += seg
    ob = mesh_from_arrays(f'{name}_fabric', V, F, UV, 'Fence', M['chain'])
    ob.visible_shadow = True

def channel_frame():
    oc = (88.6, 19.95); ang = 47 * D
    du = (math.cos(ang), math.sin(ang)); dn = (-du[1], du[0])
    return oc, du, dn

def build_outlet_channel(M):
    oc, du, dn = channel_frame()
    NU, NV, LEN, WID = 48, 40, 62, 42
    V = []; F = []
    rng = random.Random(3)
    for j in range(NV + 1):
        for i in range(NU + 1):
            u = -1.5 + LEN * i / NU; v = -WID + 2 * WID * j / NV
            hw = 11.5 + max(0, min(u, 54)) * 0.16
            bed = 470 - max(0, min(u, 54)) * (4 / 54)
            side = max(0, abs(v) - hw)
            y = bed + side / 2
            px = oc[0] + du[0] * u + dn[0] * v; py = oc[1] + du[1] * u + dn[1] * v
            th = terrain_h_local(px, py)
            if side > 0: y = min(y, th)
            if abs(v) > hw + 17: y = th - 0.05
            y += 0.25 * math.sin(px * 1.7) * math.cos(py * 2.3) * (1 if side < 14 else 0)
            V.append(L2W(px, py, y))
    for j in range(NV):
        for i in range(NU):
            a = j * (NU + 1) + i; F.append([a, a + NU + 1, a + NU + 2, a + 1])
    mesh_from_arrays('OutletChannel', V, F, box_uv(V, F, 0.08), 'Structures', M['limestone'], smooth=True)
    # rocks
    rocks = make_rock_variants(M)
    k = 0
    for _ in range(1100):
        u = 0.5 + rng.random() * 55; hw = 11.5 + u * 0.16
        v = (rng.random() - 0.5) * 2 * (hw + 9)
        px = oc[0] + du[0] * u + dn[0] * v; py = oc[1] + du[1] * u + dn[1] * v
        side = max(0, abs(v) - hw); z = 470 - u * (4 / 54) + side / 2
        if side > 0: z = min(z, terrain_h_local(px, py))
        s = 0.45 + rng.random() ** 1.5 * 1.0
        place_rock(rocks[k % len(rocks)], L2W(px, py, z + s * 0.25), s, rng, f'Rock_{k}'); k += 1

def build_weir_riprap(M):
    NR, NA = 12, 64; V = []; F = []
    for j in range(NR + 1):
        for i in range(NA + 1):
            r = 21.0 + (40.5 - 21.0) * j / NR; a = (80 + 200 * i / NA) * D
            x = r * math.cos(a); y = r * math.sin(a)
            th = terrain_h_local(x, y)
            z = th + 0.3 if th < 477.6 else th - 0.4      # riprap apron only below the water line
            z += 0.25 * math.sin(x * 2.1) * math.cos(y * 1.7)
            V.append(L2W(x, y, z))
    for j in range(NR):
        for i in range(NA):
            a = j * (NA + 1) + i; F.append([a, a + 1, a + NA + 2, a + NA + 1])
    mesh_from_arrays('WeirRiprap', V, F, box_uv(V, F, 0.08), 'Structures', M['limestone'], smooth=True)
    rocks = make_rock_variants(M, prefix='WRockBase')
    rng = random.Random(9); k = 0
    for _ in range(650):
        r = 21.8 + rng.random() * 14.0; a = (88 + rng.random() * 184) * D
        x = r * math.cos(a); y = r * math.sin(a)
        th = terrain_h_local(x, y)
        if th > 477.2: continue
        z = th + 0.2
        s = 0.45 + rng.random() ** 1.5 * 0.9
        place_rock(rocks[k % len(rocks)], L2W(x, y, z + s * 0.2), s, rng, f'WRock_{k}'); k += 1

ROCK_CACHE = {}
def make_rock_variants(M, n=6, prefix='RockBase'):
    if prefix in ROCK_CACHE: return ROCK_CACHE[prefix]
    out = []
    for i in range(n):
        bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        rng = random.Random(100 + i)
        # angular limestone look: random planar cuts + noise
        for v in bm.verts:
            p = v.co
            nse = 0.18 * math.sin(p.x * 3.1 + rng.random()) * math.cos(p.y * 2.7) + 0.12 * math.sin(p.z * 4.3 + p.x)
            sc = Vector((rng.uniform(0.9, 1.1), 1, 1))
            v.co = Vector((p.x * (1.2 + nse), p.y * (0.95 + nse * 0.5), p.z * (0.75 + nse * 0.5)))
        # flatten a few sides
        for k in range(3):
            d = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.5, 1))).normalized(); lim = rng.uniform(0.55, 0.85)
            for v in bm.verts:
                t = v.co.dot(d)
                if t > lim: v.co -= d * (t - lim)
        me = bpy.data.meshes.new(f'{prefix}{i}'); bm.to_mesh(me); bm.free()
        uv = me.uv_layers.new(name='UVMap')
        Vv = np.array([v.co for v in me.vertices]); Fv = [p.vertices[:] for p in me.polygons]
        uv.data.foreach_set('uv', box_uv(Vv, Fv, 0.5).ravel())
        me.shade_smooth(); me.materials.append(M['limestone'])
        out.append(me)
    ROCK_CACHE[prefix] = out
    return out

def place_rock(me, loc, s, rng, name):
    ob = bpy.data.objects.new(name, me); coll('Rocks').objects.link(ob)
    ob.location = loc; ob.scale = (s * rng.uniform(0.8, 1.2), s * rng.uniform(0.8, 1.2), s * rng.uniform(0.7, 1.0))
    ob.rotation_euler = (rng.uniform(0, 6.28), rng.uniform(0, 6.28), rng.uniform(0, 6.28))
    return ob

def ribbon(name, center, width, mat, col='Structures', lift=0.25, uvscale=0.25, zfun=None):
    """ground-conforming strip along a local-frame polyline (resampled every ~2 ft)."""
    pts = []
    for a, b in zip(center[:-1], center[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1]); n = max(1, int(seg / 2))
        for k in range(n): t = k / n; pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    pts.append(center[-1])
    V = []; F = []; UV = []; s = 0
    for i, p in enumerate(pts):
        a = pts[max(0, i - 1)]; b = pts[min(len(pts) - 1, i + 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]; l = math.hypot(tx, ty) or 1; tx /= l; ty /= l
        nx, ny = -ty, tx
        if i > 0: s += math.hypot(p[0] - a[0], p[1] - a[1])
        for w in (-width / 2, width / 2):
            x = p[0] + nx * w; y = p[1] + ny * w
            z = terrain_h_local(x, y) + lift
            if zfun is not None: z = zfun(x, y, s, z)
            V.append(L2W(x, y, z)); UV.append((w * uvscale, s * uvscale))
    for i in range(len(pts) - 1):
        a = i * 2; F.append([a, a + 1, a + 3, a + 2])
    UVl = [UV[v] for f in F for v in f]
    ob = mesh_from_arrays(name, V, F, UVl, col, mat, smooth=True)
    return ob

def build_walkway(M):
    G = bpy.data.collections.get('Structures')
    # 8 ft stone walkway: bridge SW end -> R=40 ft bend -> existing asphalt access drive (sheets 7, 11)
    ribbon('Walkway', WALK_SW, 9.0, M['gravel'], zfun=lambda x, y, s, z: max(z, 482.0) if s < 2 else z)
    # bridge NE end: short gravel approach down to the regraded crest (EL 480), then the mown crest track
    ribbon('CrestApproach', [(12, 24.5), (12, 48)], 9.0, M['gravel'], zfun=lambda x, y, s, z: max(z, 482.0 - 2.0 * min(1.0, s / 22.0)))
    ribbon('CrestTrack', CREST[1:], 6.0, M['track'], lift=0.12)
    # existing asphalt drives (positions from the 2005 aerial in the bid set)
    ribbon('AccessDrive', DRIVE1, 14.0, M['asphalt'], lift=0.15, uvscale=0.1)
    ribbon('LakeAccessDrive', DRIVE2, 14.0, M['asphalt'], lift=0.15, uvscale=0.1)

def build_post_cable(name, line, M):
    (ax, ay), (bx, by) = line; L = math.hypot(bx - ax, by - ay); n = max(1, round(L / 7))
    tops = []
    for i in range(n + 1):
        t = i / n; x = ax + (bx - ax) * t; y = ay + (by - ay) * t
        z = terrain_h_local(x, y)
        if abs(y) < 27 and BX0 - 4 < x < BX1 + 4: z = max(z, 481.9)
        corners = [L2W(x - 0.25, y - 0.25)[:2], L2W(x + 0.25, y - 0.25)[:2], L2W(x + 0.25, y + 0.25)[:2], L2W(x - 0.25, y + 0.25)[:2]]
        solid_from_profile(f'{name}_post{i}', corners, z - 0.3, z + 3.6, 'Fence', M['wood_post'], uvscale=0.3)
        tops.append((x, y, z))
    for i in range(len(tops) - 1):
        for h in (3.1, 1.7):
            p = tops[i]; q = tops[i + 1]
            pts = [L2W(p[0], p[1], p[2] + h), L2W((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, (p[2] + q[2]) / 2 + h - 0.12), L2W(q[0], q[1], q[2] + h)]
            curve_cable(f'{name}_cable{i}_{h}', pts, 0.025, M['galv_dark'], 'Fence')

# ----------------------------------------------------------------------------- Dam No. 2
def build_dam2(M):
    A = (-690.0, 70.0); B = (-300.0, 72.0)
    dx, dy = B[0] - A[0], B[1] - A[1]; L = math.hypot(dx, dy); dx /= L; dy /= L; nx, ny = -dy, dx
    V = []; F = []; NU = 90
    for i in range(NU + 1):
        t = -0.25 + 1.5 * i / NU; e = A[0] + dx * L * t; n = A[1] + dy * L * t
        for w in (-6, 6):
            ee = e + nx * w; nn = n + ny * w; V.append((ee, nn, terrain_h(ee, nn) + 0.2))
    for i in range(NU):
        a = i * 2; F.append([a, a + 2, a + 3, a + 1])
    mesh_from_arrays('Dam2Road', V, F, box_uv(V, F, 0.1), 'Structures', M['asphalt'], smooth=True)
    s = 10
    while s < L - 10:
        e = A[0] + dx * s - nx * 8; n = A[1] + dy * s - ny * 8; z = terrain_h(e, n)
        solid_from_profile(f'Dam2Post_{int(s)}', [(e - 0.25, n - 0.25), (e + 0.25, n - 0.25), (e + 0.25, n + 0.25), (e - 0.25, n + 0.25)], z - 0.3, z + 3.0, 'Fence', M['wood_post'], 0.3)
        s += 25
    s = 266; e = A[0] + dx * s - nx * 26; n = A[1] + dy * s - ny * 26
    cylinder_between('Dam2Riser', (e, n, 482.0), (e, n, 490.31), 2.0, M['galv_dark'], 'Structures', seg=24)
    box_obj('Dam2Grate', e, n, 490.45, 4.2, 4.2, 0.25, 0, 'Structures', M['galv_dark'])
    for k in np.arange(-1.5, 1.51, 0.5):
        box_obj(f'Dam2GrateBar_{k:+.1f}', e, n + k, 490.6, 4.2, 0.08, 0.4, 0, 'Structures', M['galv'])
    for s in (95, 310):
        e = A[0] + dx * s + nx * 66; n = A[1] + dy * s + ny * 66; z = terrain_h(e, n)
        box_obj(f'Dam2ToeDrain_{s}', e, n, z + 0.4, 1.5, 1.5, 1.2, 0, 'Structures', M['concrete'])

# ----------------------------------------------------------------------------- vegetation
def make_tree_variant(i, M, H=40.0):
    """procedural broadleaf tree ~H ft tall: trunk + 2 branch levels + leaf cards. returns collection"""
    rng = random.Random(500 + i)
    c = bpy.data.collections.new(f'Tree{i}'); bpy.context.scene.collection.children.link(c)
    c.hide_render = False
    # trunk + branches in one bmesh
    bm = bmesh.new()
    def seg(a, b, r0, r1, n=8):
        a = Vector(a); b = Vector(b); d = b - a
        if d.length < 0.1: return
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=r0, radius2=r1, depth=d.length)
        q = d.normalized().to_track_quat('Z', 'Y')
        bmesh.ops.transform(bm, matrix=Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4(), verts=res['verts'])
    trunk_h = H * rng.uniform(0.38, 0.5)
    r0 = H * 0.022
    seg((0, 0, -1), (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), trunk_h), r0, r0 * 0.55, 10)
    tips = []
    nb = rng.randint(5, 7)
    for k in range(nb):
        a = (k / nb) * 2 * math.pi + rng.uniform(-0.4, 0.4); el = rng.uniform(0.45, 1.05)
        L = H * rng.uniform(0.28, 0.42)
        start = Vector((0, 0, trunk_h * rng.uniform(0.75, 1.0)))
        end = start + Vector((math.cos(a) * math.cos(el) * L, math.sin(a) * math.cos(el) * L, math.sin(el) * L))
        seg(start, end, r0 * 0.5, r0 * 0.18)
        tips.append(end)
        for m in range(rng.randint(2, 3)):
            a2 = a + rng.uniform(-1.0, 1.0); el2 = rng.uniform(0.2, 1.1); L2 = L * rng.uniform(0.4, 0.7)
            s2 = start + (end - start) * rng.uniform(0.5, 0.95)
            e2 = s2 + Vector((math.cos(a2) * math.cos(el2) * L2, math.sin(a2) * math.cos(el2) * L2, math.sin(el2) * L2))
            seg(s2, e2, r0 * 0.2, r0 * 0.07, 6); tips.append(e2)
    me = bpy.data.meshes.new(f'TreeWood{i}'); bm.to_mesh(me); bm.free()
    uv = me.uv_layers.new(name='UVMap')
    Vv = np.array([v.co for v in me.vertices]); Fv = [p.vertices[:] for p in me.polygons]
    # cylindrical-ish uv: angle around z and height
    uvs = []
    for f in Fv:
        for vi in f:
            p = Vv[vi]; uvs.append((math.atan2(p[1], p[0]) / (2 * math.pi) * 3.0, p[2] * 0.08))
    uv.data.foreach_set('uv', np.asarray(uvs, np.float32).ravel())
    me.shade_smooth(); me.materials.append(M['bark'])
    ob = bpy.data.objects.new(f'TreeWood{i}', me); c.objects.link(ob)
    # leaf cards: ellipsoid canopy centred above the trunk, denser near branch tips
    V = []; F = []; UVl = []
    cz = trunk_h + H * 0.22; rx = H * 0.44; rz = H * 0.36
    ncards = 340; card = H * 0.125; ccen = Vector((0, 0, cz))
    for k in range(ncards):
        if k < len(tips) * 6:
            tip = tips[k % len(tips)]; ctr = tip + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.5, 1))) * H * 0.07
        else:
            u = rng.uniform(0, 2 * math.pi); v = math.acos(rng.uniform(-1, 1)); rr = rng.uniform(0.55, 1.0)
            ctr = Vector((rx * rr * math.sin(v) * math.cos(u), rx * rr * math.sin(v) * math.sin(u), cz + rz * rr * math.cos(v)))
        if ctr.z < trunk_h * 0.55: continue
        nrm = (ctr - ccen); nrm.z *= 0.6
        if nrm.length < 1e-3: nrm = Vector((1, 0, 0))
        nrm.normalize()
        Mr = nrm.to_track_quat('Y', 'Z').to_matrix() @ Euler((rng.uniform(-0.6, 0.6), rng.uniform(0, 2 * math.pi), rng.uniform(-0.6, 0.6))).to_matrix()
        base = len(V)
        for (dx, dz) in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            p = Mr @ Vector((dx * card / 2, 0, dz * card / 2)); V.append((ctr + p)[:])
        F.append([base, base + 1, base + 2, base + 3]); UVl += [(0, 0), (1, 0), (1, 1), (0, 1)]
    lo = mesh_from_arrays(f'TreeLeaves{i}', V, F, UVl, None.__class__ and 'Vegetation', M[f'leaf{i}'])
    # move leaves object from the Vegetation collection into the tree collection
    coll('Vegetation').objects.unlink(lo); c.objects.link(lo)
    bpy.context.scene.collection.children.unlink(c)   # keep as asset only (instanced)
    c['base_height'] = H
    return c

def build_trees(M):
    variants = [make_tree_variant(i, M) for i in range(3)]
    trees = json.load(open(os.path.join(ASSETS, 'trees.json')))
    rng = random.Random(1)
    vc = coll('Trees')
    for k, t in enumerate(trees):
        e, n, z, h, var, rot = t
        c = variants[var % 3]
        ob = bpy.data.objects.new(f'Tree_{k}', None); ob.instance_type = 'COLLECTION'; ob.instance_collection = c
        s = h / c['base_height']
        ob.location = (e, n, z - 0.6); ob.rotation_euler = (0, 0, rot); ob.scale = (s * rng.uniform(0.85, 1.15), s * rng.uniform(0.85, 1.15), s)
        ob.empty_display_size = 1; vc.objects.link(ob)
    return variants

def build_grass(M, terrain_inner, Vi, Fi):
    # clump variants: 3 crossed cards
    c = bpy.data.collections.new('GrassClumps'); bpy.context.scene.collection.children.link(c)
    for i in range(3):
        rng = random.Random(700 + i)
        V = []; F = []; UV = []
        w = 2.4 * rng.uniform(0.8, 1.2); h = 1.5 * rng.uniform(0.8, 1.25)
        for k in range(3):
            a = k * math.pi / 3 + rng.uniform(-0.2, 0.2); cx, cy = math.cos(a), math.sin(a)
            base = len(V)
            V += [(-cx * w / 2, -cy * w / 2, -0.1), (cx * w / 2, cy * w / 2, -0.1), (cx * w / 2, cy * w / 2, h), (-cx * w / 2, -cy * w / 2, h)]
            F.append([base, base + 1, base + 2, base + 3]); UV += [(0, 0), (1, 0), (1, 1), (0, 1)]
        ob = mesh_from_arrays(f'GrassClump{i}', V, F, UV, 'Vegetation', M['grass_clump'])
        coll('Vegetation').objects.unlink(ob); c.objects.link(ob)
    bpy.context.scene.collection.children.unlink(c)
    # density vertex group on the inner terrain: near the spillway, above water, not on concrete/riprap/walkway
    me = terrain_inner.data
    vg = terrain_inner.vertex_groups.new(name='grass')
    idx = []; wts = []
    for i, (e, n, z) in enumerate(Vi):
        lx, ly = W2L(e, n)
        if not (-140 < lx < 190 and -170 < ly < 190): continue
        if z < 477.4: continue
        if in_mask(CUT, e, n) or in_mask(W1, e, n): continue
        if math.hypot(lx, ly) < 41 and lx < 3: continue
        if BX0 - 4 < lx < BX1 + 4 and -27 < ly < 27: continue        # bridge / abutments
        if dist_to_drives(lx, ly) < 9.0: continue
        w = 1.0
        # thin out the mown lawn SW of the spillway and the stone walkway
        if ly < -24 and BX0 - 2 < lx < BX1 + 2 and ly > -40: w = 0.05
        if ly < -40 and lx < 60: w = 0.35
        d = max(abs(lx) / 190, abs(ly) / 190); w *= max(0.0, 1.0 - max(0.0, d - 0.6) / 0.4)
        if w > 0.02: idx.append(i); wts.append(w)
    for i, wgt in zip(idx, wts): vg.add([i], wgt, 'REPLACE')
    mod = terrain_inner.modifiers.new('Grass', 'PARTICLE_SYSTEM')
    ps = terrain_inner.particle_systems[-1]; ps.vertex_group_density = 'grass'
    st = ps.settings
    st.type = 'HAIR'; st.count = 42000; st.hair_length = 1.0; st.use_advanced_hair = True
    st.render_type = 'COLLECTION'; st.instance_collection = c; st.use_collection_pick_random = True
    st.particle_size = 0.55; st.size_random = 0.4
    st.use_rotations = True; st.rotation_mode = 'NOR'; st.phase_factor_random = 2.0; st.rotation_factor_random = 0.08
    st.use_rotation_instance = True
    st.emit_from = 'FACE'; st.distribution = 'RAND'; st.use_emit_random = True
    st.display_percentage = 2

# ----------------------------------------------------------------------------- world / lighting / cameras
PRESETS = {  # three.js world (x east, y up, z south) -> blender (x, -z, y)
    'bridge': ([-140, 500, 75], [-45, 478, -8]),
    'weir':   ([55, 489, 40], [-5, 476, -8]),
    'basin':  ([-120, 492, -75], [-60, 474, -10]),
    'outlet': ([-128, 481, -65], [-82, 473, -42]),
    'walk':   ([-60.5, 492, 71.9], [-14.2, 482, 6.6]),
    'dam1':   ([330, 545, -120], [40, 480, -330]),
    'dam2':   ([-880, 560, -150], [-480, 493, -62]),
    'aerial': ([-350, 1150, 950], [-100, 478, -100]),
    'weir_low': ([70, 480.5, 15], [-12, 476.5, -2]),
    'bridge_deck': ([-17.2, 487.5, 18.2], [-1.3, 481, -41.8]),
}
def t2b(p): return Vector((p[0], -p[2], p[1]))

def setup_world_and_render(sc, quality='final'):
    w = bpy.data.worlds.new('Sky'); sc.world = w; w.use_nodes = True
    nt = w.node_tree; nodes = nt.nodes
    for n in list(nodes): nodes.remove(n)
    out = nodes.new('ShaderNodeOutputWorld'); bg = nodes.new('ShaderNodeBackground'); sky = nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'MULTIPLE_SCATTERING'; sky.sun_elevation = math.radians(34); sky.sun_rotation = math.radians(205)
    sky.sun_size = math.radians(0.6); sky.sun_intensity = 1.0; sky.altitude = 150; sky.air_density = 1.0; sky.aerosol_density = 2.2; sky.ozone_density = 1.5
    sky.sun_disc = True
    bg.inputs['Strength'].default_value = 1.0
    nt.links.new(sky.outputs['Color'], bg.inputs['Color']); nt.links.new(bg.outputs['Background'], out.inputs['Surface'])
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'
    sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPENIMAGEDENOISE'; sc.cycles.denoising_prefilter = 'ACCURATE'; sc.cycles.denoising_use_gpu = False
    sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.02
    sc.cycles.max_bounces = 8; sc.cycles.diffuse_bounces = 3; sc.cycles.glossy_bounces = 3; sc.cycles.transparent_max_bounces = 48; sc.cycles.transmission_bounces = 4
    sc.cycles.caustics_reflective = False; sc.cycles.caustics_refractive = False; sc.cycles.sample_clamp_indirect = 8.0; sc.cycles.blur_glossy = 1.0
    sc.render.use_persistent_data = True
    sc.view_settings.view_transform = 'AgX'
    try: sc.view_settings.look = 'AgX - Medium High Contrast'
    except Exception: pass
    sc.view_settings.exposure = -3.4; sc.view_settings.gamma = 1.0
    sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_depth = '8'
    set_quality(sc, quality)

def set_quality(sc, quality):
    if quality == 'preview':
        sc.render.resolution_x = 960; sc.render.resolution_y = 540; sc.render.resolution_percentage = 100; sc.cycles.samples = 24
    elif quality == 'medium':
        sc.render.resolution_x = 1280; sc.render.resolution_y = 720; sc.render.resolution_percentage = 100; sc.cycles.samples = 64
    else:
        sc.render.resolution_x = 1920; sc.render.resolution_y = 1080; sc.render.resolution_percentage = 100; sc.cycles.samples = 96

def make_cameras(sc):
    cams = {}
    for name, (pos, tgt) in PRESETS.items():
        cd = bpy.data.cameras.new('Cam_' + name); cd.lens = 32 if name in ('aerial', 'dam1', 'dam2') else 28; cd.sensor_width = 36; cd.clip_end = 20000
        ob = bpy.data.objects.new('Cam_' + name, cd); coll('Cameras').objects.link(ob)
        p = t2b(pos); t = t2b(tgt)
        # keep above ground
        gz = terrain_h(p.x, p.y); p.z = max(p.z, gz + 5.5)
        ob.location = p
        ob.rotation_euler = (t - p).to_track_quat('-Z', 'Y').to_euler()
        cams[name] = ob
    return cams

# ----------------------------------------------------------------------------- build / render / export
def build():
    t0 = time.time()
    sc = clear_scene()
    M = make_materials()
    inner, Vi, Fi = build_terrain(M); print('terrain', round(time.time() - t0, 1))
    build_spillway(M); print('spillway', round(time.time() - t0, 1))
    build_dam2(M)
    build_trees(M); print('trees', round(time.time() - t0, 1))
    build_grass(M, inner, Vi, Fi); print('grass', round(time.time() - t0, 1))
    setup_world_and_render(sc, 'final')
    make_cameras(sc)
    sc.camera = bpy.data.objects['Cam_bridge']
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    print('saved', BLEND, 'objects', len(bpy.data.objects), round(time.time() - t0, 1), 's')

def render(quality, names, outdir=None):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc = bpy.context.scene; set_quality(sc, quality)
    outdir = outdir or os.path.join(OUT, 'renders_' + quality); os.makedirs(outdir, exist_ok=True)
    for name in names:
        sc.camera = bpy.data.objects['Cam_' + name]
        sc.render.filepath = os.path.join(outdir, name + '.png')
        t = time.time(); bpy.ops.render.render(write_still=True)
        print(f'{name}: {time.time() - t:.0f}s -> {sc.render.filepath}', flush=True)

# ----------------------------------------------------------------------------- 360 panoramas (local frame x, y, eye height above ground / deck)
PANOS = {
    'bridge':  {'local': (12.0, 0.0), 'z': 482.0 + 5.5, 'look': (-1.0, 0.0), 'title': 'On the bridge'},
    'walkway': {'local': (22.0, -40.0), 'z': None, 'look': (-0.3, 1.0), 'title': 'Stone walkway'},
    'shore':   {'local': (-48.0, -52.0), 'z': None, 'look': (0.7, 0.7), 'title': 'Lake shore at the weir'},
    'outlet':  {'local': (112.0, 44.0), 'z': 467.8 + 5.5, 'look': (-0.68, -0.73), 'title': 'Outlet channel'},
    'crest':   {'local': (11.0, 140.0), 'z': None, 'look': (0.0, -1.0), 'title': 'Dam No. 1 crest'},
    'dam2':    {'world': (-495.0, 71.0), 'z': 495.0 + 5.5, 'look_world': (1.0, 0.0), 'title': 'Dam No. 2 access drive'},
}
def pano_world(name):
    p = PANOS[name]
    if 'world' in p:
        e, n = p['world']; fe, fn = p['look_world']
    else:
        e, n, _ = L2W(*p['local']); fe, fn, _ = L2W(*p['look']); fe -= 0; fn -= 0
        fe, fn = fe - L2W(0, 0)[0], fn - L2W(0, 0)[1]
    z = p['z'] if p['z'] is not None else terrain_h(e, n) + 5.5
    l = math.hypot(fe, fn); return (e, n, z), (fe / l, fn / l)

def render_panos(names, width=3072, samples=64, outdir=None):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc = bpy.context.scene
    sc.render.resolution_x = width; sc.render.resolution_y = width // 2; sc.render.resolution_percentage = 100; sc.cycles.samples = samples
    outdir = outdir or os.path.join(OUT, 'panos'); os.makedirs(outdir, exist_ok=True)
    cd = bpy.data.cameras.new('PanoCam'); cd.type = 'PANO'; cd.panorama_type = 'EQUIRECTANGULAR'; cd.clip_end = 20000
    cam = bpy.data.objects.new('PanoCam', cd); sc.collection.objects.link(cam); sc.camera = cam
    mpath = os.path.join(outdir, 'panos.json')
    meta = json.load(open(mpath)) if os.path.exists(mpath) else {}
    for name in names:
        if os.path.exists(os.path.join(outdir, name + '.png')) and name in meta:
            print(f'pano {name}: exists, skipped', flush=True); continue
        (e, n, z), (fe, fn) = pano_world(name)
        cam.location = (e, n, z)
        cam.rotation_euler = (Vector((fe, fn, 0)).to_track_quat('-Z', 'Y')).to_euler()
        sc.render.filepath = os.path.join(outdir, name + '.png')
        t = time.time(); bpy.ops.render.render(write_still=True)
        meta[name] = {'pos': [e, n, z], 'forward': [fe, fn], 'title': PANOS[name]['title']}
        json.dump(meta, open(mpath, 'w'), indent=1)
        print(f'pano {name}: {time.time() - t:.0f}s', flush=True)

def export_glb(path, lite=False):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc = bpy.context.scene
    if lite:
        for n, ratio in (('TerrainInner', 0.22), ('TerrainOuter', 0.35)):
            ob = bpy.data.objects[n]; md = ob.modifiers.new('Decimate', 'DECIMATE'); md.ratio = ratio; md.use_collapse_triangulate = True
        for ob in list(bpy.data.objects):
            if ob.name.startswith('Pickets_'): bpy.data.objects.remove(ob)
        for im in bpy.data.images:
            if im.size[0] > 1024 or im.size[1] > 1024:
                im.scale(max(1, im.size[0] // 2), max(1, im.size[1] // 2))
    # simplify materials: image -> base color directly, keep normal map, drop procedural mixes
    for m in bpy.data.materials:
        if not m.use_nodes: continue
        nt = m.node_tree; bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None: continue
        alb = next((n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.name == 'ALBEDO'), None)
        if alb is not None:
            for l in list(bsdf.inputs['Base Color'].links): nt.links.remove(l)
            nt.links.new(alb.outputs['Color'], bsdf.inputs['Base Color'])
            if m.get('export_albedo', '').endswith('.png'):
                nt.links.new(alb.outputs['Alpha'], bsdf.inputs['Alpha']); m.blend_method = 'CLIP' if hasattr(m, 'blend_method') else None
            # drop mapping scale (UVs are already scaled) by relinking UV straight into the image
            tc = next((n for n in nt.nodes if n.type == 'TEX_COORD'), None)
            if tc is not None:
                for l in list(alb.inputs['Vector'].links): nt.links.remove(l)
                nt.links.new(tc.outputs['UV'], alb.inputs['Vector'])
        for l in list(bsdf.inputs['Roughness'].links): nt.links.remove(l)
        bsdf.inputs['Roughness'].default_value = float(m.get('export_rough', 0.8))
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if out is not None:
            for l in list(out.inputs['Surface'].links): nt.links.remove(l)
            nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
        nm = next((n for n in nt.nodes if n.type == 'NORMAL_MAP'), None)
        if nm is not None:
            tn = next((l.from_node for l in nm.inputs['Color'].links), None)
            if tn is not None and tc is not None:
                for l in list(tn.inputs['Vector'].links): nt.links.remove(l)
                nt.links.new(tc.outputs['UV'], tn.inputs['Vector'])
    # water: masked by alpha image -> export alpha
    for m in bpy.data.materials:
        if m.name.startswith('Water_'):
            nt = m.node_tree; bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'); mask = nt.nodes['MASK']
            nt.links.new(mask.outputs['Color'], bsdf.inputs['Alpha'])
    # remove far ground, cameras stay; particles are not exported
    for ob in list(bpy.data.objects):
        if ob.name == 'FarGround': bpy.data.objects.remove(ob)
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_apply=True, export_materials='EXPORT', export_image_format='AUTO',
                              export_jpeg_quality=80, export_normals=True, export_texcoords=True, export_cameras=True, export_lights=False,
                              export_yup=True, use_visible=True, export_extras=True)
    print('exported', path, os.path.getsize(path) / 1e6, 'MB')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', action='store_true'); ap.add_argument('--render', nargs='?', const='preview'); ap.add_argument('--export', nargs='?', const=os.path.join(ROOT, 'model', 'white_oak_lake_dams_blender.glb'))
    ap.add_argument('names', nargs='*'); ap.add_argument('--outdir'); ap.add_argument('--lite', action='store_true')
    ap.add_argument('--pano', action='store_true'); ap.add_argument('--width', type=int, default=3072); ap.add_argument('--samples', type=int, default=64)
    a = ap.parse_args()
    if a.build: build()
    if a.render: render(a.render, a.names or list(PRESETS.keys()), a.outdir)
    if a.pano: render_panos(a.names or list(PANOS.keys()), a.width, a.samples, a.outdir)
    if a.export: export_glb(a.export, a.lite)
