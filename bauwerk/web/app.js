// Bauwerk 2 – Oberfläche. Rechnen erledigt der Rust-Kern (Server oder Mac-App) über /api/berechnen.
import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';

const $ = s => document.querySelector(s);
const neueId = () => Math.random().toString(36).slice(2, 8);
const runde = (x, n = 3) => { const f = 10 ** n; return Math.round(x * f) / f; };
const zahl = (x, n = 2) => String(runde(x, n)).replace('.', ',');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ---------- Symbole ----------
const IC = {
  neu: 'M12 5v14M5 12h14', oeffnen: 'M3 7h6l2 2h10v10H3z', undo: 'M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3', redo: 'm15 14 5-5-5-5M20 9H9a5 5 0 0 0 0 10h3',
  thema: 'M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z', skizze: 'M4 20l4-1 11-11-3-3L5 16z', extr: 'M12 19V6m-5 5 5-5 5 5M5 20h14',
  drehen: 'M12 4v16M8 7a6 6 0 1 0 8 0', bohr: 'M12 3v18M7 7h10M8 12h8M9 17h6', runden: 'M5 19v-7a7 7 0 0 1 7-7h7', param: 'M4 7h10M4 12h16M4 17h7M17 4v6M13 15l4 4 4-4',
  auswahl: 'm5 4 13 6-6 2-2 6z', linie: 'M5 19 19 5', rechteck: 'M4 6h16v12H4z', rmitte: 'M4 6h16v12H4zM12 12h.01M4 6l16 12',
  kreis: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 12h.01', kreis3: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM4.5 10h.01M19.5 10h.01M12 20h.01',
  bogen: 'M5 18A9 9 0 0 1 19 8M12 18h.01', punkt: 'M12 12h.01M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0', hilfs: 'M4 20 20 4', bemass: 'M4 8v8M20 8v8M4 12h16M7 9l-3 3 3 3M17 9l3 3-3 3',
  koinz: 'M8 12a4 4 0 1 0 8 0 4 4 0 0 0-8 0M3 12h2M19 12h2', hor: 'M4 12h16', ver: 'M12 4v16', par: 'M7 18 13 6M11 18l6-12', senk: 'M6 18V6M6 18h12',
  gleich: 'M5 10h14M5 14h14', tang: 'M3 19h18M12 15a5 5 0 1 0 0-10 5 5 0 0 0 0 10', mitte: 'M4 12h16M12 9v6', fix: 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z',
  sym: 'M12 4v16M5 8l4 4-4 4M19 8l-4 4 4 4', loeschen: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13', fertig: 'm5 12 5 5 9-10', export: 'M12 4v11m-4-4 4 4 4-4M5 20h14',
  auge: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6', anfang: 'M6 5v14M18 6l-8 6 8 6', zurueck: 'M15 6l-6 6 6 6', vor: 'M9 6l6 6-6 6', ende: 'M18 5v14M6 6l8 6-8 6',
  ebene: 'M3 9l9-5 9 5-9 5z', koerper: 'M12 3 4 7v10l8 4 8-4V7zM4 7l8 4 8-4M12 11v10', messen: 'M3 17 17 3l4 4L7 21zM7 13l2 2M10 10l2 2M13 7l2 2'
};
const ico = n => `<svg class="i" viewBox="0 0 24 24"><path d="${IC[n] || ''}"/></svg>`;

// ---------- Zustand ----------
let doc = neuesDok();
let info = null;               // Antwort des Kerns (ohne Netz)
let gewaehlt = null;           // Feature-ID
let reiter = 'volumen';
let skizzeAktiv = null;        // ID der bearbeiteten Skizze
let werkzeug = 'auswahl';
let auswahl = [];              // [{t:'p'|'e'|'b', id}] – b: Index der Bedingung
let entwurf = null;
let ebenenWahl = false;
let parameterOffen = false;
const undoStapel = [], redoStapel = [];

function neuesDok() { return { id: neueId() + neueId(), name: 'Neues Teil', parameter: [], features: [] }; }
const feat = id => doc.features.find(f => f.id === id);
const skizzen = () => doc.features.filter(f => f.typ === 'skizze');
const zaehle = t => doc.features.filter(f => f.typ === t).length + 1;
const sk = () => feat(skizzeAktiv);

function merken() { undoStapel.push(JSON.stringify(doc)); if (undoStapel.length > 150) undoStapel.shift(); redoStapel.length = 0; knopfStatus(); }
function rueckgaengig() { if (!undoStapel.length) return; redoStapel.push(JSON.stringify(doc)); doc = JSON.parse(undoStapel.pop()); nachLaden(); }
function wiederholen() { if (!redoStapel.length) return; undoStapel.push(JSON.stringify(doc)); doc = JSON.parse(redoStapel.pop()); nachLaden(); }
function nachLaden() { if (gewaehlt && !feat(gewaehlt)) gewaehlt = null; if (skizzeAktiv && !feat(skizzeAktiv)) skizzeEnde(); auswahl = []; $('#name').value = doc.name; aenderung(); knopfStatus(); }
function knopfStatus() { $('#kUndo').disabled = !undoStapel.length; $('#kRedo').disabled = !redoStapel.length; }

// ---------- Ausdrücke (für Ebenenversatz in der Oberfläche) ----------
function auswerten(w) {
  if (typeof w === 'number') return w;
  if (w == null || w === '') return 0;
  const env = info?.parameter || {};
  const s = String(w).replace(/,/g, '.');
  let i = 0;
  const sieh = () => { while (s[i] === ' ') i++; return s[i]; };
  const summe = () => { let v = prod(); for (;;) { const c = sieh(); if (c === '+') { i++; v += prod(); } else if (c === '-') { i++; v -= prod(); } else return v; } };
  const prod = () => { let v = pot(); for (;;) { const c = sieh(); if (c === '*') { i++; v *= pot(); } else if (c === '/') { i++; v /= pot(); } else return v; } };
  const pot = () => { const b = ein(); if (sieh() === '^') { i++; return b ** pot(); } return b; };
  const ein = () => {
    const c = sieh();
    if (c === '-') { i++; return -pot(); }
    if (c === '(') { i++; const v = summe(); i++; return v; }
    const m = s.slice(i).match(/^(\d+\.?\d*|\.\d+)/); if (m) { i += m[0].length; return parseFloat(m[0]); }
    const n = s.slice(i).match(/^[A-Za-z_äöüÄÖÜß][\wäöüÄÖÜß]*/); if (n) { i += n[0].length; if (n[0] === 'pi') return Math.PI; return env[n[0]] ?? NaN; }
    return NaN;
  };
  const v = summe(); return isFinite(v) ? v : 0;
}
const anzeigeWert = w => typeof w === 'number' ? zahl(w) : String(w ?? '');
const eingabeWert = t => { const s = String(t).trim(); const z = Number(s.replace(',', '.')); return s !== '' && isFinite(z) ? z : s; };

// ---------- Ebenen ----------
const BASIS = { XY: { u: [1, 0, 0], v: [0, 1, 0], n: [0, 0, 1], name: 'Oben (XY)' }, XZ: { u: [1, 0, 0], v: [0, 0, 1], n: [0, -1, 0], name: 'Vorne (XZ)' }, YZ: { u: [0, 1, 0], v: [0, 0, 1], n: [1, 0, 0], name: 'Rechts (YZ)' } };
function ebene(e) {
  const b = BASIS[e?.basis] || BASIS.XY, s = e?.umgedreht ? -1 : 1;
  return { u: new THREE.Vector3(...b.u).multiplyScalar(s), v: new THREE.Vector3(...b.v), n: new THREE.Vector3(...b.n).multiplyScalar(s), o: new THREE.Vector3(...b.n).multiplyScalar(auswerten(e?.versatz)) };
}
const zuWelt = (E, x, y) => E.o.clone().addScaledVector(E.u, x).addScaledVector(E.v, y);

// ---------- Rechnen (Rust-Kern) ----------
let rechenNr = 0, unterwegs = false, nochmal = false, desktop = false;
async function rechnen() {
  if (unterwegs) { nochmal = true; return; }
  unterwegs = true; nochmal = false;
  const nr = ++rechenNr, t0 = performance.now();
  const gesendet = JSON.stringify(doc);
  try {
    const r = await fetch('api/berechnen', { method: 'POST', body: gesendet });
    if (!r.ok) throw new Error((await r.json()).text || r.status);
    const buf = await r.arrayBuffer(), dv = new DataView(buf), jl = dv.getUint32(0, true);
    const neu = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, jl)));
    let off = 4 + jl; while (off % 4) off++;
    const pos = new Float32Array(buf, off, neu.anzahl_punkte * 3); off += neu.anzahl_punkte * 12;
    const idx = new Uint32Array(buf, off, neu.anzahl_indizes);
    // Gelöste Skizzen übernehmen, solange niemand in der Zwischenzeit geändert hat
    if (JSON.stringify(doc) === gesendet) { doc = uebernehmen(neu.dok); }
    info = neu;
    koerperZeigen(pos, idx);
    $('#zeit').textContent = `${Math.round(performance.now() - t0)} ms`;
    $('#fehlerleiste').textContent = '';
  } catch (e) { $('#fehlerleiste').textContent = 'Rechnen fehlgeschlagen: ' + e.message; }
  unterwegs = false;
  oberflaeche();
  if (nochmal) rechnen();
}
// Nur Punkt-Koordinaten und Radien aus dem Kern übernehmen (Struktur bleibt aus der Oberfläche)
function uebernehmen(geloest) {
  const g = new Map(geloest.features.map(f => [f.id, f]));
  for (const f of doc.features) {
    const s = g.get(f.id); if (!s || f.typ !== 'skizze') continue;
    const pk = new Map(s.punkte.map(p => [p.id, p]));
    for (const p of f.punkte) { const q = pk.get(p.id); if (q) { p.x = q.x; p.y = q.y; } }
    if (!f.punkte.some(p => p.id === '0')) f.punkte.unshift({ id: '0', x: 0, y: 0, fest: true });
    const el = new Map(s.elemente.map(e => [e.id, e]));
    for (const e of f.elemente) { const q = el.get(e.id); if (q && e.art === 'kreis') e.r = q.r; }
  }
  return doc;
}
let rechenTimer = null, speicherTimer = null;
function aenderung(sofort) {
  clearTimeout(rechenTimer); rechenTimer = setTimeout(rechnen, sofort ? 0 : 25);
  clearTimeout(speicherTimer); speicherTimer = setTimeout(speichern, 900);
  $('#speicherstand').textContent = 'nicht gespeichert';
  oberflaeche();
}
async function speichern() {
  doc.name = $('#name').value.trim() || 'Neues Teil';
  try {
    const r = await fetch('api/projekte/' + doc.id, { method: 'PUT', body: JSON.stringify(doc) });
    if (!r.ok) throw new Error((await r.json()).text);
    $('#speicherstand').textContent = 'gespeichert';
    try { localStorage.setItem('bauwerk2-zuletzt', doc.id); } catch (e) {}
  } catch (e) { $('#speicherstand').textContent = 'Speichern fehlgeschlagen'; }
}

