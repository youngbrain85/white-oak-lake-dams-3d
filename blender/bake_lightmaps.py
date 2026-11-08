#!/usr/bin/env python3
"""
Bake Cycles lighting (direct + indirect diffuse irradiance, no albedo) into lightmaps for the web viewer.

    python3 bake_lightmaps.py --prepare            # join the static structures, add 'lm' UVs, save out/white_oak_baked.blend
    python3 bake_lightmaps.py --bake terrain_inner # bake one group (resumable: skipped if its map exists)
    python3 bake_lightmaps.py --finish             # write model/lightmaps/*.jpg + lightmaps.json, export the baked GLBs

Lightmaps are stored sRGB-encoded 8-bit, normalised per map by `scale` (irradiance = decoded value * scale).
The viewer applies them with MeshBasicMaterial.lightMap on UV channel 1 (no double lighting from the raster sun).
"""
import os, sys, json, math, time, argparse
import numpy as np
from PIL import Image
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'out'); BLEND = os.path.join(OUT, 'white_oak.blend'); BAKED_BLEND = os.path.join(OUT, 'white_oak_baked.blend')
LM_OUT = os.path.join(OUT, 'lightmaps'); LM_PUB = os.path.join(ROOT, 'model', 'lightmaps')
os.makedirs(LM_OUT, exist_ok=True); os.makedirs(LM_PUB, exist_ok=True)

GROUPS = {
    # joined into one object each so a single atlas covers them
    'structures': {'join': 'StructuresBaked', 'names': ['WallLeft', 'WallLeftWing', 'WallRight', 'WallRightWing', 'Weir', 'Slab', 'BridgeDeck'],
                   'prefixes': ['Baffle_', 'EndSill_', 'Abutment_', 'Dam2ToeDrain_'], 'size': 2048, 'samples': 96},
    'surfaces':   {'join': 'SurfacesBaked', 'names': ['OutletChannel', 'WeirRiprap', 'Walkway', 'CrestApproach', 'CrestTrack', 'AccessDrive', 'LakeAccessDrive', 'Dam2Road'],
                   'prefixes': [], 'size': 2048, 'samples': 64},
    # terrain keeps its own planar layout
    'terrain_inner': {'names': ['TerrainInner'], 'prefixes': [], 'size': 2048, 'samples': 64, 'planar': True},
    'terrain_outer': {'names': ['TerrainOuter'], 'prefixes': [], 'size': 2048, 'samples': 32, 'planar': True},
}
EXPOSURE_EV = -3.4           # view exposure used for the Cycles renders (build_scene.setup_world_and_render)

def group_objects(g):
    out = []
    for n in g['names']:
        if n in bpy.data.objects: out.append(bpy.data.objects[n])
    for ob in bpy.data.objects:
        if any(ob.name.startswith(p) for p in g['prefixes']) and ob not in out: out.append(ob)
    return out

def select_only(objs):
    for o in bpy.context.view_layer.objects: o.select_set(False)
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]

def planar_lm_uv(ob, inset=0.004):
    me = ob.data
    if 'lm' in me.uv_layers: me.uv_layers.remove(me.uv_layers['lm'])
    lm = me.uv_layers.new(name='lm')
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    mn = co[:, :2].min(0); mx = co[:, :2].max(0); span = np.maximum(mx - mn, 1e-6)
    vi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get('vertex_index', vi)
    uv = (co[vi, :2] - mn) / span * (1 - 2 * inset) + inset
    lm.data.foreach_set('uv', uv.ravel())
    return {'bounds': [float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1])]}

def fix_normals(ob, closed):
    """Cycles bakes the front side of each face: walls built with inconsistent winding baked black.
    Closed solids get consistent outward normals; open surfaces are flipped to face up."""
    import bmesh
    bm = bmesh.new(); bm.from_mesh(ob.data)
    if closed:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        # recalc_face_normals orients each shell consistently but can pick 'inward' for a shell;
        # check each connected shell against its own centroid and flip if it points in
        seen = set()
        for f in bm.faces:
            if f.index in seen: continue
            stack = [f]; shell = []
            while stack:
                g = stack.pop()
                if g.index in seen: continue
                seen.add(g.index); shell.append(g)
                for e in g.edges:
                    for h in e.link_faces:
                        if h.index not in seen: stack.append(h)
            c = sum((g.calc_center_median() for g in shell), Vector()) / len(shell)
            score = sum(g.normal.dot(g.calc_center_median() - c) for g in shell)
            if score < 0: bmesh.ops.reverse_faces(bm, faces=shell)
    else:
        down = [f for f in bm.faces if f.normal.z < 0]
        if down: bmesh.ops.reverse_faces(bm, faces=down)
    bm.to_mesh(ob.data); bm.free(); ob.data.update()

