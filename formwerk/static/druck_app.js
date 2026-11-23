// Formwerk · Druckvorbereitung fürs Handy
import * as THREE from 'three';
import { OrbitControls } from '/vendor/OrbitControls.js';
import { gestalten } from '/js/druck_gestalten.js';

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const zahl = (v, d = 0) => Number(v).toLocaleString('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ICH = [1, 0, 0, 0, 1, 0, 0, 0, 1];

// ───────── Drucker (eigene) ─────────
const DRUCKER = [
  { id: 'h2c', name: 'Bambu Lab H2C', x: 325, y: 320, z: 325, multi: true, wechsel: 20, abfall: 0.4, fluss: 15, slicer: 'Bambu Studio' },
  { id: 'h2s', name: 'Bambu Lab H2S', x: 340, y: 320, z: 340, multi: true, wechsel: 50, abfall: 1.2, fluss: 15, slicer: 'Bambu Studio' },
  { id: 'x1c', name: 'Bambu Lab X1 Carbon', x: 256, y: 256, z: 256, multi: true, wechsel: 60, abfall: 1.3, fluss: 13, slicer: 'Bambu Studio' },
  { id: 'a1', name: 'Bambu Lab A1', x: 256, y: 256, z: 256, multi: true, wechsel: 55, abfall: 1.2, fluss: 10, slicer: 'Bambu Studio' },
  { id: 'a1m', name: 'Bambu Lab A1 mini', x: 180, y: 180, z: 180, multi: true, wechsel: 55, abfall: 1.0, fluss: 9, slicer: 'Bambu Studio' },
  { id: 'u1', name: 'Snapmaker U1', x: 270, y: 270, z: 270, multi: true, wechsel: 8, abfall: 0.1, fluss: 12, slicer: 'Snapmaker Orca' },
  { id: 'k2p', name: 'Creality K2 Plus', x: 350, y: 350, z: 350, multi: true, wechsel: 60, abfall: 1.3, fluss: 14, slicer: 'Creality Print oder OrcaSlicer' },
];
const MATERIAL = { PLA: 1.24, PETG: 1.27, 'PLA-CF': 1.3, ABS: 1.04, ASA: 1.07, TPU: 1.21 };
const QUAL = { fein: [0.12, 'Fein'], standard: [0.2, 'Standard'], schnell: [0.28, 'Schnell'] };
const STD_FARBEN = ['#F08A24', '#1D9E75', '#7F4FD8', '#F2F2F2', '#1A1A1A', '#D93838', '#2E7DD7', '#F4C430'];

// ───────── Zustand ─────────
const gespeichert = (() => { try { return JSON.parse(localStorage.getItem('fw_druck') || '{}'); } catch { return {}; } })();
const S = Object.assign({
  druckerId: 'h2c', eigen: { name: 'Eigener Drucker', x: 220, y: 220, z: 250, multi: false },
  filamente: STD_FARBEN.slice(0, 4).map(f => ({ farbe: f })),
  einst: { qual: 'standard', material: 'PLA', fuellung: 15, stuetzen: 'auto', rand: 'auto' },
  format: '3mf', abstand: 8, farbModus: 'ein', einSlot: 1, thema: '',
}, gespeichert, { sid: '', schritt: 1, auswahl: null, platte: 0, nachFarbe: false, farbwechsel: [] });
const speichern = () => {
  const { druckerId, eigen, filamente, einst, format, abstand, farbModus, einSlot, thema } = S;
  try { localStorage.setItem('fw_druck', JSON.stringify({ druckerId, eigen, filamente, einst, format, abstand, farbModus, einSlot, thema })); } catch { }
};
const drucker = () => S.druckerId === 'eigen' ? { id: 'eigen', wechsel: 0, abfall: 0, fluss: 10, slicer: 'deinem Slicer', ...S.eigen } : (DRUCKER.find(d => d.id === S.druckerId) || DRUCKER[0]);
const M = {};      // Modelle: id → { info, teile:[{pos, paint, mal, ext, geo, …}], quelle }
let T = [];        // Teile auf dem Bett
let uidZ = 1;
let plan = { platten: [], zuGross: new Set() };

// ───────── Hilfen ─────────
const toastEl = $('#toast'); let toastT;
function toast(t, ms = 2600) { toastEl.textContent = t; toastEl.classList.add('an'); clearTimeout(toastT); toastT = setTimeout(() => toastEl.classList.remove('an'), ms); }
function warte(an, text = 'Lade …') { $('#warte').classList.toggle('an', an); $('#warteText').textContent = text; }
function rmul(a, b) { const r = []; for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) r.push(a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j]); return r; }
const RZ = g => { const c = Math.cos(g * Math.PI / 180), s = Math.sin(g * Math.PI / 180); return [c, -s, 0, s, c, 0, 0, 0, 1].map(v => Math.abs(v) < 1e-12 ? 0 : v); };
const RX = g => { const c = Math.cos(g * Math.PI / 180), s = Math.sin(g * Math.PI / 180); return [1, 0, 0, 0, c, -s, 0, s, c].map(v => Math.abs(v) < 1e-12 ? 0 : v); };
const RY = g => { const c = Math.cos(g * Math.PI / 180), s = Math.sin(g * Math.PI / 180); return [c, 0, s, 0, 1, 0, -s, 0, c].map(v => Math.abs(v) < 1e-12 ? 0 : v); };
const rkey = r => r.map(v => v.toFixed(4)).join(',');
const farbeVon = slot => (S.filamente[slot - 1] || S.filamente[0] || { farbe: '#888' }).farbe;
const teilVon = uid => T.find(t => t.uid === uid);
const schicht = () => QUAL[S.einst.qual][0];

// ───────── Geometrie & Kennzahlen je Lage ─────────
function bbox(mid, r) {
  const m = M[mid], k = rkey(r);
  if (m.bb.has(k)) return m.bb.get(k);
  const mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  for (const t of m.teile) {
    const p = t.pos, step = p.length > 3e6 ? 9 : 3;
    for (let i = 0; i < p.length; i += step) {
      const x = p[i], y = p[i + 1], z = p[i + 2];
      const q = [r[0] * x + r[1] * y + r[2] * z, r[3] * x + r[4] * y + r[5] * z, r[6] * x + r[7] * y + r[8] * z];
      for (let j = 0; j < 3; j++) { if (q[j] < mn[j]) mn[j] = q[j]; if (q[j] > mx[j]) mx[j] = q[j]; }
    }
  }
  const b = { mn, mx, g: [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]] };
  m.bb.set(k, b);
  return b;
}
function flaechen(m) {
  if (m.fl) return m.fl;
  let n = 0; for (const t of m.teile) n += t.pos.length / 9;
  const A = new Float32Array(n), N = new Float32Array(n * 3), C = new Float32Array(n * 3);
  let i = 0;
  for (const t of m.teile) {
    const p = t.pos;
    for (let o = 0; o < p.length; o += 9, i++) {
      const ux = p[o + 3] - p[o], uy = p[o + 4] - p[o + 1], uz = p[o + 5] - p[o + 2];
      const vx = p[o + 6] - p[o], vy = p[o + 7] - p[o + 1], vz = p[o + 8] - p[o + 2];
      let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx; const l = Math.hypot(nx, ny, nz) || 1;
      A[i] = l / 2; N[i * 3] = nx / l; N[i * 3 + 1] = ny / l; N[i * 3 + 2] = nz / l;
      C[i * 3] = (p[o] + p[o + 3] + p[o + 6]) / 3; C[i * 3 + 1] = (p[o + 1] + p[o + 4] + p[o + 7]) / 3; C[i * 3 + 2] = (p[o + 2] + p[o + 5] + p[o + 8]) / 3;
    }
  }
  return (m.fl = { A, N, C });
}
// Höhe, Überhang (mm²), Stützvolumen (mm³), Auflage (mm²) bei Maßstab 1
function lageStat(mid, r) {
  const m = M[mid], k = rkey(r);
  if (m.ls.has(k)) return m.ls.get(k);
  const { A, N, C } = flaechen(m), b = bbox(mid, r), z0 = b.mn[2];
  let st = 0, sv = 0, ko = 0;
  // Höhen von Oberseiten: was dort flach aufliegt (Schrift auf Schild, Wand auf Boden), ist kein Überhang
  const oben = new Set();
  for (let i = 0; i < A.length; i++) if (r[6] * N[i * 3] + r[7] * N[i * 3 + 1] + r[8] * N[i * 3 + 2] > 0.995) oben.add(Math.round((r[6] * C[i * 3] + r[7] * C[i * 3 + 1] + r[8] * C[i * 3 + 2] - z0) * 20));
  for (let i = 0; i < A.length; i++) {
    const nz = r[6] * N[i * 3] + r[7] * N[i * 3 + 1] + r[8] * N[i * 3 + 2];
    if (nz > -0.7071) continue;
    const h = r[6] * C[i * 3] + r[7] * C[i * 3 + 1] + r[8] * C[i * 3 + 2] - z0;
    if (nz < -0.995 && oben.has(Math.round(h * 20))) continue;
    if (nz < -0.995 && h < 0.15) ko += A[i];
    else if (h > 0.6) { st += A[i] * -nz; sv += A[i] * -nz * h; }
  }
  const s = { h: b.g[2], st, sv, ko, kosten: st / 100 * 1.2 + b.g[2] * 0.15 - Math.sqrt(ko) * 0.03 };
  m.ls.set(k, s);
  return s;
}
const masse = t => bbox(t.mid, t.r).g.map(v => v * t.s);

