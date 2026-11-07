// White Oak Lake Dams (Knox County, Indiana) – IDNR Project E015001L
// Interactive viewer for the Blender-built scene (model/white_oak_lake_dams_blender.pack.glb).
// World: X = east, Y = elevation (NAVD88 ft), Z = south. Units: feet.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { Sky } from 'three/addons/objects/Sky.js';

const ASSET = window.ASSET_BASE || 'assets/';
const MODEL = window.MODEL_URL || '../model/white_oak_lake_dams_blender.pack.glb';
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
function setupSkyAndLights() {
  const sky = new Sky(); sky.scale.setScalar(20000); scene.add(sky);
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
  dir.target.position.set(-40, 478, -10); scene.add(dir.target); scene.add(dir);
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
      m.color.setRGB(0.07, 0.12, 0.08); m.roughness = 0.2; m.metalness = 0.0; m.envMapIntensity = 0.9;
      m.normalMap = waterN; m.normalScale = new THREE.Vector2(0.3, 0.3); m.clearcoat = 0.25; m.clearcoatRoughness = 0.15;
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

// ------------------------------------------------------------------ view presets (world coords)
const PRESETS = {
  bridge:   { pos: [-140, 500, 75],  tgt: [-45, 478, -8] },
  weir:     { pos: [55, 489, 40],    tgt: [-5, 476, -8] },
  basin:    { pos: [-120, 492, -75], tgt: [-60, 474, -10] },
  outlet:   { pos: [-128, 481, -65], tgt: [-82, 473, -42] },
  walk:     { pos: [-70, 497, 110],  tgt: [-50, 481, 0] },
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
    renderer.render(scene, camera);
    frames++; if (frames === 3) window.__ready = true;
    if (!SHOT || frames < 6) requestAnimationFrame(animate);
  }
  if (SHOT) await new Promise(r => setTimeout(r, 1500));
  animate();
}
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });
main().catch(e => { console.error(e); const s = document.getElementById('status'); if (s) s.textContent = 'Error: ' + e.message; });