// ---------- 3D-Ansicht ----------
const c3d = $('#c3d'), overlay = $('#overlay'), ctx = overlay.getContext('2d');
const renderer = new THREE.WebGLRenderer({ canvas: c3d, antialias: true, powerPreference: 'low-power' });
renderer.setPixelRatio(Math.min(2, devicePixelRatio));
const szene = new THREE.Scene();
const kamera = new THREE.OrthographicCamera(-100, 100, 100, -100, -20000, 20000);
kamera.up.set(0, 0, 1);
const steuer = new OrbitControls(kamera, c3d);
steuer.enableDamping = false; steuer.zoomToCursor = true; steuer.screenSpacePanning = true;
szene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 2.2));
const licht = new THREE.DirectionalLight(0xffffff, 1.3); szene.add(licht);
let raster = new THREE.Group(); szene.add(raster);
const achsen = new THREE.Group(); szene.add(achsen);
[[0xd93025, [1, 0, 0]], [0x00ae42, [0, 1, 0]], [0x1a73e8, [0, 0, 1]]].forEach(([c, d]) => achsen.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(...d).multiplyScalar(20)]), new THREE.LineBasicMaterial({ color: c }))));
const koerperGruppe = new THREE.Group(), skizzenGruppe = new THREE.Group(); szene.add(koerperGruppe, skizzenGruppe);
const matKoerper = new THREE.MeshLambertMaterial({ color: 0xc9d1d9, flatShading: true, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, transparent: true, opacity: 1 });
const matKante = new THREE.LineBasicMaterial({ color: 0x3b4350, transparent: true, opacity: 1 });
let koerperObj = null, renderGeplant = false;
function zeichnen() { if (renderGeplant) return; renderGeplant = true; requestAnimationFrame(() => { renderGeplant = false; licht.position.copy(kamera.position).add(new THREE.Vector3(50, 30, 80)); renderer.render(szene, kamera); overlayZeichnen(); }); }
steuer.addEventListener('change', zeichnen);
function groesse() {
  const r = $('#ansicht').getBoundingClientRect(), w = Math.max(1, r.width), h = Math.max(1, r.height);
  renderer.setSize(w, h, false); overlay.width = w * devicePixelRatio; overlay.height = h * devicePixelRatio;
  const a = w / h; kamera.left = -100 * a; kamera.right = 100 * a; kamera.top = 100; kamera.bottom = -100; kamera.updateProjectionMatrix(); zeichnen();
}
new ResizeObserver(groesse).observe($('#ansicht'));
const dunkel = () => document.documentElement.dataset.thema === 'dunkel';
function farbenThema() {
  const d = dunkel();
  renderer.setClearColor(d ? 0x17191c : 0xeef0f3);
  matKoerper.color.set(d ? 0x7d8995 : 0xc9d1d9); matKante.color.set(d ? 0x0d0f12 : 0x3b4350);
  const sicht = raster.visible; szene.remove(raster); raster.traverse(o => o.geometry?.dispose());
  raster = new THREE.GridHelper(300, 30, d ? 0x4a5058 : 0x9aa3ad, d ? 0x2a2e34 : 0xd5dae0); raster.rotation.x = Math.PI / 2; raster.visible = sicht; szene.add(raster);
  zeichnen();
}
function koerperZeigen(pos, idx) {
  if (koerperObj) { koerperObj.traverse(o => o.geometry?.dispose()); koerperGruppe.remove(koerperObj); koerperObj = null; }
  if (!idx.length) { $('#masse').textContent = 'Kein Körper'; zeichnen(); return; }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3)); g.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
  koerperObj = new THREE.Group();
  const m = new THREE.Mesh(g, matKoerper); m.name = 'koerper';
  koerperObj.add(m, new THREE.LineSegments(new THREE.EdgesGeometry(g, 25), matKante));
  koerperGruppe.add(koerperObj);
  const s = info.groesse;
  $('#masse').textContent = `${zahl(s[0])} × ${zahl(s[1])} × ${zahl(s[2])} mm · ${zahl(info.volumen / 1000)} cm³ · ${info.dreiecke} Dreiecke`;
  zeichnen();
}
function skizzenLinien() {
  skizzenGruppe.children.forEach(o => o.geometry.dispose()); skizzenGruppe.clear();
  const benutzt = new Set(doc.features.filter(f => f.skizze).map(f => f.skizze));
  for (const s of skizzen()) {
    if (s.aus || s.id === skizzeAktiv || (benutzt.has(s.id) && s.id !== gewaehlt)) continue;
    const E = ebene(s.ebene), pts = [], pk = new Map(s.punkte.map(p => [p.id, p]));
    for (const e of s.elemente) for (const [a, b] of segmente(e, pk)) pts.push(zuWelt(E, a[0], a[1]), zuWelt(E, b[0], b[1]));
    if (!pts.length) continue;
    skizzenGruppe.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: s.id === gewaehlt ? 0x0a7cff : 0x6b7280, depthTest: false })));
  }
  zeichnen();
}
function segmente(e, pk) {
  const out = [];
  if (e.art === 'linie') { const a = pk.get(e.a), b = pk.get(e.b); if (a && b) out.push([[a.x, a.y], [b.x, b.y]]); }
  if (e.art === 'kreis') { const m = pk.get(e.m); if (m) { const n = 64; for (let i = 0; i < n; i++) { const w0 = i / n * 2 * Math.PI, w1 = (i + 1) / n * 2 * Math.PI; out.push([[m.x + e.r * Math.cos(w0), m.y + e.r * Math.sin(w0)], [m.x + e.r * Math.cos(w1), m.y + e.r * Math.sin(w1)]]); } } }
  if (e.art === 'bogen') { const pts = bogenPunkte(e, pk); for (let i = 0; i + 1 < pts.length; i++) out.push([pts[i], pts[i + 1]]); }
  return out;
}
function bogenPunkte(e, pk) {
  const m = pk.get(e.m), a = pk.get(e.a), b = pk.get(e.b); if (!m || !a || !b) return [];
  const r = Math.hypot(a.x - m.x, a.y - m.y), w0 = Math.atan2(a.y - m.y, a.x - m.x); let w1 = Math.atan2(b.y - m.y, b.x - m.x);
  while (w1 <= w0 + 1e-9) w1 += 2 * Math.PI;
  const n = Math.max(8, Math.ceil((w1 - w0) / (2 * Math.PI) * 64)), p = [];
  for (let i = 0; i <= n; i++) { const w = w0 + (w1 - w0) * i / n; p.push([m.x + r * Math.cos(w), m.y + r * Math.sin(w)]); }
  return p;
}
function ansicht(art) {
  const box = koerperObj ? new THREE.Box3().setFromObject(koerperObj) : new THREE.Box3(new THREE.Vector3(-40, -40, 0), new THREE.Vector3(40, 40, 20));
  const mitte = box.getCenter(new THREE.Vector3()), gr = box.getSize(new THREE.Vector3()).length() || 80;
  const r = { iso: [1, -1.2, 0.9], oben: [0, -0.0001, 1], vorne: [0, -1, 0], rechts: [1, 0, 0] }[art];
  if (r) { kamera.position.copy(mitte).add(new THREE.Vector3(...r).normalize().multiplyScalar(2000)); kamera.up.set(0, 0, 1); }
  steuer.target.copy(mitte); kamera.lookAt(mitte);
  const ra = $('#ansicht').getBoundingClientRect();
  kamera.zoom = Math.min(200 / (gr * 1.3), 200 * (ra.width / ra.height) / (gr * 1.3)); kamera.updateProjectionMatrix(); steuer.update(); zeichnen();
}

// ---------- Oberfläche: Menüband ----------
function bk(cmd, icon, text, opt = {}) { return `<button class="bk ${opt.an ? 'an' : ''} ${opt.cls || ''}" data-cmd="${cmd}" title="${esc(opt.titel || text)}" ${opt.aus ? 'disabled' : ''}>${ico(icon)}<span>${text}</span></button>`; }
function gruppe(titel, inhalt) { return `<div class="gruppe"><div class="reihe">${inhalt}</div><div class="titel">${titel}</div></div>`; }
function bandZeigen() {
  const b = $('#band');
  document.querySelectorAll('#reiter button').forEach(x => x.classList.toggle('an', x.dataset.reiter === reiter));
  if (reiter === 'skizze' && skizzeAktiv) {
    const w = (k, i, t, titel) => bk('w:' + k, i, t, { an: werkzeug === k, titel });
    const s = auswahl.length > 0;
    b.innerHTML =
      gruppe('Erstellen', w('auswahl', 'auswahl', 'Auswahl', 'Auswählen und ziehen (Esc)') + w('linie', 'linie', 'Linie', 'Linie (L)') + w('rechteck', 'rechteck', 'Rechteck', 'Rechteck über 2 Ecken (R)') + w('rechteck_mitte', 'rmitte', 'Mitte-Rechteck', 'Rechteck um Mittelpunkt') +
        w('kreis', 'kreis', 'Kreis', 'Kreis: Mittelpunkt + Radius (C)') + w('kreis3', 'kreis3', '3-Punkt-Kreis', 'Kreis durch 3 Punkte') + w('bogen', 'bogen', 'Bogen', 'Bogen: Mittelpunkt, Start, Ende (A)') + w('punkt', 'punkt', 'Punkt', 'Punkt (z. B. für Bohrungen)')) +
      gruppe('Bedingungen', bk('b:koinzident', 'koinz', 'Deckend', { aus: !s }) + bk('b:horizontal', 'hor', 'Horizontal', { aus: !s }) + bk('b:vertikal', 'ver', 'Vertikal', { aus: !s }) + bk('b:parallel', 'par', 'Parallel', { aus: !s }) +
        bk('b:senkrecht', 'senk', 'Senkrecht', { aus: !s }) + bk('b:gleich', 'gleich', 'Gleich', { aus: !s }) + bk('b:tangential', 'tang', 'Tangential', { aus: !s }) + bk('b:mittelpunkt', 'mitte', 'Mittelpunkt', { aus: !s }) +
        bk('b:symmetrisch', 'sym', 'Symmetrisch', { aus: !s }) + bk('b:fix', 'fix', 'Fixieren', { aus: !s })) +
      gruppe('Bemaßung', bk('bemassung', 'bemass', 'Bemaßung', { aus: !s, titel: 'Bemaßung für die Auswahl (D)' }) + bk('hilfs', 'hilfs', 'Hilfslinie', { aus: !s, titel: 'Auswahl zu Hilfslinie umschalten (X)' }) + bk('loeschen', 'loeschen', 'Löschen', { aus: !s, titel: 'Auswahl löschen (Entf)' })) +
      gruppe('Fertig', bk('skizze_ende', 'fertig', 'Skizze beenden', { cls: 'fertig' }));
  } else if (reiter === 'pruefen') {
    b.innerHTML = gruppe('Export', bk('export:stl', 'export', 'STL') + bk('export:3mf', 'export', '3MF') + bk('export:step', 'export', 'STEP', { titel: 'STEP (facettiert) – echte Flächen über Mesh2STEP' })) +
      gruppe('Ansicht', bk('ansicht:iso', 'koerper', 'Iso') + bk('ansicht:alles', 'auge', 'Alles zeigen')) +
      gruppe('Daten', bk('parameter', 'param', 'Parameter') + bk('datei', 'oeffnen', 'Datei'));
  } else {
    b.innerHTML = gruppe('Erstellen', bk('skizze', 'skizze', 'Skizze', { an: ebenenWahl, titel: 'Neue Skizze (S)' }) + bk('extrusion', 'extr', 'Extrudieren', { titel: 'Extrudieren (E)' }) + bk('drehung', 'drehen', 'Drehen') + bk('bohrung', 'bohr', 'Bohrung', { titel: 'Bohrung (B)' })) +
      gruppe('Ändern', bk('runden', 'runden', 'Abrunden', { titel: 'Außenecken einer Extrusion abrunden' }) + bk('parameter', 'param', 'Parameter', { an: parameterOffen })) +
      gruppe('Export', bk('export:stl', 'export', 'STL') + bk('export:3mf', 'export', '3MF') + bk('export:step', 'export', 'STEP'));
  }
  b.querySelectorAll('[data-cmd]').forEach(x => x.onclick = () => befehl(x.dataset.cmd));
}

// ---------- Browser (links) ----------
function baumZeigen() {
  const ul = $('#baum'); const z = [];
  const st = id => info?.skizzen?.[id]?.zustand || '';
  z.push(`<li data-b="parameter" class="${parameterOffen ? 'gew' : ''}">${ico('param')} Parameter<span class="neben">${doc.parameter.length}</span></li>`);
  z.push(`<li class="leer">${ico('ebene')} Ursprung</li>`);
  for (const k of Object.keys(BASIS)) z.push(`<li data-ebene="${k}" style="padding-left:22px" title="Neue Skizze auf dieser Ebene">${ico('ebene')} ${BASIS[k].name}</li>`);
  z.push(`<li class="leer">${ico('skizze')} Skizzen</li>`);
  for (const s of skizzen()) z.push(`<li data-f="${s.id}" style="padding-left:22px" class="${s.id === gewaehlt ? 'gew' : ''}"><span class="punktstatus ${st(s.id)}"></span>${esc(s.name)}${s.aus ? ' (aus)' : ''}</li>`);
  z.push(`<li class="leer">${ico('koerper')} Körper</li>`);
  if (info?.dreiecke) z.push(`<li style="padding-left:22px" data-b="koerper">${ico('koerper')} Körper 1<span class="neben">${zahl(info.volumen / 1000)} cm³</span></li>`);
  ul.innerHTML = z.join('');
  ul.querySelectorAll('[data-f]').forEach(li => { li.onclick = () => waehle(li.dataset.f); li.ondblclick = () => skizzeStart(li.dataset.f); });
  ul.querySelectorAll('[data-ebene]').forEach(li => li.onclick = () => neueSkizze({ basis: li.dataset.ebene, versatz: 0, umgedreht: false }));
  ul.querySelector('[data-b=parameter]').onclick = () => { parameterOffen = !parameterOffen; if (parameterOffen) gewaehlt = null; oberflaeche(); };
}