// ───────── Druckzeit & Material ─────────
function stueck(t, mitStuetzen) {
  const i = M[t.mid].info, s = t.s, ls = lageStat(t.mid, t.r);
  const V = i.volumen * s ** 3, Af = i.flaeche * s * s;
  const schale = Math.min(V, Af * 0.9);
  const f = S.einst.fuellung / 100;
  let vol = schale + Math.max(0, V - schale) * Math.max(f, 0.02);
  if (mitStuetzen) vol += ls.sv * s ** 3 * 0.12;
  return { vol, h: ls.h * s, st: ls.st * s * s, ko: ls.ko * s * s };
}
function brauchtStuetzen(t) { const x = stueck(t, false); return x.st / 100 > 1.5; }
function stuetzenFuer(t) { return S.einst.stuetzen === 'an' || (S.einst.stuetzen === 'auto' && brauchtStuetzen(t)); }
function brauchtRand(t) { const x = stueck(t, false), g = masse(t); return x.h > 12 && (x.ko < 80 || x.h / Math.max(1, Math.min(g[0], g[1])) > 3); }
function randFuer(t) { return S.einst.rand === 'an' || (S.einst.rand === 'auto' && brauchtRand(t)); }
function minutenFuer(vol, h, dr) {
  const q = { fein: 0.6, standard: 1, schnell: 1.3 }[S.einst.qual];
  const fl = dr.fluss * q * (S.einst.material === 'TPU' ? 0.35 : S.einst.material === 'PETG' ? 0.8 : 1);
  return vol / fl / 60 + (h / schicht()) * 3.5 / 60;
}
function schaetzung() {
  const dr = drucker(), dichte = MATERIAL[S.einst.material] || 1.24;
  let vol = 0, min = 0, wechselMin = 0, abfall = 0;
  for (const p of plan.platten) {
    let pvol = 0, ph = 0;
    for (const it of p.items) { const t = teilVon(it.uid); const x = stueck(t, stuetzenFuer(t)); pvol += x.vol; ph = Math.max(ph, x.h); }
    vol += pvol;
    min += minutenFuer(pvol, ph, dr) + 5;
    const fw = farbSchichten(p);
    wechselMin += fw.wechsel * dr.wechsel / 60;
    abfall += fw.wechsel * dr.abfall;
  }
  const gramm = vol / 1000 * dichte;
  return { min: min + wechselMin, gramm, meter: vol / (Math.PI * 0.875 ** 2) / 1000, abfall, wechselMin };
}
function dauer(min) { min = Math.max(1, Math.round(min)); const h = Math.floor(min / 60); return h ? `${h} h ${String(min % 60).padStart(2, '0')} min` : `${min} min`; }

// ───────── Farben ─────────
function exportExt(t) { return S.farbModus === 'ein' ? S.einSlot : t.ext; }
function farbenVon(t) {
  const e = exportExt(t), set = new Set();
  if (e > 0) { set.add(e); return set; }
  for (const p of M[t.mid].teile) {
    set.add(p.ext);
    for (let i = 0; i < p.paint.length; i++) { const v = p.mal[i] !== 255 ? p.mal[i] : p.paint[i]; if (v) set.add(v); }
  }
  return set;
}
function mehrfarbig() { const s = new Set(); for (const t of T) for (const f of farbenVon(t)) s.add(f); return s.size > 1 || S.farbwechsel.length > 0; }
function faerben(mid) {
  const m = M[mid];
  for (const p of m.teile) {
    const n = p.pos.length / 9, col = p.geo.attributes.color.array;
    for (let i = 0; i < n; i++) {
      const st = p.mal[i] !== 255 ? p.mal[i] : p.paint[i];
      const c = new THREE.Color(farbeVon(st || p.ext));
      for (let k = 0; k < 3; k++) { col[i * 9 + k * 3] = c.r; col[i * 9 + k * 3 + 1] = c.g; col[i * 9 + k * 3 + 2] = c.b; }
    }
    p.geo.attributes.color.needsUpdate = true;
  }
}
// Schichten, in denen mehrere Farben liegen (je Platte)
function farbSchichten(p) {
  const iv = {};
  for (const it of p.items) {
    const t = teilVon(it.uid), h = masse(t)[2];
    for (const f of farbenVon(t)) (iv[f] = iv[f] || []).push(h);
  }
  const farben = Object.keys(iv);
  let hoehe = 0;
  if (farben.length > 1) {
    const hs = farben.map(f => Math.max(...iv[f])).sort((a, b) => b - a);
    hoehe = hs[1]; // bis zur zweithöchsten Farbe liegen mindestens zwei Farben
  }
  const sch = Math.round(hoehe / schicht());
  const ext = S.farbwechsel.length;
  return { schichten: sch, hoehe, wechsel: sch * Math.max(0, farben.length - 1) + ext, farben: farben.length };
}

// ───────── Anordnen ─────────
function packen() {
  const dr = drucker(), RAND = 3, Z = 2, gap = S.abstand;
  const W = dr.x, D = dr.y, cols = Math.floor((W - 2 * RAND) / Z), rows = Math.floor((D - 2 * RAND) / Z);
  const turm = mehrfarbig() ? { x0: cols - Math.ceil(42 / Z), y0: rows - Math.ceil(42 / Z) } : null;
  const zuGross = new Set();
  const items = [];
  for (const t of T) {
    const g = masse(t);
    const w = Math.ceil((g[0] + gap) / Z), d = Math.ceil((g[1] + gap) / Z);
    const gross = g[0] > W - 2 * RAND + 0.01 || g[1] > D - 2 * RAND + 0.01 || g[2] > dr.z + 0.01;
    if (gross) zuGross.add(t.uid);
    const gruppe = S.nachFarbe ? [...farbenVon(t)].sort().join('-') : '';
    for (let k = 0; k < t.n; k++) items.push({ uid: t.uid, k, w, d, g, gross, gruppe });
  }
  const gruppen = [...new Set(items.map(i => i.gruppe))];
  const platten = [];
  for (const gr of gruppen) {
    const liste = items.filter(i => i.gruppe === gr).sort((a, b) => b.w * b.d - a.w * a.d || a.uid - b.uid || a.k - b.k);
    const offen = [];
    for (const it of liste) {
      if (it.gross || it.w > cols || it.d > rows) { platten.push(neuePlatte(cols, rows, turm, [{ ...it, x: W / 2, y: D / 2 }])); continue; }
      let ok = false;
      for (const p of offen) if (setzen(p, it)) { ok = true; break; }
      if (!ok) { const p = neuePlatte(cols, rows, turm, []); offen.push(p); platten.push(p); if (!setzen(p, it)) p.items.push({ ...it, x: W / 2, y: D / 2 }); }
    }
  }
  for (const p of platten) mitte(p, W, D, RAND, Z, turm, gap);
  plan = { platten: platten.map(p => ({ items: p.items })), zuGross };
  if (S.platte >= plan.platten.length) S.platte = 0;
}
function neuePlatte(cols, rows, turm, items) {
  const belegt = new Uint8Array(cols * rows);
  if (turm) for (let y = turm.y0; y < rows; y++) for (let x = Math.max(0, turm.x0); x < cols; x++) belegt[y * cols + x] = 1;
  return { cols, rows, belegt, items };
}
function setzen(p, it) {
  const { cols, rows, belegt } = p;
  // Summenfeld für schnelle Prüfung
  const S2 = new Int32Array((cols + 1) * (rows + 1));
  for (let y = 0; y < rows; y++) { let z = 0; for (let x = 0; x < cols; x++) { z += belegt[y * cols + x]; S2[(y + 1) * (cols + 1) + x + 1] = S2[y * (cols + 1) + x + 1] + z; } }
  const frei = (x, y, w, d) => S2[(y + d) * (cols + 1) + x + w] - S2[y * (cols + 1) + x + w] - S2[(y + d) * (cols + 1) + x] + S2[y * (cols + 1) + x] === 0;
  for (let y = 0; y + it.d <= rows; y++) for (let x = 0; x + it.w <= cols; x++) {
    if (!frei(x, y, it.w, it.d)) continue;
    for (let yy = y; yy < y + it.d; yy++) for (let xx = x; xx < x + it.w; xx++) belegt[yy * cols + xx] = 1;
    p.items.push({ ...it, gx: x, gy: y });
    return true;
  }
  return false;
}
function mitte(p, W, D, RAND, Z, turm, gap) {
  const gesetzt = p.items.filter(i => i.gx !== undefined);
  if (!gesetzt.length) return;
  let x1 = 1e9, y1 = 1e9, x2 = -1e9, y2 = -1e9;
  for (const i of gesetzt) { x1 = Math.min(x1, i.gx); y1 = Math.min(y1, i.gy); x2 = Math.max(x2, i.gx + i.w); y2 = Math.max(y2, i.gy + i.d); }
  let dx = Math.floor((p.cols - (x2 - x1)) / 2) - x1, dy = Math.floor((p.rows - (y2 - y1)) / 2) - y1;
  if (turm && gesetzt.some(i => i.gx + dx + i.w > turm.x0 && i.gy + dy + i.d > turm.y0)) { dx = Math.min(dx, 0); dy = Math.min(dy, 0); if (gesetzt.some(i => i.gx + dx + i.w > turm.x0 && i.gy + dy + i.d > turm.y0)) { dx = 0; dy = 0; } }
  for (const i of gesetzt) {
    i.x = RAND + (i.gx + dx) * Z + (i.w * Z) / 2;
    i.y = RAND + (i.gy + dy) * Z + (i.d * Z) / 2;
  }
}
function bettFuellen(t) {
  const vorher = t.n; t.n = 1; packen();
  const ziel = Math.max(1, plan.platten.length);
  let lo = 1, hi = 1;
  while (hi < 400) { t.n = hi * 2; packen(); if (plan.platten.length > ziel) break; hi *= 2; }
  hi = Math.min(hi * 2, 400);
  while (lo < hi) { const m = Math.ceil((lo + hi) / 2); t.n = m; packen(); if (plan.platten.length <= ziel) lo = m; else hi = m - 1; }
  t.n = lo; packen();
  if (lo === vorher) toast('Mehr passen nicht drauf.'); else toast(`${lo} Stück passen aufs Druckbett.`);
}

