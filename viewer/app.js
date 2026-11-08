// White Oak Lake Dams (Knox County, Indiana) – IDNR Project E015001L
// Interactive viewer for the Blender-built scene (model/white_oak_lake_dams_blender.pack.glb).
// World: X = east, Y = elevation (NAVD88 ft), Z = south. Units: feet.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { Sky } from 'three/addons/objects/Sky.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';
import { WebGLPathTracer } from 'three-gpu-pathtracer';

const ASSET = window.ASSET_BASE || 'assets/';
const MODEL = window.MODEL_URL || '../model/white_oak_lake_dams_blender.pack.glb';
const TREES_LITE = window.TREES_LITE_URL || '../model/trees_lite.glb';
const params = new URLSearchParams(location.search);
const SHOT = params.get('shot');

// ------------------------------------------------------------------ renderer / scene
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: !!SHOT, powerPreference: 'high-performance' });
renderer.setPixelRatio(SHOT ? 1 : Math.min(devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.AgXToneMapping;
renderer.toneMappingExposure = 0.9;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xd7e3ee, 0.00045);
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.5, 12000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.495; controls.minDistance = 4; controls.maxDistance = 3500;

// ------------------------------------------------------------------ heightmap (camera ground clamp)
let HGT = null;
async function loadHeight() {
  const hj = await (await fetch(ASSET + 'height.json')).json();
  const im = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = ASSET + 'height.png'; });
  const cv = document.createElement('canvas'); cv.width = im.width; cv.height = im.height;
  const ctx = cv.getContext('2d'); ctx.drawImage(im, 0, 0);
  const d = ctx.getImageData(0, 0, im.width, im.height).data;
  const data = new Uint16Array(hj.size * hj.size);
  for (let i = 0; i < data.length; i++) data[i] = (d[i * 4] << 8) | d[i * 4 + 1];
  HGT = { data, ...hj };
}
function terrainH(e, n) {
  if (!HGT) return 470;
  const g = HGT, half = g.extent / 2;
  const fx = (e + half) / g.spacing, fy = (half - n) / g.spacing;
  const x0 = Math.max(0, Math.min(g.size - 2, Math.floor(fx))), y0 = Math.max(0, Math.min(g.size - 2, Math.floor(fy)));
  const tx = Math.min(1, Math.max(0, fx - x0)), ty = Math.min(1, Math.max(0, fy - y0));
  const s = g.size, dd = g.data, k = (g.hmax - g.hmin) / 65535;
  const h = (dd[y0 * s + x0] * (1 - tx) + dd[y0 * s + x0 + 1] * tx) * (1 - ty) + (dd[(y0 + 1) * s + x0] * (1 - tx) + dd[(y0 + 1) * s + x0 + 1] * tx) * ty;
  return g.hmin + h * k;
}

// ------------------------------------------------------------------ sky / lights
let SKY = null, SUN = null;
function setupSkyAndLights() {
  const sky = new Sky(); sky.scale.setScalar(20000); scene.add(sky); SKY = sky;
  const sun = new THREE.Vector3();
  const elev = 34, az = 205;
  sun.setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - elev), THREE.MathUtils.degToRad(az));
  const u = sky.material.uniforms;
  u.sunPosition.value.copy(sun); u.turbidity.value = 4; u.rayleigh.value = 1.5; u.mieCoefficient.value = 0.004; u.mieDirectionalG.value = 0.85;
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(sky, 0.02).texture;
  scene.environmentIntensity = 0.45;
  const dir = new THREE.DirectionalLight(0xfff1dc, 2.3);
  dir.position.copy(sun).multiplyScalar(1500);
  dir.castShadow = true; dir.shadow.mapSize.set(4096, 4096);
  const sc = dir.shadow.camera; sc.left = -320; sc.right = 320; sc.top = 320; sc.bottom = -320; sc.near = 500; sc.far = 2800;
  dir.shadow.bias = -0.0003; dir.shadow.normalBias = 0.5; dir.shadow.radius = 2;
  dir.target.position.set(-40, 478, -10); scene.add(dir.target); scene.add(dir); SUN = dir;
  scene.add(new THREE.HemisphereLight(0xbfd4ee, 0x546436, 0.3));
}