// ---------- Zeitleiste (unten) ----------
const FICO = { skizze: 'skizze', extrusion: 'extr', drehung: 'drehen', bohrung: 'bohr' };
function zeitleisteZeigen() {
  const z = $('#zeitleiste'), bis = doc.bis ?? doc.features.length;
  const fi = new Map((info?.features || []).map(f => [f.id, f]));
  let h = `<button class="zk" data-z="anfang" title="Zum Anfang">${ico('anfang')}</button><button class="zk" data-z="zurueck" title="Einen Schritt zurück">${ico('zurueck')}</button><button class="zk" data-z="vor" title="Einen Schritt vor">${ico('vor')}</button><button class="zk" data-z="ende" title="Zum Ende">${ico('ende')}</button><div class="zl">`;
  doc.features.forEach((f, i) => {
    if (i === bis) h += `<div class="marke" title="Zeitleisten-Marke"></div>`;
    const err = fi.get(f.id)?.fehler;
    h += `<div class="zf ${f.id === gewaehlt ? 'gew' : ''} ${f.aus ? 'aus' : ''} ${err ? 'fehler' : ''} ${i >= bis ? 'spaeter' : ''}" data-f="${f.id}" title="${esc(f.name)}${err ? ' – ' + esc(err) : ''}">${ico(FICO[f.typ])}</div>`;
  });
  if (bis >= doc.features.length) h += `<div class="marke" title="Zeitleisten-Marke"></div>`;
  h += `</div><span class="sp"></span><span style="color:var(--text2);font-size:11px">Zeitleiste</span>`;
  z.innerHTML = h;
  z.querySelectorAll('[data-f]').forEach(el => { el.onclick = () => waehle(el.dataset.f); el.ondblclick = () => { const f = feat(el.dataset.f); if (f?.typ === 'skizze') skizzeStart(f.id); }; });
  z.querySelectorAll('[data-z]').forEach(el => el.onclick = () => {
    const n = doc.features.length, b = doc.bis ?? n;
    const neu = { anfang: 0, zurueck: Math.max(0, b - 1), vor: Math.min(n, b + 1), ende: n }[el.dataset.z];
    merken(); doc.bis = neu >= n ? undefined : neu; aenderung();
  });
}

// ---------- Eigenschaften (rechts) ----------
function feld(label, key, wert, typ = 'zahl', optionen, hinweis) {
  if (typ === 'wahl') return `<div class="feld"><label>${label}</label><select data-k="${key}">${optionen.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(wert) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>`;
  if (typ === 'haken') return `<div class="feld"><label>${label}</label><input type="checkbox" data-k="${key}" ${wert ? 'checked' : ''}></div>`;
  if (typ === 'text') return `<div class="feld"><label>${label}</label><input data-k="${key}" value="${esc(wert)}"></div>`;
  const ausdruck = typeof wert === 'string';
  return `<div class="feld"><label>${label}</label><input data-k="${key}" data-wert inputmode="decimal" value="${esc(anzeigeWert(wert))}" title="Zahl oder Ausdruck, z. B. breite/2">${ausdruck ? `<span class="wert">= ${zahl(auswerten(wert))}</span>` : ''}${hinweis ? `<span class="wert">${hinweis}</span>` : ''}</div>`;
}
const BOHR = [['', 'Eigene'], ['2.4', 'M2 Durchgang'], ['3.4', 'M3 Durchgang'], ['4.5', 'M4 Durchgang'], ['5.5', 'M5 Durchgang'], ['6.6', 'M6 Durchgang'], ['8.8', 'M8 Durchgang'], ['2.5', 'M3 Kern (selbstschneidend)'], ['4', 'Einschmelzmutter M3'], ['5.6', 'Einschmelzmutter M4'], ['6.4', 'Einschmelzmutter M5']];
const BNAMEN = { koinzident: 'Deckend', horizontal: 'Horizontal', vertikal: 'Vertikal', parallel: 'Parallel', senkrecht: 'Senkrecht', gleich: 'Gleich', fix: 'Fixiert', punkt_auf_linie: 'Punkt auf Linie', punkt_auf_kreis: 'Punkt auf Kreis', mittelpunkt: 'Mittelpunkt', tangential: 'Tangential', symmetrisch: 'Symmetrisch', abstand: 'Abstand', abstand_x: 'Abstand horizontal', abstand_y: 'Abstand vertikal', laenge: 'Länge', radius: 'Radius', durchmesser: 'Durchmesser', winkel: 'Winkel' };
function formZeigen() {
  const fo = $('#form'), t = $('#formtitel');
  if (ebenenWahl && !skizzeAktiv) {
    t.textContent = 'NEUE SKIZZE';
    fo.innerHTML = `<p class="leer">Eine gerade Fläche des Körpers anklicken – oder eine Grundebene wählen:</p><div class="reihe2">${Object.entries(BASIS).map(([k, b]) => `<button class="k" data-ebene="${k}">${b.name}</button>`).join('')}</div><div class="reihe2"><button class="k" data-abbruch>Abbrechen</button></div>`;
    fo.querySelectorAll('[data-ebene]').forEach(x => x.onclick = () => neueSkizze({ basis: x.dataset.ebene, versatz: 0, umgedreht: false }));
    fo.querySelector('[data-abbruch]').onclick = () => { ebenenWahl = false; hinweis(''); oberflaeche(); };
    return;
  }
  if (parameterOffen && !skizzeAktiv) return parameterZeigen(fo, t);
  if (skizzeAktiv) return skizzenFormZeigen(fo, t);
  const f = feat(gewaehlt);
  if (!f) {
    t.textContent = 'EIGENSCHAFTEN';
    fo.innerHTML = `<p class="leer">${doc.features.length ? 'Element im Browser oder in der Zeitleiste wählen.' : 'So geht’s: Skizze → Formen zeichnen → bemaßen → Skizze beenden → Extrudieren.'}</p><p class="leer">Drehen: linke Maustaste · Verschieben: rechte Maustaste · Zoom: Mausrad</p><p class="leer">Werte dürfen Ausdrücke mit Parametern sein, z. B. <i>breite/2</i>.</p>`;
    return;
  }
  t.textContent = f.name.toUpperCase();
  const fehler = info?.features?.find(x => x.id === f.id)?.fehler;
  const skOpt = skizzen().map(s => [s.id, s.name]);
  let h = feld('Name', 'name', f.name, 'text');
  if (f.typ === 'skizze') {
    const st = info?.skizzen?.[f.id];
    h += feld('Ebene', 'ebene.basis', f.ebene.basis, 'wahl', Object.entries(BASIS).map(([k, b]) => [k, b.name])) + feld('Versatz', 'ebene.versatz', f.ebene.versatz) + feld('Umgedreht', 'ebene.umgedreht', f.ebene.umgedreht, 'haken') +
      `<p class="leer">${f.elemente.length} Elemente · ${f.bedingungen.length} Bedingungen${st ? ' · ' + statusText(st) : ''}</p>` +
      `<div class="reihe2"><button class="k voll" data-a="bearb">${ico('skizze')}Skizze bearbeiten</button></div><div class="reihe2"><button class="k" data-a="extr">${ico('extr')}Extrudieren</button><button class="k" data-a="dreh">${ico('drehen')}Drehen</button><button class="k" data-a="bohr">${ico('bohr')}Bohrung</button></div>`;
  }
  if (f.typ === 'extrusion') {
    h += feld('Skizze', 'skizze', f.skizze, 'wahl', skOpt) + feld('Länge (mm)', 'laenge', f.laenge) +
      feld('Richtung', 'richtung', f.richtung, 'wahl', [['normal', 'Nach außen'], ['umgekehrt', 'Nach innen'], ['symmetrisch', 'Beidseitig']]) +
      feld('Vorgang', 'modus', f.modus, 'wahl', [['hinzu', 'Verbinden'], ['abziehen', 'Ausschneiden'], ['schnitt', 'Schnittmenge']]) +
      feld('Außenecken', 'ecken.art', f.ecken?.art || 'keine', 'wahl', [['keine', 'Scharf'], ['rund', 'Abrunden'], ['fase', 'Fasen']]) +
      (f.ecken?.art && f.ecken.art !== 'keine' ? feld('Radius (mm)', 'ecken.r', f.ecken.r) : '');
  }
  if (f.typ === 'drehung') {
    const s = feat(f.skizze), linien = (s?.elemente || []).filter(e => e.art === 'linie').map((e, i) => [e.id, (e.hilfs ? 'Hilfslinie ' : 'Linie ') + (i + 1)]);
    h += feld('Skizze', 'skizze', f.skizze, 'wahl', skOpt) + feld('Achse', 'achse', f.achse, 'wahl', linien.length ? linien : [['', '– keine Linie –']]) + feld('Winkel (°)', 'winkel', f.winkel) +
      feld('Vorgang', 'modus', f.modus, 'wahl', [['hinzu', 'Verbinden'], ['abziehen', 'Ausschneiden'], ['schnitt', 'Schnittmenge']]) + `<p class="leer">Tipp: Achse als Hilfslinie zeichnen (X), dann zählt sie nicht zum Profil.</p>`;
  }
  if (f.typ === 'bohrung') {
    const vor = BOHR.find(b => b[0] && typeof f.d === 'number' && Math.abs(+b[0] - f.d) < 1e-6)?.[0] || '';
    h += feld('Skizze', 'skizze', f.skizze, 'wahl', skOpt) + `<div class="feld"><label>Vorlage</label><select data-vorlage>${BOHR.map(([v, x]) => `<option value="${v}" ${v === vor ? 'selected' : ''}>${x}</option>`).join('')}</select></div>` +
      feld('Ø (mm)', 'd', f.d) + feld('Tiefe', 'tiefe', f.tiefe, 'zahl', null, '0 = durch alles') +
      feld('Senkung', 'senkung', f.senkung, 'wahl', [['keine', 'Keine'], ['kegel', 'Senkkopf 90°'], ['zylinder', 'Zylinderkopf']]) +
      (f.senkung !== 'keine' ? feld('Kopf-Ø', 'sd', f.sd) + (f.senkung === 'zylinder' ? feld('Kopftiefe', 'st', f.st) : '') : '') +
      `<p class="leer">Jeder Kreismittelpunkt und jeder freie Punkt der Skizze wird gebohrt.</p>`;
  }
  if (fehler) h += `<p class="fehlertext">${esc(fehler)}</p>`;
  h += `<div class="reihe2"><button class="k" data-a="aus">${ico('auge')}${f.aus ? 'Einschalten' : 'Ausschalten'}</button><button class="k" data-a="hoch" title="In der Zeitleiste nach vorne">◀</button><button class="k" data-a="runter" title="In der Zeitleiste nach hinten">▶</button><button class="k" data-a="weg">${ico('loeschen')}Löschen</button></div>`;
  fo.innerHTML = h; binde(f);
  const a = (n, fn) => fo.querySelector(`[data-a="${n}"]`)?.addEventListener('click', fn);
  a('bearb', () => skizzeStart(f.id)); a('extr', () => befehl('extrusion')); a('dreh', () => befehl('drehung')); a('bohr', () => befehl('bohrung'));
  a('aus', () => { merken(); f.aus = !f.aus; aenderung(); });
  a('weg', () => featureLoeschen(f.id));
  a('hoch', () => verschieben(f.id, -1)); a('runter', () => verschieben(f.id, 1));
  fo.querySelector('[data-vorlage]')?.addEventListener('change', e => { if (e.target.value) { merken(); f.d = +e.target.value; aenderung(); } });
}
function statusText(st) { return st.zustand === 'voll_bestimmt' ? 'voll bestimmt' : st.zustand === 'unterbestimmt' ? `${st.freiheitsgrade} Freiheitsgrade offen` : 'widersprüchlich'; }
function setze(o, pfad, w) { const t = pfad.split('.'); for (let i = 0; i < t.length - 1; i++) { if (o[t[i]] == null) o[t[i]] = {}; o = o[t[i]]; } o[t.at(-1)] = w; }
function binde(obj, nachher) {
  $('#form').querySelectorAll('[data-k]').forEach(el => {
    const k = el.dataset.k; let gemerkt = false;
    const wahl = el.tagName === 'SELECT' || el.type === 'checkbox';
    const anwenden = () => {
      if (!gemerkt) { merken(); gemerkt = true; }
      let w = el.type === 'checkbox' ? el.checked : el.dataset.wert !== undefined ? eingabeWert(el.value) : el.value;
      setze(obj, k, w);
      if (k === 'name' && obj.typ) baumZeigen();
      nachher?.(k, w);
      aenderung();
    };
    el.addEventListener(wahl ? 'change' : 'input', anwenden);
    el.addEventListener('change', () => { gemerkt = false; if (wahl) formZeigen(); });
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter') el.blur();
      if (el.dataset.wert !== undefined && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        const z = Number(String(el.value).replace(',', '.')); if (!isFinite(z)) return;
        e.preventDefault(); const s = e.shiftKey ? 10 : e.altKey ? 0.1 : 1; el.value = zahl(z + (e.key === 'ArrowUp' ? s : -s), 3); anwenden();
      }
    });
  });
}
function parameterZeigen(fo, t) {
  t.textContent = 'PARAMETER';
  const erg = info?.parameter || {};
  fo.innerHTML = `<p class="leer">Namen in Maßen und Längen verwenden, z. B. <i>breite/2</i>. Ausdrücke dürfen frühere Parameter nutzen.</p>
   <table class="par"><tbody>${doc.parameter.map((p, i) => `<tr><td style="width:38%"><input data-p="${i}" data-f="name" value="${esc(p.name)}"></td><td><input data-p="${i}" data-f="ausdruck" value="${esc(anzeigeWert(p.ausdruck))}"></td><td class="erg">${erg[p.name] != null ? '= ' + zahl(erg[p.name]) : '?'}</td><td><button class="k klein" data-weg="${i}">×</button></td></tr>`).join('')}</tbody></table>
   <div class="reihe2"><button class="k" data-neu>+ Parameter</button></div>`;
  fo.querySelectorAll('[data-p]').forEach(el => {
    el.addEventListener('focus', () => merken(), { once: true });
    el.addEventListener('input', () => { const p = doc.parameter[+el.dataset.p]; p[el.dataset.f] = el.dataset.f === 'ausdruck' ? eingabeWert(el.value) : el.value.replace(/[^\wäöüÄÖÜß]/g, '_'); aenderung(); });
  });
  fo.querySelectorAll('[data-weg]').forEach(b => b.onclick = () => { merken(); doc.parameter.splice(+b.dataset.weg, 1); aenderung(); });
  fo.querySelector('[data-neu]').onclick = () => { merken(); let n = 1; while (doc.parameter.some(p => p.name === 'p' + n)) n++; doc.parameter.push({ name: 'p' + n, ausdruck: 10 }); aenderung(); };
}