// ───────── 3D-Ansicht ─────────
const cv = $('#cv'), ansichtEl = $('#ansicht');
const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const cam = new THREE.PerspectiveCamera(35, 1, 1, 8000); cam.up.set(0, 0, 1);
const ctl = new OrbitControls(cam, cv); ctl.enableDamping = false; ctl.maxPolarAngle = Math.PI * 0.495;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f96, 1.6));
const sonne = new THREE.DirectionalLight(0xffffff, 1.5); sonne.position.set(-0.4, -1, 1.4); scene.add(sonne);
const bettG = new THREE.Group(), teileG = new THREE.Group(); scene.add(bettG, teileG);
let ebeneFW = null;
let blick = '3d';
const zeichnen = () => renderer.render(scene, cam);
ctl.addEventListener('change', zeichnen);
new ResizeObserver(() => { const w = ansichtEl.clientWidth, h = ansichtEl.clientHeight; if (!w) return; renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); zeichnen(); }).observe(ansichtEl);
function farbeCSS(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function bettBauen() {
  bettG.clear();
  const dr = drucker();
  const platte = new THREE.Mesh(new THREE.BoxGeometry(dr.x, dr.y, 1.2), new THREE.MeshStandardMaterial({ color: farbeCSS('--pn'), roughness: 0.9 }));
  platte.position.set(dr.x / 2, dr.y / 2, -0.6); bettG.add(platte);
  const pts = [], st = dr.x > 200 ? 25 : 20;
  for (let x = 0; x <= dr.x + 0.1; x += st) pts.push(x, 0, 0.05, x, dr.y, 0.05);
  for (let y = 0; y <= dr.y + 0.1; y += st) pts.push(0, y, 0.05, dr.x, y, 0.05);
  const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  bettG.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: farbeCSS('--grid') })));
  const rand = new THREE.Mesh(new THREE.BoxGeometry(dr.x, 3, 1.4), new THREE.MeshStandardMaterial({ color: 0x00AE42 }));
  rand.position.set(dr.x / 2, -1.5, -0.6); bettG.add(rand);
  const c = document.createElement('canvas'); c.width = 256; c.height = 64; const g = c.getContext('2d');
  g.fillStyle = farbeCSS('--mu'); g.font = '600 34px ui-monospace,Menlo,monospace'; g.textAlign = 'center'; g.fillText('HINTEN', 128, 44);
  const tx = new THREE.CanvasTexture(c);
  const schild = new THREE.Mesh(new THREE.PlaneGeometry(60, 15), new THREE.MeshBasicMaterial({ map: tx, transparent: true }));
  schild.position.set(dr.x / 2, dr.y - 12, 0.2); bettG.add(schild);
  if (mehrfarbig()) {
    const turm = new THREE.Mesh(new THREE.BoxGeometry(36, 36, 0.4), new THREE.MeshBasicMaterial({ color: 0x00AE42, transparent: true, opacity: 0.14 }));
    turm.position.set(dr.x - 3 - 21, dr.y - 3 - 21, 0.3); bettG.add(turm);
  }
}
function blickSetzen(b) {
  blick = b; $$('[data-blick]').forEach(x => x.classList.toggle('an', x.dataset.blick === b));
  const dr = drucker(), gr = Math.max(dr.x, dr.y);
  ctl.target.set(dr.x / 2, dr.y / 2, 0);
  if (b === 'oben') cam.position.set(dr.x / 2, dr.y / 2 - 0.01, gr * 1.75);
  else if (b === 'vorne') cam.position.set(dr.x / 2, -gr * 1.25, gr * 0.35);
  else cam.position.set(dr.x / 2 - gr * 0.18, -gr * 0.62, gr * 0.95);
  ctl.update(); zeichnen();
}
const matCache = {};
function mat(farbe, gewaehlt, vertex) {
  const k = `${farbe}|${gewaehlt}|${vertex}`;
  return matCache[k] || (matCache[k] = new THREE.MeshStandardMaterial({ color: vertex ? 0xffffff : farbe, vertexColors: vertex, roughness: 0.62, metalness: 0.02, emissive: gewaehlt ? 0x00AE42 : 0x000000, emissiveIntensity: gewaehlt ? 0.22 : 0, flatShading: true }));
}
function szeneBauen() {
  teileG.clear();
  const p = plan.platten[S.platte];
  if (p) for (const it of p.items) {
    const t = teilVon(it.uid); if (!t) continue;
    const b = bbox(t.mid, t.r), s = t.s, r = t.r;
    const g = new THREE.Group();
    const m4 = new THREE.Matrix4().set(r[0] * s, r[1] * s, r[2] * s, 0, r[3] * s, r[4] * s, r[5] * s, 0, r[6] * s, r[7] * s, r[8] * s, 0, 0, 0, 0, 1);
    m4.setPosition(it.x - (b.mn[0] + b.mx[0]) / 2 * s, it.y - (b.mn[1] + b.mx[1]) / 2 * s, -b.mn[2] * s);
    g.matrixAutoUpdate = false; g.matrix.copy(m4);
    const e = exportExt(t), gew = t.uid === S.auswahl, zg = plan.zuGross.has(t.uid);
    for (const part of M[t.mid].teile) {
      const mesh = new THREE.Mesh(part.geo, zg ? mat('#E53935', gew, false) : e > 0 ? mat(farbeVon(e), gew, false) : mat('#ffffff', gew, true));
      mesh.userData.uid = t.uid; g.add(mesh);
    }
    teileG.add(g);
  }
  if (ebeneFW) scene.remove(ebeneFW), ebeneFW = null;
  zeichnen();
}
// Antippen = auswählen (oder einfärben)
let tip = null;
cv.addEventListener('pointerdown', e => { tip = { x: e.clientX, y: e.clientY, t: Date.now() }; if (!malen) $('#hinwAnsicht').classList.add('weg'); });
cv.addEventListener('pointerup', e => {
  if (!tip || Math.hypot(e.clientX - tip.x, e.clientY - tip.y) > 7 || Date.now() - tip.t > 600) return;
  const r = cv.getBoundingClientRect();
  const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), cam);
  const hit = ray.intersectObjects(teileG.children, true)[0];
  if (malen) { if (hit) malenTippen(hit); return; }
  if (hit) { S.auswahl = hit.object.userData.uid; zeigen(); }
});

// ───────── Bereiche einfärben ─────────
let malen = null; // { slot, modus:'flaeche'|'dreieck' }
function nachbarn(p) {
  if (p.nb) return p.nb;
  const n = p.pos.length / 9, id = new Map(), vid = new Uint32Array(n * 3);
  const P = p.pos;
  for (let i = 0; i < n * 3; i++) { const k = `${Math.round(P[i * 3] * 1e3)},${Math.round(P[i * 3 + 1] * 1e3)},${Math.round(P[i * 3 + 2] * 1e3)}`; let v = id.get(k); if (v === undefined) { v = id.size; id.set(k, v); } vid[i] = v; }
  const kante = new Map(), nb = Array.from({ length: n }, () => []);
  for (let t = 0; t < n; t++) for (let k = 0; k < 3; k++) {
    const a = vid[t * 3 + k], b = vid[t * 3 + (k + 1) % 3], key = a < b ? a * 4294967296 + b : b * 4294967296 + a;
    const o = kante.get(key); if (o === undefined) kante.set(key, t); else { nb[t].push(o); nb[o].push(t); }
  }
  return (p.nb = nb);
}
function malenTippen(hit) {
  const t = teilVon(hit.object.userData.uid); if (!t) return;
  const m = M[t.mid], part = m.teile.find(p => p.geo === hit.object.geometry); if (!part) return;
  const start = hit.faceIndex, slot = malen.slot;
  if (malen.modus === 'dreieck') part.mal[start] = slot;
  else {
    const nb = nachbarn(part), P = part.pos;
    const nrm = i => { const o = i * 9; const ux = P[o + 3] - P[o], uy = P[o + 4] - P[o + 1], uz = P[o + 5] - P[o + 2], vx = P[o + 6] - P[o], vy = P[o + 7] - P[o + 1], vz = P[o + 8] - P[o + 2]; const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx, l = Math.hypot(x, y, z) || 1; return [x / l, y / l, z / l]; };
    const seen = new Uint8Array(nb.length), q = [start]; seen[start] = 1;
    const ref = nrm(start);
    let n = 0;
    while (q.length && n < 400000) {
      const i = q.pop(); part.mal[i] = slot; n++;
      const ni = nrm(i);
      for (const j of nb[i]) if (!seen[j]) { const nj = nrm(j); if (nj[0] * ni[0] + nj[1] * ni[1] + nj[2] * ni[2] > 0.94 && nj[0] * ref[0] + nj[1] * ref[1] + nj[2] * ref[2] > 0.5) { seen[j] = 1; q.push(j); } }
    }
  }
  if (S.farbModus === 'ein') S.farbModus = 'jedes';
  t.ext = 0;
  faerben(t.mid); packen(); szeneBauen(); zeigen();
}
function malenStart(slot) {
  malen = { slot, modus: 'flaeche' };
  $('#hinwAnsicht').classList.remove('weg');
  ansichtEl.classList.add('malen');
  $('#hinwAnsicht').innerHTML = `<span class="punkt" style="display:inline-block;vertical-align:-2px;background:${farbeVon(slot)}"></span> Fläche antippen <button class="btn klein" id="malModus" style="padding:2px 8px;font-size:11.5px">Einzelne Dreiecke</button> <button class="btn klein gruen" id="malEnde" style="color:#fff;padding:2px 10px;font-size:11.5px">Fertig</button>`;
  $('#malModus').onclick = () => { malen.modus = malen.modus === 'flaeche' ? 'dreieck' : 'flaeche'; $('#malModus').textContent = malen.modus === 'flaeche' ? 'Einzelne Dreiecke' : 'Ganze Flächen'; };
  $('#malEnde').onclick = malenEnde;
  toast('Tippe Flächen an, um sie einzufärben.');
}
function malenEnde() { malen = null; ansichtEl.classList.remove('malen'); $('#hinwAnsicht').textContent = 'Teil antippen = auswählen · Ziehen = drehen · Zwei Finger = zoomen'; }