// ------------------------------------------------------------------ model
const texLoader = new THREE.TextureLoader();
function instanceSharedMeshes(root) {
  // group meshes by geometry+material; anything shared by >= 6 nodes becomes an InstancedMesh
  const groups = new Map();
  root.updateMatrixWorld(true);
  root.traverse(o => {
    if (!o.isMesh) return;
    const key = o.geometry.uuid + '|' + o.material.uuid;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(o);
  });
  const out = new THREE.Group(); out.name = 'instanced';
  let instanced = 0;
  for (const [key, list] of groups) {
    if (list.length < 6) continue;
    const proto = list[0];
    const im = new THREE.InstancedMesh(proto.geometry, proto.material, list.length);
    for (let i = 0; i < list.length; i++) im.setMatrixAt(i, list[i].matrixWorld);
    im.castShadow = true; im.receiveShadow = true; im.frustumCulled = false;
    im.name = proto.name.replace(/[._]\d+$/, '') + '_instanced';
    if (proto.material.alphaTest > 0) im.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: proto.material.map, alphaTest: proto.material.alphaTest, side: THREE.DoubleSide });
    im.computeBoundingSphere();
    out.add(im); instanced += list.length;
    for (const o of list) o.removeFromParent();
  }
  // remove now-empty tree/rock nodes
  const empties = [];
  root.traverse(o => { if (!o.isMesh && o !== root && o.children.length === 0 && !o.isLight && !o.isCamera) empties.push(o); });
  for (const e of empties) e.removeFromParent();
  root.add(out);
  return instanced;
}

function tuneMaterials(root) {
  const waterN = texLoader.load(ASSET + 'water_n.jpg'); waterN.wrapS = waterN.wrapT = THREE.RepeatWrapping; waterN.repeat.set(70, 70);
  const seen = new Set();
  root.traverse(o => {
    if (!o.isMesh) return;
    const m = o.material; if (!m || seen.has(m.uuid)) { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } return; }
    seen.add(m.uuid);
    const n = m.name || '';
    if (n.startsWith('Leaves')) { m.transparent = false; m.alphaTest = 0.5; m.side = THREE.DoubleSide; m.depthWrite = true; m.roughness = 0.7; m.color.setRGB(1.05, 1.05, 1.0); }
    else if (n === 'ChainLink') { m.transparent = false; m.alphaTest = 0.4; m.side = THREE.DoubleSide; m.metalness = 0.8; m.roughness = 0.45; }
    else if (n.startsWith('Water')) {
      m.transparent = false; m.alphaTest = 0.5; m.depthWrite = true;
      m.color.setRGB(0.07, 0.12, 0.08); m.roughness = 0.42; m.metalness = 0.0; m.envMapIntensity = 0.7;
      m.normalMap = waterN; m.normalScale = new THREE.Vector2(0.35, 0.35); m.clearcoat = 0.0; m.specularIntensity = 0.6;
      m.userData.water = true;
    }
    else if (n === 'Terrain') { m.roughness = 1.0; m.envMapIntensity = 0.25; m.color.setRGB(0.78, 0.82, 0.72); }
    else if (n === 'Bark') { m.roughness = 0.95; }
    else if (n.startsWith('Concrete')) { m.roughness = 0.82; m.envMapIntensity = 0.35; m.color.setRGB(0.78, 0.77, 0.75); }
    else if (n === 'Limestone') { m.roughness = 0.92; m.envMapIntensity = 0.3; m.color.setRGB(0.8, 0.75, 0.66); }
    m.needsUpdate = true;
    o.castShadow = true; o.receiveShadow = true;
  });
}