def smart_lm_uv(ob):
    me = ob.data
    if 'lm' in me.uv_layers: me.uv_layers.remove(me.uv_layers['lm'])
    lm = me.uv_layers.new(name='lm'); me.uv_layers.active = lm
    select_only([ob])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.006, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    return {}

def prepare():
    if os.path.exists(BAKED_BLEND):
        print('prepared already:', BAKED_BLEND); return
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    # the two terrains share one material; give the outer its own copy so each can bake to its own image
    to = bpy.data.objects['TerrainOuter']; to.data.materials[0] = to.data.materials[0].copy(); to.data.materials[0].name = 'TerrainOuterMat'
    for key, g in GROUPS.items():
        objs = group_objects(g)
        print(key, 'objects:', len(objs))
        if g.get('join'):
            select_only(objs)
            with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
                bpy.ops.object.join()
            ob = objs[0]; ob.name = g['join']; ob.data.name = g['join']
            fix_normals(ob, closed=(key == 'structures'))
            smart_lm_uv(ob)
        else:
            for ob in objs: planar_lm_uv(ob)
    bpy.ops.wm.save_as_mainfile(filepath=BAKED_BLEND, compress=True)
    print('saved', BAKED_BLEND)

def bake(key):
    g = GROUPS[key]; size = g['size']
    exr = os.path.join(LM_OUT, key + '.exr')
    if os.path.exists(exr):
        print('exists, skipped:', exr); return
    bpy.ops.wm.open_mainfile(filepath=BAKED_BLEND)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = g['samples']; sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.03
    sc.cycles.max_bounces = 6; sc.cycles.diffuse_bounces = 3; sc.cycles.glossy_bounces = 2; sc.cycles.transparent_max_bounces = 32
    sc.render.bake.use_pass_direct = True; sc.render.bake.use_pass_indirect = True; sc.render.bake.use_pass_color = False
    sc.render.bake.margin = 8; sc.render.bake.target = 'IMAGE_TEXTURES'
    objs = [bpy.data.objects[g['join']]] if g.get('join') else group_objects(g)
    img = bpy.data.images.new('LM_' + key, size, size, float_buffer=True, alpha=True); img.colorspace_settings.name = 'Non-Color'
    img.generated_color = (0, 0, 0, 0)
    mats = set()
    for ob in objs:
        for slot in ob.material_slots:
            if slot.material: mats.add(slot.material)
    for m in mats:
        nt = m.node_tree; node = nt.nodes.new('ShaderNodeTexImage'); node.image = img; node.name = 'LM_TARGET'; nt.nodes.active = node
    select_only(objs)
    t = time.time()
    bpy.ops.object.bake(type='DIFFUSE', pass_filter={'DIRECT', 'INDIRECT'}, margin=8, use_clear=True, uv_layer='lm', target='IMAGE_TEXTURES')
    print(f'bake {key}: {time.time() - t:.0f}s', flush=True)
    img.filepath_raw = exr; img.file_format = 'OPEN_EXR'; img.save()
    # raw float copy for the finish step
    arr = np.array(img.pixels[:], dtype=np.float32).reshape(size, size, 4)
    np.save(os.path.join(LM_OUT, key + '.npy'), arr)
    print('saved', exr)