// ───────── Laden ─────────
async function laden(dateien, opt = {}) {
  const fd = new FormData();
  if (S.sid) fd.append('sid', S.sid);
  if (opt.zusammen) { fd.append('zusammen', '1'); fd.append('titel', opt.titel || ''); }
  dateien.forEach((d, i) => { fd.append('file', d.blob || d, d.name); if (opt.zusammen) { fd.append('ext', String(d.ext || 1)); fd.append('teilname', d.teilname || ''); } });
  schritt(2); warte(true, 'Lade Modell …');
  try {
    const r = await fetch('/api/prep/load', { method: 'POST', body: fd });
    const j = await r.json().catch(() => ({ error: `Server antwortet nicht (${r.status})` }));
    if (j.error) throw new Error(j.error);
    S.sid = j.sid;
    const quelle = { dateien: dateien.map(d => ({ name: d.name, blob: d.blob || d, ext: d.ext, teilname: d.teilname })), zusammen: !!opt.zusammen, titel: opt.titel || '' };
    let erstes = null;
    for (const info of j.modelle) {
      await modellHolen(info, quelle);
      const t = neuesTeil(info.id, opt);
      erstes = erstes || t;
    }
    if (erstes) S.auswahl = erstes.uid;
    packen(); bettBauen(); szeneBauen(); zeigen();
    if (S.schritt !== 2) schritt(2);
  } catch (e) { toast(e.message || String(e), 4500); if (!T.length) schritt(1); }
  finally { warte(false); }
}
async function modellHolen(info, quelle) {
  const r = await fetch(`/api/prep/${S.sid}/${info.id}/bin`);
  if (!r.ok) throw new Error('Modell nicht abrufbar');
  const buf = await r.arrayBuffer(), dv = new DataView(buf);
  let o = 0; const n = dv.getUint32(o, true); o += 4;
  const teile = [];
  for (let k = 0; k < n; k++) {
    const ext = dv.getUint32(o, true), nt = dv.getUint32(o + 4, true); o += 8;
    const pos = new Float32Array(buf.slice(o, o + nt * 36)); o += nt * 36;
    const paint = new Uint8Array(buf.slice(o, o + nt)); o += nt;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pos.length), 3));
    geo.computeVertexNormals();
    teile.push({ ext, pos, paint, mal: new Uint8Array(nt).fill(255), geo });
  }
  M[info.id] = { info, teile, quelle, bb: new Map(), ls: new Map() };
  faerben(info.id);
}
function neuesTeil(mid, opt = {}) {
  const info = M[mid].info;
  const t = { uid: uidZ++, mid, name: info.name || 'Modell', n: opt.anzahl || 1, s: 1, r: ICH.slice(), ext: 0, lage: null };
  T.push(t);
  const bunt = info.bemalt.length > 0 || new Set(info.teile.map(p => p.ext)).size > 1;
  if (bunt || opt.zusammen) S.farbModus = 'jedes';
  else if (S.farbModus === 'jedes') { const benutzt = new Set(T.map(x => x.ext)); t.ext = [1, 2, 3, 4, 5, 6, 7, 8].find(s => s <= S.filamente.length && !benutzt.has(s)) || 1; }
  // beste Drucklage automatisch
  const best = info.lagen[0], orig = info.orig;
  if (best && !opt.ohneLage && best.kosten < orig.kosten - 0.6 && (best.hoehe < orig.hoehe * 0.85 || best.stuetz < orig.stuetz * 0.6 - 30)) {
    t.r = best.rot.slice(); t.lage = { auto: true, vorH: orig.hoehe, nachH: best.hoehe };
  }
  return t;
}

// ───────── Ansicht aktualisieren ─────────
function schritt(n) {
  S.schritt = n;
  for (const k of [1, 2, 3]) $('#s' + k).hidden = k !== n;
  $$('#schritte button').forEach(b => { const s = +b.dataset.s; b.classList.toggle('an', s === n); b.classList.toggle('fertig', s < n); });
  if (n !== 2) malenEnde();
  if (n === 2) { setTimeout(() => { bettBauen(); blickSetzen(blick); szeneBauen(); }, 0); }
  if (n === 3) checkZeigen();
  leiste(); scrollTo({ top: 0 });
}
function leiste() {
  const w = $('#weiter'), z = $('#zurueck'), e = S.einst;
  const t = teilVon(S.auswahl) || T[0];
  const st = T.reduce((a, x) => a + x.n, 0);
  $('#leisteInfo').innerHTML = T.length
    ? `<b>${esc(t.name)}${st > 1 ? ' · ' + st + '×' : ''}</b> &nbsp;<span class="mono">${QUAL[e.qual][1]} · ${e.material} · Füllung ${e.fuellung}%</span>`
    : `<b>Erst eine Datei laden</b> &nbsp;<span class="mono">${QUAL[e.qual][1]} · ${e.material} · Füllung ${e.fuellung}%</span><br><span style="color:var(--gr-t)">Drucker: ${esc(drucker().name)} – passende Profile geladen.</span>`;
  z.hidden = S.schritt === 1;
  if (S.schritt === 1) { w.disabled = !T.length; w.textContent = T.length ? 'Weiter: Anpassen →' : 'Erst ein Modell wählen'; }
  else if (S.schritt === 2) { w.disabled = !T.length; w.textContent = 'Weiter: Drucken →'; }
  else { w.disabled = !T.length; w.textContent = '⬇  Download'; }
}
function zeigen() {
  const dr = drucker();
  $('#drName').textContent = dr.name; $('#drMass').textContent = `${dr.x}×${dr.y}×${dr.z} MM`;
  // Platten
  const pl = $('#platten');
  pl.innerHTML = plan.platten.length > 1 ? plan.platten.map((p, i) => `<button data-pl="${i}" class="${i === S.platte ? 'an' : ''}">Platte ${i + 1} · ${p.items.length}</button>`).join('') : '';
  pl.querySelectorAll('button').forEach(b => b.onclick = () => { S.platte = +b.dataset.pl; zeigen(); szeneBauen(); });
  // Teil-Panel
  const t = teilVon(S.auswahl);
  $('#teilPanel').hidden = !t;
  if (t) {
    const g = masse(t), e = exportExt(t);
    $('#tpName').textContent = t.name; $('#tpMass').textContent = `${zahl(g[0])} × ${zahl(g[1])} × ${zahl(g[2])} mm`;
    $('#tpPunkt').style.background = punkt(t);
    $('#tpAnzahl').textContent = t.n; $('#tagName').textContent = t.name;
    if (!plan.platten[S.platte]?.items.some(i => i.uid === t.uid)) { const i = plan.platten.findIndex(p => p.items.some(x => x.uid === t.uid)); if (i >= 0 && i !== S.platte) { S.platte = i; pl.querySelectorAll('button').forEach((b, k) => b.classList.toggle('an', k === i)); szeneBauen(); } }
  } else $('#tagName').textContent = T.length ? 'Teil antippen' : '–';
  listeZeigen(); slotsZeigen(); passtZeigen(); favZeigen(); leiste();
  if (S.schritt === 3) checkZeigen();
}
function listeZeigen() {
  const l = $('#teileListe');
  if (!T.length) { l.innerHTML = '<div class="leer">Noch nichts auf dem Druckbett.</div>'; return; }
  l.innerHTML = T.map(t => {
    const f = punkt(t), g = masse(t);
    return `<div class="eintrag ${t.uid === S.auswahl ? 'an' : ''}" data-uid="${t.uid}">
      <button class="punkt" data-farbe="${t.uid}" style="width:22px;height:22px;background:${f}" aria-label="Farbe"></button>
      <div style="flex:1;min-width:0" data-waehle="${t.uid}"><b style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.name)}</b><span class="klein mono">${zahl(g[0])}×${zahl(g[1])}×${zahl(g[2])} mm${plan.zuGross.has(t.uid) ? ' · <span style="color:var(--err)">zu groß</span>' : ''}</span></div>
      <div class="zahl"><button data-minus="${t.uid}">−</button><span>${t.n}</span><button data-plus="${t.uid}">+</button></div></div>`;
  }).join('');
  l.querySelectorAll('[data-waehle]').forEach(b => b.onclick = () => { S.auswahl = +b.dataset.waehle; zeigen(); szeneBauen(); });
  l.querySelectorAll('[data-farbe]').forEach(b => b.onclick = () => { S.auswahl = +b.dataset.farbe; zeigen(); szeneBauen(); blatt('farbe'); });
  l.querySelectorAll('[data-plus]').forEach(b => b.onclick = () => { const t = teilVon(+b.dataset.plus); t.n++; neu(); });
  l.querySelectorAll('[data-minus]').forEach(b => b.onclick = () => {
    const t = teilVon(+b.dataset.minus);
    if (t.n > 1) t.n--; else if (confirm(`„${t.name}“ vom Druckbett nehmen?`)) { T = T.filter(x => x !== t); if (S.auswahl === t.uid) S.auswahl = T[0]?.uid ?? null; }
    neu();
  });
}
function punkt(t) {
  const f = [...farbenVon(t)];
  if (f.length === 1) return farbeVon(f[0]);
  return `conic-gradient(${f.slice(0, 6).map(farbeVon).join(',')},${farbeVon(f[0])})`;
}
function slotsZeigen() {
  $$('#farbModus button').forEach(b => b.classList.toggle('an', b.dataset.m === S.farbModus));
  $('#farbHilfe').textContent = S.farbModus === 'ein' ? 'Alles in einer Farbe. Farbpunkt antippen = Farbe wählen.' : 'Farbpunkt antippen = Farbe des gewählten Teils. Mehrfarbige Dateien behalten ihre Farben.';
  const t = teilVon(S.auswahl);
  $('#slotListe').innerHTML = S.filamente.map((f, i) => {
    const an = S.farbModus === 'ein' ? S.einSlot === i + 1 : t && t.ext === i + 1;
    return `<button class="farbe ${an ? 'an' : ''}" data-slot="${i + 1}" style="background:${f.farbe}" aria-label="Filament ${i + 1}">${i + 1}</button>`;
  }).join('');
  $$('#slotListe [data-slot]').forEach(b => b.onclick = () => slotWaehlen(+b.dataset.slot));
  $('#fwListe').innerHTML = S.farbwechsel.length ? 'Farbwechsel: ' + S.farbwechsel.map((w, i) => `ab ${zahl(w.z, 1)} mm → <span class="punkt" style="display:inline-block;vertical-align:-2px;background:${farbeVon(w.ext)}"></span> <button class="btn klein" data-fwweg="${i}">×</button>`).join(' · ') : '';
  $$('[data-fwweg]').forEach(b => b.onclick = () => { S.farbwechsel.splice(+b.dataset.fwweg, 1); neu(); });
}
function slotWaehlen(slot) {
  if (S.farbModus === 'ein') S.einSlot = slot;
  else { const t = teilVon(S.auswahl); if (t) t.ext = slot; }
  speichern(); neu();
}
function passtZeigen() {
  const el = $('#passt'), n = T.reduce((a, t) => a + t.n, 0);
  if (!T.length) { el.hidden = true; return; } el.hidden = false;
  const t = teilVon(S.auswahl) || T[0], g = masse(t);
  if (plan.zuGross.size) { el.className = 'passt nein'; el.textContent = `⚠ ${[...plan.zuGross].map(u => teilVon(u)?.name).join(', ')} ist größer als das Druckbett – unter „Mehr“ einpassen oder zerlegen.`; }
  else if (plan.platten.length > 1) { el.className = 'passt nein'; el.textContent = `Verteilt auf ${plan.platten.length} Platten · ${n} Stück`; }
  else { el.className = 'passt ok'; el.textContent = `✓ Passt aufs Druckbett · ${zahl(g[0], 1)} × ${zahl(g[1], 1)} × ${zahl(g[2], 1)} mm · ${n} Stück`; }
}
function neu() { packen(); bettBauen(); szeneBauen(); zeigen(); }

