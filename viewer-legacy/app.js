// White Oak Lake Dams (Knox County, Indiana) – Dam No.1 / No.2 Rehabilitation, IDNR Project E015001L
// 3D reconstruction from the September 2013 bid set (Commonwealth Engineers / KIVA Structural).
// Units: feet.  World: X = east, Y = elevation (NAVD88 ft), Z = south.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';

const ASSET = (window.ASSET_BASE || 'assets/');
const params = new URLSearchParams(location.search);
const SHOT = params.get('shot');           // headless screenshot mode (preset name)
const LOW = params.get('low') === '1';

// ------------------------------------------------------------------ renderer / scene
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: !!SHOT, powerPreference: 'high-performance' });
renderer.setPixelRatio(SHOT ? 1 : Math.min(devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xd7e3ee, 0.00055);

const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 1, 9000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.495;
controls.minDistance = 8; controls.maxDistance = 3000;

// ------------------------------------------------------------------ coordinate frames
// local spillway frame: x downstream (WNW), y up, z lateral toward right wall (NNE, along dam)
const U = new THREE.Vector3(-0.9666, 0, -0.2563);   // local +x in world
const V = new THREE.Vector3(0.2563, 0, -0.9666);    // local +z in world
const localGroup = new THREE.Group();
localGroup.matrix.makeBasis(U, new THREE.Vector3(0, 1, 0), V);
localGroup.matrixAutoUpdate = false;
scene.add(localGroup);
const L2W = (x, y, z) => new THREE.Vector3(x * U.x + z * V.x, y, x * U.z + z * V.z);

// ------------------------------------------------------------------ loaders
const texLoader = new THREE.TextureLoader();
function tex(name, { srgb = true, repeat = null, aniso = 8 } = {}) {
  const t = texLoader.load(ASSET + name);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  if (repeat) t.repeat.set(repeat[0], repeat[1]);
  t.anisotropy = aniso;
  return t;
}
async function loadImageData(name) {
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = ASSET + name; });
  const cv = document.createElement('canvas'); cv.width = img.width; cv.height = img.height;
  const ctx = cv.getContext('2d'); ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, img.width, img.height);
}

// ------------------------------------------------------------------ materials
const M = {};
function makeMaterials() {
  M.concrete = new THREE.MeshStandardMaterial({ map: tex('concrete.jpg', { repeat: [0.15, 0.15] }), normalMap: tex('concrete_n.jpg', { srgb: false, repeat: [0.15, 0.15] }), normalScale: new THREE.Vector2(0.5, 0.5), roughness: 0.86, metalness: 0.0, color: 0xd8d6d0 });
  M.concreteWet = M.concrete.clone(); M.concreteWet.color = new THREE.Color(0xb9b5ac); M.concreteWet.roughness = 0.7;
  M.riprap = new THREE.MeshStandardMaterial({ map: tex('riprap.jpg', { repeat: [0.15, 0.15] }), normalMap: tex('riprap_n.jpg', { srgb: false, repeat: [0.15, 0.15] }), normalScale: new THREE.Vector2(1.0, 1.0), aoMap: tex('riprap_ao.jpg', { srgb: false, repeat: [0.15, 0.15] }), roughness: 0.95, color: 0xcfcbc2 });
  M.gravel = new THREE.MeshStandardMaterial({ map: tex('gravel.jpg', { repeat: [0.25, 0.25] }), normalMap: tex('gravel_n.jpg', { srgb: false, repeat: [0.25, 0.25] }), roughness: 0.95, color: 0xcfc9bd });
  M.wood = new THREE.MeshStandardMaterial({ map: tex('wood.jpg'), normalMap: tex('wood_n.jpg', { srgb: false }), roughness: 0.8, color: 0xd3c3a8 });
  M.woodPost = new THREE.MeshStandardMaterial({ map: tex('wood.jpg', { repeat: [0.5, 2] }), roughness: 0.85, color: 0x9f8b6c });
  M.corten = new THREE.MeshStandardMaterial({ map: tex('corten.jpg', { repeat: [0.3, 0.3] }), roughness: 0.75, metalness: 0.35, color: 0xa86e46 });
  M.galv = new THREE.MeshStandardMaterial({ color: 0x8e969b, roughness: 0.5, metalness: 0.8 });
  M.galvDark = new THREE.MeshStandardMaterial({ color: 0x6f7579, roughness: 0.6, metalness: 0.8 });
  M.chain = new THREE.MeshStandardMaterial({ map: tex('chainlink.png', { repeat: [1, 1] }), transparent: true, alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.5, metalness: 0.7, color: 0x7d858b });
  M.grassLedge = new THREE.MeshStandardMaterial({ map: tex('grass_detail.jpg', { repeat: [0.2, 0.2] }), color: 0x8aa84a, roughness: 1.0 });
  M.asphalt = new THREE.MeshStandardMaterial({ map: tex('asphalt.jpg', { repeat: [0.1, 0.1] }), roughness: 0.95, color: 0x8a8a88 });
  M.mud = new THREE.MeshStandardMaterial({ color: 0x8a7a5c, roughness: 1.0 });
}

// ------------------------------------------------------------------ terrain
let HGT = null;   // {data: Uint16Array, size, spacing, hmin, hmax, extent}
function terrainH(e, n) {
  // bilinear sample of heightmap; e east, n north (ft) relative to spillway center
  const g = HGT; const half = g.extent / 2;
  const fx = (e + half) / g.spacing, fy = (half - n) / g.spacing;
  const x0 = Math.max(0, Math.min(g.size - 2, Math.floor(fx))), y0 = Math.max(0, Math.min(g.size - 2, Math.floor(fy)));
  const tx = Math.min(1, Math.max(0, fx - x0)), ty = Math.min(1, Math.max(0, fy - y0));
  const s = g.size, d = g.data, k = (g.hmax - g.hmin) / 65535;
  const h00 = d[y0 * s + x0], h10 = d[y0 * s + x0 + 1], h01 = d[(y0 + 1) * s + x0], h11 = d[(y0 + 1) * s + x0 + 1];
  const h = (h00 * (1 - tx) + h10 * tx) * (1 - ty) + (h01 * (1 - tx) + h11 * tx) * ty;
  return g.hmin + h * k;
}
function terrainHLocal(x, z) { const w = L2W(x, 0, z); return terrainH(w.x, -w.z); }

let CUT = null; // ImageData of cut mask (1px = 1ft, row0 = north)
function inCut(e, n, dil = 1) {
  if (!CUT) return false;
  const half = CUT.width / 2;
  for (let dy = -dil; dy <= dil; dy++) for (let dx = -dil; dx <= dil; dx++) {
    const px = Math.round(e + half) + dx, py = Math.round(half - n) + dy;
    if (px < 0 || py < 0 || px >= CUT.width || py >= CUT.height) continue;
    if (CUT.data[(py * CUT.width + px) * 4] > 127) return true;
  }
  return false;
}