// ---------- Ablauf ----------
function oberflaeche() { bandZeigen(); baumZeigen(); zeitleisteZeigen(); if (!formFokus()) formZeigen(); else ergebnisseAuffrischen(); skizzenLinien(); skizzenStatus(); zeichnen(); }
function ergebnisseAuffrischen() {
  if (!parameterOffen) return;
  const erg = info?.parameter || {};
  document.querySelectorAll('#form table.par tr').forEach((tr, i) => { const p = doc.parameter[i], c = tr.querySelector('.erg'); if (p && c) c.textContent = erg[p.name] != null ? '= ' + zahl(erg[p.name]) : '?'; });
}
function formFokus() { const a = document.activeElement; return a && $('#eigenschaften').contains(a) && /INPUT|SELECT/.test(a.tagName) && a.type !== 'checkbox' && a.tagName !== 'SELECT'; }
function waehle(id) { if (skizzeAktiv && id !== skizzeAktiv) skizzeEnde(); gewaehlt = id; parameterOffen = false; ebenenWahl = false; oberflaeche(); }
function featureLoeschen(id) {
  const abh = doc.features.filter(f => f.skizze === id);
  if (abh.length && !confirm(`Diese Skizze wird von ${abh.map(f => f.name).join(', ')} benutzt. Alles zusammen löschen?`)) return;
  merken(); doc.features = doc.features.filter(f => f.id !== id && f.skizze !== id);
  if (!feat(gewaehlt)) gewaehlt = null; if (skizzeAktiv === id) skizzeEnde(); aenderung();
}
function verschieben(id, r) {
  const i = doc.features.findIndex(f => f.id === id), j = i + r; if (j < 0 || j >= doc.features.length) return;
  merken(); [doc.features[i], doc.features[j]] = [doc.features[j], doc.features[i]]; aenderung();
}
function letzteSkizze() { const g = feat(gewaehlt); if (g?.typ === 'skizze') return g; if (g?.skizze) return feat(g.skizze); return skizzen().at(-1); }
function befehl(c) {
  if (c.startsWith('w:')) { werkzeug = c.slice(2); entwurf = null; if (werkzeug !== 'auswahl') auswahl = []; oberflaeche(); return; }
  if (c.startsWith('b:')) return bedingungSetzen(c.slice(2));
  if (c.startsWith('export:')) return exportieren(c.slice(7));
  if (c.startsWith('ansicht:')) return ansicht(c.slice(8));
  switch (c) {
    case 'skizze': ebenenWahl = !ebenenWahl; parameterOffen = false; hinweis(ebenenWahl ? 'Fläche anklicken oder rechts eine Ebene wählen' : '', 0); oberflaeche(); return;
    case 'parameter': parameterOffen = !parameterOffen; if (parameterOffen) gewaehlt = null; oberflaeche(); return;
    case 'skizze_ende': skizzeEnde(true); return;
    case 'bemassung': bemassen(); return;
    case 'hilfs': hilfsUmschalten(); return;
    case 'loeschen': auswahlLoeschen(); return;
    case 'datei': oeffnenDialog(); return;
    case 'runden': {
      const g = feat(gewaehlt);
      if (g?.typ !== 'extrusion') return hinweis('Erst eine Extrusion wählen – dann werden ihre Außenecken abgerundet');
      merken(); if (!g.ecken || g.ecken.art === 'keine') g.ecken = { art: 'rund', r: g.ecken?.r || 2 }; aenderung();
      setTimeout(() => $('#form [data-k="ecken.r"]')?.select(), 40); return;
    }
    case 'extrusion': case 'drehung': case 'bohrung': {
      const s = letzteSkizze(); if (!s) return hinweis('Zuerst eine Skizze anlegen');
      merken();
      let f;
      if (c === 'extrusion') f = { id: neueId(), typ: 'extrusion', name: 'Extrusion ' + zaehle('extrusion'), skizze: s.id, laenge: 10, richtung: 'normal', modus: 'hinzu', ecken: { art: 'keine', r: 2 } };
      if (c === 'drehung') { const ach = s.elemente.find(e => e.art === 'linie' && e.hilfs) || s.elemente.find(e => e.art === 'linie'); f = { id: neueId(), typ: 'drehung', name: 'Drehung ' + zaehle('drehung'), skizze: s.id, achse: ach?.id || '', winkel: 360, modus: 'hinzu' }; }
      if (c === 'bohrung') f = { id: neueId(), typ: 'bohrung', name: 'Bohrung ' + zaehle('bohrung'), skizze: s.id, d: 3.4, tiefe: 0, senkung: 'keine', sd: 6.5, st: 3.3 };
      const bis = doc.bis ?? doc.features.length; doc.features.splice(bis, 0, f); if (doc.bis != null) doc.bis++;
      gewaehlt = f.id; parameterOffen = false; aenderung(); return;
    }
  }
}

// ---------- Skizzen-Modus ----------
let gespeicherteKamera = null;
function neueSkizze(eb) {
  merken();
  const s = { id: neueId(), typ: 'skizze', name: 'Skizze ' + zaehle('skizze'), ebene: eb, punkte: [{ id: '0', x: 0, y: 0, fest: true }], elemente: [], bedingungen: [] };
  const bis = doc.bis ?? doc.features.length; doc.features.splice(bis, 0, s); if (doc.bis != null) doc.bis++;
  ebenenWahl = false; hinweis(''); skizzeStart(s.id); aenderung();
}
function skizzeStart(id) {
  const s = feat(id); if (!s) return;
  skizzeAktiv = id; gewaehlt = id; auswahl = []; entwurf = null; parameterOffen = false; reiter = 'skizze';
  werkzeug = s.elemente.length ? 'auswahl' : 'linie';
  gespeicherteKamera = { pos: kamera.position.clone(), up: kamera.up.clone(), ziel: steuer.target.clone(), zoom: kamera.zoom };
  const E = ebene(s.ebene);
  // Blickpunkt auf die Skizzenebene projizieren, damit die Ansicht nicht springt
  const ziel = steuer.target.clone(), z = ziel.clone().sub(E.o).dot(E.n);
  ziel.addScaledVector(E.n, -z);
  steuer.target.copy(ziel); kamera.position.copy(ziel).addScaledVector(E.n, 2000); kamera.up.copy(E.v); kamera.lookAt(ziel); kamera.updateProjectionMatrix();
  steuer.enableRotate = false; steuer.mouseButtons = { LEFT: null, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN }; steuer.touches = { ONE: null, TWO: THREE.TOUCH.DOLLY_PAN };
  raster.visible = false; matKoerper.opacity = 0.35; matKante.opacity = 0.5;
  steuer.update(); oberflaeche();
}
function skizzeEnde(fertig) {
  const s = sk(); if (!skizzeAktiv) return;
  skizzeAktiv = null; entwurf = null; auswahl = []; reiter = 'volumen';
  steuer.enableRotate = true; steuer.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN }; steuer.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
  raster.visible = true; matKoerper.opacity = 1; matKante.opacity = 1;
  if (gespeicherteKamera) { kamera.position.copy(gespeicherteKamera.pos); kamera.up.copy(gespeicherteKamera.up); steuer.target.copy(gespeicherteKamera.ziel); kamera.zoom = gespeicherteKamera.zoom; kamera.updateProjectionMatrix(); steuer.update(); }
  oberflaeche();
  if (fertig && s && s.elemente.length && !doc.features.some(f => f.skizze === s.id)) hinweis('Jetzt „Extrudieren“, „Drehen“ oder „Bohrung“ wählen');
}
function skizzenStatus() {
  const el = $('#skizzenstatus');
  const st = skizzeAktiv && info?.skizzen?.[skizzeAktiv];
  el.className = st ? st.zustand : ''; el.textContent = st ? statusText(st) : '';
}
const ray = new THREE.Raycaster();
function zuEbene(cx, cy) {
  const r = c3d.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2((cx - r.left) / r.width * 2 - 1, -(cy - r.top) / r.height * 2 + 1), kamera);
  const E = ebene(sk().ebene), pl = new THREE.Plane().setFromNormalAndCoplanarPoint(E.n, E.o), p = new THREE.Vector3();
  if (!ray.ray.intersectPlane(pl, p)) return null;
  const d = p.sub(E.o); return [d.dot(E.u), d.dot(E.v)];
}
function zuSchirm(E, x, y) { const p = zuWelt(E, x, y).project(kamera); return [(p.x + 1) / 2 * overlay.width, (1 - p.y) / 2 * overlay.height]; }
const pxProMm = () => (c3d.getBoundingClientRect().height) / ((kamera.top - kamera.bottom) / kamera.zoom);
function rasterSchritt() { const p = pxProMm(); for (const s of [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100]) if (s * p >= 10) return s; return 100; }
const pkt = id => sk()?.punkte.find(p => p.id === id);
const el = id => sk()?.elemente.find(e => e.id === id);