// ───────── Druck-Check ─────────
function hinweise() {
  const h = [], dr = drucker(), sch = schicht();
  for (const t of T) {
    const g = masse(t), i = M[t.mid].info;
    if (plan.zuGross.has(t.uid)) h.push({ art: 'fehler', text: `„${t.name}“ ist größer als das Druckbett (${zahl(g[0])} × ${zahl(g[1])} × ${zahl(g[2])} mm, Platz: ${dr.x} × ${dr.y} × ${dr.z} mm).`, akt: [['Aufs Bett einpassen', () => einpassen(t)], ['In Teile zerlegen', () => zerlegen(t)]] });
    if (Math.max(...g) < 3) h.push({ art: 'warn', text: `„${t.name}“ ist nur ${zahl(Math.max(...g), 2)} mm groß – vielleicht in Zentimetern oder Zoll gespeichert?`, akt: [['× 10 (cm)', () => { t.s *= 10; neu(); }], ['× 25,4 (Zoll)', () => { t.s *= 25.4; neu(); }]] });
    if (t.lage?.auto) {
      const vor = minutenFuer(stueckBei(t, i.orig).vol, t.lage.vorH * t.s, dr), nach = minutenFuer(stueck(t, false).vol, t.lage.nachH * t.s, dr);
      const spar = Math.round(vor - nach);
      h.push({ art: 'info', text: `✨ „${t.name}“ wurde automatisch in die beste Drucklage gebracht: liegt flacher${i.orig.stuetz > i.lagen[0]?.stuetz + 30 ? ', braucht weniger Stützen' : ''} und ist schneller fertig (Höhe ${zahl(t.lage.vorH * t.s, 1)} → ${zahl(t.lage.nachH * t.s, 1)} mm)${spar > 0 ? `, spart etwa ${spar} Min. pro Stück` : ''}.`, akt: [['Original-Lage', () => { t.r = ICH.slice(); t.lage = null; neu(); }]] });
    } else {
      const best = i.lagen[0], cur = lageStat(t.mid, t.r);
      if (best && best.kosten < cur.kosten - 1 && (best.hoehe < cur.h * 0.8 || best.stuetz < cur.st * 0.6 - 40)) h.push({ art: 'info', text: `„${t.name}“ könnte besser liegen: ${best.hoehe < cur.h * 0.8 ? `niedriger (${zahl(cur.h * t.s, 1)} → ${zahl(best.hoehe * t.s, 1)} mm)` : 'mit weniger Stützen'}.`, akt: [['Flach hinlegen', () => flachLegen(t)]] });
    }
    const x = stueck(t, false), cm2 = x.st / 100;
    if (cm2 > 1.5) {
      if (S.einst.stuetzen === 'aus') h.push({ art: 'warn', text: `„${t.name}“ hat Überhänge (ca. ${zahl(cm2)} cm²) – ohne Stützen hängt es dort durch.`, akt: [['Stützen nur wo nötig', () => { S.einst.stuetzen = 'auto'; einstZeigen(); checkZeigen(); }]] });
      else h.push({ art: 'info', text: `Stützen nur wo nötig: „${t.name}“ bekommt Stützen für ca. ${zahl(cm2)} cm² Überhang.`, akt: [] });
    }
    if (brauchtRand(t) && S.einst.rand === 'aus') h.push({ art: 'warn', text: `„${t.name}“ steht auf kleiner Fläche – ein Rand (Brim) hält es besser auf dem Bett.`, akt: [['Rand einschalten', () => { S.einst.rand = 'auto'; einstZeigen(); checkZeigen(); }]] });
    else if (brauchtRand(t)) h.push({ art: 'info', text: `„${t.name}“ ist hoch und steht auf kleiner Fläche – es bekommt einen Rand (Brim).`, akt: [] });
  }
  const farben = new Set(); let ausTeilen = false;
  for (const t of T) { for (const f of farbenVon(t)) farben.add(f); if (exportExt(t) === 0 && new Set(M[t.mid].teile.map(p => p.ext)).size > 1) ausTeilen = true; }
  if (farben.size > 1) {
    const akt = [];
    if (ausTeilen || T.length > 1) akt.push(S.nachFarbe ? ['Alles auf eine Platte', () => { S.nachFarbe = false; neu(); }] : ['Nach Farben auf Platten aufteilen', () => { S.nachFarbe = true; neu(); }]);
    h.push({ art: 'info', text: S.nachFarbe ? `Aufgeteilt nach Farben: jede Platte eine Farbe – danach zusammenbauen.` : `Mehrfarbiges Modell aus ${farben.size} Farben. Du kannst es in einem Stück mehrfarbig drucken${dr.multi ? ' (mit AMS / CFS)' : ''} – oder die Teile nach Farben auf Druckplatten verteilen: jede Platte eine Farbe, danach zusammenbauen.`, akt });
    if (!dr.multi) h.push({ art: 'warn', text: `${dr.name} hat kein Mehrfarbsystem – jeder Farbwechsel braucht eine Pause zum Umspulen.`, akt: [] });
    if (S.einst.material === 'TPU') h.push({ art: 'warn', text: 'TPU läuft meist nicht durchs AMS – für mehrfarbig lieber PLA oder PETG.', akt: [] });
  }
  plan.platten.forEach((p, i) => {
    const fw = farbSchichten(p);
    if (fw.schichten > 25 && !S.nachFarbe) h.push({ art: fw.schichten > 80 ? 'warn' : 'info', text: `Viele Farbwechsel${plan.platten.length > 1 ? ` (Platte ${i + 1})` : ''}: In etwa ${fw.schichten} Schichten (${zahl(fw.hoehe)} mm Höhe) liegen mehrere Farben – z. B. ein Logo auf einer senkrechten Wand oder verschiedenfarbige Teile nebeneinander. Das kostet ca. ${dauer(fw.wechsel * dr.wechsel / 60)} und ${zahl(fw.wechsel * dr.abfall)} g Spülabfall. Tipp: mehrere Stück auf einmal drucken (die Wechsel zählen nur einmal pro Schicht) oder einfarbig drucken und danach bemalen.`, akt: [['Einfarbig drucken', () => { S.farbModus = 'ein'; neu(); }]] });
  });
  const maxH = Math.max(0, ...T.map(t => masse(t)[2]));
  for (const w of S.farbwechsel) if (w.z >= maxH) h.push({ art: 'warn', text: `Der Farbwechsel ab ${zahl(w.z, 1)} mm liegt über dem höchsten Teil (${zahl(maxH, 1)} mm) und passiert nicht.`, akt: [] });
  if (plan.platten.length > 1 && !S.nachFarbe) h.push({ art: 'info', text: `Nicht alles passt auf eine Platte – verteilt auf ${plan.platten.length} Platten. Die 3MF enthält alle Platten.`, akt: [] });
  if (S.format === 'stl' && farben.size > 1) h.push({ art: 'info', text: 'STL speichert keine Farben – für mehrfarbig „3MF für den Slicer“ wählen.', akt: [['3MF nehmen', () => { S.format = '3mf'; speichern(); einstZeigen(); checkZeigen(); }]] });
  return h;
}
function stueckBei(t, lage) { const i = M[t.mid].info, s = t.s, V = i.volumen * s ** 3, A = i.flaeche * s * s, schale = Math.min(V, A * 0.9); return { vol: schale + Math.max(0, V - schale) * Math.max(S.einst.fuellung / 100, 0.02), h: lage.hoehe * s }; }
function checkZeigen() {
  const el = $('#check');
  if (!T.length) { el.innerHTML = '<div class="leer">Erst ein Modell laden.</div>'; return; }
  const h = hinweise(), schlimm = h.some(x => x.art === 'fehler'), warn = h.some(x => x.art === 'warn');
  el.innerHTML = `<div class="kopfc"><span class="ampel" style="background:${schlimm ? 'var(--err)' : warn ? 'var(--warn)' : '#1F8F55'}"></span><div><b style="font-size:16px">${schlimm ? 'Bitte erst beheben' : warn ? 'Fast bereit – bitte prüfen' : 'Alles bereit zum Drucken'}</b><div class="klein">${schlimm ? 'Der Druck-Check hat ein Problem gefunden.' : warn ? 'Der Druck-Check hat Hinweise.' : 'Der Druck-Check hat nichts gefunden.'}</div></div></div>`
    + h.map((x, i) => `<div class="hinweis ${x.art}"><span class="dot"></span><div style="flex:1">${esc(x.text)}${x.akt.length ? `<div class="akt">${x.akt.map((a, k) => `<button data-h="${i}" data-k="${k}">${esc(a[0])}</button>`).join('')}</div>` : ''}</div></div>`).join('');
  el.querySelectorAll('[data-h]').forEach(b => b.onclick = () => { h[+b.dataset.h].akt[+b.dataset.k][1](); checkZeigen(); });
  const sc = schaetzung(), n = T.reduce((a, t) => a + t.n, 0);
  $('#werte').innerHTML = `<div><span class="klein">Druckzeit</span><b>${dauer(sc.min)}</b></div><div><span class="klein">Filament</span><b>${zahl(sc.gramm + sc.abfall)} g</b></div><div><span class="klein">Länge</span><b>${zahl(sc.meter, 1)} m</b></div>`;
  $('#werteHinweis').textContent = `Grobe Schätzung für ${n} Stück auf ${plan.platten.length} Platte${plan.platten.length > 1 ? 'n' : ''} mit ${drucker().name}${sc.abfall > 0.5 ? `, davon ca. ${zahl(sc.abfall)} g Spülabfall` : ''}. Genaue Werte zeigt der Slicer.`;
  einstZeigen();
}
function einstZeigen() {
  const e = S.einst;
  $$('#eQual button').forEach(b => b.classList.toggle('an', b.dataset.v === e.qual));
  $('#eMat').innerHTML = Object.keys(MATERIAL).map(m => `<button class="chip ${m === e.material ? 'an' : ''}" data-mat="${m}">${m}</button>`).join('');
  $$('[data-mat]').forEach(b => b.onclick = () => { e.material = b.dataset.mat; speichern(); checkZeigen(); leiste(); });
  $('#eFuell').value = e.fuellung; $('#eFuellWert').textContent = e.fuellung + ' %';
  $('#eFuellChips').innerHTML = [10, 15, 25, 50, 100].map(v => `<button class="chip ${v === +e.fuellung ? 'an' : ''}" data-fu="${v}">${v} %</button>`).join('');
  $$('[data-fu]').forEach(b => b.onclick = () => { e.fuellung = +b.dataset.fu; speichern(); checkZeigen(); leiste(); });
  $$('#eStuetz button').forEach(b => b.classList.toggle('an', b.dataset.v === e.stuetzen));
  $$('#eRand button').forEach(b => b.classList.toggle('an', b.dataset.v === e.rand));
  $$('#eFormat button').forEach(b => b.classList.toggle('an', b.dataset.v === S.format));
  const dr = drucker();
  $('#formatHilfe').textContent = S.format === '3mf'
    ? `Öffnen mit ${dr.slicer}: Druckbett, Platten, Farben je Teil und die Einstellungen pro Objekt sind schon drin. Im Slicer nur noch den ${dr.name} wählen und „Slicen“.`
    : 'Eine STL je Platte, schon richtig auf dem Druckbett angeordnet – z. B. für Bambu Handy oder Creality Cloud. Farben und Einstellungen wählst du dort.';
}
$('#eFuell').oninput = e => { S.einst.fuellung = +e.target.value; $('#eFuellWert').textContent = S.einst.fuellung + ' %'; };
$('#eFuell').onchange = () => { speichern(); checkZeigen(); leiste(); };
for (const [id, key] of [['#eQual', 'qual'], ['#eStuetz', 'stuetzen'], ['#eRand', 'rand']]) $$(id + ' button').forEach(b => b.onclick = () => { S.einst[key] = b.dataset.v; speichern(); checkZeigen(); leiste(); });
$$('#eFormat button').forEach(b => b.onclick = () => { S.format = b.dataset.v; speichern(); checkZeigen(); });