function buildTerrainMesh(step, extentHalf, innerHalf, albedo, skipInside) {
  // grid over [-extentHalf, extentHalf]^2 (east, north) with given step; drop triangles in cut mask or inside inner square
  const n = Math.round(extentHalf * 2 / step) + 1;
  const pos = new Float32Array(n * n * 3), uv = new Float32Array(n * n * 2);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const e = -extentHalf + i * step, nn = extentHalf - j * step;
    const k = j * n + i;
    pos[k * 3] = e; pos[k * 3 + 1] = terrainH(e, nn); pos[k * 3 + 2] = -nn;
    uv[k * 2] = (e + 1200) / 2400; uv[k * 2 + 1] = (nn + 1200) / 2400;
  }
  const idx = [];
  const inside = (e, nn) => Math.abs(e) < innerHalf && Math.abs(nn) < innerHalf;
  for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
    const a = j * n + i, b = a + 1, c = a + n, d = c + 1;
    const tris = [[a, c, b], [b, c, d]];
    for (const t of tris) {
      let drop = false;
      for (const v of t) {
        const e = pos[v * 3], nn = -pos[v * 3 + 2];
        if (inCut(e, nn, 0)) { drop = true; break; }
      }
      if (!drop && skipInside) {
        let allIn = true;
        for (const v of t) { if (!inside(pos[v * 3], -pos[v * 3 + 2])) { allIn = false; break; } }
        if (allIn) drop = true;
      }
      if (!drop) idx.push(t[0], t[1], t[2]);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ map: albedo, roughness: 1.0, metalness: 0, normalMap: tex('grass_n.jpg', { srgb: false, repeat: [240, 240] }), normalScale: new THREE.Vector2(0.35, 0.35) });
  const detail = tex('grass_detail.jpg', { repeat: [1, 1] });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.detailMap = { value: detail };
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <map_pars_fragment>', '#include <map_pars_fragment>\nuniform sampler2D detailMap;')
      .replace('#include <map_fragment>', `#include <map_fragment>
        vec3 det = texture2D(detailMap, vMapUv * 300.0).rgb;
        vec3 det2 = texture2D(detailMap, vMapUv * 37.0).rgb;
        diffuseColor.rgb *= (det * 1.25 + 0.1) * (det2 * 0.9 + 0.35);`);
  };
  mat.customProgramCacheKey = () => 'terrain-detail';
  const mesh = new THREE.Mesh(g, mat);
  mesh.receiveShadow = true; mesh.castShadow = false;
  mesh.name = 'terrain';
  return mesh;
}

// ------------------------------------------------------------------ geometry helpers
function arcPts(cx, cz, r, a0, a1, n) {
  const out = [];
  for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; out.push([cx + r * Math.cos(a), cz + r * Math.sin(a)]); }
  return out;
}
// wall from polyline of inside-face points [{x,z,top}], thickness outward (sign: +1 => outward is +left-normal)
function buildWall(pts, thick, bottom, outwardSign, material, { ledge = 0, ledgeMat = null } = {}) {
  const inner = [], outer = [];
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    let tx = b.x - a.x, tz = b.z - a.z; const l = Math.hypot(tx, tz) || 1; tx /= l; tz /= l;
    // left normal of tangent in (x,z) plane: (-tz, tx)
    const nx = -tz * outwardSign, nz = tx * outwardSign;
    inner.push([p.x, p.z, p.top]); outer.push([p.x + nx * thick, p.z + nz * thick, p.top]);
  }
  const V = [], UVs = [];
  let s = 0;
  const quad = (p1, p2, p3, p4, u1, u2, v1, v2) => { // p1..p4 counter-clockwise
    V.push(...p1, ...p2, ...p3, ...p1, ...p3, ...p4);
    UVs.push(u1, v1, u2, v1, u2, v2, u1, v1, u2, v2, u1, v2);
  };
  for (let i = 0; i < pts.length - 1; i++) {
    const i0 = inner[i], i1 = inner[i + 1], o0 = outer[i], o1 = outer[i + 1];
    const seg = Math.hypot(i1[0] - i0[0], i1[1] - i0[1]);
    const u0 = s, u1 = s + seg; s += seg;
    // inner face (faces toward channel):
    quad([i0[0], bottom, i0[1]], [i1[0], bottom, i1[1]], [i1[0], i1[2], i1[1]], [i0[0], i0[2], i0[1]], u0, u1, 0, 1);
    // outer face
    quad([o1[0], bottom, o1[1]], [o0[0], bottom, o0[1]], [o0[0], o0[2], o0[1]], [o1[0], o1[2], o1[1]], u0, u1, 0, 1);
    // top
    quad([i0[0], i0[2], i0[1]], [i1[0], i1[2], i1[1]], [o1[0], o1[2], o1[1]], [o0[0], o0[2], o0[1]], u0, u1, 0, 0.1);
  }
  // end caps
  const capAt = (i, flip) => {
    const a = inner[i], b = outer[i];
    const p = [[a[0], bottom, a[1]], [b[0], bottom, b[1]], [b[0], b[2], b[1]], [a[0], a[2], a[1]]];
    if (flip) p.reverse();
    quad(p[0], p[1], p[2], p[3], 0, 0.1, 0, 1);
  };
  capAt(0, false); capAt(pts.length - 1, true);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(V, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(UVs, 2));
  g.computeVertexNormals();
  // fix winding so that normals face outward: compute by checking inner face normal vs direction to outside; simpler: DoubleSide
  const mesh = new THREE.Mesh(g, material);
  mesh.material = material.clone(); mesh.material.side = THREE.DoubleSide;
  mesh.castShadow = true; mesh.receiveShadow = true;
  const grp = new THREE.Group(); grp.add(mesh);
  if (ledge > 0) {
    const LV = [], LU = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const o0 = outer[i], o1 = outer[i + 1];
      const p = pts[i], q = pts[i + 1];
      const dx0 = (o0[0] - inner[i][0]) / thick, dz0 = (o0[1] - inner[i][1]) / thick;
      const dx1 = (o1[0] - inner[i + 1][0]) / thick, dz1 = (o1[1] - inner[i + 1][1]) / thick;
      const e0 = [o0[0] + dx0 * ledge, o0[1] + dz0 * ledge], e1 = [o1[0] + dx1 * ledge, o1[1] + dz1 * ledge];
      const h0 = Math.min(o0[2], terrainHLocal(e0[0], e0[1]) + 0.05), h1 = Math.min(o1[2], terrainHLocal(e1[0], e1[1]) + 0.05);
      LV.push(o0[0], o0[2] - 0.02, o0[1], o1[0], o1[2] - 0.02, o1[1], e1[0], h1, e1[1], o0[0], o0[2] - 0.02, o0[1], e1[0], h1, e1[1], e0[0], h0, e0[1]);
      for (let k = 0; k < 6; k++) LU.push(LV[LV.length - 18 + k * 3] * 0.2, LV[LV.length - 16 + k * 3] * 0.2);
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.Float32BufferAttribute(LV, 3));
    lg.setAttribute('uv', new THREE.Float32BufferAttribute(LU, 2));
    lg.computeVertexNormals();
    const lm = new THREE.Mesh(lg, ledgeMat); lm.material = ledgeMat.clone(); lm.material.side = THREE.DoubleSide; lm.receiveShadow = true;
    grp.add(lm);
  }
  return grp;
}