async function loadModel(say) {
  const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
  let gltf;
  if (window.MODEL_B64) {
    // artifact build: model shipped as base64 inside a script file
    const bin = atob(window.MODEL_B64); const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    gltf = await new Promise((res, rej) => loader.parse(buf.buffer, '', res, rej));
  } else {
    gltf = await new Promise((res, rej) => loader.load(MODEL, res, xhr => { if (xhr.total) say(`Loading model… ${(xhr.loaded / 1e6).toFixed(1)} / ${(xhr.total / 1e6).toFixed(1)} MB`); }, rej));
  }
  const root = gltf.scene;
  // cameras exported from Blender are not needed
  root.traverse(o => { if (o.isCamera) o.visible = false; });
  tuneMaterials(root);
  const n = instanceSharedMeshes(root);
  root.traverse(o => { if (o.isMesh && o.name.startsWith('Lake')) o.castShadow = false; });
  scene.add(root);
  return { root, instanced: n };
}

// ------------------------------------------------------------------ in-browser path tracing (three-gpu-pathtracer)
// Builds a second, flattened copy of the scene (near trees in full, far trees as low-poly variants, rocks merged)
// and renders it progressively with physically based path tracing on the viewer's GPU: the same materials,
// sun and sky as the Cycles renders, converging over a few seconds while the camera is still.
const PT = { tracer: null, scene: null, on: false, building: false, samples: 0, quality: 'fast', scale: 0.6, liteGltf: null, lastKey: '' };
const PT_QUALITY = { fast: { near: 200, far: 900 }, full: { near: 320, far: 1e9 } };

