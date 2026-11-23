// Formwerk · Selbst gestalten: Vorlagen, Schilder & QR, Bild → 3D, Zeichnen, Modell finden
import * as THREE from 'three';
import { OrbitControls } from '/vendor/OrbitControls.js';

// ───────── Dreiecke ─────────
function geoTris(geo) { const g = geo.index ? geo.toNonIndexed() : geo; return new Float32Array(g.attributes.position.array); }
function verbinden(listen) { let n = 0; for (const l of listen) n += l.length; const o = new Float32Array(n); let i = 0; for (const l of listen) { o.set(l, i); i += l.length; } return o; }
function kiste(x0, y0, z0, x1, y1, z1) {
  const v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]];
  const f = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]];
  const o = new Float32Array(108); let i = 0; for (const t of f) for (const k of t) { o[i++] = v[k][0]; o[i++] = v[k][1]; o[i++] = v[k][2]; } return o;
}
function verschieben(tris, dx, dy, dz) { const o = new Float32Array(tris); for (let i = 0; i < o.length; i += 3) { o[i] += dx; o[i + 1] += dy; o[i + 2] += dz; } return o; }
function stl(tris) {
  const n = tris.length / 9, buf = new ArrayBuffer(84 + n * 50), dv = new DataView(buf);
  dv.setUint32(80, n, true); let o = 84;
  for (let i = 0; i < tris.length; i += 9) {
    const ux = tris[i + 3] - tris[i], uy = tris[i + 4] - tris[i + 1], uz = tris[i + 5] - tris[i + 2], vx = tris[i + 6] - tris[i], vy = tris[i + 7] - tris[i + 1], vz = tris[i + 8] - tris[i + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx, l = Math.hypot(nx, ny, nz) || 1;
    dv.setFloat32(o, nx / l, true); dv.setFloat32(o + 4, ny / l, true); dv.setFloat32(o + 8, nz / l, true); o += 12;
    for (let k = 0; k < 9; k++) { dv.setFloat32(o, tris[i + k], true); o += 4; }
    o += 2;
  }
  return new Blob([buf], { type: 'model/stl' });
}

// ───────── 2D-Konturen ─────────
const flaeche = p => { let a = 0; for (let i = 0; i < p.length; i++) { const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length]; a += x1 * y2 - x2 * y1; } return a / 2; };
const innen = (pt, p) => { let c = false; for (let i = 0, j = p.length - 1; i < p.length; j = i++) { const [xi, yi] = p[i], [xj, yj] = p[j]; if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) c = !c; } return c; };
// Konturen → THREE.Shapes (Löcher nach Verschachtelung, egal wie herum gezeichnet)
function formen(konturen) {
  const k = konturen.filter(p => p.length > 2 && Math.abs(flaeche(p)) > 1e-4).map(p => ({ p, a: Math.abs(flaeche(p)) })).sort((a, b) => b.a - a.a);
  for (const c of k) { c.eltern = null; c.tiefe = 0; for (const d of k) if (d !== c && d.a > c.a && innen(c.p[0], d.p) && (!c.eltern || d.a < c.eltern.a)) c.eltern = d; }
  const tiefe = c => c.eltern ? 1 + tiefe(c.eltern) : 0;
  const shapes = [];
  for (const c of k) if (tiefe(c) % 2 === 0) {
    const pts = flaeche(c.p) < 0 ? c.p.slice().reverse() : c.p;
    const s = new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)));
    for (const h of k) if (h.eltern === c) { const hp = flaeche(h.p) > 0 ? h.p.slice().reverse() : h.p; s.holes.push(new THREE.Path(hp.map(([x, y]) => new THREE.Vector2(x, y)))); }
    shapes.push(s);
  }
  return shapes;
}
function hoch(konturen, h, z0 = 0) {
  const sh = formen(konturen); if (!sh.length || h <= 0) return new Float32Array(0);
  const g = new THREE.ExtrudeGeometry(sh, { depth: h, bevelEnabled: false, curveSegments: 18 });
  g.translate(0, 0, z0); return geoTris(g);
}
const verschiebe = (konturen, dx, dy, k = 1) => konturen.map(p => p.map(([x, y]) => [x * k + dx, y * k + dy]));
function rundRechteck(w, h, r, cx = 0, cy = 0) {
  r = Math.max(0, Math.min(r, w / 2 - 0.01, h / 2 - 0.01)); const p = [];
  if (r < 0.05) return [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]];
  const ecken = [[w / 2 - r, h / 2 - r, 0], [-w / 2 + r, h / 2 - r, 90], [-w / 2 + r, -h / 2 + r, 180], [w / 2 - r, -h / 2 + r, 270]];
  for (const [x, y, a0] of ecken) for (let i = 0; i <= 8; i++) { const a = (a0 + i * 90 / 8) * Math.PI / 180; p.push([cx + x + r * Math.cos(a), cy + y + r * Math.sin(a)]); }
  return p;
}
const kreis = (d, cx = 0, cy = 0, n = 64) => Array.from({ length: n }, (_, i) => [cx + d / 2 * Math.cos(i / n * Math.PI * 2), cy + d / 2 * Math.sin(i / n * Math.PI * 2)]);
const vieleck = (d, n, cx = 0, cy = 0, rot = 90) => Array.from({ length: n }, (_, i) => { const a = (rot + i * 360 / n) * Math.PI / 180; return [cx + d / 2 * Math.cos(a), cy + d / 2 * Math.sin(a)]; });
const stern = (d, n = 5) => Array.from({ length: n * 2 }, (_, i) => { const r = i % 2 ? d * 0.2 : d / 2, a = (90 + i * 180 / n) * Math.PI / 180; return [r * Math.cos(a), r * Math.sin(a)]; });
const herz = (w, h) => Array.from({ length: 80 }, (_, i) => { const t = i / 80 * Math.PI * 2; const x = 16 * Math.sin(t) ** 3, y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t); return [x / 32 * w, (y + 2) / 30 * h]; });
const ellipse = (w, h) => Array.from({ length: 72 }, (_, i) => [w / 2 * Math.cos(i / 72 * Math.PI * 2), h / 2 * Math.sin(i / 72 * Math.PI * 2)]);
function grenzen(konturen) { let x1 = 1e9, y1 = 1e9, x2 = -1e9, y2 = -1e9; for (const p of konturen) for (const [x, y] of p) { x1 = Math.min(x1, x); y1 = Math.min(y1, y); x2 = Math.max(x2, x); y2 = Math.max(y2, y); } return { x1, y1, x2, y2, w: x2 - x1, h: y2 - y1 }; }