function box(w, h, d, mat, x, y, z, { ry = 0, cast = true } = {}) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z); m.rotation.y = ry; m.castShadow = cast; m.receiveShadow = true;
  return m;
}
function cyl(r, h, mat, x, y, z, seg = 10) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), mat);
  m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; return m;
}
function tubeBetween(a, b, r, mat, seg = 6) {
  const dir = new THREE.Vector3().subVectors(b, a); const len = dir.length();
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), mat);
  m.position.copy(a).add(b).multiplyScalar(0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
  m.castShadow = true; return m;
}

// ------------------------------------------------------------------ spillway (Dam No.1), local frame
function slabElev(x, z) {
  // station along left wall approx: straight part x; beyond bend use blend
  if (x < 0) return 473.46 + 0.54 * Math.min(1, -x / 20.5);
  const tbl = [[0, 473.46], [13, 473.12], [15, 472.81], [50, 472.0], [60, 472.0], [75, 471.25], [90, 470.85], [110, 470.0], [140, 469.0]];
  // progress: for bend region map (x,z) to along-left-wall distance roughly
  let s = x;
  if (x > 54.7) { // in bend: use distance along a 52deg arc centered (54.7,15) r=35.5 from angle -90deg
    const ang = Math.atan2(z - 15, x - 54.7); // -90deg at start
    const sweep = ang + Math.PI / 2;           // radians from start
    s = 54.7 + Math.max(0, sweep) * 35.5;
    const end = 54.7 + (52 * Math.PI / 180) * 35.5;
    if (s > end) { // beyond arc: project along direction 52deg from (82.7,-6.9)
      const dx = x - 82.7, dz = z + 6.9; s = end + dx * Math.cos(52 * Math.PI / 180) + dz * Math.sin(52 * Math.PI / 180);
    }
  }
  for (let i = 0; i < tbl.length - 1; i++) if (s >= tbl[i][0] && s <= tbl[i + 1][0]) {
    const t = (s - tbl[i][0]) / (tbl[i + 1][0] - tbl[i][0]); return tbl[i][1] + (tbl[i + 1][1] - tbl[i][1]) * t;
  }
  return s < 0 ? 473.46 : 469.0;
}