def finish():
    from scipy import ndimage
    meta = {'exposure_ev': EXPOSURE_EV, 'maps': {}}
    for key, g in GROUPS.items():
        npy = os.path.join(LM_OUT, key + '.npy')
        if not os.path.exists(npy): print('missing', key); continue
        arr = np.load(npy); rgb = arr[..., :3]; a = arr[..., 3]
        covered = a > 0.01
        # fireflies + a little smoothing (bakes have no denoiser)
        rgb = np.minimum(rgb, np.percentile(rgb[covered], 99.9) if covered.any() else rgb.max())
        for c in range(3):
            rgb[..., c] = ndimage.median_filter(rgb[..., c], size=3)
            rgb[..., c] = ndimage.gaussian_filter(rgb[..., c], 0.7)
        lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
        S = float(np.percentile(lum[covered], 99.0)) if covered.any() else float(lum.max())
        v = np.clip(rgb / S, 0, 1)
        srgb = np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)
        im = Image.fromarray((srgb * 255 + 0.5).astype(np.uint8)[::-1])     # Blender images are bottom-up
        im.save(os.path.join(LM_PUB, key + '.jpg'), quality=90, optimize=True, progressive=True)
        im.resize((g['size'] // 2, g['size'] // 2), Image.LANCZOS).save(os.path.join(LM_PUB, key + '_s.jpg'), quality=88, optimize=True)
        names = [g['join']] if g.get('join') else g['names']
        # viewer units: Blender irradiance * 2^EV / (toneMappingExposure 0.9 handled in viewer)
        meta['maps'][key] = {'file': key + '.jpg', 'file_small': key + '_s.jpg', 'scale': S, 'objects': names, 'sunlit_p99': S,
                             'mean_lum': float(lum[covered].mean()) if covered.any() else 0.0}
        print(f'{key}: scale {S:.2f}, mean {meta["maps"][key]["mean_lum"]:.2f}, covered {covered.mean():.2f}')
    json.dump(meta, open(os.path.join(LM_PUB, 'lightmaps.json'), 'w'), indent=1)
    # export GLBs from the baked blend. The glTF exporter only writes UV maps that a material references,
    # so give every baked material a (black, 4x4) emissive texture read through the 'lm' UV map: TEXCOORD_1 is
    # then exported for the baked meshes and the emissive contributes nothing.
    EXPORT_BLEND = os.path.join(OUT, 'white_oak_baked_export.blend')
    bpy.ops.wm.open_mainfile(filepath=BAKED_BLEND)
    surf = bpy.data.objects['SurfacesBaked']
    for i, slot in enumerate(surf.material_slots):            # Limestone is shared with the rocks (no 'lm' UVs there)
        if slot.material and slot.material.users > 1 and slot.material.name == 'Limestone':
            slot.material = slot.material.copy(); slot.material.name = 'LimestoneBaked'
    dummy = bpy.data.images.new('LM_DUMMY', 4, 4); dummy.generated_color = (0, 0, 0, 1); dummy.colorspace_settings.name = 'Non-Color'
    baked_mats = set()
    for key, g in GROUPS.items():
        for n in ([g['join']] if g.get('join') else g['names']):
            ob = bpy.data.objects.get(n)
            if ob is None: continue
            for slot in ob.material_slots:
                if slot.material: baked_mats.add(slot.material)
    for m in baked_mats:
        nt = m.node_tree; bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None: continue
        for n in [n for n in nt.nodes if n.name == 'LM_TARGET']: nt.nodes.remove(n)
        tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = dummy; tex.name = 'LM_UV_CARRIER'; tex.location = (200, 600)
        uvn = nt.nodes.new('ShaderNodeUVMap'); uvn.uv_map = 'lm'; uvn.location = (0, 600)
        nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
        for l in list(bsdf.inputs['Emission Color'].links): nt.links.remove(l)
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Emission Color']); bsdf.inputs['Emission Strength'].default_value = 1.0
    bpy.ops.wm.save_as_mainfile(filepath=EXPORT_BLEND, compress=True)
    sys.path.insert(0, HERE); import build_scene as B
    B.BLEND = EXPORT_BLEND
    B.export_glb(os.path.join(ROOT, 'model', 'white_oak_lake_dams_blender_baked.glb'))
    B.export_glb(os.path.join(ROOT, 'model', 'white_oak_lake_dams_blender_baked_lite.glb'), lite=True)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--prepare', action='store_true'); ap.add_argument('--bake'); ap.add_argument('--finish', action='store_true')
    a = ap.parse_args()
    if a.prepare: prepare()
    if a.bake: bake(a.bake)
    if a.finish: finish()