// ───────── Aktionen am Teil ─────────
function flachLegen(t) {
  const best = M[t.mid].info.lagen[0];
  if (!best) return toast('Keine bessere Lage gefunden.');
  const v = lageStat(t.mid, t.r).h;
  t.r = best.rot.slice(); t.lage = { auto: false, vorH: v, nachH: best.hoehe };
  neu(); toast('Flach hingelegt.');
}
function drehen(t, R) { t.r = rmul(R, t.r); t.lage = null; neu(); }
function einpassen(t) {
  const dr = drucker(), b = bbox(t.mid, t.r).g;
  const k = Math.min((dr.x - 10) / b[0], (dr.y - 10) / b[1], (dr.z - 2) / b[2]);
  t.s = Math.floor(k * 1000) / 1000; neu(); toast(`Auf ${zahl(t.s * 100)} % verkleinert.`);
}
async function zerlegen(t) {
  warte(true, 'Zerlege in Teile …'); schritt(2); warte(true, 'Zerlege in Teile …');
  try {
    const dr = drucker();
    const r = await fetch(`/api/prep/${S.sid}/zerlegen`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ m: t.mid, r: t.r, s: t.s, drucker: { name: dr.name, x: dr.x, y: dr.y, z: dr.z, speed: 1 } }) });
    const j = await r.json(); if (j.error) throw new Error(j.error);
    T = T.filter(x => x !== t);
    for (const info of j.modelle) { await modellHolen(info, null); const n = neuesTeil(info.id, { ohneLage: true }); n.n = t.n; n.ext = t.ext; }
    S.auswahl = T[T.length - 1]?.uid;
    neu();
    if (j.dateien?.length) blattInhalt('Zerlegt', `<p>„${esc(t.name)}“ wurde in ${j.modelle.length} Teile zerlegt – jedes passt aufs Druckbett und hat Verbinder an den Schnittflächen.</p>${j.dateien.map(d => `<a class="option" href="${d.url}" download style="text-decoration:none;color:inherit"><b>${esc(d.name)}</b><span class="klein">${d.name.endsWith('.txt') ? 'Montageanleitung' : 'Dübel zum Mitdrucken'}</span></a>`).join('')}`);
  } catch (e) { toast(e.message, 4500); }
  finally { warte(false); }
}
$('#dLinks').onclick = () => { const t = teilVon(S.auswahl); if (t) drehen(t, RZ(90)); };
$('#dRechts').onclick = () => { const t = teilVon(S.auswahl); if (t) drehen(t, RZ(-90)); };
$('#dKippen').onclick = () => { const t = teilVon(S.auswahl); if (t) drehen(t, RX(90)); };
$('#dFlach').onclick = () => { const t = teilVon(S.auswahl); if (t) flachLegen(t); };
$$('[data-blick]').forEach(b => b.onclick = () => blickSetzen(b.dataset.blick));
$$('#farbModus button').forEach(b => b.onclick = () => {
  S.farbModus = b.dataset.m;
  if (S.farbModus === 'jedes') { let i = 0; for (const t of T) { const m = M[t.mid]; const bunt = m.info.bemalt.length || new Set(m.teile.map(p => p.ext)).size > 1 || m.teile.some(p => p.mal.some(v => v !== 255)); if (!bunt && !t.ext) t.ext = (i++ % S.filamente.length) + 1; } }
  speichern(); neu();
});

// ───────── Download ─────────
async function herunterladen() {
  if (plan.zuGross.size) { toast('Erst die zu großen Teile einpassen oder zerlegen.', 3500); schritt(3); return; }
  const dr = drucker(), e = S.einst;
  const bemalung = {};
  for (const t of T) {
    const m = M[t.mid]; if (bemalung[t.mid]) continue;
    const liste = m.teile.map(p => { const a = []; p.mal.forEach((v, i) => { if (v !== 255) a.push([i, v]); }); return a; });
    if (liste.some(a => a.length)) bemalung[t.mid] = liste;
  }
  const titel = (T[0]?.name || 'druck').replace(/\.[^.]+$/, '');
  const auftrag = {
    format: S.format, drucker: dr.name, bett: [dr.x, dr.y], titel, mehrfarbig: !!dr.multi,
    einst: { schicht: schicht(), fuellung: e.fuellung, stuetzen: false, rand: e.rand !== 'aus', material: e.material },
    farbwechsel: S.farbwechsel.map(w => ({ z: w.z, ext: w.ext, farbe: farbeVon(w.ext) })),
    bemalung,
    platten: plan.platten.map(p => p.items.map(it => { const t = teilVon(it.uid); return { m: t.mid, r: t.r, s: t.s, x: it.x, y: it.y, ext: exportExt(t), name: t.n > 1 ? `${t.name} ${it.k + 1}` : t.name, stuetzen: stuetzenFuer(t), rand: randFuer(t) }; })),
  };
  $('#weiter').disabled = true; $('#weiter').textContent = 'Erstelle Datei …';
  try {
    const r = await fetch(`/api/prep/${S.sid}/export`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(auftrag) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || `Fehler ${r.status}`); }
    const blob = await r.blob();
    const name = (r.headers.get('content-disposition') || '').match(/filename="([^"]+)"/)?.[1] || `${titel}.${S.format}`;
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    toast(`${name} ist fertig.`);
  } catch (err) { toast(err.message, 4500); }
  finally { leiste(); }
}

// ───────── Favoriten (auf dem Gerät) ─────────
function idb() { return new Promise((ok, no) => { const r = indexedDB.open('formwerk', 1); r.onupgradeneeded = () => r.result.createObjectStore('fav', { keyPath: 'id', autoIncrement: true }); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); }); }
async function favAlle() { try { const db = await idb(); return await new Promise(ok => { const q = db.transaction('fav').objectStore('fav').getAll(); q.onsuccess = () => ok(q.result || []); q.onerror = () => ok([]); }); } catch { return []; } }
async function favMerken(t) {
  const q = M[t.mid].quelle; if (!q) return toast('Dieses Teil kann nicht gemerkt werden.');
  const db = await idb(); db.transaction('fav', 'readwrite').objectStore('fav').add({ name: t.name, quelle: q, zeit: Date.now() });
  toast('Als Favorit gemerkt – erscheint oben beim Start.'); favZeigen();
}
async function favZeigen() {
  const f = (await favAlle()).sort((a, b) => b.zeit - a.zeit);
  $('#favBox').hidden = !f.length;
  $('#favListe').innerHTML = f.map(x => `<button data-fav="${x.id}">★ ${esc(x.name)}</button>`).join('');
  $$('[data-fav]').forEach(b => {
    const x = f.find(y => y.id === +b.dataset.fav);
    b.onclick = () => laden(x.quelle.dateien.map(d => ({ name: d.name, blob: d.blob, ext: d.ext, teilname: d.teilname })), { zusammen: x.quelle.zusammen, titel: x.quelle.titel });
    b.oncontextmenu = async ev => { ev.preventDefault(); if (confirm(`Favorit „${x.name}“ löschen?`)) { const db = await idb(); db.transaction('fav', 'readwrite').objectStore('fav').delete(x.id); setTimeout(favZeigen, 200); } };
  });
}

// ───────── Blätter ─────────
const blattEl = $('#blatt'), schleier = $('#schleier');
let blattZu = null;
function blattInhalt(titel, html, init, beimSchliessen) {
  $('#blattTitel').textContent = titel; $('#blattInhalt').innerHTML = html;
  blattEl.classList.add('an'); schleier.classList.add('an');
  blattZu = beimSchliessen || null;
  if (init) init($('#blattInhalt'));
}
function blattSchliessen() { blattEl.classList.remove('an'); schleier.classList.remove('an'); if (blattZu) { const f = blattZu; blattZu = null; f(); } if (ebeneFW) { scene.remove(ebeneFW); ebeneFW = null; zeichnen(); } }
$('#blattFertig').onclick = blattSchliessen; schleier.onclick = blattSchliessen;
document.addEventListener('click', e => { const b = e.target.closest('[data-blatt]'); if (b) blatt(b.dataset.blatt); });