function buildSpillway() {
  const G = new THREE.Group(); G.name = 'spillway_dam1';
  const D = Math.PI / 180;
  // ---- left wall (z<0): inside face polyline
  const left = [];
  left.push({ x: 0, z: -20.5, top: 477 }, { x: 1, z: -20.5, top: 477 }, { x: 13, z: -20.5, top: 480 }, { x: 54.7, z: -20.5, top: 480 });
  const arcL = arcPts(54.7, 15, 35.5, -90 * D, -38 * D, 26);
  for (let i = 1; i < arcL.length; i++) {
    const f = i / (arcL.length - 1); const sArc = f * 52 * D * 35.5;
    const top = sArc < 25.7 ? 480 - 3 * (sArc / 25.7) : 477;
    left.push({ x: arcL[i][0], z: arcL[i][1], top });
  }
  left.push({ x: 88.1, z: 0.0, top: 477 }, { x: 96.9, z: 11.4, top: 476 });
  const leftWing = [{ x: 96.9, z: 11.4, top: 476 }, { x: 105.9, z: 4.2, top: 476 }];
  // ---- right wall (z>0)
  const right = [];
  right.push({ x: 0, z: 20.5, top: 477 }, { x: 1, z: 20.5, top: 477 }, { x: 13, z: 20.5, top: 480 }, { x: 58.7, z: 20.5, top: 480 });
  const arcR = arcPts(58.7, 52, 31.5, -90 * D, -49 * D, 22);
  for (let i = 1; i < arcR.length; i++) { const f = i / (arcR.length - 1); right.push({ x: arcR[i][0], z: arcR[i][1], top: 480 - 4 * f }); }
  const rightWing = [{ x: 80.3, z: 28.5, top: 476 }, { x: 72.4, z: 36.8, top: 476 }];
  // left wall: channel is on +z side => outward is -z side.  tangent along +x: left normal (-tz, tx) = (0,1)=+z, so outwardSign=-1
  G.add(buildWall(left, 1.0, 466, -1, M.concrete, { ledge: 3.5, ledgeMat: M.grassLedge }));
  G.add(buildWall(leftWing, 1.0, 466, -1, M.concrete, { ledge: 3.0, ledgeMat: M.grassLedge }));
  G.add(buildWall(right, 1.0, 466, +1, M.concrete, { ledge: 3.5, ledgeMat: M.grassLedge }));
  G.add(buildWall(rightWing, 1.0, 466, +1, M.concrete, { ledge: 3.0, ledgeMat: M.grassLedge }));
  // ---- weir (semicircle, inside face R=20.5, top 477, 1' thick)
  const weirArc = arcPts(0, 0, 20.5, 90 * D, 270 * D, 48).map(p => ({ x: p[0], z: p[1], top: 477 }));
  // tangent goes from (0,20.5) toward apex; left normal of tangent points to center => outward is -1
  G.add(buildWall(weirArc, 1.0, 470, -1, M.concrete));
  // weir crest rounded cap (visual): torus-like strip omitted; small chamfer bar
  // ---- slab: half-disk + ribbon
  {
    const V = [], UVs = [];
    const push = (p) => { V.push(p[0], p[1], p[2]); UVs.push(p[0] * 0.1, p[2] * 0.1); };
    const tri = (a, b, c) => { push(a); push(b); push(c); };
    // half disk fan (x<0)
    const rim = arcPts(0, 0, 21.0, 90 * D, 270 * D, 48);
    const ctr = [0, slabElev(0, 0), 0];
    for (let i = 0; i < rim.length - 1; i++) {
      const a = rim[i], b = rim[i + 1];
      tri(ctr, [b[0], slabElev(b[0], b[1]), b[1]], [a[0], slabElev(a[0], a[1]), a[1]]);
    }
    // ribbon between left and right inner polylines (parametrized by fraction of length)
    const polyLen = (P) => { let L = 0; for (let i = 1; i < P.length; i++) L += Math.hypot(P[i].x - P[i - 1].x, P[i].z - P[i - 1].z); return L; };
    const atFrac = (P, f) => {
      const L = polyLen(P); let t = f * L;
      for (let i = 1; i < P.length; i++) { const seg = Math.hypot(P[i].x - P[i - 1].x, P[i].z - P[i - 1].z); if (t <= seg || i === P.length - 1) { const u = Math.max(0, Math.min(1, t / seg)); return [P[i - 1].x + (P[i].x - P[i - 1].x) * u, P[i - 1].z + (P[i].z - P[i - 1].z) * u]; } t -= seg; }
      return [P[P.length - 1].x, P[P.length - 1].z];
    };
    const lp = left.map(p => ({ x: p.x, z: p.z + 0.5 })), rp = right.map(p => ({ x: p.x, z: p.z - 0.5 }));
    lp[0].x = -0.5; rp[0].x = -0.5;
    const N = 80; let prevL = null, prevR = null;
    for (let i = 0; i <= N; i++) {
      const f = i / N; const l = atFrac(lp, f), r = atFrac(rp, f);
      const L = [l[0], slabElev(l[0], l[1]), l[1]], R = [r[0], slabElev(r[0], r[1]), r[1]];
      if (prevL) { tri(prevL, prevR, R); tri(prevL, R, L); }
      prevL = L; prevR = R;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(V, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(UVs, 2));
    g.computeVertexNormals();
    const slab = new THREE.Mesh(g, M.concreteWet.clone()); slab.material.side = THREE.DoubleSide; slab.receiveShadow = true; slab.name = 'slab';
    G.add(slab);
    // shallow water film in the stilling basin (downstream of baffles) – puddles
    const wf = new THREE.Mesh(new THREE.PlaneGeometry(60, 30), new THREE.MeshStandardMaterial({ color: 0x4a4a3a, roughness: 0.08, metalness: 0.1, transparent: true, opacity: 0.55 }));
    wf.rotation.x = -Math.PI / 2; wf.position.set(80, slabElev(80, 10) + 0.08, 10); wf.rotation.z = 0.3; G.add(wf);
  }
  // ---- baffle blocks (3) upstream face at x=60
  {
    const shape = new THREE.Shape(); shape.moveTo(0, 0); shape.lineTo(2.8, 0); shape.lineTo(0.75, 3.75); shape.lineTo(0, 3.75); shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 5, bevelEnabled: false });
    for (const zc of [-11.3, 0, 11.3]) {
      const m = new THREE.Mesh(geo, M.concrete); m.position.set(60, slabElev(60, zc) - 0.02, zc - 2.5); m.castShadow = true; m.receiveShadow = true; G.add(m);
    }
  }
  // ---- end sill blocks (6) along outlet line
  {
    const a = new THREE.Vector2(96.9, 11.4), b = new THREE.Vector2(80.3, 28.5);
    const dir = b.clone().sub(a); const len = dir.length(); dir.normalize();
    const ang = Math.atan2(dir.y, dir.x);
    for (let i = 0; i < 6; i++) {
      const t = (i + 0.5) / 6 * len; const p = a.clone().add(dir.clone().multiplyScalar(t));
      const bx = box(2, 1.75, 2, M.concrete, p.x, 470 + 0.875, p.y, { ry: -ang });
      G.add(bx);
    }
  }
  // ---- cutoff wall is buried; bridge abutments (behind walls, 12' long, top 481.0)
  for (const sgn of [-1, 1]) {
    G.add(box(12, 6, 3, M.concrete, 52, 478.0, sgn * 23.0));
  }
  // ---- pedestrian truss bridge: 46' clear, 8' wide, deck 482.0, along z at x in [48,56]
  G.add(buildBridge());
  // ---- chain link fence on wall tops (from x>=58 to outlet)
  G.add(buildChainLink(left.filter(p => p.x >= 57.5).map(p => ({ ...p, z: p.z - 0.5 })).concat([{ x: 100.5, z: 8.5, top: 476 }, { x: 105.9, z: 4.2, top: 476 }]), -1));
  G.add(buildChainLink(right.filter(p => p.x >= 57.5).map(p => ({ ...p, z: p.z + 0.5 })).concat([{ x: 76.3, z: 32.6, top: 476 }, { x: 72.4, z: 36.8, top: 476 }]), +1));
  // ---- outlet riprap channel (24" class I riprap on broken concrete base)
  G.add(buildOutletChannel());
  // ---- riprap ring around the weir (below water line)
  G.add(buildWeirRiprap());
  // ---- stone walkway & wooden post/cable fences
  G.add(buildWalkway());
  G.add(buildPostCableFence([[47.0, -25.5], [47.0, -46.5]]));
  G.add(buildPostCableFence([[57.0, -25.5], [57.0, -46.5]]));
  G.add(buildPostCableFence([[58.5, 25.5], [58.5, 46.5]]));
  G.add(buildPostCableFence([[60.0, -25.0], [81.0, -25.0]]));
  // ---- 24" CMP temporary drain is removed at end of construction (not modelled)
  return G;
}

function buildBridge() {
  const B = new THREE.Group(); B.name = 'bridge';
  const x0 = 48, x1 = 56, zA = -23.5, zB = 23.5, deckY = 482.0, botChord = 481.6, topChord = 485.6;
  // deck: 2x6 planks across (x), laid along z
  const deck = new THREE.Mesh(new THREE.BoxGeometry(8.0, 0.14, zB - zA), M.wood.clone());
  deck.material.map = deck.material.map.clone(); deck.material.map.repeat.set(1, (zB - zA) / 2.9); deck.material.map.needsUpdate = true;
  deck.material.normalMap = deck.material.normalMap.clone(); deck.material.normalMap.repeat.set(1, (zB - zA) / 2.9); deck.material.normalMap.needsUpdate = true;
  deck.position.set((x0 + x1) / 2, deckY - 0.07, 0); deck.rotation.y = 0; deck.castShadow = true; deck.receiveShadow = true;
  // planks run across the bridge: rotate texture by making the box's long axis z, texture v repeats along z (planks across x)
  B.add(deck);
  // stringers / floor beams
  for (const x of [x0 + 0.6, (x0 + x1) / 2, x1 - 0.6]) B.add(box(0.3, 0.8, zB - zA, M.corten, x, deckY - 0.55, 0));
  // side trusses
  const panels = 8, pw = (zB - zA) / panels;
  for (const x of [x0 + 0.2, x1 - 0.2]) {
    B.add(box(0.33, 0.33, zB - zA + 1.0, M.corten, x, botChord, 0));
    B.add(box(0.33, 0.33, zB - zA + 1.0, M.corten, x, topChord, 0));
    for (let i = 0; i <= panels; i++) {
      const z = zA + i * pw;
      B.add(box(0.25, topChord - botChord, 0.25, M.corten, x, (topChord + botChord) / 2, z));
      if (i < panels) {
        const a = new THREE.Vector3(x, botChord, z), b = new THREE.Vector3(x, topChord, z + pw);
        if (i % 2 === 1) { a.z = z + pw; b.z = z; }
        B.add(tubeBetween(a, b, 0.1, M.corten));
      }
    }
    // safety pickets (vertical bars 4" o.c.) as instanced mesh
    const count = Math.floor((zB - zA) / 0.333);
    const pick = new THREE.InstancedMesh(new THREE.BoxGeometry(0.06, topChord - botChord - 0.4, 0.06), M.galvDark, count);
    const mtx = new THREE.Matrix4();
    for (let i = 0; i < count; i++) { mtx.makeTranslation(x, (topChord + botChord) / 2, zA + 0.2 + i * 0.333); pick.setMatrixAt(i, mtx); }
    pick.castShadow = true; pick.name = 'pickets'; B.add(pick);
    // handrail on top of top chord
    B.add(box(0.2, 0.15, zB - zA + 1.0, M.corten, x, topChord + 0.25, 0));
  }
  // cross frames under deck at abutments
  return B;
}