// Fangen: vorhandener Punkt (ID) oder Raster
let fang = null, maus = null;
function fangen(p, ev, ohne = []) {
  fang = null;
  const tol = 10 / pxProMm();
  if (!ev.shiftKey) {
    let best = null, bd = tol;
    for (const q of sk().punkte) { if (ohne.includes(q.id)) continue; const d = Math.hypot(q.x - p[0], q.y - p[1]); if (d < bd) { bd = d; best = q; } }
    if (entwurf?.neuePunkte) for (const q of entwurf.neuePunkte) { const d = Math.hypot(q.x - p[0], q.y - p[1]); if (d < bd && !ohne.includes(q.id)) { bd = d; best = q; } }
    if (best) { fang = best; return { x: best.x, y: best.y, id: best.id }; }
    const s = rasterSchritt() >= 1 ? rasterSchritt() / (rasterSchritt() >= 10 ? 10 : rasterSchritt() >= 5 ? 5 : 1) : rasterSchritt();
    return { x: runde(Math.round(p[0] / s) * s, 4), y: runde(Math.round(p[1] / s) * s, 4) };
  }
  return { x: runde(p[0], 4), y: runde(p[1], 4) };
}
function punktAus(f) { if (f.id) return f.id; const id = neueId(); sk().punkte.push({ id, x: f.x, y: f.y }); return id; }
function linieNeu(a, b, hilfs) { const id = neueId(); const e = { art: 'linie', id, a, b }; if (hilfs) e.hilfs = true; sk().elemente.push(e); return id; }
function bed(b) { sk().bedingungen.push(b); }
function autoHV(lid) {
  const e = el(lid), a = pkt(e.a), b = pkt(e.b), dx = b.x - a.x, dy = b.y - a.y, w = Math.abs(Math.atan2(dy, dx) * 180 / Math.PI);
  if (Math.hypot(dx, dy) < 1e-9) return;
  if (w < 2 || w > 178) bed({ art: 'horizontal', linie: lid }); else if (Math.abs(w - 90) < 2) bed({ art: 'vertikal', linie: lid });
}

// Treffer: Bemaßungs-Etiketten, Punkte, Elemente
let etiketten = [];
function treffer(cx, cy) {
  const r = c3d.getBoundingClientRect(), sx = (cx - r.left) * devicePixelRatio, sy = (cy - r.top) * devicePixelRatio;
  for (const e of etiketten) if (sx >= e.x0 && sx <= e.x1 && sy >= e.y0 && sy <= e.y1) return { t: 'b', id: e.i };
  const p = zuEbene(cx, cy); if (!p) return null;
  const tol = 9 / pxProMm(), s = sk();
  let best = null, bd = tol;
  for (const q of s.punkte) { const d = Math.hypot(q.x - p[0], q.y - p[1]); if (d < bd) { bd = d; best = { t: 'p', id: q.id }; } }
  if (best) return best;
  bd = tol;
  const pk = new Map(s.punkte.map(q => [q.id, q]));
  for (const e of s.elemente) {
    let d = Infinity;
    if (e.art === 'kreis') { const m = pk.get(e.m); if (m) d = Math.abs(Math.hypot(p[0] - m.x, p[1] - m.y) - e.r); }
    else for (const [a, b] of segmente(e, pk)) d = Math.min(d, abstandSeg(p, a, b));
    if (d < bd) { bd = d; best = { t: 'e', id: e.id }; }
  }
  return best;
}
function abstandSeg(p, a, b) { const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy || 1; let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l; t = Math.max(0, Math.min(1, t)); return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy); }
const istGew = (t, id) => auswahl.some(a => a.t === t && a.id === id);

// Ziehen
let ziehen = null;
c3d.addEventListener('pointerdown', ev => {
  if (!skizzeAktiv) { if (ebenenWahl && ev.button === 0) flaecheWaehlen(ev); return; }
  if (ev.button !== 0) return;
  const roh = zuEbene(ev.clientX, ev.clientY); if (!roh) return;
  const s = sk();
  if (werkzeug === 'auswahl') {
    const t = treffer(ev.clientX, ev.clientY);
    if (!t) { auswahl = []; oberflaeche(); return; }
    if (ev.shiftKey || ev.metaKey || ev.ctrlKey) { auswahl = istGew(t.t, t.id) ? auswahl.filter(a => !(a.t === t.t && a.id === t.id)) : [...auswahl, t]; }
    else auswahl = [t];
    oberflaeche();
    // Ziehen vorbereiten
    if (t.t === 'p' && t.id !== '0') ziehen = { punkte: [t.id], start: roh, orig: [[pkt(t.id).x, pkt(t.id).y]] };
    if (t.t === 'e') {
      const e = el(t.id);
      if (e.art === 'kreis' && Math.hypot(roh[0] - pkt(e.m).x, roh[1] - pkt(e.m).y) > 0) ziehen = { kreis: e.id, start: roh };
      else { const ids = [e.a, e.b, e.m].filter(Boolean).filter(i => i !== '0'); ziehen = { punkte: ids, start: roh, orig: ids.map(i => [pkt(i).x, pkt(i).y]) }; }
    }
    if (ziehen) { ziehen.gemerkt = false; c3d.setPointerCapture(ev.pointerId); }
    return;
  }
  const f = fangen(roh, ev);
  klick(f, ev);
});
c3d.addEventListener('pointermove', ev => {
  if (!skizzeAktiv) return;
  const roh = zuEbene(ev.clientX, ev.clientY); if (!roh) return;
  if (ziehen) {
    if (!ziehen.gemerkt) { merken(); ziehen.gemerkt = true; }
    const s = sk();
    if (ziehen.kreis) { const e = el(ziehen.kreis), m = pkt(e.m); e.r = runde(Math.hypot(roh[0] - m.x, roh[1] - m.y), 4); ziehenRechnen([]); }
    else {
      const dx = roh[0] - ziehen.start[0], dy = roh[1] - ziehen.start[1];
      ziehen.punkte.forEach((id, i) => { const p = pkt(id); p.x = runde(ziehen.orig[i][0] + dx, 4); p.y = runde(ziehen.orig[i][1] + dy, 4); });
      ziehenRechnen(ziehen.punkte);
    }
    zeichnen(); return;
  }
  maus = fangen(roh, ev, entwurf?.ohne || []);
  if (entwurf) entwurf.maus = maus;
  zeichnen();
});
c3d.addEventListener('pointerup', () => {
  if (!ziehen) return;
  const warGezogen = ziehen.gemerkt; ziehen = null;
  for (const p of sk()?.punkte || []) delete p._zieh;
  if (warGezogen) aenderung(true);
});
function ziehenRechnen(ids) {
  // Gezogene Punkte für die Berechnung festhalten, Rest folgt den Bedingungen
  const s = sk();
  for (const p of s.punkte) if (p._zieh) { delete p._zieh; if (p.id !== '0') delete p.fest; }
  for (const id of ids) { const p = pkt(id); if (!p.fest) { p.fest = true; p._zieh = true; } }
  const kopie = JSON.stringify(doc, (k, v) => k === '_zieh' ? undefined : v);
  for (const id of ids) { const p = pkt(id); if (p._zieh) delete p.fest; }
  schnellRechnen(kopie);
}
let schnellUnterwegs = false, schnellNaechste = null;
async function schnellRechnen(json) {
  if (schnellUnterwegs) { schnellNaechste = json; return; }
  schnellUnterwegs = true;
  try {
    const r = await fetch('api/berechnen', { method: 'POST', body: json });
    const buf = await r.arrayBuffer(), dv = new DataView(buf), jl = dv.getUint32(0, true);
    const neu = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, jl)));
    let off = 4 + jl; while (off % 4) off++;
    const pos = new Float32Array(buf, off, neu.anzahl_punkte * 3); off += neu.anzahl_punkte * 12;
    const idx = new Uint32Array(buf, off, neu.anzahl_indizes);
    if (ziehen) {
      const gez = new Set(ziehen.punkte || []);
      const g = neu.dok.features.find(f => f.id === skizzeAktiv), s = sk();
      if (g && s) { for (const q of g.punkte) { if (gez.has(q.id)) continue; const p = s.punkte.find(x => x.id === q.id); if (p) { p.x = q.x; p.y = q.y; } } for (const q of g.elemente) { const e = s.elemente.find(x => x.id === q.id); if (e && e.art === 'kreis' && !(ziehen.kreis === e.id)) e.r = q.r; } }
      info = neu; koerperZeigen(pos, idx); skizzenStatus();
    }
  } catch (e) {}
  schnellUnterwegs = false;
  if (schnellNaechste) { const j = schnellNaechste; schnellNaechste = null; schnellRechnen(j); }
}
c3d.addEventListener('dblclick', () => { if (skizzeAktiv && entwurf?.art === 'linie') linieBeenden(); });

function klick(f, ev) {
  const s = sk();
  switch (werkzeug) {
    case 'punkt': merken(); if (!f.id) s.punkte.push({ id: neueId(), x: f.x, y: f.y }); aenderung(); return;
    case 'linie': {
      if (!entwurf) { entwurf = { art: 'linie', start: f, kette: [], maus: f }; return; }
      const a = entwurf.letzter || entwurf.start;
      if (Math.hypot(f.x - a.x, f.y - a.y) < 1e-9) return;
      if (!entwurf.gemerkt) { merken(); entwurf.gemerkt = true; }
      const ida = a.id || punktAus(a); if (!a.id) { a.id = ida; if (entwurf.start === a) entwurf.start.id = ida; }
      const geschlossen = f.id && f.id === entwurf.start.id;
      const idb = punktAus(f);
      const lid = linieNeu(ida, idb, false); autoHV(lid);
      entwurf.letzter = { x: f.x, y: f.y, id: idb };
      if (geschlossen) { entwurf = null; werkzeug = 'linie'; }
      aenderung(); return;
    }
    case 'rechteck': case 'rechteck_mitte': case 'kreis': case 'bogen': case 'kreis3': {
      if (!entwurf) { entwurf = { art: werkzeug, pkte: [f], maus: f }; return; }
      entwurf.pkte.push(f);
      const n = werkzeug === 'bogen' || werkzeug === 'kreis3' ? 3 : 2;
      if (entwurf.pkte.length >= n) { formFertig(entwurf); entwurf = null; }
      zeichnen(); return;
    }
  }
}
function linieBeenden() { entwurf = null; oberflaeche(); }
function formFertig(e) {
  const s = sk(); merken();
  const [p0, p1, p2] = e.pkte;
  if (e.art === 'rechteck' || e.art === 'rechteck_mitte') {
    let ecken;
    if (e.art === 'rechteck') ecken = [p0, { x: p1.x, y: p0.y }, p1, { x: p0.x, y: p1.y }];
    else { const dx = p1.x - p0.x, dy = p1.y - p0.y; ecken = [{ x: p0.x - dx, y: p0.y - dy }, { x: p0.x + dx, y: p0.y - dy }, { x: p0.x + dx, y: p0.y + dy }, { x: p0.x - dx, y: p0.y + dy }]; if (e.art === 'rechteck_mitte') ecken[2] = p1.id ? p1 : ecken[2]; }
    if (Math.abs(ecken[2].x - ecken[0].x) < 1e-6 || Math.abs(ecken[2].y - ecken[0].y) < 1e-6) { undoStapel.pop(); return; }
    const ids = ecken.map(c => punktAus(c));
    const l = [0, 1, 2, 3].map(i => linieNeu(ids[i], ids[(i + 1) % 4]));
    bed({ art: 'horizontal', linie: l[0] }); bed({ art: 'horizontal', linie: l[2] }); bed({ art: 'vertikal', linie: l[1] }); bed({ art: 'vertikal', linie: l[3] });
    if (e.art === 'rechteck_mitte') { const m = punktAus(p0); const d = linieNeu(ids[0], ids[2], true); bed({ art: 'mittelpunkt', punkt: m, linie: d }); }
    auswahl = [];
  }
  if (e.art === 'kreis') {
    const r = Math.hypot(p1.x - p0.x, p1.y - p0.y); if (r < 1e-6) { undoStapel.pop(); return; }
    const m = punktAus(p0), id = neueId(); s.elemente.push({ art: 'kreis', id, m, r: runde(r, 4) });
    if (p1.id) bed({ art: 'punkt_auf_kreis', punkt: p1.id, kreis: id });
    auswahl = [{ t: 'e', id }];
  }
  if (e.art === 'kreis3') {
    const k = umkreis(p0, p1, p2); if (!k) { undoStapel.pop(); return hinweis('Die drei Punkte liegen auf einer Linie'); }
    const m = punktAus({ x: runde(k.x, 4), y: runde(k.y, 4) }), id = neueId();
    s.elemente.push({ art: 'kreis', id, m, r: runde(k.r, 4) });
    for (const p of [p0, p1, p2]) bed({ art: 'punkt_auf_kreis', punkt: punktAus(p), kreis: id });
    auswahl = [{ t: 'e', id }];
  }
  if (e.art === 'bogen') {
    const r = Math.hypot(p1.x - p0.x, p1.y - p0.y); if (r < 1e-6) { undoStapel.pop(); return; }
    const w = Math.atan2(p2.y - p0.y, p2.x - p0.x), pe = p2.id ? p2 : { x: runde(p0.x + r * Math.cos(w), 4), y: runde(p0.y + r * Math.sin(w), 4) };
    const id = neueId(); s.elemente.push({ art: 'bogen', id, m: punktAus(p0), a: punktAus(p1), b: punktAus(pe) });
    auswahl = [{ t: 'e', id }];
  }
  aenderung();
}
function umkreis(a, b, c) {
  const d = 2 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y)); if (Math.abs(d) < 1e-9) return null;
  const a2 = a.x * a.x + a.y * a.y, b2 = b.x * b.x + b.y * b.y, c2 = c.x * c.x + c.y * c.y;
  const x = (a2 * (b.y - c.y) + b2 * (c.y - a.y) + c2 * (a.y - b.y)) / d, y = (a2 * (c.x - b.x) + b2 * (a.x - c.x) + c2 * (b.x - a.x)) / d;
  return { x, y, r: Math.hypot(a.x - x, a.y - y) };
}