const BL = {
  drucker() {
    const liste = () => [...DRUCKER, { id: 'eigen', name: S.eigen.name, x: S.eigen.x, y: S.eigen.y, z: S.eigen.z, slicer: 'eigene Maße' }];
    blattInhalt('Drucker wählen', `<div class="feld"><span>Drucker suchen · ${DRUCKER.length + 1} Drucker</span><input class="eing" id="drSuche" placeholder="z. B. H2C"></div><div id="drListe"></div>
      <div class="karte" id="eigenBox" style="margin-top:8px"><b>Eigener Drucker</b><div class="drei" style="margin-top:8px"><label class="feld"><span>X mm</span><input type="number" id="ex" value="${S.eigen.x}"></label><label class="feld"><span>Y mm</span><input type="number" id="ey" value="${S.eigen.y}"></label><label class="feld"><span>Z mm</span><input type="number" id="ez" value="${S.eigen.z}"></label></div>
      <label class="feld"><span>Name</span><input type="text" id="en" value="${esc(S.eigen.name)}"></label><label class="zeile klein"><input type="checkbox" id="em" ${S.eigen.multi ? 'checked' : ''}> hat ein Mehrfarbsystem</label></div>`, el => {
      const zeichne = () => {
        const q = el.querySelector('#drSuche').value.toLowerCase();
        el.querySelector('#drListe').innerHTML = liste().filter(d => d.name.toLowerCase().includes(q)).map(d => `<button class="drucker ${d.id === S.druckerId ? 'an' : ''}" data-dr="${d.id}"><span class="rad"></span><span><b>${esc(d.name)}</b><br><span class="klein">${d.x}×${d.y}×${d.z} mm · Slicer: ${esc(d.slicer)}</span></span></button>`).join('');
        el.querySelectorAll('[data-dr]').forEach(b => b.onclick = () => { S.druckerId = b.dataset.dr; speichern(); zeichne(); neu(); blickSetzen(blick); });
      };
      el.querySelector('#drSuche').oninput = zeichne; zeichne();
      for (const k of ['ex', 'ey', 'ez', 'en', 'em']) el.querySelector('#' + k).onchange = () => {
        S.eigen = { name: el.querySelector('#en').value || 'Eigener Drucker', x: +el.querySelector('#ex').value || 220, y: +el.querySelector('#ey').value || 220, z: +el.querySelector('#ez').value || 250, multi: el.querySelector('#em').checked };
        S.druckerId = 'eigen'; speichern(); zeichne(); neu(); blickSetzen(blick);
      };
    });
  },
  groesse() {
    const t = teilVon(S.auswahl); if (!t) return;
    const b = bbox(t.mid, t.r).g;
    blattInhalt(t.name, `<div class="feld"><span>Größe (%)</span><div class="zwei"><input type="number" id="gp" value="${+(t.s * 100).toFixed(1)}" step="1"><button class="btn" id="gBett">Aufs Bett einpassen</button></div></div>
      <input type="range" id="gr" min="5" max="400" step="1" value="${Math.min(400, Math.round(t.s * 100))}">
      <div class="chips" style="margin:10px 0 14px">${[25, 50, 75, 100, 150, 200].map(v => `<button class="chip" data-gs="${v}">${v} %</button>`).join('')}</div>
      <div class="feld"><span>Maße in mm (Seitenverhältnis bleibt)</span><div class="drei"><input type="number" id="gx" step="0.1"><input type="number" id="gy" step="0.1"><input type="number" id="gz" step="0.1"></div></div>`, el => {
      const auf = () => { el.querySelector('#gp').value = +(t.s * 100).toFixed(1); el.querySelector('#gr').value = Math.min(400, Math.round(t.s * 100)); ['gx', 'gy', 'gz'].forEach((k, i) => el.querySelector('#' + k).value = +(b[i] * t.s).toFixed(1)); };
      const setz = s => { if (s > 0.001 && isFinite(s)) { t.s = s; neu(); auf(); } };
      auf();
      el.querySelector('#gp').onchange = e => setz(+e.target.value / 100);
      el.querySelector('#gr').oninput = e => { t.s = +e.target.value / 100; auf(); };
      el.querySelector('#gr').onchange = () => neu();
      el.querySelectorAll('[data-gs]').forEach(x => x.onclick = () => setz(+x.dataset.gs / 100));
      el.querySelector('#gBett').onclick = () => { einpassen(t); auf(); };
      ['gx', 'gy', 'gz'].forEach((k, i) => el.querySelector('#' + k).onchange = e => setz(+e.target.value / b[i]));
    });
  },
  drehen() {
    const t = teilVon(S.auswahl); if (!t) return;
    const lagen = M[t.mid].info.lagen;
    blattInhalt(`${t.name} drehen`, `
      <button class="option" id="rFlach"><b>⤓ Flach hinlegen</b><span class="klein">Dreht das Teil auf die beste Auflagefläche, braucht weniger Stützen</span></button>
      <div class="zwei"><button class="option" id="rKx"><b>↻ Um 90° kippen</b><span class="klein">nach vorne</span></button><button class="option" id="rKy"><b>↻ Um 90° kippen</b><span class="klein">zur Seite</span></button></div>
      <div class="zwei"><button class="option" id="rZl"><b>⟲ 90° links</b><span class="klein">auf dem Bett</span></button><button class="option" id="rZr"><b>⟳ 90° rechts</b><span class="klein">auf dem Bett</span></button></div>
      <div class="feld"><span>Auf dem Bett drehen (Grad)</span><input type="range" id="rWinkel" min="-180" max="180" step="5" value="0"></div>
      <button class="option" id="rOrig"><b>Original-Lage</b><span class="klein">So wie in der Datei</span></button>
      ${lagen.length ? `<div class="lbl">Vorschläge</div>${lagen.slice(0, 5).map((l, i) => `<button class="option" data-lage="${i}"><b>Lage ${i + 1}${i === 0 ? ' · beste' : ''}</b><span class="klein">Höhe ${zahl(l.hoehe * t.s, 1)} mm · Stützen ca. ${zahl(l.stuetz * t.s * t.s / 100)} cm² · Auflage ${zahl(l.kontakt * t.s * t.s / 100, 1)} cm²</span></button>`).join('')}` : ''}`, el => {
      el.querySelector('#rFlach').onclick = () => flachLegen(t);
      el.querySelector('#rKx').onclick = () => drehen(t, RX(90));
      el.querySelector('#rKy').onclick = () => drehen(t, RY(90));
      el.querySelector('#rZl').onclick = () => drehen(t, RZ(90));
      el.querySelector('#rZr').onclick = () => drehen(t, RZ(-90));
      let basis = t.r.slice();
      el.querySelector('#rWinkel').oninput = e => { t.r = rmul(RZ(+e.target.value), basis); t.lage = null; neu(); };
      el.querySelector('#rOrig').onclick = () => { t.r = ICH.slice(); t.lage = null; basis = t.r.slice(); neu(); };
      el.querySelectorAll('[data-lage]').forEach(b => b.onclick = () => { t.r = lagen[+b.dataset.lage].rot.slice(); t.lage = null; basis = t.r.slice(); neu(); });
    });
  },
  anzahl() {
    const t = teilVon(S.auswahl); if (!t) return;
    blattInhalt(`${t.name} · Anzahl`, `<div class="zeile" style="justify-content:center;margin:6px 0 16px"><div class="zahl" style="transform:scale(1.35)"><button id="aM">−</button><span id="aN">${t.n}</span><button id="aP">+</button></div></div>
      <div class="chips" style="justify-content:center;margin-bottom:14px">${[1, 2, 4, 6, 10, 20].map(v => `<button class="chip" data-an="${v}">${v}</button>`).join('')}</div>
      <button class="option" id="aFuell"><b>▦ Rest des Betts damit füllen</b><span class="klein">So viele Stück wie noch Platz haben – alle gleich ausgerichtet</span></button>
      <div class="feld"><span>Abstand zwischen allen Teilen (mm)</span><input type="number" id="aAbst" value="${S.abstand}" min="1" max="40"></div>`, el => {
      const auf = () => { el.querySelector('#aN').textContent = t.n; };
      el.querySelector('#aM').onclick = () => { t.n = Math.max(1, t.n - 1); neu(); auf(); };
      el.querySelector('#aP').onclick = () => { t.n++; neu(); auf(); };
      el.querySelectorAll('[data-an]').forEach(b => b.onclick = () => { t.n = +b.dataset.an; neu(); auf(); });
      el.querySelector('#aFuell').onclick = () => { bettFuellen(t); bettBauen(); szeneBauen(); zeigen(); auf(); };
      el.querySelector('#aAbst').onchange = e => { S.abstand = Math.max(1, Math.min(40, +e.target.value || 8)); speichern(); neu(); };
    });
  },
  farbe() {
    const t = teilVon(S.auswahl); if (!t) return;
    const m = M[t.mid], bunt = m.info.bemalt.length || new Set(m.teile.map(p => p.ext)).size > 1 || m.teile.some(p => p.mal.some(v => v !== 255));
    blattInhalt(`${t.name} · Farbe`, `<div class="seg" style="margin-bottom:12px"><button data-fm="ein" class="${S.farbModus === 'ein' ? 'an' : ''}">Einfarbig</button><button data-fm="jedes" class="${S.farbModus === 'jedes' ? 'an' : ''}">Jedes Teil eigene Farbe</button></div>
      <div class="klein" style="margin-bottom:10px">${S.farbModus === 'ein' ? 'Gilt für alles auf dem Druckbett.' : 'Gilt für dieses Teil.'}</div>
      <div class="farben" style="margin-bottom:14px">${S.filamente.map((f, i) => `<button class="farbe ${(S.farbModus === 'ein' ? S.einSlot : t.ext) === i + 1 ? 'an' : ''}" data-fs="${i + 1}" style="background:${f.farbe}">${i + 1}</button>`).join('')}</div>
      ${bunt ? `<button class="option ${S.farbModus === 'jedes' && t.ext === 0 ? 'an' : ''}" id="fDatei"><b>Farben aus der Datei</b><span class="klein">Mehrfarbige 3MF bleiben, wie sie sind</span></button>` : ''}
      <div class="lbl">Bereiche einfärben</div><div class="klein" style="margin-bottom:8px">Farbe wählen, dann Flächen am Modell antippen (z. B. ein Logo oder eine Seite).</div>
      <div class="farben" style="margin-bottom:12px">${S.filamente.map((f, i) => `<button class="farbe" data-mal="${i + 1}" style="background:${f.farbe}">🖌</button>`).join('')}</div>
      <button class="option" id="fMalWeg"><b>Einfärbung entfernen</b><span class="klein">Alles, was hier eingefärbt wurde</span></button>
      <button class="btn voll" data-blatt="slots">Filamente bearbeiten</button>`, el => {
      el.querySelectorAll('[data-fm]').forEach(b => b.onclick = () => { $(`#farbModus [data-m="${b.dataset.fm}"]`).click(); BL.farbe(); });
      el.querySelectorAll('[data-fs]').forEach(b => b.onclick = () => { slotWaehlen(+b.dataset.fs); BL.farbe(); });
      el.querySelector('#fDatei')?.addEventListener('click', () => { S.farbModus = 'jedes'; t.ext = 0; neu(); BL.farbe(); });
      el.querySelectorAll('[data-mal]').forEach(b => b.onclick = () => { blattSchliessen(); malenStart(+b.dataset.mal); });
      el.querySelector('#fMalWeg').onclick = () => { for (const p of m.teile) p.mal.fill(255); faerben(t.mid); neu(); toast('Einfärbung entfernt.'); };
    });
  },
  mehr() {
    const t = teilVon(S.auswahl); if (!t) return;
    blattInhalt(t.name, `
      <button class="option" id="mFlach"><b>⤓ Flach hinlegen</b><span class="klein">Dreht das Teil auf die beste Auflagefläche, braucht weniger Stützen</span></button>
      <button class="option" id="mKipp"><b>↻ Um 90° kippen</b><span class="klein">Teil von Hand drehen</span></button>
      <button class="option" id="mFuell"><b>▦ Rest des Betts damit füllen</b><span class="klein">So viele Stück wie noch Platz haben</span></button>
      <button class="option" id="mFav"><b>☆ Als Favorit merken</b><span class="klein">Erscheint dann immer oben zum schnellen Öffnen</span></button>
      <button class="option" id="mZer"><b>✂ In Teile zerlegen</b><span class="klein">Zu große Modelle passend fürs Druckbett teilen, mit Dübeln</span></button>
      <button class="option" id="mDup"><b>⧉ Als eigenes Teil verdoppeln</b><span class="klein">z. B. um es in anderer Farbe oder Größe zu drucken</span></button>
      <button class="option" id="mWeg" style="color:var(--err)"><b>Vom Druckbett nehmen</b></button>
      <div class="feld" style="margin-top:12px"><span>Größe (%)</span><div class="zwei"><input type="number" id="mGr" value="${+(t.s * 100).toFixed(1)}"><button class="btn" id="mBett">Aufs Bett einpassen</button></div></div>
      <div class="klein" id="mMass"></div>
      <div class="feld" style="margin-top:12px"><span>Abstand zwischen allen Teilen (mm)</span><input type="number" id="mAbst" value="${S.abstand}" min="1" max="40"></div>
      <label class="feld"><span>Name</span><input type="text" id="mName" value="${esc(t.name)}"></label>`, el => {
      const auf = () => { const g = masse(t); el.querySelector('#mMass').textContent = `Größe: ${zahl(g[0], 1)} × ${zahl(g[1], 1)} × ${zahl(g[2], 1)} mm`; el.querySelector('#mGr').value = +(t.s * 100).toFixed(1); };
      auf();
      el.querySelector('#mFlach').onclick = () => { flachLegen(t); auf(); };
      el.querySelector('#mKipp').onclick = () => { drehen(t, RX(90)); auf(); };
      el.querySelector('#mFuell').onclick = () => { bettFuellen(t); bettBauen(); szeneBauen(); zeigen(); };
      el.querySelector('#mFav').onclick = () => favMerken(t);
      el.querySelector('#mZer').onclick = () => { blattSchliessen(); zerlegen(t); };
      el.querySelector('#mDup').onclick = () => { const n = { ...t, uid: uidZ++, r: t.r.slice(), n: 1, name: t.name + ' (2)' }; T.push(n); S.auswahl = n.uid; neu(); blattSchliessen(); };
      el.querySelector('#mWeg').onclick = () => { T = T.filter(x => x !== t); S.auswahl = T[0]?.uid ?? null; blattSchliessen(); neu(); if (!T.length) schritt(1); };
      el.querySelector('#mGr').onchange = e => { const v = +e.target.value; if (v > 0) { t.s = v / 100; neu(); auf(); } };
      el.querySelector('#mBett').onclick = () => { einpassen(t); auf(); };
      el.querySelector('#mAbst').onchange = e => { S.abstand = Math.max(1, Math.min(40, +e.target.value || 8)); speichern(); neu(); };
      el.querySelector('#mName').onchange = e => { t.name = e.target.value || t.name; zeigen(); };
    });
  },
  slots() {
    blattInhalt('Filamente', `<div class="klein" style="margin-bottom:10px">Die Nummern entsprechen den Plätzen im AMS / CFS bzw. den Druckköpfen. Im Slicer kannst du sie mit dem Drucker abgleichen.</div><div id="slListe"></div><button class="btn voll" id="slPlus" style="margin-top:8px">+ Filament</button>`, el => {
      const zeichne = () => {
        el.querySelector('#slListe').innerHTML = S.filamente.map((f, i) => `<div class="zeile" style="margin-bottom:8px"><b style="width:20px">${i + 1}</b><input type="color" data-fc="${i}" value="${f.farbe}"><div class="chips" style="flex:1">${STD_FARBEN.map(c => `<button class="farbe" style="width:26px;height:26px;background:${c}" data-fq="${i}" data-c="${c}"></button>`).join('')}</div>${S.filamente.length > 1 ? `<button class="btn klein" data-fx="${i}">×</button>` : ''}</div>`).join('');
        el.querySelectorAll('[data-fc]').forEach(x => x.oninput = e => { S.filamente[+x.dataset.fc].farbe = e.target.value; auf(); });
        el.querySelectorAll('[data-fq]').forEach(x => x.onclick = () => { S.filamente[+x.dataset.fq].farbe = x.dataset.c; zeichne(); auf(); });
        el.querySelectorAll('[data-fx]').forEach(x => x.onclick = () => { const i = +x.dataset.fx; S.filamente.splice(i, 1); for (const t of T) if (t.ext > S.filamente.length) t.ext = S.filamente.length; if (S.einSlot > S.filamente.length) S.einSlot = 1; zeichne(); auf(); });
      };
      const auf = () => { speichern(); for (const id in M) faerben(id); Object.keys(matCache).forEach(k => delete matCache[k]); neu(); };
      el.querySelector('#slPlus').onclick = () => { if (S.filamente.length >= 8) return toast('Höchstens 8 Filamente.'); S.filamente.push({ farbe: STD_FARBEN[S.filamente.length] }); zeichne(); auf(); };
      zeichne();
    });
  },
  farbwechsel() {
    const maxH = Math.max(1, ...T.map(t => masse(t)[2]));
    blattInhalt('Farbwechsel ab Höhe', `<div class="klein" style="margin-bottom:10px">Ab dieser Höhe druckt alles in einer anderen Farbe weiter – z. B. für Schilder mit farbiger Schrift oben. Der Drucker wechselt automatisch${drucker().multi ? '' : ' (ohne Mehrfarbsystem: Pause zum Umspulen)'}.</div>
      <div class="feld"><span>Höhe: <b id="fwH"></b></span><input type="range" id="fwR" min="${schicht()}" max="${maxH.toFixed(2)}" step="${schicht()}" value="${(maxH / 2).toFixed(2)}"></div>
      <div class="feld"><span>Neue Farbe</span><div class="farben" id="fwF">${S.filamente.map((f, i) => `<button class="farbe ${i === 1 ? 'an' : ''}" data-fw="${i + 1}" style="background:${f.farbe}">${i + 1}</button>`).join('')}</div></div>
      <button class="btn gruen voll" id="fwAdd">Farbwechsel hinzufügen</button>`, el => {
      let ext = Math.min(2, S.filamente.length);
      const dr = drucker();
      const ebene = () => {
        const z = +el.querySelector('#fwR').value; el.querySelector('#fwH').textContent = `${zahl(z, 2)} mm`;
        if (!ebeneFW) { ebeneFW = new THREE.Mesh(new THREE.PlaneGeometry(dr.x, dr.y), new THREE.MeshBasicMaterial({ color: farbeVon(ext), transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false })); scene.add(ebeneFW); }
        ebeneFW.material.color.set(farbeVon(ext)); ebeneFW.position.set(dr.x / 2, dr.y / 2, z); zeichnen();
      };
      el.querySelector('#fwR').oninput = ebene; ebene();
      el.querySelectorAll('[data-fw]').forEach(b => b.onclick = () => { ext = +b.dataset.fw; el.querySelectorAll('[data-fw]').forEach(x => x.classList.toggle('an', x === b)); ebene(); });
      el.querySelector('#fwAdd').onclick = () => { S.farbwechsel.push({ z: +el.querySelector('#fwR').value, ext }); S.farbwechsel.sort((a, b) => a.z - b.z); blattSchliessen(); neu(); toast('Farbwechsel eingefügt.'); };
    });
  },
};
function blatt(name) { if (BL[name]) BL[name](); }