function buildChainLink(poly, side) {
  // poly: points along wall centerline with top elevations; 42" fabric, posts ~6 ft
  const F = new THREE.Group(); F.name = 'chainlink';
  const H = 3.5;
  // resample every ~6 ft
  const pts = [];
  let acc = 0;
  for (let i = 0; i < poly.length - 1; i++) {
    const a = poly[i], b = poly[i + 1]; const seg = Math.hypot(b.x - a.x, b.z - a.z);
    const n = Math.max(1, Math.round(seg / 6));
    for (let k = 0; k < n; k++) { const t = k / n; pts.push({ x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t, top: a.top + (b.top - a.top) * t }); }
  }
  pts.push(poly[poly.length - 1]);
  for (const p of pts) { const c = cyl(0.1, H + 0.1, M.galv, p.x, p.top + H / 2, p.z, 8); c.castShadow = true; F.add(c); }
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    F.add(tubeBetween(new THREE.Vector3(a.x, a.top + H, a.z), new THREE.Vector3(b.x, b.top + H, b.z), 0.07, M.galv));
    F.add(tubeBetween(new THREE.Vector3(a.x, a.top + 0.15, a.z), new THREE.Vector3(b.x, b.top + 0.15, b.z), 0.05, M.galv));
    // fabric panel
    const g = new THREE.BufferGeometry();
    const seg = Math.hypot(b.x - a.x, b.z - a.z);
    const P = [a.x, a.top + 0.1, a.z, b.x, b.top + 0.1, b.z, b.x, b.top + H, b.z, a.x, a.top + H, a.z];
    g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, seg * 1.5, 0, seg * 1.5, H * 1.5, 0, H * 1.5], 2));
    g.setIndex([0, 1, 2, 0, 2, 3]); g.computeVertexNormals();
    const m = new THREE.Mesh(g, M.chain); m.castShadow = false; F.add(m);
  }
  return F;
}

function buildOutletChannel() {
  // local frame: outlet center (88.6,19.95), direction 47deg; bed 470->466 over 54', half width 11.5->20, 2:1 sides
  const oc = new THREE.Vector2(88.6, 19.95); const ang = 47 * Math.PI / 180;
  const du = new THREE.Vector2(Math.cos(ang), Math.sin(ang)), dn = new THREE.Vector2(-du.y, du.x);
  const NU = 40, NV = 36, LEN = 62, WID = 42;
  const V = [], UVs = [], idx = [];
  const noiseAmp = 0.45;
  for (let j = 0; j <= NV; j++) for (let i = 0; i <= NU; i++) {
    const u = -1.5 + LEN * i / NU, v = -WID + 2 * WID * j / NV;
    const hw = 11.5 + Math.max(0, Math.min(u, 54)) * 0.16;
    const bed = 470 - Math.max(0, Math.min(u, 54)) * (4 / 54);
    const side = Math.max(0, Math.abs(v) - hw);
    let y = bed + side / 2;
    const px = oc.x + du.x * u + dn.x * v, pz = oc.y + du.y * u + dn.y * v;
    const th = terrainHLocal(px, pz);
    if (side > 0) y = Math.min(y, th);
    if (Math.abs(v) > hw + 17) y = th - 0.05;
    // riprap bumpiness
    const nz = Math.sin(px * 1.7) * Math.cos(pz * 2.3) + Math.sin(px * 3.1 + pz * 2.7) * 0.6;
    y += noiseAmp * 0.3 * nz * (side < 14 ? 1 : 0);
    V.push(px, y, pz); UVs.push(u * 0.25, v * 0.25);
  }
  for (let j = 0; j < NV; j++) for (let i = 0; i < NU; i++) {
    const a = j * (NU + 1) + i, b = a + 1, c = a + NU + 1, d = c + 1;
    idx.push(a, c, b, b, c, d);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(V, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(UVs, 2));
  g.setAttribute('uv1', new THREE.Float32BufferAttribute(UVs, 2));
  g.setIndex(idx); g.computeVertexNormals();
  const m = new THREE.Mesh(g, M.riprap.clone()); m.material.side = THREE.DoubleSide; m.receiveShadow = true; m.castShadow = true; m.name = 'outlet_riprap';
  // a few individual boulders for silhouette
  const G = new THREE.Group(); G.add(m);
  const rock = new THREE.IcosahedronGeometry(1, 1);
  const rockMat = M.riprap.clone(); rockMat.map = rockMat.map.clone(); rockMat.map.repeat.set(1.2, 1.2); rockMat.map.needsUpdate = true;
  let seed = 3;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  for (let k = 0; k < 160; k++) {
    const u = 2 + rnd() * 52, v = (rnd() - 0.5) * 2 * (11.5 + u * 0.16 + 6);
    const px = oc.x + du.x * u + dn.x * v, pz = oc.y + du.y * u + dn.y * v;
    const hw = 11.5 + u * 0.16; const side = Math.max(0, Math.abs(v) - hw);
    const y = 470 - u * (4 / 54) + side / 2;
    const r = new THREE.Mesh(rock, rockMat); const s = 0.45 + rnd() * 0.7;
    r.scale.set(s, s * (0.6 + rnd() * 0.4), s * (0.7 + rnd() * 0.6)); r.position.set(px, y + 0.2, pz); r.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3);
    r.castShadow = true; r.receiveShadow = true; G.add(r);
  }
  return G;
}