// ───────── Schrift ─────────
let schriftP = null;
function schrift() { return schriftP || (schriftP = (async () => { const ot = (await import('/vendor/opentype.min.js')).default; return ot.parse(await (await fetch('/vendor/schrift.woff')).arrayBuffer()); })()); }
async function textKonturen(text, groesse) {
  if (!text.trim()) return [];
  const f = await schrift();
  const capH = (f.tables.os2 && f.tables.os2.sCapHeight) || 0.72 * f.unitsPerEm;
  const em = groesse / (capH / f.unitsPerEm);
  const out = []; let cur = null, x = 0, y = 0;
  for (const c of f.getPath(text, 0, 0, em).commands) {
    if (c.type === 'M') { if (cur && cur.length > 2) out.push(cur); cur = [[c.x, -c.y]]; x = c.x; y = c.y; }
    else if (c.type === 'L') { cur.push([c.x, -c.y]); x = c.x; y = c.y; }
    else if (c.type === 'Q') { for (let i = 1; i <= 6; i++) { const t = i / 6, a = (1 - t) ** 2, b = 2 * (1 - t) * t, d = t * t; cur.push([a * x + b * c.x1 + d * c.x, -(a * y + b * c.y1 + d * c.y)]); } x = c.x; y = c.y; }
    else if (c.type === 'C') { for (let i = 1; i <= 8; i++) { const t = i / 8, a = (1 - t) ** 3, b = 3 * (1 - t) ** 2 * t, e = 3 * (1 - t) * t * t, d = t ** 3; cur.push([a * x + b * c.x1 + e * c.x2 + d * c.x, -(a * y + b * c.y1 + e * c.y2 + d * c.y)]); } x = c.x; y = c.y; }
    else if (c.type === 'Z') { if (cur && cur.length > 2) out.push(cur); cur = null; }
  }
  if (cur && cur.length > 2) out.push(cur);
  return out;
}
// Text mittig in ein Feld setzen (verkleinert, falls zu breit)
async function textIn(text, groesse, cx, cy, maxW, maxH = 1e9) {
  let k = await textKonturen(text, groesse); if (!k.length) return [];
  const g = grenzen(k), f = Math.min(1, maxW / g.w, maxH / g.h);
  return verschiebe(k, 0, 0, f).map(p => p.map(([x, y]) => [x - (g.x1 + g.w / 2) * f + cx, y - (g.y1 + g.h / 2) * f + cy]));
}

// ───────── QR ─────────
let qrP = null;
async function qrModule(text) {
  const q = (await (qrP || (qrP = import('/vendor/qrcode.js')))).default;
  q.stringToBytes = s => [...new TextEncoder().encode(s)];
  const c = q(0, 'M'); c.addData(text); c.make();
  const n = c.getModuleCount(); return { n, dunkel: (r, k) => c.isDark(r, k) };
}
// Raster → Rechtecke (zeilenweise Läufe, dann gleich breite Läufe nach unten zusammenfassen)
function rechtecke(w, h, an) {
  const offen = new Map(), out = [];
  for (let y = 0; y < h; y++) {
    const laeufe = []; let x = 0;
    while (x < w) { if (an(x, y)) { const s = x; while (x < w && an(x, y)) x++; laeufe.push([s, x]); } else x++; }
    const jetzt = new Map();
    for (const [a, b] of laeufe) { const k = a + ',' + b, o = offen.get(k); if (o) { o.y2 = y + 1; jetzt.set(k, o); offen.delete(k); } else jetzt.set(k, { x1: a, x2: b, y1: y, y2: y + 1 }); }
    for (const o of offen.values()) out.push(o);
    offen.clear(); for (const [k, o] of jetzt) offen.set(k, o);
  }
  for (const o of offen.values()) out.push(o);
  return out;
}

// ───────── Höhenfeld (Lithophane) ─────────
function hoehenfeld(nx, ny, p, H) {
  const tris = []; const T = (a, b, c) => tris.push(...a, ...b, ...c);
  const top = (i, j) => [i * p, j * p, H[j * nx + i]], bot = (i, j) => [i * p, j * p, 0];
  for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    T(top(i, j), top(i + 1, j), top(i + 1, j + 1)); T(top(i, j), top(i + 1, j + 1), top(i, j + 1));
    T(bot(i, j), bot(i + 1, j + 1), bot(i + 1, j)); T(bot(i, j), bot(i, j + 1), bot(i + 1, j + 1));
  }
  for (let i = 0; i < nx - 1; i++) {
    T(bot(i, 0), bot(i + 1, 0), top(i + 1, 0)); T(bot(i, 0), top(i + 1, 0), top(i, 0));
    const j = ny - 1; T(bot(i + 1, j), bot(i, j), top(i, j)); T(bot(i + 1, j), top(i, j), top(i + 1, j));
  }
  for (let j = 0; j < ny - 1; j++) {
    T(bot(0, j + 1), bot(0, j), top(0, j)); T(bot(0, j + 1), top(0, j), top(0, j + 1));
    const i = nx - 1; T(bot(i, j), bot(i, j + 1), top(i, j + 1)); T(bot(i, j), top(i, j + 1), top(i, j));
  }
  return new Float32Array(tris);
}