// Gestalten-Werkzeuge (Vorlagen, Schilder, Bild → 3D, Zeichnen, Modell finden, Baukasten)
gestalten({ BL, blattInhalt, blattSchliessen, toast, esc, zahl, farbeVon, S, THREE,
  ladeTeile: (teile, titel) => laden(teile, { zusammen: true, titel }) });

// ───────── Bedienung ─────────
$('#oeffnen').onclick = () => $('#datei').click();
$('#weiteres').onclick = () => $('#datei').click();
$('#datei').onchange = e => { const f = [...e.target.files]; e.target.value = ''; if (f.length) laden(f); };
$$('#schritte button').forEach(b => b.onclick = () => { const s = +b.dataset.s; if (s > 1 && !T.length) return toast('Erst ein Modell wählen.'); schritt(s); });
$('#zurueck').onclick = () => schritt(Math.max(1, S.schritt - 1));
$('#weiter').onclick = () => { if (S.schritt === 1) schritt(2); else if (S.schritt === 2) schritt(3); else herunterladen(); };
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => { e.preventDefault(); const f = [...(e.dataTransfer?.files || [])]; if (f.length) laden(f); });
function thema() {
  const dunkel = S.thema ? S.thema === 'dunkel' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.classList.toggle('dunkel', dunkel);
  document.querySelector('meta[name=theme-color]').content = dunkel ? '#141517' : '#F4F5F6';
  scene.background = new THREE.Color(farbeCSS('--cv'));
  bettBauen(); zeichnen();
}
$('#thema').onclick = () => { const jetzt = document.documentElement.classList.contains('dunkel'); S.thema = jetzt ? 'hell' : 'dunkel'; speichern(); thema(); };
thema(); zeigen(); schritt(1);
window.__formwerk = { cam, teileG, cv };