function buildWeirRiprap() {
  const D = Math.PI / 180;
  const NR = 10, NA = 56; const V = [], UVs = [], idx = [];
  for (let j = 0; j <= NR; j++) for (let i = 0; i <= NA; i++) {
    const r = 21.0 + (40.5 - 21.0) * j / NR; const a = (86 + 188 * i / NA) * D;
    const x = r * Math.cos(a), z = r * Math.sin(a);
    let y = 475.6 - (r - 21.0) * 0.5;
    const th = terrainHLocal(x, z); if (r > 36.0) y = th - 0.05;
    y += 0.25 * Math.sin(x * 2.1) * Math.cos(z * 1.7);
    V.push(x, y, z); UVs.push(x * 0.25, z * 0.25);
  }
  for (let j = 0; j < NR; j++) for (let i = 0; i < NA; i++) { const a = j * (NA + 1) + i, b = a + 1, c = a + NA + 1, d = c + 1; idx.push(a, b, c, b, d, c); }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(V, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(UVs, 2)); g.setAttribute('uv1', new THREE.Float32BufferAttribute(UVs, 2));
  g.setIndex(idx); g.computeVertexNormals();
  const m = new THREE.Mesh(g, M.riprap.clone()); m.material.side = THREE.DoubleSide; m.receiveShadow = true; m.name = 'weir_riprap';
  return m;
}

function buildWalkway() {
  // 8' wide stone path: from bridge SW end (x 48..56, z=-24.5) straight to z=-60, then R=40 curve toward -x ending near access drive
  const G = new THREE.Group(); G.name = 'stone_walkway';
  const center = []; // [x,z]
  for (let z = -24.5; z >= -60; z -= 2) center.push([52, z]);
  const cx = 52 - 40, cz = -60; // curve center (turn toward -x)
  for (let a = 0; a <= 90; a += 6) { const r = a * Math.PI / 180; center.push([cx + 40 * Math.cos(r), cz - 40 * Math.sin(r)]); }
  for (let k = 1; k <= 8; k++) center.push([12 - k * 3, -100]);
  const V = [], UVs = [], idx = []; let s = 0;
  for (let i = 0; i < center.length; i++) {
    const p = center[i], a = center[Math.max(0, i - 1)], b = center[Math.min(center.length - 1, i + 1)];
    let tx = b[0] - a[0], tz = b[1] - a[1]; const l = Math.hypot(tx, tz) || 1; tx /= l; tz /= l;
    const nx = -tz, nz = tx;
    if (i > 0) s += Math.hypot(p[0] - a[0], p[1] - a[1]);
    for (const w of [-4.5, 4.5]) {
      const x = p[0] + nx * w, z = p[1] + nz * w;
      let y = terrainHLocal(x, z) + 0.25;
      if (p[1] > -26) y = Math.max(y, 482.0);
      V.push(x, y, z); UVs.push(w * 0.25, s * 0.25);
    }
  }
  for (let i = 0; i < center.length - 1; i++) { const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(V, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(UVs, 2)); g.setIndex(idx); g.computeVertexNormals();
  const m = new THREE.Mesh(g, M.gravel.clone()); m.material.side = THREE.DoubleSide; m.receiveShadow = true; G.add(m);
  // 2x8 wooden handrail along the SW approach is on the fence lines; see post/cable fences
  return G;
}

function buildPostCableFence(line) {
  // 6x6 treated posts 7' o.c. with two steel cables (post & cable detail, sheet 15)
  const G = new THREE.Group(); G.name = 'post_cable_fence';
  const [a, b] = line; const len = Math.hypot(b[0] - a[0], b[1] - a[1]); const n = Math.max(1, Math.round(len / 7));
  const tops = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n; const x = a[0] + (b[0] - a[0]) * t, z = a[1] + (b[1] - a[1]) * t;
    let y = terrainHLocal(x, z); if (Math.abs(z) < 27 && x > 44 && x < 60) y = Math.max(y, 481.9);
    const post = box(0.5, 3.6, 0.5, M.woodPost, x, y + 1.8, z); G.add(post);
    tops.push(new THREE.Vector3(x, y, z));
  }
  for (let i = 0; i < tops.length - 1; i++) for (const h of [3.1, 1.7]) {
    const p = tops[i].clone(); p.y += h; const q = tops[i + 1].clone(); q.y += h;
    const mid = p.clone().add(q).multiplyScalar(0.5); mid.y -= 0.12; // sag
    G.add(tubeBetween(p, mid, 0.025, M.galvDark, 5)); G.add(tubeBetween(mid, q, 0.025, M.galvDark, 5));
  }
  return G;
}

// ------------------------------------------------------------------ Dam No.2 features (world frame)
function buildDam2() {
  const G = new THREE.Group(); G.name = 'dam2';
  const A = new THREE.Vector2(-690, 70), B = new THREE.Vector2(-300, 72);     // crest line (east, north)
  const d = B.clone().sub(A); const L = d.length(); d.normalize(); const nrm = new THREE.Vector2(-d.y, d.x);
  // asphalt lake access drive on crest (12' wide) – ribbon conforming to terrain, extended both ends
  const V = [], UVs = [], idx = [];
  const NU = 80;
  for (let i = 0; i <= NU; i++) {
    const t = -0.25 + 1.5 * i / NU; const e = A.x + d.x * L * t, n = A.y + d.y * L * t;
    for (const w of [-6, 6]) {
      const ee = e + nrm.x * w, nn = n + nrm.y * w;
      V.push(ee, terrainH(ee, nn) + 0.2, -nn); UVs.push(w * 0.1, t * L * 0.1);
    }
  }
  for (let i = 0; i < NU; i++) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(V, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(UVs, 2)); g.setIndex(idx); g.computeVertexNormals();
  const road = new THREE.Mesh(g, M.asphalt.clone()); road.material.side = THREE.DoubleSide; road.receiveShadow = true; G.add(road);
  // existing wood posts along the crest (lake side), ~25' o.c.
  for (let s = 10; s < L - 10; s += 25) {
    const e = A.x + d.x * s - nrm.x * 8, n = A.y + d.y * s - nrm.y * 8;
    const y = terrainH(e, n);
    const p = box(0.5, 3.0, 0.5, M.woodPost, e, y + 1.5, -n); G.add(p);
  }
  // principal spillway: 48" CMP riser with 4'x4' grate at sta 13+66 (266' from west end), ~25' into lake
  {
    const s = 266; const e = A.x + d.x * s - nrm.x * 26, n = A.y + d.y * s - nrm.y * 26;
    const riser = cyl(2.0, 16, M.galvDark, e, 490.31 - 8, -n, 20); G.add(riser);
    const grate = box(4.2, 0.25, 4.2, M.galvDark, e, 490.45, -n); G.add(grate);
    for (let k = -1.5; k <= 1.5; k += 0.5) G.add(box(4.2, 0.4, 0.08, M.galv, e, 490.6, -n + k));
  }
  // toe drain outlet structures (2) at downstream toe
  for (const s of [95, 310]) {
    const e = A.x + d.x * s + nrm.x * 66, n = A.y + d.y * s + nrm.y * 66; const y = terrainH(e, n);
    G.add(box(1.5, 1.2, 1.5, M.concrete, e, y + 0.4, -n));
  }
  return G;
}