// ───────── Vorlagen ─────────
const lathe = (profil, n = 72) => { const g = new THREE.LatheGeometry(profil.map(([r, z]) => new THREE.Vector2(r, z)), n); g.rotateX(Math.PI / 2); return geoTris(g); };
const ring = (da, di, h, z0 = 0) => hoch([kreis(da), kreis(di)], h, z0);
const VORLAGEN = [
  { id: 'box', name: 'Box mit Deckel', kurz: 'Aufbewahrungsbox, Deckel steckt fest', gruppe: 'Boxen', p: { breite: 80, tiefe: 60, hoehe: 40, wand: 2, rundung: 6 },
    bau: v => { const { breite: b, tiefe: t, hoehe: h, wand: w, rundung: r } = v, tol = 0.25;
      const box = verbinden([hoch([rundRechteck(b, t, r)], 2), hoch([rundRechteck(b, t, r), rundRechteck(b - 2 * w, t - 2 * w, r - w)], h - 2, 2)]);
      const dx = b + 8, deckel = verbinden([hoch([rundRechteck(b, t, r, dx)], 2), hoch([rundRechteck(b - 2 * w - 2 * tol, t - 2 * w - 2 * tol, r - w, dx), rundRechteck(b - 4 * w - 2 * tol, t - 4 * w - 2 * tol, r - 2 * w, dx)], 5, 2)]);
      return [{ name: 'Box', ext: 1, tris: box }, { name: 'Deckel', ext: 1, tris: deckel }]; } },
  { id: 'dose', name: 'Runde Dose', kurz: 'Dose mit Steckdeckel', gruppe: 'Boxen', p: { durchmesser: 70, hoehe: 50, wand: 2 },
    bau: v => { const { durchmesser: d, hoehe: h, wand: w } = v, tol = 0.25, dx = d + 8;
      return [{ name: 'Dose', ext: 1, tris: verbinden([hoch([kreis(d)], 2), ring(d, d - 2 * w, h - 2, 2)]) },
        { name: 'Deckel', ext: 1, tris: verbinden([hoch([kreis(d, dx)], 2), hoch([kreis(d - 2 * w - 2 * tol, dx), kreis(d - 4 * w - 2 * tol, dx)], 5, 2)]) }]; } },
  { id: 'sortier', name: 'Sortierkasten', kurz: 'Kasten mit Fächern', gruppe: 'Boxen', p: { breite: 120, tiefe: 80, hoehe: 35, faecher_x: 3, faecher_y: 2, wand: 1.6 },
    bau: v => { const { breite: b, tiefe: t, hoehe: h, wand: w } = v, nx = Math.max(1, Math.round(v.faecher_x)), ny = Math.max(1, Math.round(v.faecher_y));
      const l = [hoch([rundRechteck(b, t, 4)], 1.6), hoch([rundRechteck(b, t, 4), rundRechteck(b - 2 * w, t - 2 * w, 4 - w)], h - 1.6, 1.6)];
      for (let i = 1; i < nx; i++) { const x = -b / 2 + i * b / nx; l.push(kiste(x - w / 2, -t / 2 + w / 2, 1.6, x + w / 2, t / 2 - w / 2, h - 2)); }
      for (let j = 1; j < ny; j++) { const y = -t / 2 + j * t / ny; l.push(kiste(-b / 2 + w / 2, y - w / 2, 1.6, b / 2 - w / 2, y + w / 2, h - 2)); }
      return [{ name: 'Sortierkasten', ext: 1, tris: verbinden(l) }]; } },
  { id: 'stift', name: 'Stifthalter', kurz: 'Becher für Stifte & Pinsel', gruppe: 'Halter', p: { durchmesser: 70, hoehe: 95, wand: 2, ecken: 6 },
    bau: v => { const n = Math.round(v.ecken), d = v.durchmesser, a = n >= 3 && n < 20 ? vieleck(d, n) : kreis(d), i = n >= 3 && n < 20 ? vieleck(d - 2 * v.wand / Math.cos(Math.PI / n), n) : kreis(d - 2 * v.wand);
      return [{ name: 'Stifthalter', ext: 1, tris: verbinden([hoch([a], 2.4), hoch([a, i], v.hoehe - 2.4, 2.4)]) }]; } },
  { id: 'topf', name: 'Blumentopf', kurz: 'mit Abflussloch und Untersetzer', gruppe: 'Haus', p: { oben: 100, unten: 75, hoehe: 90, wand: 2, abfluss: 8 },
    bau: v => { const R1 = v.unten / 2, R2 = v.oben / 2, h = v.hoehe, w = v.wand, b = 2.4, rh = Math.max(0.01, v.abfluss / 2);
      const k = (R2 - R1) / h;
      const topf = lathe([[rh, 0], [R1, 0], [R2, h], [R2 - w, h], [R1 - w + k * b, b], [rh, b]]);
      const dx = R2 + R1 + 20, Ru = R1 + 10;
      const unter = verschieben(verbinden([hoch([kreis(Ru * 2)], 2), ring(Ru * 2, Ru * 2 - 4, 8, 2)]), dx, 0, 0);
      return [{ name: 'Topf', ext: 1, tris: topf }, { name: 'Untersetzer', ext: 1, tris: unter }]; } },
  { id: 'unters', name: 'Untersetzer', kurz: 'rund mit Rand', gruppe: 'Haus', p: { durchmesser: 95, rand: 3, hoehe: 4 },
    bau: v => [{ name: 'Untersetzer', ext: 1, tris: verbinden([hoch([kreis(v.durchmesser)], 1.6), ring(v.durchmesser, v.durchmesser - 2 * v.rand, v.hoehe - 1.6, 1.6)]) }] },
  { id: 'schale', name: 'Schale', kurz: 'runde Schale', gruppe: 'Haus', p: { durchmesser: 120, hoehe: 45, wand: 2 },
    bau: v => { const R = v.durchmesser / 2, h = v.hoehe, w = v.wand, pr = [[0, 0]];
      for (let i = 0; i <= 24; i++) { const t = i / 24; pr.push([R * 0.45 + (R - R * 0.45) * Math.sin(t * Math.PI / 2), h * (1 - Math.cos(t * Math.PI / 2))]); }
      pr.push([R - w, h]); for (let i = 24; i >= 0; i--) { const t = i / 24; pr.push([Math.max(0.01, R * 0.45 - w + (R - R * 0.45) * Math.sin(t * Math.PI / 2)), Math.max(2, h * (1 - Math.cos(t * Math.PI / 2)))]); }
      pr.push([0.01, 2]); return [{ name: 'Schale', ext: 1, tris: lathe(pr) }]; } },
  { id: 'staender', name: 'Handyständer', kurz: 'schräger Ständer für Handy oder Tablet', gruppe: 'Halter', p: { breite: 70, winkel: 65, dicke_geraet: 12 },
    bau: v => { const a = Math.max(35, Math.min(85, v.winkel)) * Math.PI / 180, L = 95, t = 5, s = v.dicke_geraet + 1, ca = Math.cos(a), sa = Math.sin(a);
      const oben = [18 - ca * L, 6 + sa * L], bx = Math.min(-10, 18 - ca * L * 0.9);
      const prof = [[bx, 0], [62, 0], [62, 6], [22 + s, 6], [22 + s, 18], [18 + s, 18], [18 + s, 6], [18, 6], oben, [oben[0] - sa * t, oben[1] - ca * t], [18 - t / sa, 6], [bx, 6]];
      const g = new THREE.ExtrudeGeometry(formen([prof]), { depth: v.breite, bevelEnabled: false }); g.translate(0, 0, -v.breite / 2); g.rotateX(Math.PI / 2);
      return [{ name: 'Handyständer', ext: 1, tris: geoTris(g) }]; } },
  { id: 'clip', name: 'Kabelhalter', kurz: 'Clip zum Aufkleben', gruppe: 'Halter', p: { kabel: 6, breite: 12, anzahl: 3 },
    bau: v => { const d = v.kabel, n = Math.max(1, Math.round(v.anzahl)), ab = d + 6, L = n * ab + 4, l = [kiste(-L / 2, -v.breite / 2, 0, L / 2, v.breite / 2, 2)];
      for (let i = 0; i < n; i++) { const cx = -L / 2 + 2 + ab / 2 + i * ab; const ra = d / 2 + 1.6, ri = d / 2 + 0.1;
        const cy = 2 + ra - 0.8, ringk = [...Array.from({ length: 41 }, (_, k) => { const a = (120 + k * 300 / 40) * Math.PI / 180; return [cx + ra * Math.cos(a), cy + ra * Math.sin(a)]; }), ...Array.from({ length: 41 }, (_, k) => { const a = (420 - k * 300 / 40) * Math.PI / 180; return [cx + ri * Math.cos(a), cy + ri * Math.sin(a)]; })];
        const g = new THREE.ExtrudeGeometry(formen([ringk]), { depth: v.breite, bevelEnabled: false }); g.translate(0, 0, -v.breite / 2); g.rotateX(Math.PI / 2); l.push(geoTris(g)); }
      return [{ name: 'Kabelhalter', ext: 1, tris: verbinden(l) }]; } },
  { id: 'ring', name: 'Distanzring', kurz: 'Abstandshalter / Scheibe', gruppe: 'Technik', p: { innen: 5.3, aussen: 12, hoehe: 5 },
    bau: v => [{ name: 'Distanzring', ext: 1, tris: ring(v.aussen, v.innen, v.hoehe) }] },
  { id: 'knopf', name: 'Möbelknopf', kurz: 'mit Loch für eine M4-Schraube', gruppe: 'Technik', p: { durchmesser: 30, hoehe: 22, loch: 3.4 },
    bau: v => { const R = v.durchmesser / 2, h = v.hoehe, rl = v.loch / 2;
      return [{ name: 'Möbelknopf', ext: 1, tris: lathe([[rl, 0], [R * 0.5, 0], [R * 0.5, h * 0.45], [R, h * 0.75], [R, h - 2], [R - 2, h], [0.01, h], [0.01, h * 0.6], [rl, h * 0.6]]) }]; } },
  { id: 'wuerfel', name: 'Kalibrierwürfel', kurz: 'Würfel mit X/Y/Z zum Testen', gruppe: 'Technik', p: { kante: 20 },
    bau: async v => { const k = v.kante, t = await textIn('XYZ', k * 0.28, 0, 0, k * 0.8);
      return [{ name: 'Würfel', ext: 1, tris: kiste(-k / 2, -k / 2, 0, k / 2, k / 2, k) }, { name: 'Schrift', ext: 2, tris: hoch(t, 0.6, k) }]; } },
  { id: 'schachtel', name: 'Schubladeneinsatz', kurz: 'flache Schale mit Fächern', gruppe: 'Boxen', p: { breite: 150, tiefe: 100, hoehe: 25, faecher_x: 4, faecher_y: 1, wand: 1.2 },
    bau: v => VORLAGEN.find(x => x.id === 'sortier').bau(v).map(t => ({ ...t, name: 'Einsatz' })) },
];
const NAMEN = { breite: 'Breite', tiefe: 'Tiefe', hoehe: 'Höhe', wand: 'Wandstärke', rundung: 'Eckenrundung', durchmesser: 'Durchmesser', faecher_x: 'Fächer quer', faecher_y: 'Fächer längs', ecken: 'Ecken (0 = rund)', oben: 'Ø oben', unten: 'Ø unten', abfluss: 'Abflussloch Ø', rand: 'Randbreite', winkel: 'Winkel (°)', dicke_geraet: 'Gerätedicke', kabel: 'Kabel Ø', anzahl: 'Anzahl', innen: 'Ø innen', aussen: 'Ø außen', loch: 'Loch Ø', kante: 'Kantenlänge' };
const EINHEIT = k => ['faecher_x', 'faecher_y', 'ecken', 'anzahl', 'winkel'].includes(k) ? '' : ' mm';