// Bedingungen aus der Auswahl
function auswahlTypen() {
  const p = auswahl.filter(a => a.t === 'p').map(a => a.id);
  const es = auswahl.filter(a => a.t === 'e').map(a => el(a.id)).filter(Boolean);
  return { p, l: es.filter(e => e.art === 'linie').map(e => e.id), k: es.filter(e => e.art !== 'linie').map(e => e.id) };
}
function bedingungSetzen(art) {
  const { p, l, k } = auswahlTypen(); const neu = [];
  if (art === 'horizontal' || art === 'vertikal') { for (const x of l) neu.push({ art, linie: x }); if (!l.length && p.length === 2) neu.push({ art: art === 'horizontal' ? 'abstand_y' : 'abstand_x', a: p[0], b: p[1], wert: 0 }); }
  if (art === 'parallel' || art === 'senkrecht') for (let i = 1; i < l.length; i++) neu.push({ art, a: l[0], b: l[i] });
  if (art === 'gleich') { for (let i = 1; i < l.length; i++) neu.push({ art, a: l[0], b: l[i] }); for (let i = 1; i < k.length; i++) neu.push({ art, a: k[0], b: k[i] }); }
  if (art === 'koinzident') { if (p.length >= 2) for (let i = 1; i < p.length; i++) neu.push({ art, a: p[0], b: p[i] }); else if (p.length === 1 && l.length) neu.push({ art: 'punkt_auf_linie', punkt: p[0], linie: l[0] }); else if (p.length === 1 && k.length) neu.push({ art: 'punkt_auf_kreis', punkt: p[0], kreis: k[0] }); }
  if (art === 'tangential' && l.length && k.length) neu.push({ art, linie: l[0], kreis: k[0] });
  if (art === 'mittelpunkt' && p.length && l.length) neu.push({ art, punkt: p[0], linie: l[0] });
  if (art === 'symmetrisch' && p.length === 2 && l.length) neu.push({ art, a: p[0], b: p[1], linie: l[0] });
  if (art === 'fix') for (const x of p) neu.push({ art, punkt: x });
  if (!neu.length) return hinweis({ horizontal: 'Linien wählen', vertikal: 'Linien wählen', parallel: 'Zwei Linien wählen', senkrecht: 'Zwei Linien wählen', gleich: 'Zwei Linien oder zwei Kreise wählen', koinzident: 'Zwei Punkte (oder Punkt + Linie/Kreis) wählen', tangential: 'Linie und Kreis/Bogen wählen', mittelpunkt: 'Punkt und Linie wählen', symmetrisch: 'Zwei Punkte und eine Linie wählen', fix: 'Punkte wählen' }[art]);
  merken(); sk().bedingungen.push(...neu); auswahl = []; pruefenNachAenderung();
}
async function pruefenNachAenderung() {
  // Wenn die Skizze dadurch widersprüchlich wird: zurücknehmen
  await rechnenSofort();
  if (info?.skizzen?.[skizzeAktiv]?.zustand === 'widerspruechlich') { rueckgaengig(); redoStapel.pop(); knopfStatus(); hinweis('Das würde der Skizze widersprechen – nicht übernommen'); }
}
function rechnenSofort() { clearTimeout(rechenTimer); clearTimeout(speicherTimer); speicherTimer = setTimeout(speichern, 900); oberflaeche(); return new Promise(r => { const warte = () => unterwegs ? setTimeout(warte, 10) : rechnen().then(r); warte(); }); }
function bemassen() {
  const { p, l, k } = auswahlTypen(), s = sk(); let b = null;
  const P = id => pkt(id);
  if (l.length === 1 && !p.length && !k.length) { const e = el(l[0]), a = P(e.a), c = P(e.b); b = { art: 'laenge', linie: l[0], wert: runde(Math.hypot(c.x - a.x, c.y - a.y)) }; }
  else if (k.length === 1 && !p.length && !l.length) { const e = el(k[0]); if (e.art === 'kreis') b = { art: 'durchmesser', kreis: k[0], wert: runde(e.r * 2) }; else { const m = P(e.m), a = P(e.a); b = { art: 'radius', kreis: k[0], wert: runde(Math.hypot(a.x - m.x, a.y - m.y)) }; } }
  else if (p.length === 2) { const a = P(p[0]), c = P(p[1]), dx = Math.abs(c.x - a.x), dy = Math.abs(c.y - a.y); b = dy < 1e-6 ? { art: 'abstand_x', a: p[0], b: p[1], wert: runde(dx) } : dx < 1e-6 ? { art: 'abstand_y', a: p[0], b: p[1], wert: runde(dy) } : { art: 'abstand', a: p[0], b: p[1], wert: runde(Math.hypot(dx, dy)) }; }
  else if (p.length === 1 && l.length === 1) { const q = P(p[0]), e = el(l[0]), a = P(e.a), c = P(e.b), d = Math.abs((c.x - a.x) * (q.y - a.y) - (c.y - a.y) * (q.x - a.x)) / Math.hypot(c.x - a.x, c.y - a.y); b = { art: 'abstand', a: p[0], b: l[0], wert: runde(d) }; }
  else if (l.length === 2) { const d = id => { const e = el(id), a = P(e.a), c = P(e.b); return [c.x - a.x, c.y - a.y]; }; const u = d(l[0]), v = d(l[1]); const w = Math.acos(Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / (Math.hypot(...u) * Math.hypot(...v))))) * 180 / Math.PI; b = { art: 'winkel', a: l[0], b: l[1], wert: runde(w, 2) }; }
  if (!b) return hinweis('Bemaßung: eine Linie, einen Kreis/Bogen, zwei Punkte, Punkt + Linie oder zwei Linien wählen');
  merken(); s.bedingungen.push(b); auswahl = [{ t: 'b', id: s.bedingungen.length - 1 }];
  pruefenNachAenderung().then(() => setTimeout(() => { const f = $('#form [data-k="wert"]'); f?.focus(); f?.select(); }, 30));
}
function hilfsUmschalten() { const { l, k } = auswahlTypen(); if (!l.length && !k.length) return; merken(); for (const id of [...l, ...k]) { const e = el(id); if (e.hilfs) delete e.hilfs; else e.hilfs = true; } aenderung(); }
function auswahlLoeschen() {
  if (!auswahl.length) return; merken();
  const s = sk();
  const bIdx = new Set(auswahl.filter(a => a.t === 'b').map(a => a.id));
  s.bedingungen = s.bedingungen.filter((_, i) => !bIdx.has(i));
  const weg = new Set(auswahl.filter(a => a.t !== 'b').map(a => a.id)); weg.delete('0');
  const wegEl = s.elemente.filter(e => weg.has(e.id) || [e.a, e.b, e.m].some(x => weg.has(x)));
  s.elemente = s.elemente.filter(e => !wegEl.includes(e));
  // Punkte der gelöschten Elemente mitnehmen, wenn sonst nichts sie braucht
  const gebraucht = new Set(['0']); for (const e of s.elemente) for (const x of [e.a, e.b, e.m]) if (x) gebraucht.add(x);
  for (const e of wegEl) for (const x of [e.a, e.b, e.m]) if (x && !gebraucht.has(x)) weg.add(x);
  s.punkte = s.punkte.filter(p => !weg.has(p.id));
  const ids = new Set([...s.punkte.map(p => p.id), ...s.elemente.map(e => e.id)]);
  s.bedingungen = s.bedingungen.filter(b => ['a', 'b', 'linie', 'kreis', 'punkt'].every(k => b[k] == null || ids.has(b[k])));
  auswahl = []; aenderung();
}

function skizzenFormZeigen(fo, t) {
  const s = sk(), st = info?.skizzen?.[s.id];
  if (auswahl.length === 1 && auswahl[0].t === 'b') {
    const b = s.bedingungen[auswahl[0].id];
    if (!b) { auswahl = []; return skizzenFormZeigen(fo, t); }
    t.textContent = (BNAMEN[b.art] || b.art).toUpperCase();
    fo.innerHTML = (b.wert !== undefined ? feld(b.art === 'winkel' ? 'Wert (°)' : 'Wert (mm)', 'wert', b.wert) + `<p class="leer">Zahl oder Ausdruck mit Parametern, z. B. <i>breite/2</i>.</p>` : `<p class="leer">Bedingung ohne Wert.</p>`) +
      `<div class="reihe2"><button class="k" data-a="weg">${ico('loeschen')}Löschen</button></div>`;
    binde(b);
    fo.querySelector('[data-a=weg]').onclick = auswahlLoeschen;
    return;
  }
  if (auswahl.length === 1 && auswahl[0].t === 'p') {
    const p = pkt(auswahl[0].id); if (!p) { auswahl = []; return skizzenFormZeigen(fo, t); }
    t.textContent = p.id === '0' ? 'URSPRUNG' : 'PUNKT';
    fo.innerHTML = p.id === '0' ? '<p class="leer">Fester Ursprung der Skizze.</p>' : feld('X', 'x', p.x) + feld('Y', 'y', p.y) + `<p class="leer">Direkt gesetzte Koordinaten gelten, bis eine Bedingung sie bestimmt. Für feste Maße besser „Bemaßung“.</p>`;
    binde(p); return;
  }
  if (auswahl.length === 1 && auswahl[0].t === 'e') {
    const e = el(auswahl[0].id); if (!e) { auswahl = []; return skizzenFormZeigen(fo, t); }
    t.textContent = { linie: 'LINIE', kreis: 'KREIS', bogen: 'BOGEN' }[e.art];
    let h = '';
    if (e.art === 'linie') { const a = pkt(e.a), b = pkt(e.b); h = `<p class="leer">Länge ${zahl(Math.hypot(b.x - a.x, b.y - a.y))} mm</p>`; }
    if (e.art === 'kreis') h = `<p class="leer">Ø ${zahl(e.r * 2)} mm</p>`;
    h += feld('Hilfslinie', 'hilfs', !!e.hilfs, 'haken');
    const bezug = s.bedingungen.map((b, i) => [b, i]).filter(([b]) => [b.a, b.b, b.linie, b.kreis].includes(e.id));
    if (bezug.length) h += `<p class="leer">Bedingungen: ${bezug.map(([b, i]) => `<a href="#" data-bi="${i}">${BNAMEN[b.art]}${b.wert !== undefined ? ' ' + esc(anzeigeWert(b.wert)) : ''}</a>`).join(', ')}</p>`;
    h += `<div class="reihe2"><button class="k" data-a="bem">${ico('bemass')}Bemaßen</button><button class="k" data-a="weg">${ico('loeschen')}Löschen</button></div>`;
    fo.innerHTML = h; binde(e);
    fo.querySelector('[data-a=bem]').onclick = bemassen; fo.querySelector('[data-a=weg]').onclick = auswahlLoeschen;
    fo.querySelectorAll('[data-bi]').forEach(a => a.onclick = ev => { ev.preventDefault(); auswahl = [{ t: 'b', id: +a.dataset.bi }]; oberflaeche(); });
    return;
  }
  t.textContent = s.name.toUpperCase();
  const tipps = { auswahl: 'Klicken wählt, Umschalt+Klick wählt mehrere. Punkte und Linien lassen sich ziehen – die Bedingungen bleiben erhalten.', linie: 'Punkte klicken. Klick auf den Startpunkt schließt die Form, Doppelklick oder Esc beendet. Fast waagrechte/senkrechte Linien bekommen automatisch die Bedingung.', rechteck: 'Zwei gegenüberliegende Ecken klicken.', rechteck_mitte: 'Mittelpunkt klicken, dann eine Ecke.', kreis: 'Mittelpunkt klicken, dann den Radius.', kreis3: 'Drei Punkte auf dem Kreis klicken.', bogen: 'Mittelpunkt, Startpunkt, dann Endpunkt (gegen den Uhrzeigersinn).', punkt: 'Punkte setzen – zum Beispiel als Bohrungsmitten.' };
  fo.innerHTML = `<p class="leer">${tipps[werkzeug] || ''}</p>${auswahl.length > 1 ? `<p class="leer">${auswahl.length} Objekte gewählt – oben eine Bedingung oder Bemaßung wählen.</p>` : ''}<p class="leer">${st ? statusText(st) : ''}</p>${feld('Name', 'name', s.name, 'text')}<p class="leer">Raster rastet ein – Umschalt hält frei. Formen in Formen werden zu Löchern.</p>`;
  binde(s);
}