// ------------------------------------------------------------------ water
function buildWater(level, maskName, color) {
  const geo = new THREE.PlaneGeometry(2400, 2400, 1, 1); geo.rotateX(-Math.PI / 2);
  const alpha = tex(maskName, { srgb: false }); alpha.wrapS = alpha.wrapT = THREE.ClampToEdgeWrapping;
  const normal = tex('water_n.jpg', { srgb: false, repeat: [60, 60] });
  const mat = new THREE.MeshPhysicalMaterial({ color, roughness: 0.3, metalness: 0.0, transparent: true, opacity: 0.97, alphaMap: alpha, alphaTest: 0.35, normalMap: normal, normalScale: new THREE.Vector2(0.25, 0.25), envMapIntensity: 1.0, clearcoat: 0.6, clearcoatRoughness: 0.1 });
  const m = new THREE.Mesh(geo, mat); m.position.y = level; m.receiveShadow = true; m.name = 'water_' + level;
  m.userData.normal = normal;
  return m;
}

// ------------------------------------------------------------------ vegetation
function buildTrees(list) {
  const G = new THREE.Group(); G.name = 'trees';
  const atlas = tex('leaves.png'); atlas.wrapS = atlas.wrapT = THREE.ClampToEdgeWrapping;
  const geo = (() => {
    const a = new THREE.PlaneGeometry(1, 1); a.translate(0, 0.5, 0);
    const b = a.clone(); b.rotateY(Math.PI / 2);
    const c = a.clone(); c.rotateY(Math.PI / 4); const d2 = a.clone(); d2.rotateY(-Math.PI / 4);
    return BufferGeometryUtils.mergeGeometries([a, b]);
  })();
  const byVar = [[], [], []];
  for (const t of list) byVar[t[4] % 3].push(t);
  byVar.forEach((arr, k) => {
    const map = atlas.clone(); map.repeat.set(1 / 3, 1); map.offset.set(k / 3, 0); map.needsUpdate = true;
    const mat = new THREE.MeshStandardMaterial({ map, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.9, color: 0xffffff });
    const im = new THREE.InstancedMesh(geo, mat, arr.length);
    const mtx = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3();
    arr.forEach((t, i) => {
      const h = t[3]; p.set(t[0], t[2] - 0.5, -t[1]); q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), t[5]); s.set(h * 0.95, h, h * 0.95);
      mtx.compose(p, q, s); im.setMatrixAt(i, mtx);
      const hv = ((t[0] * 12.9898 + t[1] * 78.233) % 1 + 1) % 1; const col = new THREE.Color().setHSL(0.25 + (hv - 0.5) * 0.06, 0.45 + hv * 0.25, 0.42 + ((t[3] - 28) / 27) * 0.1 + (hv - 0.5) * 0.12);
      im.setColorAt(i, col);
    });
    im.castShadow = true; im.receiveShadow = false;
    im.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map, alphaTest: 0.5, side: THREE.DoubleSide });
    im.name = 'trees_' + k; G.add(im);
  });
  return G;
}
function buildGrassTufts(list) {
  const map = tex('grass_tuft.png'); map.wrapS = map.wrapT = THREE.ClampToEdgeWrapping;
  const a = new THREE.PlaneGeometry(1, 1); a.translate(0, 0.5, 0); const b = a.clone(); b.rotateY(Math.PI / 2);
  const geo = BufferGeometryUtils.mergeGeometries([a, b]);
  const mat = new THREE.MeshStandardMaterial({ map, alphaTest: 0.45, side: THREE.DoubleSide, roughness: 1, color: 0x9fb07a });
  const per = 3; const im = new THREE.InstancedMesh(geo, mat, list.length * per);
  const mtx = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3();
  let seed = 11; const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  let i = 0;
  for (const t of list) for (let k = 0; k < per; k++) {
    const e = t[0] + (rnd() - 0.5) * 3, n = t[1] + (rnd() - 0.5) * 3; const w = 0.9 + rnd() * 0.8, h = 0.55 + rnd() * 0.6;
    p.set(e, terrainH(e, n) - 0.15, -n); q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rnd() * 6.28); s.set(w, h, w);
    mtx.compose(p, q, s); im.setMatrixAt(i++, mtx);
  }
  im.castShadow = false; im.name = 'grass_tufts';
  return im;
}

// ------------------------------------------------------------------ sky / lights
function setupSkyAndLights() {
  const sky = new Sky(); sky.scale.setScalar(20000); scene.add(sky);
  const sun = new THREE.Vector3();
  const elev = 38, az = 215;  // afternoon sun from SSW
  const phi = THREE.MathUtils.degToRad(90 - elev), theta = THREE.MathUtils.degToRad(az);
  sun.setFromSphericalCoords(1, phi, theta);
  sky.material.uniforms.sunPosition.value.copy(sun);
  sky.material.uniforms.turbidity.value = 4; sky.material.uniforms.rayleigh.value = 1.6;
  sky.material.uniforms.mieCoefficient.value = 0.004; sky.material.uniforms.mieDirectionalG.value = 0.85;
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(sky, 0.02).texture;
  scene.environmentIntensity = 0.55;

  const dir = new THREE.DirectionalLight(0xfff2dd, 2.6);
  dir.position.copy(sun).multiplyScalar(1500).add(new THREE.Vector3(0, 0, 0));
  dir.castShadow = true;
  dir.shadow.mapSize.set(LOW ? 2048 : 4096, LOW ? 2048 : 4096);
  const sc = dir.shadow.camera; sc.left = -260; sc.right = 260; sc.top = 260; sc.bottom = -260; sc.near = 600; sc.far = 2600;
  dir.shadow.bias = -0.0004; dir.shadow.normalBias = 0.6; dir.shadow.radius = 2;
  dir.target.position.set(-40, 478, -10); scene.add(dir.target);
  scene.add(dir);
  const hemi = new THREE.HemisphereLight(0xbfd4ee, 0x5a6a3a, 0.55); scene.add(hemi);
  return { dir, sun };
}