function mergeTransformed(geo, matrices, mat, name) {
  if (!matrices.length) return null;
  const parts = [];
  for (const m of matrices) { const g = geo.clone(); g.applyMatrix4(m); for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k); parts.push(g); }
  const merged = BufferGeometryUtils.mergeGeometries(parts, false); parts.forEach(g => g.dispose());
  const mesh = new THREE.Mesh(merged, mat); mesh.name = name; return mesh;
}
function ptMaterial(src) {
  // the path tracer needs Standard/Physical materials; keep textures, drop raster-only tweaks
  const m = src.isMeshPhysicalMaterial ? src.clone() : new THREE.MeshPhysicalMaterial({ map: src.map, normalMap: src.normalMap, normalScale: src.normalScale, color: src.color, roughness: src.roughness, metalness: src.metalness, side: src.side, alphaTest: src.alphaTest, transparent: false });
  m.envMapIntensity = 1; m.name = src.name;
  if (src.userData.water) { m.color.setRGB(0.05, 0.085, 0.055); m.roughness = 0.08; m.ior = 1.33; m.clearcoat = 0; m.normalMap = src.normalMap; m.normalScale = new THREE.Vector2(0.15, 0.15); }
  if (/^Leaves/.test(src.name)) { m.roughness = 0.6; m.color.setRGB(1, 1, 1); m.transmission = 0; }
  if (src.name === 'Terrain') { m.color.setRGB(0.86, 0.9, 0.8); }
  return m;
}
async function buildPathTraceScene(say) {
  const q = PT_QUALITY[PT.quality]; const key = PT.quality;
  if (PT.scene && PT.lastKey === key) return PT.scene;
  if (PT.scene) { PT.scene.traverse(o => { if (o.isMesh && o.geometry && o.userData.ptOwned) o.geometry.dispose(); }); PT.scene = null; }
  say('Path tracer: preparing scene…');
  const ps = new THREE.Scene();
  const matCache = new Map(); const pm = m => { if (!matCache.has(m.uuid)) matCache.set(m.uuid, ptMaterial(m)); return matCache.get(m.uuid); };
  // plain meshes (terrain, structures, water)
  scene.traverse(o => { if (o.isMesh && !o.isInstancedMesh && o.visible && o.material && o.material.name && o.parent && o.parent.name !== 'instanced' && !o.material.uniforms) { const c = new THREE.Mesh(o.geometry, pm(o.material)); o.updateWorldMatrix(true, false); c.applyMatrix4(o.matrixWorld); c.name = o.name; ps.add(c); } });
  // instanced groups: rocks merged as-is, trees split by distance
  if (!PT.liteGltf) { const gl = new GLTFLoader(); PT.liteGltf = await new Promise((res, rej) => gl.load(TREES_LITE, res, undefined, rej)); }
  const lite = {}; PT.liteGltf.scene.traverse(o => { if (o.isMesh) lite[o.name] = o; });
  const mtx = new THREE.Matrix4(); const pos = new THREE.Vector3();
  let tris = 0;
  scene.traverse(o => {
    if (!o.isInstancedMesh || !o.visible) return;
    const name = o.name; const near = [], far = [];
    for (let i = 0; i < o.count; i++) { o.getMatrixAt(i, mtx); pos.setFromMatrixPosition(mtx); const d = Math.hypot(pos.x, pos.z); if (/^Tree/.test(name)) { if (d <= q.near) near.push(mtx.clone()); else if (d <= q.far) far.push(mtx.clone()); } else near.push(mtx.clone()); }
    const m1 = mergeTransformed(o.geometry, near, pm(o.material), name + '_near'); if (m1) { m1.userData.ptOwned = true; ps.add(m1); tris += m1.geometry.index ? m1.geometry.index.count / 3 : m1.geometry.attributes.position.count / 3; }
    const mm = name.match(/^Tree(Leaves|Wood)(\d)/);
    if (mm && far.length) { const src = lite['TreeLite' + mm[1] + mm[2]]; if (src) { const m2 = mergeTransformed(src.geometry, far, pm(o.material), name + '_far'); if (m2) { m2.userData.ptOwned = true; ps.add(m2); tris += m2.geometry.index ? m2.geometry.index.count / 3 : m2.geometry.attributes.position.count / 3; } } }
  });
  // sun + sky: render the Sky dome into a cube map so the tracer can importance-sample it
  if (SUN) { const l = new THREE.DirectionalLight(SUN.color, 2.0); l.position.copy(SUN.position); l.target.position.copy(SUN.target.position); ps.add(l); ps.add(l.target); }
  const crt = new THREE.WebGLCubeRenderTarget(512, { type: THREE.HalfFloatType });
  const cc = new THREE.CubeCamera(1, 50000, crt); const skyScene = new THREE.Scene(); skyScene.add(SKY.clone()); cc.update(renderer, skyScene);
  ps.environment = crt.texture; ps.environmentIntensity = 0.9; ps.background = crt.texture;
  ps.userData.tris = tris; PT.scene = ps; PT.lastKey = key;
  return ps;
}
async function enablePathTracing(on, say) {
  if (!on) { PT.on = false; say(''); return; }
  if (PT.building) return;
  try {
    PT.building = true;
    if (!PT.tracer) { PT.tracer = new WebGLPathTracer(renderer); PT.tracer.bounces = 4; PT.tracer.minSamples = 1; PT.tracer.dynamicLowRes = true; PT.tracer.lowResScale = 0.2; PT.tracer.tiles.set(2, 2); PT.tracer.textureSize.set(1024, 1024); PT.tracer.renderToCanvas = true; }
    PT.tracer.renderScale = PT.scale;
    const ps = await buildPathTraceScene(say);
    say(`Path tracer: building BVH for ${(ps.userData.tris / 1e6).toFixed(2)} M triangles…`);
    await new Promise(r => setTimeout(r, 50));   // let the message paint; the build itself is synchronous (no cross-origin workers on a static host)
    PT.tracer.setScene(ps, camera);
    PT.on = true; PT.samples = 0; say('');
  } catch (e) { console.error(e); say('Path tracing unavailable: ' + e.message); PT.on = false; const cb = document.getElementById('tgPT'); if (cb) cb.checked = false; }
  finally { PT.building = false; }
}
window.__PT = PT;

// ------------------------------------------------------------------ view presets (world coords)
const PRESETS = {
  bridge:   { pos: [-140, 500, 75],  tgt: [-45, 478, -8] },
  weir:     { pos: [55, 489, 40],    tgt: [-5, 476, -8] },
  basin:    { pos: [-120, 492, -75], tgt: [-60, 474, -10] },
  outlet:   { pos: [-128, 481, -65], tgt: [-82, 473, -42] },
  walk:     { pos: [-60.5, 492, 71.9], tgt: [-14.2, 482, 6.6] },
  dam1:     { pos: [330, 545, -120], tgt: [40, 480, -330] },
  dam2:     { pos: [-880, 560, -150], tgt: [-480, 493, -62] },
  aerial:   { pos: [-350, 1150, 950], tgt: [-100, 478, -100] },
};
function applyPreset(name) {
  const p = PRESETS[name] || PRESETS.bridge;
  camera.position.set(...p.pos);
  camera.position.y = Math.max(camera.position.y, terrainH(p.pos[0], -p.pos[2]) + 5.5);
  controls.target.set(...p.tgt); controls.update();
}