// ───────── Vorschau ─────────
let pv = null;
function vorschau3D(canvas, teile, farbeVon) {
  if (!pv || pv.canvas !== canvas) {
    pv?.r.dispose();
    const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); r.setPixelRatio(Math.min(devicePixelRatio, 2));
    const sc = new THREE.Scene(), cam = new THREE.PerspectiveCamera(30, 1, 0.1, 5000); cam.up.set(0, 0, 1);
    sc.add(new THREE.HemisphereLight(0xffffff, 0x888888, 1.7)); const l = new THREE.DirectionalLight(0xffffff, 1.4); l.position.set(-0.5, -1, 1.5); sc.add(l);
    const ctl = new OrbitControls(cam, canvas); const g = new THREE.Group(); sc.add(g);
    pv = { canvas, r, sc, cam, ctl, g }; ctl.addEventListener('change', () => r.render(sc, cam));
  }
  const { r, sc, cam, ctl, g } = pv;
  const w = canvas.clientWidth || 300, h = canvas.clientHeight || 220; r.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
  g.clear();
  const box = new THREE.Box3();
  for (const t of teile) {
    if (!t.tris.length) continue;
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(t.tris, 3)); geo.computeVertexNormals(); geo.computeBoundingBox(); box.union(geo.boundingBox);
    g.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: farbeVon(t.ext), roughness: 0.6, flatShading: true, side: THREE.DoubleSide })));
  }
  if (box.isEmpty()) { r.render(sc, cam); return; }
  const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3()).length();
  ctl.target.copy(c); cam.position.set(c.x - s * 0.35, c.y - s * 1.1, c.z + s * 0.9); ctl.update(); r.render(sc, cam);
}