// Fläche anklicken → Skizze darauf
function flaecheWaehlen(ev) {
  if (!koerperObj) return;
  const r = c3d.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2((ev.clientX - r.left) / r.width * 2 - 1, -(ev.clientY - r.top) / r.height * 2 + 1), kamera);
  const t = ray.intersectObject(koerperObj.getObjectByName('koerper'))[0]; if (!t) return;
  const n = t.face.normal.clone().normalize();
  for (const [k, b] of Object.entries(BASIS)) {
    const bn = new THREE.Vector3(...b.n), d = n.dot(bn);
    if (Math.abs(Math.abs(d) - 1) < 1e-3) { neueSkizze({ basis: k, versatz: runde(t.point.dot(bn), 4), umgedreht: d < 0 }); return; }
  }
  hinweis('Schräge Flächen gehen noch nicht – bitte eine gerade Fläche wählen');
}

// ---------- Overlay (Skizze) ----------
function overlayZeichnen() {
  ctx.clearRect(0, 0, overlay.width, overlay.height); etiketten = [];
  const s = sk(); if (!s) return;
  const E = ebene(s.ebene), dpr = devicePixelRatio, S = (x, y) => zuSchirm(E, x, y), d = dunkel();
  const st = rasterSchritt(), gross = st * 5, r = c3d.getBoundingClientRect();
  const ecken = [[0, 0], [r.width, 0], [0, r.height], [r.width, r.height]].map(([x, y]) => zuEbene(r.left + x, r.top + y)).filter(Boolean);
  if (ecken.length === 4) {
    const xs = ecken.map(e => e[0]), ys = ecken.map(e => e[1]);
    const x0 = Math.floor(Math.min(...xs) / st) * st, x1 = Math.max(...xs), y0 = Math.floor(Math.min(...ys) / st) * st, y1 = Math.max(...ys);
    ctx.lineWidth = 1;
    const linie = (a, b, c) => { ctx.strokeStyle = c; ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke(); };
    for (let x = x0; x <= x1; x += st) linie(S(x, y0), S(x, y1), Math.abs(x / gross - Math.round(x / gross)) < 1e-6 ? (d ? '#363b42' : '#d4d9df') : (d ? '#24272c' : '#e7eaee'));
    for (let y = y0; y <= y1; y += st) linie(S(x0, y), S(x1, y), Math.abs(y / gross - Math.round(y / gross)) < 1e-6 ? (d ? '#363b42' : '#d4d9df') : (d ? '#24272c' : '#e7eaee'));
    ctx.lineWidth = 1.5 * dpr; linie(S(x0, 0), S(x1, 0), '#d93025'); linie(S(0, y0), S(0, y1), '#00ae42');
  }
  const blau = '#0a7cff', norm = d ? '#e8eaed' : '#1f2329', hilfsF = d ? '#8a9099' : '#8a9099', voll = info?.skizzen?.[s.id]?.zustand === 'voll_bestimmt';
  const linienF = voll ? (d ? '#e8eaed' : '#1f2329') : (d ? '#7fb4ff' : '#1f5fbf');
  const pk = new Map(s.punkte.map(p => [p.id, p]));
  ctx.font = `${11 * dpr}px -apple-system,Segoe UI,sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (const e of s.elemente) {
    const gew = istGew('e', e.id);
    ctx.strokeStyle = gew ? blau : e.hilfs ? hilfsF : linienF; ctx.lineWidth = (gew ? 2.6 : 1.7) * dpr; ctx.setLineDash(e.hilfs ? [6 * dpr, 4 * dpr] : []);
    ctx.beginPath();
    if (e.art === 'kreis') { const m = pk.get(e.m); if (!m) continue; const c = S(m.x, m.y); ctx.arc(c[0], c[1], e.r * pxProMm() * dpr, 0, 2 * Math.PI); }
    else { const pts = e.art === 'linie' ? [[pk.get(e.a)?.x, pk.get(e.a)?.y], [pk.get(e.b)?.x, pk.get(e.b)?.y]] : bogenPunkte(e, pk); pts.forEach((p, i) => { const q = S(p[0], p[1]); i ? ctx.lineTo(...q) : ctx.moveTo(...q); }); }
    ctx.stroke(); ctx.setLineDash([]);
  }
  // Bedingungs-Symbole
  const sym = { horizontal: 'H', vertikal: 'V', parallel: '∥', senkrecht: '⊥', gleich: '=', tangential: 'T', mittelpunkt: 'M', symmetrisch: 'S', fix: '⚓', koinzident: '●', punkt_auf_linie: '◦', punkt_auf_kreis: '◦' };
  const mitte = id => { const e = pk.has(id) ? null : s.elemente.find(x => x.id === id); if (pk.has(id)) { const p = pk.get(id); return [p.x, p.y]; } if (!e) return null; if (e.art === 'linie') { const a = pk.get(e.a), b = pk.get(e.b); return a && b ? [(a.x + b.x) / 2, (a.y + b.y) / 2] : null; } const m = pk.get(e.m); return m ? [m.x + (e.r || 0), m.y] : null; };
  const zaehler = new Map();
  s.bedingungen.forEach((b, i) => {
    const z = sym[b.art]; if (!z || b.art === 'koinzident') return;
    const ziel = b.linie || b.a || b.punkt; const m = mitte(ziel); if (!m) return;
    const n = zaehler.get(ziel) || 0; zaehler.set(ziel, n + 1);
    const q = S(m[0], m[1]), x = q[0] + (10 + n * 16) * dpr, y = q[1] - 10 * dpr, gew = istGew('b', i);
    ctx.fillStyle = gew ? blau : (d ? '#2b3a2f' : '#e3f6ea'); ctx.fillRect(x - 7 * dpr, y - 7 * dpr, 14 * dpr, 14 * dpr);
    ctx.fillStyle = gew ? '#fff' : (d ? '#7fe0a5' : '#0f6e3c'); ctx.fillText(z, x, y);
    etiketten.push({ i, x0: x - 7 * dpr, x1: x + 7 * dpr, y0: y - 7 * dpr, y1: y + 7 * dpr });
  });
  // Bemaßungen
  const etikett = (txt, x, y, i) => {
    const w = ctx.measureText(txt).width + 10 * dpr, gew = istGew('b', i);
    ctx.fillStyle = gew ? blau : (d ? '#222529' : '#ffffff'); ctx.strokeStyle = blau; ctx.lineWidth = 1;
    ctx.fillRect(x - w / 2, y - 9 * dpr, w, 18 * dpr); ctx.strokeRect(x - w / 2, y - 9 * dpr, w, 18 * dpr);
    ctx.fillStyle = gew ? '#fff' : blau; ctx.fillText(txt, x, y);
    etiketten.push({ i, x0: x - w / 2, x1: x + w / 2, y0: y - 9 * dpr, y1: y + 9 * dpr });
  };
  const masslinie = (a, b, off) => {
    const A = S(...a), B = S(...b), dx = B[0] - A[0], dy = B[1] - A[1], l = Math.hypot(dx, dy) || 1, nx = -dy / l * off * dpr, ny = dx / l * off * dpr;
    ctx.strokeStyle = blau; ctx.lineWidth = 1 * dpr; ctx.beginPath(); ctx.moveTo(A[0], A[1]); ctx.lineTo(A[0] + nx, A[1] + ny); ctx.lineTo(B[0] + nx, B[1] + ny); ctx.lineTo(B[0], B[1]); ctx.stroke();
    return [(A[0] + B[0]) / 2 + nx, (A[1] + B[1]) / 2 + ny];
  };
  s.bedingungen.forEach((b, i) => {
    if (b.wert === undefined) return;
    const w = auswerten(b.wert), txt = (typeof b.wert === 'string' ? b.wert + ' = ' : '') + zahl(w);
    if (b.art === 'laenge') { const e = s.elemente.find(x => x.id === b.linie); const a = pk.get(e?.a), c = pk.get(e?.b); if (!a || !c) return; const m = masslinie([a.x, a.y], [c.x, c.y], 18); etikett(txt, m[0], m[1], i); }
    else if (b.art === 'abstand' || b.art === 'abstand_x' || b.art === 'abstand_y') {
      const a = pk.get(b.a); let c = pk.get(b.b); if (!a) return;
      if (!c) { const e = s.elemente.find(x => x.id === b.b); const p0 = pk.get(e?.a), p1 = pk.get(e?.b); if (!p0 || !p1) return; const dx = p1.x - p0.x, dy = p1.y - p0.y, t = ((a.x - p0.x) * dx + (a.y - p0.y) * dy) / (dx * dx + dy * dy); c = { x: p0.x + t * dx, y: p0.y + t * dy }; }
      const z = b.art === 'abstand_x' ? [c.x, a.y] : b.art === 'abstand_y' ? [a.x, c.y] : [c.x, c.y];
      const m = masslinie([a.x, a.y], z, b.art === 'abstand' ? 0 : 0); etikett((b.art === 'abstand_x' ? '↔ ' : b.art === 'abstand_y' ? '↕ ' : '') + txt, m[0], m[1] - 12 * dpr, i);
    }
    else if (b.art === 'durchmesser' || b.art === 'radius') { const e = s.elemente.find(x => x.id === b.kreis); const m = pk.get(e?.m); if (!m) return; const r = e.art === 'kreis' ? e.r : Math.hypot(pk.get(e.a).x - m.x, pk.get(e.a).y - m.y); const q = S(m.x + r * 0.7071, m.y + r * 0.7071); etikett((b.art === 'durchmesser' ? 'Ø ' : 'R ') + txt, q[0] + 16 * dpr, q[1] - 10 * dpr, i); }
    else if (b.art === 'winkel') { const m1 = mitte(b.a), m2 = mitte(b.b); if (!m1 || !m2) return; const q = S((m1[0] + m2[0]) / 2, (m1[1] + m2[1]) / 2); etikett(txt + '°', q[0], q[1], i); }
  });
  // Punkte
  for (const p of s.punkte) {
    const q = S(p.x, p.y), gew = istGew('p', p.id), urs = p.id === '0';
    ctx.fillStyle = gew ? blau : urs ? '#d93025' : (d ? '#e8eaed' : '#1f2329');
    const g = (urs ? 4 : 3) * dpr; ctx.fillRect(q[0] - g, q[1] - g, 2 * g, 2 * g);
  }
  // Entwurf
  if (entwurf && entwurf.maus) {
    const m = entwurf.maus; ctx.strokeStyle = blau; ctx.lineWidth = 1.5 * dpr; ctx.setLineDash([6 * dpr, 4 * dpr]); ctx.beginPath();
    const P = entwurf.pkte || [];
    const masse = [];
    if (entwurf.art === 'linie') { const a = entwurf.letzter || entwurf.start; const A = S(a.x, a.y), B = S(m.x, m.y); ctx.moveTo(...A); ctx.lineTo(...B); masse.push([zahl(Math.hypot(m.x - a.x, m.y - a.y)), (A[0] + B[0]) / 2, (A[1] + B[1]) / 2 - 14 * dpr]); }
    if (entwurf.art === 'rechteck' || entwurf.art === 'rechteck_mitte') { const a = P[0]; const dx = m.x - a.x, dy = m.y - a.y; const c = entwurf.art === 'rechteck' ? [[a.x, a.y], [m.x, a.y], [m.x, m.y], [a.x, m.y]] : [[a.x - dx, a.y - dy], [a.x + dx, a.y - dy], [a.x + dx, a.y + dy], [a.x - dx, a.y + dy]]; c.forEach((p, i) => { const q = S(...p); i ? ctx.lineTo(...q) : ctx.moveTo(...q); }); ctx.closePath(); const b = Math.abs(c[1][0] - c[0][0]), h = Math.abs(c[2][1] - c[1][1]); const q = S((c[0][0] + c[1][0]) / 2, Math.min(c[0][1], c[2][1])); masse.push([`${zahl(b)} × ${zahl(h)}`, q[0], q[1] + 16 * dpr]); }
    if (entwurf.art === 'kreis') { const a = P[0], r = Math.hypot(m.x - a.x, m.y - a.y), c = S(a.x, a.y); ctx.arc(c[0], c[1], r * pxProMm() * dpr, 0, 2 * Math.PI); masse.push(['Ø ' + zahl(2 * r), c[0], c[1] - r * pxProMm() * dpr - 14 * dpr]); }
    if (entwurf.art === 'kreis3') { const pts = [...P, m]; if (pts.length === 3) { const k = umkreis(...pts); if (k) { const c = S(k.x, k.y); ctx.arc(c[0], c[1], k.r * pxProMm() * dpr, 0, 2 * Math.PI); masse.push(['Ø ' + zahl(2 * k.r), c[0], c[1]]); } } else { const A = S(P[0].x, P[0].y), B = S(m.x, m.y); ctx.moveTo(...A); ctx.lineTo(...B); } }
    if (entwurf.art === 'bogen') { const c = P[0]; if (P.length === 1) { const A = S(c.x, c.y), B = S(m.x, m.y); ctx.moveTo(...A); ctx.lineTo(...B); } else { const a = P[1], r = Math.hypot(a.x - c.x, a.y - c.y), w0 = Math.atan2(a.y - c.y, a.x - c.x); let w1 = Math.atan2(m.y - c.y, m.x - c.x); while (w1 <= w0) w1 += 2 * Math.PI; for (let i = 0; i <= 48; i++) { const w = w0 + (w1 - w0) * i / 48, q = S(c.x + r * Math.cos(w), c.y + r * Math.sin(w)); i ? ctx.lineTo(...q) : ctx.moveTo(...q); } masse.push(['R ' + zahl(r), ...S(c.x, c.y)]); } }
    ctx.stroke(); ctx.setLineDash([]);
    for (const [t, x, y] of masse) { const w = ctx.measureText(t).width + 10 * dpr; ctx.fillStyle = d ? '#222529' : '#fff'; ctx.fillRect(x - w / 2, y - 9 * dpr, w, 18 * dpr); ctx.fillStyle = blau; ctx.fillText(t, x, y); }
  }
  if (fang && werkzeug !== 'auswahl') { const q = S(fang.x, fang.y); ctx.strokeStyle = '#00ae42'; ctx.lineWidth = 2 * dpr; ctx.strokeRect(q[0] - 6 * dpr, q[1] - 6 * dpr, 12 * dpr, 12 * dpr); }
  if (maus && werkzeug !== 'auswahl') { const q = S(maus.x, maus.y); ctx.fillStyle = d ? '#9aa0a6' : '#6b7280'; ctx.textAlign = 'left'; ctx.fillText(`${zahl(maus.x)}; ${zahl(maus.y)}`, q[0] + 12 * dpr, q[1] + 16 * dpr); }
}

// ---------- Export, Öffnen ----------
async function exportieren(f) {
  if (!info?.dreiecke) return hinweis('Noch kein Körper zum Exportieren');
  clearTimeout(speicherTimer); await speichern();
  const a = document.createElement('a'); a.href = `api/projekte/${doc.id}/export.${f}`; a.download = ''; document.body.appendChild(a); a.click(); a.remove();
}
async function oeffnenDialog() {
  const dlg = $('#dlgOeffnen'), li = $('#projliste'); dlg.showModal(); li.textContent = 'Lade …';
  try {
    const p = await (await fetch('api/projekte')).json();
    if (!p.length) { li.textContent = 'Noch keine Projekte.'; return; }
    li.innerHTML = ''; li.className = '';
    for (const x of p) {
      const d = document.createElement('div'); d.className = 'proj';
      d.innerHTML = `${ico('koerper')}<span>${esc(x.name)}</span><span class="zeit">${new Date(x.zeit * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })}</span><button class="k klein" title="Löschen">×</button>`;
      d.onclick = async ev => {
        if (ev.target.closest('button')) { ev.stopPropagation(); if (confirm(`„${x.name}“ löschen?`)) { await fetch('api/projekte/' + x.id, { method: 'DELETE' }); oeffnenDialog(); } return; }
        laden(await (await fetch('api/projekte/' + x.id)).json()); dlg.close();
      };
      li.appendChild(d);
    }
  } catch (e) { li.textContent = 'Server nicht erreichbar.'; }
}
function laden(j) {
  if (!j || !Array.isArray(j.features)) return hinweis('Keine gültige Bauwerk-Datei');
  if (skizzeAktiv) skizzeEnde();
  doc = { id: j.id || neueId() + neueId(), name: j.name || 'Teil', parameter: j.parameter || [], features: j.features, bis: j.bis };
  undoStapel.length = 0; redoStapel.length = 0; gewaehlt = null; parameterOffen = false;
  $('#name').value = doc.name; knopfStatus();
  // altes Format (Bauwerk 1) wandelt der Kern um – Ergebnis übernehmen
  fetch('api/berechnen', { method: 'POST', body: JSON.stringify(doc) }).then(r => r.arrayBuffer()).then(buf => {
    const jl = new DataView(buf).getUint32(0, true); const neu = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, jl)));
    if (j.features.some(f => f.formen)) doc = { ...neu.dok, id: doc.id };
    rechnen().then(() => setTimeout(() => ansicht('iso'), 30));
  });
  try { localStorage.setItem('bauwerk2-zuletzt', doc.id); } catch (e) {}
}
function hinweis(t, dauer = 3500) { const h = $('#hinweis'); clearTimeout(hinweis.t); h.textContent = t; h.style.display = t ? 'block' : 'none'; if (t && dauer) hinweis.t = setTimeout(() => h.style.display = 'none', dauer); }

// ---------- Tasten & Knöpfe ----------
document.addEventListener('keydown', e => {
  const imFeld = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
  const strg = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  if (strg && k === 's') { e.preventDefault(); speichern(); return; }
  if (imFeld) return;
  if (strg && k === 'z') { e.preventDefault(); e.shiftKey ? wiederholen() : rueckgaengig(); return; }
  if (strg && k === 'y') { e.preventDefault(); wiederholen(); return; }
  if (strg) return;
  if (skizzeAktiv) {
    if (e.key === 'Escape') { if (entwurf) { entwurf = null; zeichnen(); } else if (werkzeug !== 'auswahl') { werkzeug = 'auswahl'; oberflaeche(); } else if (auswahl.length) { auswahl = []; oberflaeche(); } else skizzeEnde(true); return; }
    if (e.key === 'Enter' && entwurf?.art === 'linie') { linieBeenden(); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { auswahlLoeschen(); return; }
    const w = { l: 'linie', r: 'rechteck', c: 'kreis', a: 'bogen', p: 'punkt' }[k];
    if (w) { werkzeug = w; entwurf = null; auswahl = []; oberflaeche(); return; }
    if (k === 'd') bemassen(); if (k === 'x') hilfsUmschalten(); if (k === 'h') bedingungSetzen('horizontal'); if (k === 'v') bedingungSetzen('vertikal');
  } else {
    if (e.key === 'Escape') { ebenenWahl = false; parameterOffen = false; gewaehlt = null; hinweis(''); oberflaeche(); }
    if ((e.key === 'Delete' || e.key === 'Backspace') && gewaehlt) featureLoeschen(gewaehlt);
    const w = { s: 'skizze', e: 'extrusion', b: 'bohrung' }[k]; if (w) befehl(w);
  }
});
document.querySelectorAll('#reiter button').forEach(b => b.onclick = () => {
  const r = b.dataset.reiter;
  if (r === 'skizze' && !skizzeAktiv) { const s = letzteSkizze(); if (s) skizzeStart(s.id); else { reiter = 'volumen'; befehl('skizze'); } return; }
  if (r !== 'skizze' && skizzeAktiv) skizzeEnde(true);
  reiter = r; oberflaeche();
});
$('#kNeu').innerHTML = ico('neu') + '<span class="nurgross">Neu</span>';
$('#kOeffnen').innerHTML = ico('oeffnen') + '<span class="nurgross">Öffnen</span>';
$('#kUndo').innerHTML = ico('undo'); $('#kRedo').innerHTML = ico('redo'); $('#kThema').innerHTML = ico('thema');
$('#kNeu').onclick = () => { speichern(); laden(neuesDok()); };
$('#kOeffnen').onclick = oeffnenDialog;
$('#kUndo').onclick = rueckgaengig; $('#kRedo').onclick = wiederholen;
$('#kThema').onclick = () => { const t = dunkel() ? 'hell' : 'dunkel'; document.documentElement.dataset.thema = t; try { localStorage.setItem('bauwerk-thema', t); } catch (e) {} farbenThema(); oberflaeche(); };
$('#name').addEventListener('change', e => { merken(); doc.name = e.target.value; aenderung(); });
document.querySelectorAll('[data-ansicht]').forEach(b => b.onclick = () => { if (skizzeAktiv) skizzeEnde(true); ansicht(b.dataset.ansicht); });
document.querySelectorAll('[data-schliessen]').forEach(b => b.onclick = () => b.closest('dialog').close());
$('#kDateiLaden').onclick = () => $('#dateiwahl').click();
$('#dateiwahl').onchange = async e => { const f = e.target.files[0]; if (!f) return; try { const j = JSON.parse(await f.text()); j.id = neueId() + neueId(); laden(j); $('#dlgOeffnen').close(); } catch (x) { hinweis('Datei nicht lesbar'); } e.target.value = ''; };
$('#kDateiSichern').onclick = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 1)], { type: 'application/json' })); a.download = (doc.name || 'teil').replace(/[\\/:*?"<>|]+/g, '_') + '.bwk'; a.click(); };

// ---------- Start ----------
try { const t = localStorage.getItem('bauwerk-thema'); if (t) document.documentElement.dataset.thema = t; } catch (e) {}
farbenThema(); knopfStatus(); groesse();
window.__bauwerk = { get doc() { return doc; }, get info() { return info; }, laden, befehl, skizzeStart, skizzeEnde, neueSkizze, aenderung, rechnenSofort, set auswahl(a) { auswahl = a; oberflaeche(); } };
(async () => {
  const q = new URLSearchParams(location.search).get('projekt');
  let id = q; try { id ||= localStorage.getItem('bauwerk2-zuletzt'); } catch (e) {}
  if (id) { try { const r = await fetch('api/projekte/' + encodeURIComponent(id)); if (r.ok) { laden(await r.json()); return; } } catch (e) {} }
  oberflaeche(); rechnen(); ansicht('iso');
})();