// ------------------------------------------------------------------ main
async function main() {
  const status = document.getElementById('status');
  const say = t => { if (status) status.textContent = t; };
  say('Loading terrain data…');
  await loadHeight();
  setupSkyAndLights();
  say('Loading model…');
  const { instanced } = await loadModel(say);
  console.log('instanced meshes', instanced);
  document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => applyPreset(b.dataset.view)));
  const tg = (id, pred) => { const el = document.getElementById(id); if (!el) return; el.addEventListener('change', () => scene.traverse(o => { if (pred(o)) o.visible = el.checked; })); };
  tg('tgTrees', o => /^Tree(Leaves|Wood)/.test(o.name));
  tg('tgRocks', o => /^(W?Rock)/.test(o.name));
  tg('tgWater', o => /^Lake/.test(o.name));
  const photos = document.getElementById('photos'); if (photos) photos.addEventListener('click', () => photos.classList.toggle('open'));
  const ptCb = document.getElementById('tgPT'), ptQ = document.getElementById('ptQuality'), ptS = document.getElementById('ptScale'), ptInfo = document.getElementById('ptInfo');
  const ptSay = t => { if (ptInfo) ptInfo.textContent = t; };
  if (ptCb) ptCb.addEventListener('change', () => enablePathTracing(ptCb.checked, ptSay));
  if (ptQ) ptQ.addEventListener('change', () => { PT.quality = ptQ.value; if (PT.on || ptCb.checked) { PT.on = false; enablePathTracing(true, ptSay); } });
  if (ptS) ptS.addEventListener('change', () => { PT.scale = parseFloat(ptS.value); if (PT.tracer) { PT.tracer.renderScale = PT.scale; PT.tracer.reset(); } });
  controls.addEventListener('change', () => { if (PT.on && PT.tracer) { PT.tracer.updateCamera(); PT.samples = 0; } });
  if (params.get('pt') === '1') { PT.quality = params.get('ptq') || 'fast'; PT.scale = parseFloat(params.get('pts') || '0.5'); if (ptCb) ptCb.checked = true; enablePathTracing(true, ptSay); }
  applyPreset(SHOT || 'bridge');
  window.__scene = scene; window.__camera = camera; window.__THREE = THREE; window.__renderOnce = () => renderer.render(scene, camera);
  say('');
  const loader = document.getElementById('loader'); if (loader) loader.style.display = 'none';
  const clock = new THREE.Clock(); let frames = 0;
  const waters = []; scene.traverse(o => { if (o.isMesh && o.material && o.material.userData.water) waters.push(o.material); });
  function animate() {
    const t = clock.getElapsedTime();
    for (const w of waters) if (w.normalMap) w.normalMap.offset.set(t * 0.004, t * 0.002);
    controls.update();
    const gy = terrainH(camera.position.x, -camera.position.z) + 2.5; if (camera.position.y < gy) camera.position.y = gy;
    if (PT.on && PT.tracer) { PT.tracer.renderSample(); PT.samples = PT.tracer.samples; if (ptInfo && (frames % 10 === 0)) ptInfo.textContent = `Path tracing · ${Math.floor(PT.samples)} samples · ${(PT.scene.userData.tris / 1e6).toFixed(2)} M tris`; }
    else renderer.render(scene, camera);
    frames++; if (frames === 3) window.__ready = true;
    if (PT.on && PT.samples >= (parseInt(params.get('ptn') || '0') || 1e9)) window.__ptDone = true;
    if (!SHOT || frames < 6 || (PT.on || PT.building) && !window.__ptDone) requestAnimationFrame(animate);
  }
  if (SHOT) await new Promise(r => setTimeout(r, 1500));
  animate();
}
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });
main().catch(e => { console.error(e); const s = document.getElementById('status'); if (s) s.textContent = 'Error: ' + e.message; });