// ------------------------------------------------------------------ view presets (world coords)
const PRESETS = {
  bridge:   { pos: [-140, 500, 75],  tgt: [-45, 478, -8] },
  weir:     { pos: [55, 489, 40],    tgt: [-5, 476, -8] },
  basin:    { pos: [-120, 492, -75], tgt: [-60, 474, -10] },
  outlet:   { pos: [-128, 481, -65], tgt: [-82, 473, -42] },
  dam1:     { pos: [330, 545, -120], tgt: [40, 480, -330] },
  dam2:     { pos: [-880, 560, -150], tgt: [-480, 493, -62] },
  aerial:   { pos: [-350, 1150, 950], tgt: [-100, 478, -100] },
  walk:     { pos: [-70, 497, 110], tgt: [-50, 481, 0] },
  top:      { pos: [-60, 760, -5], tgt: [-60, 478, -6] },
};
function applyPreset(name) {
  const p = PRESETS[name] || PRESETS.bridge;
  camera.position.set(...p.pos); if (HGT) camera.position.y = Math.max(camera.position.y, terrainH(p.pos[0], -p.pos[2]) + 6.5); controls.target.set(...p.tgt); controls.update();
}

// ------------------------------------------------------------------ GLB export (bake instances)
async function exportGLB() {
  const exp = new GLTFExporter();
  const root = new THREE.Group();
  scene.traverse(o => { if (o.isMesh && !o.isInstancedMesh && o.name !== 'sky' && !(o.parent && o.parent.isSky)) {} });
  // collect: clone everything except Sky; convert instanced meshes to merged geometry
  const clone = scene.clone(true);
  const toReplace = [];
  clone.traverse(o => { if (o.isInstancedMesh) toReplace.push(o); });
  for (const im of toReplace) {
    const geos = []; const mtx = new THREE.Matrix4();
    for (let i = 0; i < im.count; i++) { im.getMatrixAt(i, mtx); const g = im.geometry.clone(); g.applyMatrix4(mtx); geos.push(g); }
    const merged = BufferGeometryUtils.mergeGeometries(geos); const mesh = new THREE.Mesh(merged, im.material); mesh.name = im.name;
    im.parent.add(mesh); im.parent.remove(im);
  }
  const skies = []; clone.traverse(o => { if (o.isSky || (o.material && o.material.uniforms && o.material.uniforms.sunPosition)) skies.push(o); });
  skies.forEach(s => s.parent.remove(s));
  const result = await new Promise((res, rej) => exp.parse(clone, res, rej, { binary: true, onlyVisible: true, maxTextureSize: 2048 }));
  const blob = new Blob([result], { type: 'model/gltf-binary' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'white_oak_lake_dam1_spillway.glb'; a.click();
  return blob.size;
}
window.exportGLB = exportGLB;

// ------------------------------------------------------------------ main
async function main() {
  const status = document.getElementById('status');
  const say = (t) => { if (status) status.textContent = t; };
  say('Loading terrain data…');
  makeMaterials();
  const hj = await (await fetch(ASSET + 'height.json')).json();
  const hid = await loadImageData('height.png');
  const hdata = new Uint16Array(hj.size * hj.size);
  for (let i = 0; i < hdata.length; i++) hdata[i] = (hid.data[i * 4] << 8) | hid.data[i * 4 + 1];
  HGT = { data: hdata, size: hj.size, spacing: hj.spacing, hmin: hj.hmin, hmax: hj.hmax, extent: hj.extent };
  CUT = await loadImageData('cutmask.png');
  const albedo = tex('albedo.jpg', { aniso: 16 }); albedo.wrapS = albedo.wrapT = THREE.ClampToEdgeWrapping;
  say('Building terrain…');
  const inner = buildTerrainMesh(2, 450, 0, albedo, false);
  const outer = buildTerrainMesh(6, 1200, 440, albedo, true);
  outer.material = inner.material; scene.add(inner, outer);
  say('Building structures…');
  localGroup.add(buildSpillway());
  scene.add(buildDam2());
  const w1 = buildWater(476.6, 'water1.png', 0x3a5a30); const w2 = buildWater(490.4, 'water2.png', 0x33402f);
  scene.add(w1, w2);
  say('Placing vegetation…');
  const trees = await (await fetch(ASSET + 'trees.json')).json();
  const tufts = await (await fetch(ASSET + 'tufts.json')).json();
  const treeGrp = buildTrees(LOW ? trees.filter((_, i) => i % 2 === 0) : trees); scene.add(treeGrp);
  const tuftMesh = buildGrassTufts(tufts); scene.add(tuftMesh);
  const { dir } = setupSkyAndLights();
  // far ground skirt
  const skirt = new THREE.Mesh(new THREE.PlaneGeometry(12000, 12000), new THREE.MeshStandardMaterial({ color: 0x6b7a4a, roughness: 1 }));
  skirt.rotation.x = -Math.PI / 2; skirt.position.y = 468; scene.add(skirt);

  // UI wiring
  document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => applyPreset(b.dataset.view)));
  const tg = (id, obj) => { const el = document.getElementById(id); if (el) el.addEventListener('change', () => { obj.visible = el.checked; }); };
  tg('tgTrees', treeGrp); tg('tgGrass', tuftMesh); tg('tgWater', w1);
  const exBtn = document.getElementById('btnExport'); if (exBtn) exBtn.addEventListener('click', async () => { exBtn.textContent = 'Exporting…'; const n = await exportGLB(); exBtn.textContent = 'GLB exported (' + (n / 1e6).toFixed(1) + ' MB)'; });
  const photos = document.getElementById('photos'); if (photos) photos.addEventListener('click', () => photos.classList.toggle('open'));

  if (params.get('dbg') === '1') { skirt.visible = false; w1.visible = false; w2.visible = false; treeGrp.visible = false; tuftMesh.visible = false; }
  console.log('H@C', terrainH(0, 0).toFixed(2), 'H@walkcam', terrainH(-75, -120).toFixed(2), 'H@outletcam', terrainH(-205, -25).toFixed(2), 'H@SWhill', terrainH(-100, -100).toFixed(2), 'inner tris', inner.geometry.index.count / 3, 'outer tris', outer.geometry.index.count / 3);
  applyPreset(SHOT || 'bridge');
  say('');
  const loader = document.getElementById('loader'); if (loader) loader.style.display = 'none';

  const clock = new THREE.Clock();
  let frames = 0;
  function animate() {
    const t = clock.getElapsedTime();
    w1.userData.normal.offset.set(t * 0.004, t * 0.002); w2.userData.normal.offset.set(t * 0.003, -t * 0.002);
    controls.update();
    { const gy = terrainH(camera.position.x, -camera.position.z) + 3.0; if (camera.position.y < gy) camera.position.y = gy; }
    renderer.render(scene, camera);
    frames++;
    if (frames === 3) window.__ready = true;
    if (!SHOT || frames < 6) requestAnimationFrame(animate);
  }
  // wait for textures to finish loading before first frames in shot mode
  if (SHOT) { await new Promise(r => setTimeout(r, 2500)); }
  animate();
}
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });
main().catch(e => { console.error(e); const s = document.getElementById('status'); if (s) s.textContent = 'Error: ' + e.message; });