// ───────── Blätter ─────────
export function gestalten(ctx) {
  const { BL, blattInhalt, toast, esc, zahl, farbeVon, ladeTeile } = ctx;
  const auf3D = (titel, teile) => {
    const leer = teile.filter(t => t.tris.length).length === 0;
    if (leer) return toast('Da ist noch nichts zu drucken.');
    ctx.blattSchliessen();
    ladeTeile(teile.filter(t => t.tris.length).map(t => ({ name: `${t.name}.stl`, blob: stl(t.tris), ext: t.ext, teilname: t.name })), titel);
  };
  const leiste = (zahlFeld = '') => `<div class="vorschau2d" style="padding:0"><canvas id="gV" style="width:100%;height:230px;max-height:none"></canvas></div>${zahlFeld}`;

  BL.vorlagen = () => {
    const gruppen = ['Alle', ...new Set(VORLAGEN.map(v => v.gruppe))];
    blattInhalt('Vorlagen mit Maßen', `<input class="eing" id="vSuche" placeholder="Vorlage suchen, z. B. Halter, Box, Würfel" style="margin-bottom:10px">
      <div class="chips" id="vGr" style="margin-bottom:12px">${gruppen.map((g, i) => `<button class="chip ${i ? '' : 'an'}" data-g="${g}">${g === 'Alle' ? `Alle (${VORLAGEN.length})` : g}</button>`).join('')}</div><div class="raster" id="vListe"></div>`, el => {
      let gr = 'Alle';
      const zeichne = () => { const q = el.querySelector('#vSuche').value.toLowerCase();
        el.querySelector('#vListe').innerHTML = VORLAGEN.filter(v => (gr === 'Alle' || v.gruppe === gr) && (v.name + v.kurz).toLowerCase().includes(q)).map(v => `<button class="option" data-v="${v.id}"><b>${esc(v.name)}</b><span class="klein">${esc(v.kurz)}</span></button>`).join('') || '<div class="leer">Nichts gefunden.</div>';
        el.querySelectorAll('[data-v]').forEach(b => b.onclick = () => vorlage(VORLAGEN.find(v => v.id === b.dataset.v))); };
      el.querySelector('#vSuche').oninput = zeichne;
      el.querySelectorAll('[data-g]').forEach(b => b.onclick = () => { gr = b.dataset.g; el.querySelectorAll('[data-g]').forEach(x => x.classList.toggle('an', x === b)); zeichne(); });
      zeichne();
    });
  };
  function vorlage(v) {
    const werte = { ...v.p };
    blattInhalt(v.name, `${leiste()}<div class="zwei">${Object.keys(v.p).map(k => `<label class="feld"><span>${NAMEN[k] || k}${EINHEIT(k)}</span><input type="number" step="0.1" data-k="${k}" value="${v.p[k]}"></label>`).join('')}</div>
      <button class="btn gruen voll" id="vOk">Aufs Druckbett</button><button class="btn voll" id="vZur" style="margin-top:8px">← Alle Vorlagen</button>`, el => {
      let teile = [];
      const neu = async () => { try { teile = await v.bau(werte); vorschau3D(el.querySelector('#gV'), teile, farbeVon); } catch (e) { toast('Diese Maße gehen nicht: ' + e.message); } };
      el.querySelectorAll('[data-k]').forEach(i => i.onchange = () => { const x = +i.value; if (x > 0 || i.dataset.k === 'ecken') { werte[i.dataset.k] = x; neu(); } });
      el.querySelector('#vOk').onclick = () => auf3D(v.name, teile);
      el.querySelector('#vZur').onclick = () => BL.vorlagen();
      setTimeout(neu, 30);
    });
  }

  // Schilder, Anhänger, QR, Schriftzug, eigene Formen
  const SCHILD = { art: 'name', text: 'Benny’s 3D Stube', text2: '', qr: 'https://', breite: 80, hoehe: 30, dicke: 3, relief: 1, form: 'rund', loecher: 'keine', lochD: 4, rand: false };
  BL.schild = (art) => {
    if (art) SCHILD.art = art;
    const ARTEN = [['name', 'Namensschild'], ['anhaenger', 'Schlüsselanhänger'], ['qr', 'QR-Code-Schild'], ['schrift', 'Nur Schriftzug'], ['form', 'Eigene Form']];
    const FORMEN = [['rechteck', 'Rechteck'], ['rund', 'Abgerundet'], ['kreis', 'Kreis'], ['oval', 'Oval'], ['sechseck', 'Sechseck'], ['stern', 'Stern'], ['herz', 'Herz']];
    const s = SCHILD;
    blattInhalt(s.art === 'form' ? 'Baukasten' : 'Schild, Anhänger & QR', `<div class="chips" style="margin-bottom:12px">${ARTEN.map(([k, n]) => `<button class="chip ${k === s.art ? 'an' : ''}" data-art="${k}">${n}</button>`).join('')}</div>
      ${leiste()}
      <div class="zwei"><label class="feld"><span>Text</span><input type="text" id="sT" value="${esc(s.text)}"></label><label class="feld"><span>2. Zeile (optional)</span><input type="text" id="sT2" value="${esc(s.text2)}"></label></div>
      ${s.art === 'qr' ? `<label class="feld"><span>QR-Code-Inhalt (Link oder Text)</span><input type="url" id="sQ" value="${esc(s.qr)}"></label>` : ''}
      ${s.art === 'form' ? `<div class="feld"><span>Form</span><div class="chips">${FORMEN.map(([k, n]) => `<button class="chip ${k === s.form ? 'an' : ''}" data-form="${k}">${n}</button>`).join('')}</div></div>` : ''}
      <div class="drei"><label class="feld"><span>Breite mm</span><input type="number" id="sB" value="${s.breite}"></label><label class="feld"><span>Höhe mm</span><input type="number" id="sH" value="${s.hoehe}"></label><label class="feld"><span>Dicke mm</span><input type="number" id="sD" value="${s.dicke}" step="0.2"></label></div>
      <div class="zwei"><label class="feld"><span>Schrift erhaben mm</span><input type="number" id="sR" value="${s.relief}" step="0.2"></label>
      ${s.art === 'form' || s.art === 'name' ? `<label class="feld"><span>Löcher</span><select id="sL">${[['keine', 'keine'], ['oben', '1 oben'], ['seiten', '2 seitlich'], ['ecken', '4 Ecken'], ['mitte', '1 in der Mitte']].map(([k, n]) => `<option value="${k}" ${k === s.loecher ? 'selected' : ''}>${n}</option>`).join('')}</select></label>` : '<span></span>'}</div>
      <label class="zeile klein" style="margin-bottom:12px"><input type="checkbox" id="sRand" ${s.rand ? 'checked' : ''}> erhabener Rand in Schriftfarbe</label>
      <div class="klein" style="margin-bottom:10px">Schild = Filament 1, Schrift${s.art === 'qr' ? ' und QR-Code' : ''} = Filament 2 – mit AMS in einem Druck zweifarbig, sonst per „Farbwechsel ab Höhe“.</div>
      <button class="btn gruen voll" id="sOk">Aufs Druckbett</button>`, el => {
      let teile = [];
      const lese = () => { s.text = el.querySelector('#sT').value; s.text2 = el.querySelector('#sT2').value; s.qr = el.querySelector('#sQ')?.value ?? s.qr; s.breite = +el.querySelector('#sB').value || 80; s.hoehe = +el.querySelector('#sH').value || 30; s.dicke = +el.querySelector('#sD').value || 3; s.relief = +el.querySelector('#sR').value || 0; s.loecher = el.querySelector('#sL')?.value ?? s.loecher; s.rand = el.querySelector('#sRand').checked; };
      const neu = async () => { lese(); try { teile = await schildBauen(s); vorschau3D(el.querySelector('#gV'), teile, farbeVon); } catch (e) { console.error(e); toast(e.message); } };
      el.querySelectorAll('input,select').forEach(i => i.onchange = neu);
      el.querySelectorAll('[data-art]').forEach(b => b.onclick = () => { lese(); s.art = b.dataset.art; if (s.art === 'anhaenger') { s.breite = 55; s.hoehe = 22; } if (s.art === 'qr') { s.breite = 70; s.hoehe = 36; } BL.schild(); });
      el.querySelectorAll('[data-form]').forEach(b => b.onclick = () => { lese(); s.form = b.dataset.form; BL.schild(); });
      el.querySelector('#sOk').onclick = () => { lese(); auf3D(s.text || 'Schild', teile); };
      setTimeout(neu, 30);
    });
  };
  BL.baukasten = () => BL.schild('form');
  async function schildBauen(s) {
    const B = s.breite, H = s.hoehe, D = s.dicke, R = s.relief, teile = [];
    let basis, feld = { cx: 0, cy: 0, w: B - 6, h: H - 6 };
    const loecher = [];
    if (s.art === 'anhaenger') {
      basis = [rundRechteck(B, H, H / 2.6)]; loecher.push(kreis(5, -B / 2 + H / 2.6, 0)); feld = { cx: H / 2.6 / 2 + 1.5, cy: 0, w: B - H / 1.3 - 6, h: H - 6 };
    } else if (s.art === 'schrift') {
      const z1 = await textIn(s.text, Math.min(H * 0.8, 40), 0, 0, B), g = grenzen(z1);
      if (!z1.length) return [];
      teile.push({ name: 'Schriftzug', ext: 1, tris: hoch(z1, D) });
      teile.push({ name: 'Steg', ext: 1, tris: hoch([rundRechteck(g.w + 2, Math.max(1.6, H * 0.08), 0.8, 0, g.y1 + Math.max(0.8, H * 0.04))], D) });
      return teile;
    } else if (s.art === 'form') {
      basis = [{ rechteck: rundRechteck(B, H, 0), rund: rundRechteck(B, H, Math.min(B, H) * 0.18), kreis: ellipse(Math.min(B, H), Math.min(B, H)), oval: ellipse(B, H), sechseck: vieleck(Math.min(B, H) * 1.1, 6, 0, 0, 0), stern: stern(Math.min(B, H)), herz: herz(B, H) }[s.form]];
      if (['kreis', 'sechseck', 'stern', 'herz'].includes(s.form)) feld = { cx: 0, cy: s.form === 'herz' ? H * 0.08 : 0, w: Math.min(B, H) * 0.62, h: Math.min(B, H) * 0.42 };
    } else basis = [rundRechteck(B, H, Math.min(4, H / 5))];
    const lochD = Math.max(2, s.lochD), m = lochD / 2 + 3;
    if (s.art === 'name' || s.art === 'form') {
      const L = { oben: [[0, H / 2 - m]], seiten: [[-B / 2 + m, 0], [B / 2 - m, 0]], ecken: [[-B / 2 + m, H / 2 - m], [B / 2 - m, H / 2 - m], [-B / 2 + m, -H / 2 + m], [B / 2 - m, -H / 2 + m]], mitte: [[0, 0]] }[s.loecher] || [];
      for (const [x, y] of L) loecher.push(kreis(lochD, x, y, 40));
      if (s.loecher === 'seiten') { feld.w -= 2 * (lochD + 3); }
      if (s.loecher === 'ecken') { feld.w -= 2 * (lochD + 3); }
      if (s.loecher === 'oben') { feld.h -= lochD + 3; feld.cy -= (lochD + 3) / 2; }
    }
    teile.push({ name: 'Schild', ext: 1, tris: hoch([...basis, ...loecher], D) });
    const oben = [];
    if (s.art === 'qr' && s.qr.trim()) {
      const q = await qrModule(s.qr.trim()), seite = H - 6, mod = seite / q.n, x0 = -B / 2 + 3, y0 = -seite / 2;
      for (const r of rechtecke(q.n, q.n, (x, y) => q.dunkel(y, x))) oben.push(kiste(x0 + r.x1 * mod, y0 + (q.n - r.y2) * mod, D, x0 + r.x2 * mod, y0 + (q.n - r.y1) * mod, D + R));
      feld = { cx: (seite + 3) / 2, cy: 0, w: B - seite - 9, h: H - 6 };
    }
    if (s.rand && basis[0]) {
      const g = grenzen(basis), k = Math.max(0.5, Math.min((g.w - 3) / g.w, (g.h - 3) / g.h));
      oben.push(hoch([basis[0], verschiebe([basis[0]], 0, 0, k)[0]], R, D));
    }
    let zeilen = [s.text, s.text2].filter(x => x && x.trim());
    // langer Text in schmalem Feld: auf zwei Zeilen umbrechen
    if (zeilen.length === 1 && zeilen[0].includes(' ')) {
      const g = grenzen(await textKonturen(zeilen[0], Math.min(feld.h * 0.62, 14)));
      if (g.w > feld.w * 1.6) { const w = zeilen[0].split(' '); let best = 1, d = 1e9; for (let i = 1; i < w.length; i++) { const a = w.slice(0, i).join(' ').length, b = w.slice(i).join(' ').length; if (Math.abs(a - b) < d) { d = Math.abs(a - b); best = i; } } zeilen = [w.slice(0, best).join(' '), w.slice(best).join(' ')]; }
    }
    if (zeilen.length) {
      const zh = feld.h / zeilen.length;
      for (let i = 0; i < zeilen.length; i++) {
        const cy = feld.cy + feld.h / 2 - zh * (i + 0.5);
        const k = await textIn(zeilen[i], Math.min(zh * 0.62, 14), feld.cx, cy, feld.w, zh * 0.8);
        oben.push(hoch(k, R, D));
      }
    }
    if (R > 0 && oben.length) teile.push({ name: 'Schrift', ext: 2, tris: verbinden(oben) });
    return teile;
  }

  // Bild → 3D
  const BILD = { art: 'litho', breite: 100, duenn: 0.8, dick: 3.0, rahmen: 3, schwelle: 50, umkehren: false, basis: 2, relief: 1.2, nurLogo: false, bild: null };
  BL.bild = () => {
    const b = BILD;
    blattInhalt('Bild → 3D', `<div class="vorschau2d"><canvas id="bC" width="300" height="200"></canvas></div>
      <button class="btn gruen voll" id="bWahl" style="margin-bottom:12px">Bild auswählen (JPG, PNG)</button><input type="file" id="bDatei" accept="image/*" hidden>
      <div class="seg" style="margin-bottom:12px"><button data-ba="litho" class="${b.art === 'litho' ? 'an' : ''}">Lithophane</button><button data-ba="logo" class="${b.art === 'logo' ? 'an' : ''}">Schild / Logo</button></div>
      ${b.art === 'litho' ? `<div class="klein karte" style="margin-bottom:12px">Lithophane: Das Bild wird als dünne Platte gedruckt. Gegen Licht gehalten erscheint das Foto – dunkle Stellen sind dicker. Am besten mit weißem PLA, Qualität Fein und 100 % Füllung.</div>
      <div class="drei"><label class="feld"><span>Breite mm</span><input type="number" id="bB" value="${b.breite}"></label><label class="feld"><span>Dünnste mm</span><input type="number" id="bD1" value="${b.duenn}" step="0.1"></label><label class="feld"><span>Dickste mm</span><input type="number" id="bD2" value="${b.dick}" step="0.1"></label></div>
      <label class="feld"><span>Rahmen mm (0 = ohne)</span><input type="number" id="bR" value="${b.rahmen}" step="0.5"></label>`
      : `<div class="klein karte" style="margin-bottom:12px">Logo oder Zeichnung wird zum erhabenen Relief (Filament 2) auf einer Platte (Filament 1). Am besten Bilder mit klaren Kontrasten.</div>
      <label class="feld"><span>Helligkeits-Schwelle: <b id="bSw">${b.schwelle} %</b></span><input type="range" id="bS" min="5" max="95" value="${b.schwelle}"></label>
      <div class="drei"><label class="feld"><span>Breite mm</span><input type="number" id="bB" value="${b.breite}"></label><label class="feld"><span>Platte mm</span><input type="number" id="bP" value="${b.basis}" step="0.2"></label><label class="feld"><span>Relief mm</span><input type="number" id="bRe" value="${b.relief}" step="0.2"></label></div>
      <label class="zeile klein" style="margin-bottom:6px"><input type="checkbox" id="bU" ${b.umkehren ? 'checked' : ''}> Hell und Dunkel tauschen</label>
      <label class="zeile klein" style="margin-bottom:12px"><input type="checkbox" id="bN" ${b.nurLogo ? 'checked' : ''}> nur das Logo, ohne Platte</label>`}
      <button class="btn gruen voll" id="bOk">Aufs Druckbett</button>`, el => {
      const cv = el.querySelector('#bC');
      const lese = () => { const n = (id, d) => { const x = el.querySelector(id); return x ? +x.value : d; }; b.breite = n('#bB', b.breite); b.duenn = n('#bD1', b.duenn); b.dick = n('#bD2', b.dick); b.rahmen = n('#bR', b.rahmen); b.schwelle = n('#bS', b.schwelle); b.basis = n('#bP', b.basis); b.relief = n('#bRe', b.relief); b.umkehren = el.querySelector('#bU')?.checked ?? b.umkehren; b.nurLogo = el.querySelector('#bN')?.checked ?? b.nurLogo; };
      const male = () => {
        const g = cv.getContext('2d');
        if (!b.bild) { g.fillStyle = '#9aa0a6'; g.fillRect(0, 0, 300, 200); g.fillStyle = '#fff'; g.beginPath(); g.arc(230, 60, 22, 0, 7); g.fill(); g.fillStyle = '#6a7178'; g.beginPath(); g.moveTo(0, 200); g.lineTo(80, 110); g.lineTo(140, 160); g.lineTo(200, 90); g.lineTo(300, 180); g.lineTo(300, 200); g.fill(); return; }
        const w = 300, h = Math.round(300 * b.bild.height / b.bild.width); cv.width = w; cv.height = h; g.drawImage(b.bild, 0, 0, w, h);
        const d = g.getImageData(0, 0, w, h);
        for (let i = 0; i < d.data.length; i += 4) { const l = (0.299 * d.data[i] + 0.587 * d.data[i + 1] + 0.114 * d.data[i + 2]) * (d.data[i + 3] / 255) + 255 * (1 - d.data[i + 3] / 255); let v = l;
          if (b.art === 'logo') { const an = (l < b.schwelle * 2.55) !== b.umkehren; v = an ? 40 : 235; }
          d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255; }
        g.putImageData(d, 0, 0);
      };
      male();
      el.querySelector('#bWahl').onclick = () => el.querySelector('#bDatei').click();
      el.querySelector('#bDatei').onchange = e => { const f = e.target.files[0]; if (!f) return; const img = new Image(); img.onload = () => { b.bild = img; male(); }; img.onerror = () => toast('Bild nicht lesbar.'); img.src = URL.createObjectURL(f); };
      el.querySelectorAll('[data-ba]').forEach(x => x.onclick = () => { lese(); b.art = x.dataset.ba; BL.bild(); });
      el.querySelectorAll('input[type=number],input[type=checkbox]').forEach(i => i.onchange = () => { lese(); male(); });
      el.querySelector('#bS')?.addEventListener('input', e => { b.schwelle = +e.target.value; el.querySelector('#bSw').textContent = b.schwelle + ' %'; male(); });
      el.querySelector('#bOk').onclick = () => { lese(); if (!b.bild) return toast('Erst ein Bild auswählen.'); auf3D(b.art === 'litho' ? 'Lithophane' : 'Logo', bildBauen(b)); };
    });
  };
  function bildPixel(img, nx) {
    const ny = Math.max(2, Math.round(nx * img.height / img.width)), c = document.createElement('canvas'); c.width = nx; c.height = ny;
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, nx, ny); g.drawImage(img, 0, 0, nx, ny);
    const d = g.getImageData(0, 0, nx, ny).data, L = new Float32Array(nx * ny);
    for (let i = 0; i < nx * ny; i++) L[i] = (0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]) / 255;
    return { nx, ny, L };
  }
  function bildBauen(b) {
    if (b.art === 'litho') {
      const p = 0.25, nx = Math.min(480, Math.max(20, Math.round(b.breite / p))), pp = b.breite / nx;
      const { ny, L } = bildPixel(b.bild, nx + 1);
      const W = nx + 1, H = new Float32Array(W * ny), rp = Math.round(b.rahmen / pp);
      for (let j = 0; j < ny; j++) for (let i = 0; i < W; i++) {
        const l = L[(ny - 1 - j) * W + i];
        const rand = rp > 0 && (i < rp || j < rp || i >= W - rp || j >= ny - rp);
        H[j * W + i] = rand ? b.dick + 0.4 : b.duenn + (1 - l) * (b.dick - b.duenn);
      }
      return [{ name: 'Lithophane', ext: 1, tris: hoehenfeld(W, ny, pp, H) }];
    }
    const nx = Math.min(260, Math.max(20, Math.round(b.breite / 0.35))), px = b.breite / nx;
    const { ny, L } = bildPixel(b.bild, nx);
    const an = (x, y) => (L[y * nx + x] < b.schwelle / 100) !== b.umkehren;
    const k = [];
    for (const r of rechtecke(nx, ny, an)) k.push(kiste(r.x1 * px, (ny - r.y2) * px, b.nurLogo ? 0 : b.basis, r.x2 * px, (ny - r.y1) * px, (b.nurLogo ? 0 : b.basis) + (b.nurLogo ? Math.max(b.relief, b.basis) : b.relief)));
    const teile = [];
    if (!b.nurLogo) teile.push({ name: 'Platte', ext: 1, tris: hoch([rundRechteck(nx * px + 6, ny * px + 6, 3, nx * px / 2, ny * px / 2)], b.basis) });
    teile.push({ name: 'Logo', ext: b.nurLogo ? 1 : 2, tris: verbinden(k) });
    return teile;
  }

  // Zeichnen mit dem Finger
  const ZEICH = { breite: 80, dicke: 3, art: 'flaeche', strich: 4, oese: false, striche: [] };
  BL.zeichnen = () => {
    const z = ZEICH;
    blattInhalt('Zeichnen', `<div class="klein" style="margin-bottom:8px">Mit dem Finger eine Form malen – jede Linie wird geschlossen. Mehrere Formen gehen auch.</div>
      <canvas class="zeichnen" id="zC" width="600" height="600"></canvas>
      <div class="zwei" style="margin:10px 0"><button class="btn" id="zUndo">Letzte Linie weg</button><button class="btn" id="zLeer">Alles löschen</button></div>
      <div class="seg" style="margin-bottom:12px"><button data-za="flaeche" class="${z.art === 'flaeche' ? 'an' : ''}">Fläche</button><button data-za="linie" class="${z.art === 'linie' ? 'an' : ''}">Linie</button></div>
      <div class="drei"><label class="feld"><span>Größe mm</span><input type="number" id="zB" value="${z.breite}"></label><label class="feld"><span>Dicke mm</span><input type="number" id="zD" value="${z.dicke}" step="0.2"></label><label class="feld"><span>Strich mm</span><input type="number" id="zS" value="${z.strich}" step="0.5"></label></div>
      <label class="zeile klein" style="margin-bottom:12px"><input type="checkbox" id="zO" ${z.oese ? 'checked' : ''}> Öse für einen Schlüsselring oben</label>
      <button class="btn gruen voll" id="zOk">Aufs Druckbett</button>`, el => {
      const c = el.querySelector('#zC'), g = c.getContext('2d'); let akt = null;
      const male = () => { g.clearRect(0, 0, 600, 600); g.strokeStyle = '#ccc'; g.lineWidth = 1; for (let i = 60; i < 600; i += 60) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 600); g.moveTo(0, i); g.lineTo(600, i); g.stroke(); }
        g.lineJoin = 'round'; g.lineCap = 'round';
        for (const s of [...z.striche, ...(akt ? [akt] : [])]) { if (s.length < 2) continue; g.beginPath(); g.moveTo(...s[0]); for (const p of s) g.lineTo(...p);
          if (z.art === 'flaeche' && s !== akt) { g.closePath(); g.fillStyle = farbeVon(1) + 'cc'; g.fill(); }
          g.strokeStyle = farbeVon(1); g.lineWidth = z.art === 'linie' ? z.strich / z.breite * 600 : 4; g.stroke(); } };
      male();
      const pt = e => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) / r.width * 600, (e.clientY - r.top) / r.height * 600]; };
      c.onpointerdown = e => { c.setPointerCapture(e.pointerId); akt = [pt(e)]; male(); };
      c.onpointermove = e => { if (!akt) return; const p = pt(e), l = akt[akt.length - 1]; if (Math.hypot(p[0] - l[0], p[1] - l[1]) > 4) { akt.push(p); male(); } };
      c.onpointerup = () => { if (akt && akt.length > 2) z.striche.push(akt); akt = null; male(); };
      el.querySelector('#zUndo').onclick = () => { z.striche.pop(); male(); };
      el.querySelector('#zLeer').onclick = () => { z.striche = []; male(); };
      el.querySelectorAll('[data-za]').forEach(b => b.onclick = () => { z.art = b.dataset.za; el.querySelectorAll('[data-za]').forEach(x => x.classList.toggle('an', x === b)); male(); });
      const lese = () => { z.breite = +el.querySelector('#zB').value || 80; z.dicke = +el.querySelector('#zD').value || 3; z.strich = +el.querySelector('#zS').value || 4; z.oese = el.querySelector('#zO').checked; male(); };
      el.querySelectorAll('input').forEach(i => i.onchange = lese);
      el.querySelector('#zOk').onclick = () => {
        lese(); if (!z.striche.length) return toast('Erst etwas zeichnen.');
        const k = z.breite / 600, tris = [];
        const pts = z.striche.map(s => s.map(([x, y]) => [x * k, (600 - y) * k]));
        if (z.art === 'flaeche') for (const p of pts) tris.push(hoch([p], z.dicke));
        else for (const p of pts) { for (let i = 1; i < p.length; i++) { const [x1, y1] = p[i - 1], [x2, y2] = p[i], l = Math.hypot(x2 - x1, y2 - y1) || 1, nx = -(y2 - y1) / l * z.strich / 2, ny = (x2 - x1) / l * z.strich / 2; tris.push(hoch([[[x1 + nx, y1 + ny], [x2 + nx, y2 + ny], [x2 - nx, y2 - ny], [x1 - nx, y1 - ny]]], z.dicke)); } for (const q of p) tris.push(hoch([kreis(z.strich, q[0], q[1], 16)], z.dicke)); }
        if (z.oese) { const g2 = grenzen(pts.flat().length ? pts : [[[0, 0]]]), top = pts.flat().reduce((a, b) => b[1] > a[1] ? b : a); tris.push(hoch([kreis(12, top[0], top[1] + 4), kreis(5, top[0], top[1] + 5)], z.dicke)); void g2; }
        auf3D('Zeichnung', [{ name: 'Zeichnung', ext: 1, tris: verbinden(tris) }]);
      };
    });
  };

  BL.finden = () => {
    const QUELLEN = [['MakerWorld', q => `https://makerworld.com/de/search/models?keyword=${q}`], ['Printables', q => `https://www.printables.com/search/models?q=${q}`], ['Thingiverse', q => `https://www.thingiverse.com/search?q=${q}`], ['Cults3D', q => `https://cults3d.com/de/suche?q=${q}`]];
    blattInhalt('Modell finden', `<input class="eing" id="fQ" placeholder="z. B. Kopfhörerhalter" style="margin-bottom:12px"><div id="fL"></div>
      <div class="klein" style="margin-top:8px">Datei dort herunterladen, dann hier mit „3D-Datei öffnen“ laden – auch direkt aus „Dateien“ auf dem iPhone.</div>`, el => {
      const zeichne = () => { const q = encodeURIComponent(el.querySelector('#fQ').value.trim());
        el.querySelector('#fL').innerHTML = QUELLEN.map(([n, u]) => `<a class="option" target="_blank" rel="noopener" href="${q ? u(q) : u('').replace(/[?&][^=]+=$/, '')}" style="text-decoration:none;color:inherit"><b>${n} ↗</b><span class="klein">${q ? `Suche nach „${esc(decodeURIComponent(q))}“` : 'Stöbern'}</span></a>`).join(''); };
      el.querySelector('#fQ').oninput = zeichne; zeichne();
    });
  };
}
