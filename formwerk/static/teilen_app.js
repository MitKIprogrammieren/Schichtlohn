// Formwerk · Teilen – Schnittwerkzeuge nach Art von ModelSplitter
import * as THREE from 'three';
import { OrbitControls } from '/vendor/OrbitControls.js';

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const DRUCKER = [
  { name: 'Bambu Lab H2C', x: 325, y: 320, z: 325 },
  { name: 'Bambu Lab H2S', x: 340, y: 320, z: 340 },
  { name: 'Bambu Lab P2S', x: 256, y: 256, z: 256 },
  { name: 'Bambu Lab X1 Carbon', x: 256, y: 256, z: 256 },
  { name: 'Bambu Lab A1', x: 256, y: 256, z: 256 },
  { name: 'Bambu Lab A1 mini', x: 180, y: 180, z: 180 },
  { name: 'Snapmaker U1', x: 270, y: 270, z: 270 },
  { name: 'Creality K2 Plus', x: 350, y: 350, z: 350 },
];
const GRAU = 0x9a9ea3, AUSGEWAEHLT = 0xf08a3c, GRUEN = 0x00ae42;
// Ersatzfarben, falls die 3MF keine Filamentfarben mitbringt
const PALETTE = ['#F4F4F4', '#E53935', '#1E88E5', '#FDD835', '#43A047', '#8E24AA', '#FB8C00', '#212121', '#00ACC1', '#6D4C41', '#EC407A', '#9E9E9E'];
function filFarbe(f) {
  const l = stand?.filamente || [];
  return (l[f - 1] && /^#[0-9a-f]{6}$/i.test(l[f - 1])) ? l[f - 1] : PALETTE[(f - 1) % PALETTE.length];
}
const bemalung = nr => stand?.bemalung?.find(b => b.teil === nr);

// ───────── Zustand ─────────
let sid = null, stand = null, werkzeug = 'band', auswahl = null, plan = null, band = null;
let letzteDauer = null;
const teilObj = new Map();        // nr → THREE.Mesh
const geoCache = new Map();       // nr → Geometrie (je Sitzung)
const einst = Object.assign({ fbStecken: true, fbTiefe: 1.2, fbSpiel: 0.15, fbMin: 4, fbZusammen: false, art: 'fest', form: 'rund', d: '', spiel: 0.15, anz: '', md: 6, mh: 3, nummern: true, labels: true, explo: false,
  drucker: 0, rand: 5, ebAchse: 2, ebKippA: 0, ebKippB: 0, mf: [1, 1, 2], pinselPx: 28, kipp: 0, schub: 0 },
  JSON.parse(localStorage.getItem('fw_teilen') || '{}'));
const merken = () => localStorage.setItem('fw_teilen', JSON.stringify(einst));

// ───────── 3D ─────────
const view = $('#view'), cv = $('#cv');
const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const hgFarbe = () => new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim() || '#e8e8e8');
scene.background = hgFarbe();
const cam = new THREE.PerspectiveCamera(35, 1, 1, 50000); cam.up.set(0, 0, 1); cam.position.set(300, -500, 350);
const ctl = new OrbitControls(cam, cv); ctl.enableDamping = false;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f96, 1.5));
const sonne = new THREE.DirectionalLight(0xffffff, 1.4); sonne.position.set(-0.4, -1, 1.4); scene.add(sonne);
const sonne2 = new THREE.DirectionalLight(0xffffff, 0.45); sonne2.position.set(1, 0.8, -0.3); scene.add(sonne2);
const bettGrp = new THREE.Group(), teileGrp = new THREE.Group(), hilfGrp = new THREE.Group();
scene.add(bettGrp, teileGrp, hilfGrp);

function groesse() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h, false); cam.aspect = w / Math.max(h, 1); cam.updateProjectionMatrix();
  $('#overlay').setAttribute('viewBox', `0 0 ${w} ${h}`);
}
new ResizeObserver(groesse).observe(view); groesse();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { scene.background = hgFarbe(); });

function maus() {
  const links = ['band', 'ebene', 'mehrfach', 'auto', 'farben'].includes(werkzeug) ? THREE.MOUSE.ROTATE : null;
  ctl.mouseButtons = { LEFT: links, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE };
}

// ───────── Hilfen ─────────
const v3 = a => new THREE.Vector3(a[0], a[1], a[2]);
const arr = v => [v.x, v.y, v.z];
function busy(an, text) { $('#busy').classList.toggle('on', an); if (text) $('#busyText').textContent = text; }
function meldung(liste, fehler) {
  $('#msgs').innerHTML = (liste || []).map(m => `<div class="${fehler ? 'e' : ''}">${esc(m)}</div>`).join('');
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(pfad, daten, text = 'Rechne …', still = false) {
  if (!still) busy(true, text);
  try {
    const r = await fetch(`/api/teilen/${pfad}`, daten === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(daten) });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('json')) { if (!r.ok) throw new Error('Serverfehler ' + r.status); return r; }
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || 'Fehler');
    return j;
  } finally { if (!still) busy(false); }
}

function drucker() { return DRUCKER[einst.drucker] || DRUCKER[0]; }
function verbindung() {
  return { art: einst.art, form: einst.form, d: +einst.d || 0, spiel: +einst.spiel || 0, anzahl: +einst.anz || 0, magnet_d: +einst.md || 6, magnet_h: +einst.mh || 3, nummern: einst.nummern };
}
function passt(g) {
  const d = drucker(), r = +einst.rand || 0;
  const a = [...g].sort((x, y) => y - x), b = [d.x - 2 * r, d.y - 2 * r, d.z].sort((x, y) => y - x);
  return a.every((x, i) => x <= b[i] + 1e-6);
}
const teilInfo = nr => stand?.teile.find(t => t.nr === nr);
function gesamtBox() {
  const b = new THREE.Box3();
  for (const t of stand?.teile || []) { b.expandByPoint(v3(t.min)); b.expandByPoint(v3(t.max)); }
  return b;
}
function versatz(nr) {
  const m = teilObj.get(nr);
  return m ? m.position.clone() : new THREE.Vector3();
}

// ───────── Laden ─────────
$('#oeffnen').onclick = () => $('#file').click();
$('#dropBox').onclick = () => $('#file').click();
$('#file').onchange = e => { if (e.target.files[0]) laden(e.target.files[0]); e.target.value = ''; };
view.addEventListener('dragover', e => { e.preventDefault(); $('#drop').classList.add('over'); });
view.addEventListener('dragleave', () => $('#drop').classList.remove('over'));
view.addEventListener('drop', e => { e.preventDefault(); $('#drop').classList.remove('over'); if (e.dataTransfer.files[0]) laden(e.dataTransfer.files[0]); });

async function laden(datei) {
  const fd = new FormData(); fd.append('file', datei);
  busy(true, 'Lade Modell …');
  try {
    const r = await fetch('/api/teilen/laden', { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || 'Fehler');
    sid = j.sid; geoCache.clear(); malGeo.clear(); for (const m of teilObj.values()) teileGrp.remove(m); teilObj.clear();
    auswahl = null; nahtWeg();
    await zeigen(j, true);
    meldung([]);
    if (j.bemalung?.length && werkzeug !== 'farben') $('#tools .t[data-t="farben"]').click();
  } catch (e) { meldung([e.message], true); } finally { busy(false); }
}

async function geometrie(nr) {
  if (geoCache.has(nr)) return geoCache.get(nr);
  const r = await fetch(`/api/teilen/${sid}/teil/${nr}`);
  if (!r.ok) throw new Error('Teil konnte nicht geladen werden – Sitzung abgelaufen?');
  const pos = new Float32Array(await r.arrayBuffer());
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.computeVertexNormals(); g.computeBoundingBox(); g.computeBoundingSphere();
  geoCache.set(nr, g);
  return g;
}

async function zeigen(st, kamera = false) {
  stand = st;
  $('#modellName').textContent = st.name || 'Teilen';
  $('#drop').style.display = 'none';
  const da = new Set(st.teile.map(t => t.nr));
  for (const [nr, m] of teilObj) if (!da.has(nr)) { teileGrp.remove(m); m.material.dispose(); teilObj.delete(nr); }
  await Promise.all(st.teile.map(async t => {
    if (teilObj.has(t.nr)) return;
    const g = await geometrie(t.nr);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: GRAU, roughness: 0.72, metalness: 0.04 }));
    m.userData.nr = t.nr; m.userData.geo = g;
    teilObj.set(t.nr, m); teileGrp.add(m);
  }));
  if (!auswahl || !teilInfo(auswahl)) {
    const groesstes = [...st.teile].sort((a, b) => b.volumen - a.volumen)[0];
    auswahl = groesstes?.nr ?? null;
  }
  explosion();
  faerben();
  bett();
  liste();
  if (kamera) blick('home');
  werkzeugOptionen();
  knoepfe();
  if (st.hinweise?.length) meldung(st.hinweise);
}

const malGeo = new Map(); // nr → bemalte Vorschau-Geometrie
async function bemaltHolen(nr) {
  if (malGeo.has(nr)) return malGeo.get(nr);
  malGeo.set(nr, null);
  const r = await fetch(`/api/teilen/${sid}/bemalung/${nr}`);
  if (!r.ok) return null;
  const buf = await r.arrayBuffer(), n = new Uint32Array(buf, 0, 1)[0];
  const pos = new Float32Array(buf, 4, n * 9), fil = new Uint8Array(buf, 4 + n * 36, n);
  const col = new Float32Array(n * 9), c = new THREE.Color();
  for (let i = 0; i < n; i++) { c.set(filFarbe(fil[i] || 1)).convertSRGBToLinear(); for (let k = 0; k < 3; k++) col.set([c.r, c.g, c.b], i * 9 + k * 3); }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.computeVertexNormals(); g.computeBoundingBox(); g.computeBoundingSphere();
  malGeo.set(nr, g); faerben();
  return g;
}
function faerben() {
  for (const [nr, m] of teilObj) {
    const t = teilInfo(nr);
    const bunt = werkzeug === 'farben' && bemalung(nr);
    const mg = bunt ? malGeo.get(nr) : null;
    if (bunt && !malGeo.has(nr)) bemaltHolen(nr);
    const soll = mg || m.userData.geo;
    if (soll && m.geometry !== soll) m.geometry = soll;
    const malt = (werkzeug === 'malen' && m.geometry.getAttribute('color') && nr === auswahl) || !!mg;
    m.material.vertexColors = !!malt;
    const fil = t?.farbe > 0;
    m.material.color.set(malt ? 0xffffff : fil ? filFarbe(t.farbe) : nr === auswahl ? AUSGEWAEHLT : GRAU);
    m.material.emissive.set(nr === auswahl && fil && !mg ? 0x3a1c00 : 0x000000);
    m.material.needsUpdate = true;
  }
}

function explosion() {
  const box = gesamtBox(), mitte = box.getCenter(new THREE.Vector3());
  const k = einst.explo ? 0.4 : 0;
  for (const t of stand?.teile || []) {
    const m = teilObj.get(t.nr); if (!m) continue;
    const c = v3(t.min).add(v3(t.max)).multiplyScalar(0.5);
    m.position.copy(c.sub(mitte).multiplyScalar(k));
  }
}

function bett() {
  bettGrp.clear();
  if (!stand?.teile.length) return;
  const d = drucker(), box = gesamtBox(), c = box.getCenter(new THREE.Vector3());
  const z = box.min.z - 0.05;
  const pl = new THREE.Mesh(new THREE.PlaneGeometry(d.x, d.y), new THREE.MeshStandardMaterial({ color: 0xd4d4d4, roughness: 1 }));
  pl.position.set(c.x, c.y, z - 0.3); bettGrp.add(pl);
  const pts = [];
  for (let x = -d.x / 2; x <= d.x / 2 + 0.01; x += d.x / 8) pts.push(c.x + x, c.y - d.y / 2, z, c.x + x, c.y + d.y / 2, z);
  for (let y = -d.y / 2; y <= d.y / 2 + 0.01; y += d.y / 8) pts.push(c.x - d.x / 2, c.y + y, z, c.x + d.x / 2, c.y + y, z);
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  bettGrp.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xbdbdbd })));
}

function blick(art) {
  const box = gesamtBox(); if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() * 0.5;
  const dist = r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2)) * 1.05;
  const dir = art === 'oben' ? new THREE.Vector3(0, -0.001, 1) : art === 'vorne' ? new THREE.Vector3(0, -1, 0.05) : new THREE.Vector3(0.55, -1, 0.7);
  cam.position.copy(c).add(dir.normalize().multiplyScalar(dist));
  cam.near = Math.max(0.5, dist / 500); cam.far = dist * 20; cam.updateProjectionMatrix();
  ctl.target.copy(c); ctl.update();
}
$('#vHome').onclick = () => blick('home');
$('#vOben').onclick = () => blick('oben');
$('#vVorne').onclick = () => blick('vorne');

// ───────── Teileliste & Werte ─────────
function liste() {
  const st = stand;
  if (!st?.teile.length) { $('#teile').innerHTML = '<div class="leer">Noch kein Modell geladen</div>'; return; }
  $('#teile').innerHTML = st.teile.map(t => {
    const g = t.groesse.map(x => Math.round(x)).join('×');
    const ok = passt(t.groesse);
    return `<div class="obj ${t.nr === auswahl ? 'on' : ''}" data-nr="${t.nr}" title="Doppelklick zum Umbenennen">
      <i style="background:${t.farbe > 0 ? filFarbe(t.farbe) : t.nr === auswahl ? '#f08a3c' : '#9a9ea3'};${t.farbe > 0 ? 'border:1px solid rgba(0,0,0,.2)' : ''}${t.nr === auswahl && t.farbe > 0 ? ';outline:2px solid #f08a3c' : ''}"></i><span class="n">${t.nr} · ${esc(t.name)}${t.gruppe ? ' <span style="color:var(--muted)">⛓</span>' : ''}</span>
      <span class="s">${g}</span><span class="${ok ? 'ok' : 'x'}">${ok ? '✓' : '✗'}</span></div>`;
  }).join('');
  $$('#teile .obj').forEach(el => {
    el.onclick = () => waehlen(+el.dataset.nr);
    el.ondblclick = async () => {
      const t = teilInfo(+el.dataset.nr); const n = prompt('Name für das Teil', t.name);
      if (n && n.trim()) { try { await zeigen(await api(`${sid}/umbenennen`, { teil: t.nr, name: n })); } catch (e) { meldung([e.message], true); } }
    };
  });
  const zapfen = st.fugen.reduce((s, f) => s + f.anzahl, 0);
  const anzOk = st.teile.filter(t => passt(t.groesse)).length;
  const d = drucker();
  $('#stats').innerHTML = [
    ['Druckbett', `${d.x} × ${d.y} × ${d.z} mm`],
    ['Teile', st.teile.length],
    ['Fugen', st.fugen.length],
    ['Verbinder', zapfen + (st.lose ? ` · ${st.lose} lose Zapfen` : '')],
    ['Passt aufs Bett', anzOk === st.teile.length ? '<span class="ok">alle ✓</span>' : `<span class="no">${anzOk} von ${st.teile.length}</span>`],
    ['Volumen', `${st.teile.reduce((s, t) => s + t.volumen, 0).toFixed(1)} cm³`],
    ...(letzteDauer != null ? [['Schnittdauer', `${(letzteDauer / 1000).toFixed(1).replace('.', ',')} s`]] : []),
  ].map(([a, b]) => `<span>${a}</span><span>${b}</span>`).join('');
}

function waehlen(nr) {
  if (nr === auswahl) return;
  auswahl = nr; nahtWeg(); faerben(); liste(); werkzeugOptionen();
}

function knoepfe() {
  const hat = !!sid && !!stand;
  const kann = hat && (!!plan || ['mehrfach', 'auto'].includes(werkzeug) && auswahl != null);
  $('#schneidenOben').disabled = !kann; $('#schneidenUnten').disabled = !kann;
  $('#zurueck').disabled = !(hat && stand.zurueck);
  $('#speichern').disabled = !hat;
  $$('[data-ex]').forEach(b => b.disabled = !hat); $('#pdf').disabled = !hat;
  $('#bar').style.display = hat && ['band', 'malen', 'linie', 'ebene'].includes(werkzeug) ? 'flex' : 'none';
}

// ───────── Einstellungen ─────────
function sw(id, key, nach) {
  const el = $(id); el.classList.toggle('on', !!einst[key]);
  el.onclick = () => { einst[key] = !einst[key]; el.classList.toggle('on', einst[key]); merken(); nach?.(); };
}
sw('#swNum', 'nummern');
sw('#swLbl', 'labels');
sw('#swExp', 'explo', () => { explosion(); ringeZeigen(); });
function seg(id, key, nach) {
  $$(`${id} [data-v]`).forEach(el => {
    el.classList.toggle('on', el.dataset.v === einst[key]);
    el.onclick = () => { einst[key] = el.dataset.v; $$(`${id} [data-v]`).forEach(x => x.classList.toggle('on', x === el)); merken(); nach?.(); };
  });
}
function artUmschalten() {
  $('#formWahl').style.display = ['magnet', 'keine'].includes(einst.art) ? 'none' : '';
  $('#magnetWahl').style.display = einst.art === 'magnet' ? '' : 'none';
}
seg('#art', 'art', artUmschalten); seg('#form', 'form'); artUmschalten();
for (const [id, key] of [['#vd', 'd'], ['#spiel', 'spiel'], ['#anz', 'anz'], ['#md', 'md'], ['#mh', 'mh'], ['#rand', 'rand']]) {
  $(id).value = einst[key]; $(id).oninput = () => { einst[key] = $(id).value; merken(); if (key === 'rand') liste(); };
}
$('#drucker').innerHTML = DRUCKER.map((d, i) => `<option value="${i}">${d.name.replace('Bambu Lab ', '')}</option>`).join('');
$('#drucker').value = einst.drucker;
$('#drucker').onchange = () => { einst.drucker = +$('#drucker').value; merken(); bett(); liste(); werkzeugOptionen(); };
$$('.sec h3').forEach(h => h.onclick = () => h.parentElement.classList.toggle('zu'));

// ───────── Werkzeuge ─────────
const HINWEIS = {
  band: 'Auf ein Glied klicken – das Band legt sich quer herum · Ziehen dreht · Mittelklick verschiebt',
  malen: 'Über das Stück malen, das ab soll – der Pinsel malt durch das ganze Glied · Shift = radieren · Rechtsklick dreht',
  linie: 'Linie über das Modell ziehen – geschnitten wird in Blickrichtung · Rechtsklick dreht',
  ebene: 'Teil anklicken, Achse und Lage wählen · Ziehen dreht',
  mehrfach: 'Teil anklicken, Anzahl je Richtung wählen · Ziehen dreht',
  auto: 'Teil anklicken – Formwerk teilt es in möglichst wenige Stücke, die aufs Bett passen',
  farben: 'Bemaltes Teil anklicken – jede gemalte Farbe wird ein eigenes, druckbares Teil',
};
$$('#tools .t[data-t]').forEach(el => {
  el.classList.toggle('on', el.dataset.t === werkzeug);
  el.onclick = () => {
    if (werkzeug === el.dataset.t) return;
    werkzeug = el.dataset.t;
    $$('#tools .t').forEach(x => x.classList.toggle('on', x === el));
    nahtWeg(); maus(); werkzeugOptionen(); faerben();
  };
});

function zeile(label, inhalt) { return `<div class="row"><label>${label}</label><div class="c">${inhalt}</div></div>`; }
function regler(id, min, max, step, wert, einheit) {
  return `<input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${wert}"><span class="u" id="${id}W" style="min-width:42px;text-align:right">${wert}${einheit}</span>`;
}

function werkzeugOptionen() {
  const o = $('#werkzeugOpt');
  $('#hint').textContent = sid ? HINWEIS[werkzeug] : 'Modell öffnen';
  const t = teilInfo(auswahl);
  if (werkzeug === 'band') {
    o.innerHTML = zeile('Band kippen', regler('kipp', -45, 45, 1, einst.kipp, '°')) + zeile('Band verschieben', regler('schub', -40, 40, 0.5, einst.schub, ' mm')) +
      '<div class="help">Formwerk sucht die schmalste Stelle quer zum Glied. Mit Kippen und Verschieben fein einstellen.</div>';
    for (const k of ['kipp', 'schub']) $('#' + k).oninput = e => { einst[k] = +e.target.value; $(`#${k}W`).textContent = e.target.value + (k === 'kipp' ? '°' : ' mm'); merken(); bandAnpassen(); };
  } else if (werkzeug === 'malen') {
    o.innerHTML = zeile('Pinselgröße', regler('pinsel', 5, 120, 1, einst.pinselPx, ' px')) +
      '<div class="help">Formwerk legt eine Schnittebene durch den Rand der bemalten Fläche und trennt genau dieses Stück ab.</div>';
    $('#pinsel').oninput = e => { einst.pinselPx = +e.target.value; $('#pinselW').textContent = e.target.value + ' px'; merken(); };
  } else if (werkzeug === 'linie') {
    o.innerHTML = '<div class="help">Ein gerader Schnitt durch das ganze ausgewählte Teil – wie mit einem Messer in Blickrichtung. Für schräge Schnitte das Modell vorher drehen.</div>';
  } else if (werkzeug === 'ebene') {
    const ax = einst.ebAchse, mn = t ? t.min[ax] : 0, mx = t ? t.max[ax] : 100;
    if (einst.ebPos == null || einst.ebPos < mn || einst.ebPos > mx || einst.ebTeil !== auswahl) { einst.ebPos = +((mn + mx) / 2).toFixed(1); einst.ebTeil = auswahl; }
    o.innerHTML = `<div class="seg" id="ebAchse">${['X', 'Y', 'Z'].map((a, i) => `<span data-a="${i}" class="${i === ax ? 'on' : ''}">${a}</span>`).join('')}</div>` +
      zeile('Lage', regler('ebPos', mn.toFixed(1), mx.toFixed(1), 0.1, einst.ebPos, ' mm')) +
      zeile('Kippen A', regler('ebKippA', -60, 60, 1, einst.ebKippA, '°')) + zeile('Kippen B', regler('ebKippB', -60, 60, 1, einst.ebKippB, '°'));
    $$('#ebAchse span').forEach(s => s.onclick = () => { einst.ebAchse = +s.dataset.a; einst.ebPos = null; merken(); werkzeugOptionen(); });
    for (const k of ['ebPos', 'ebKippA', 'ebKippB']) $('#' + k).oninput = e => { einst[k] = +e.target.value; $(`#${k}W`).textContent = e.target.value + (k === 'ebPos' ? ' mm' : '°'); merken(); ebenePlanen(); };
    ebenePlanen();
  } else if (werkzeug === 'mehrfach') {
    o.innerHTML = ['X', 'Y', 'Z'].map((a, i) => zeile(`Stücke in ${a}`, `<input type="number" id="mf${i}" min="1" max="12" step="1" value="${einst.mf[i]}">`)).join('') +
      '<div class="help">Teilt das ausgewählte Teil gleichmäßig in jede Richtung.</div>';
    [0, 1, 2].forEach(i => $('#mf' + i).oninput = e => { einst.mf[i] = Math.max(1, Math.min(12, +e.target.value || 1)); merken(); mehrfachVorschau(); });
    mehrfachVorschau();
  } else if (werkzeug === 'farben') {
    farbOptionen(o, t);
  } else if (werkzeug === 'auto') {
    const d = drucker();
    o.innerHTML = `<div class="help">Druckbett: <b>${d.name}</b> (${d.x}×${d.y}×${d.z} mm, ${einst.rand} mm Rand) – rechts unter „Messwerte“ änderbar.<br>` +
      (t ? (passt(t.groesse) ? '<span class="ok">Das ausgewählte Teil passt schon aufs Bett.</span>' : `Ausgewähltes Teil: ${t.groesse.map(Math.round).join('×')} mm – wird an den schmalsten Stellen geteilt.`) : '') + '</div>';
    hilfGrp.clear();
  }
  knoepfe();
}

function farbOptionen(o, t) {
  hilfGrp.clear();
  const b = t ? bemalung(t.nr) : null;
  const alle = stand?.bemalung || [];
  if (!b) {
    const fertig = stand?.teile.some(x => x.farbe > 0) && !alle.length;
    if (fertig) {
      o.innerHTML = '<div class="help"><span class="ok">Farben sind herausgelöst.</span> Die Farbteile stehen rechts in der Liste.<br><br>Ist der Grundkörper zu groß fürs Druckbett, jetzt mit Band, Ebene oder Auto schneiden – die Verbinder kommen wie gewohnt dazu.<br><br>Export: <b>Bambu-3MF</b> legt jedes Teil mit seinem Filament an.</div>';
      return;
    }
    o.innerHTML = `<div class="help">${alle.length ? 'Das ausgewählte Teil hat keine Bemalung (mehr). Bemaltes Teil anklicken' + (alle.length ? ` – z. B. Teil ${alle.map(x => x.teil).join(', ')}` : '') + '.' :
      'Gemalte Farben aus Bambu Studio, Orca oder PrusaSlicer werden zu festen Teilen – jede Farbe ein eigenes, druckbares Stück.<br><br>Dafür eine <b>bemalte 3MF</b> öffnen. Farben am besten <b>vor dem Schneiden</b> herauslösen.'}</div>`;
    return;
  }
  const min = +einst.fbMin || 0;
  const zeilen = [`<div class="fl"><i style="background:${filFarbe(b.basis)}"></i><span class="n"><b>Filament ${b.basis}</b> · Grundkörper</span><span class="s">bleibt</span></div>`];
  for (const f of b.farben) {
    if (f.f === b.basis) continue;
    const gross = f.bereiche.filter(a => a >= min).length, klein = f.bereiche.length - gross;
    const text = f.bereiche.length ? `${gross} ${gross === 1 ? 'Bereich' : 'Bereiche'}${klein ? ` <span style="color:var(--muted)">(+${klein} zu klein)</span>` : ''}` : 'eigener Körper';
    zeilen.push(`<div class="fl"><i style="background:${filFarbe(f.f)}"></i><span class="n"><b>Filament ${f.f}</b> · ${text}</span><span class="s">wird Teil</span></div>`);
  }
  o.innerHTML = '<div class="help">Gemalte Farben werden zu festen Teilen – jede Farbe ein eigenes, druckbares Stück.</div>' + zeilen.join('') +
    '<div style="margin-top:8px;color:var(--muted);font-size:12px">Ergebnis</div>' +
    `<div class="seg" id="fbModus"><span data-v="ams" class="${einst.fbStecken ? '' : 'on'}">Im Objekt (AMS)</span><span data-v="stecken" class="${einst.fbStecken ? 'on' : ''}">Zum Einstecken</span></div>` +
    `<div class="help" style="margin-top:0">${einst.fbStecken ? 'Jedes Farbteil einzeln und einfarbig drucken, dann in die Tasche im Grundkörper stecken (ggf. kleben). Sichtseite liegt beim Druck unten.' : 'Alles bleibt ein Objekt mit passgenauen Teilen je Filament – mit AMS in einem Rutsch drucken.'}</div>` +
    zeile('Tiefe der Farbteile', `<input type="number" id="fbTiefe" min="0.4" max="10" step="0.1" value="${einst.fbTiefe}"><span class="u">mm</span>`) +
    (einst.fbStecken ? zeile('Spiel', `<input type="number" id="fbSpiel" min="0" max="0.6" step="0.05" value="${einst.fbSpiel}"><span class="u">mm</span>`) : '') +
    zeile('Kleine Flecken weglassen unter', `<input type="number" id="fbMin" min="0" step="1" value="${einst.fbMin}"><span class="u">mm²</span>`) +
    zeile('Gleiche Farbe zu einem Teil', '<div class="sw" id="swFbZus"></div>') +
    '<button class="btn p" id="fbLos" style="width:100%;margin-top:6px">Farben herauslösen</button>';
  $$('#fbModus span').forEach(s => s.onclick = () => { einst.fbStecken = s.dataset.v === 'stecken'; merken(); werkzeugOptionen(); });
  for (const k of ['fbTiefe', 'fbSpiel', 'fbMin']) if ($('#' + k)) $('#' + k).onchange = e => { einst[k] = +e.target.value; merken(); if (k === 'fbMin') werkzeugOptionen(); };
  sw('#swFbZus', 'fbZusammen');
  $('#fbLos').onclick = async () => {
    try {
      const r = await api(`${sid}/farben`, { teil: t.nr, stecken: !!einst.fbStecken, tiefe: +einst.fbTiefe || 1.2, spiel: +einst.fbSpiel || 0, min_flaeche: +einst.fbMin || 0, zusammen: !!einst.fbZusammen }, 'Löse Farben heraus …');
      auswahl = null; await zeigen(r);
      if (!einst.explo) { einst.explo = true; $('#swExp').classList.add('on'); merken(); explosion(); }
    } catch (e) { meldung([e.message], true); }
  };
}

// ───────── Vorschau-Ringe ─────────
let ringDaten = null; // { teil, ringe }
function ringeZeigen() {
  hilfGrp.clear();
  if (ringDaten) {
    const off = versatz(ringDaten.teil);
    const mat = new THREE.LineBasicMaterial({ color: GRUEN, depthTest: false, transparent: true });
    for (const r of ringDaten.ringe) {
      const g = new THREE.BufferGeometry().setFromPoints(r.map(p => v3(p).add(off)));
      const l = new THREE.LineLoop(g, mat); l.renderOrder = 10; hilfGrp.add(l);
    }
  }
  if (ebenenVorschau) for (const e of ebenenVorschau) hilfGrp.add(e);
}
let ebenenVorschau = null;
function ebeneFlaeche(punkt, n, groesse) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(groesse, groesse), new THREE.MeshBasicMaterial({ color: GRUEN, transparent: true, opacity: 0.13, side: THREE.DoubleSide, depthWrite: false }));
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n.clone().normalize());
  m.position.copy(punkt);
  return m;
}

let ringTimer = null, ringNr = 0;
function ringHolen(anfrage, alsPlan) {
  clearTimeout(ringTimer);
  ringTimer = setTimeout(async () => {
    const meine = ++ringNr;
    try {
      const r = await api(`${sid}/ring`, anfrage, '', true);
      if (meine !== ringNr) return;
      ringDaten = { teil: anfrage.teil, ringe: r.ringe };
      plan = r.ringe.length ? { teil: anfrage.teil, punkt: r.punkt, normale: r.normale, ort: alsPlan, ...(anfrage.linie ? { linie: anfrage.linie } : {}) } : null;
      if (!r.ringe.length) meldung(['Die Schnittebene trifft das Teil hier nicht.']);
      else meldung([]);
      ringeZeigen(); knoepfe();
    } catch (e) { if (meine === ringNr) { meldung([e.message], true); plan = null; ringDaten = null; ringeZeigen(); knoepfe(); } }
  }, 120);
}

function nahtWeg() {
  plan = null; band = null; ringDaten = null; ebenenVorschau = null; linie = null;
  $('#overlay').innerHTML = '';
  for (const m of teilObj.values()) if (m.userData.geo?.getAttribute('color')) { m.userData.geo.deleteAttribute('color'); m.userData.gemalt = null; }
  faerben(); ringeZeigen(); knoepfe();
}
$('#nahtWeg').onclick = () => { nahtWeg(); if (werkzeug === 'ebene') ebenePlanen(); };

// Band
async function bandSetzen(nr, punkt, sn) {
  einst.kipp = 0; einst.schub = 0; merken();
  if ($('#kipp')) { $('#kipp').value = 0; $('#kippW').textContent = '0°'; $('#schub').value = 0; $('#schubW').textContent = '0 mm'; }
  try {
    const r = await api(`${sid}/ring`, { teil: nr, punkt: arr(punkt), flaeche_n: arr(sn), kipp: 0, ort: 'rand' }, 'Suche die schmalste Stelle …');
    band = { teil: nr, punkt, sn, n0: v3(r.normale) };
    ringDaten = { teil: nr, ringe: r.ringe };
    plan = r.ringe.length ? { teil: nr, punkt: r.punkt, normale: r.normale, ort: 'rand' } : null;
    meldung([]); ringeZeigen(); knoepfe();
  } catch (e) { meldung([e.message], true); }
}
function bandAnpassen() {
  if (!band) return;
  const k = THREE.MathUtils.degToRad(einst.kipp);
  const n0 = band.n0, ax = new THREE.Vector3().crossVectors(n0, band.sn).normalize();
  const n = ax.lengthSq() > 0.5 ? n0.clone().multiplyScalar(Math.cos(k)).add(new THREE.Vector3().crossVectors(ax, n0).multiplyScalar(Math.sin(k))).normalize() : n0.clone();
  const p = band.punkt.clone().add(n0.clone().multiplyScalar(einst.schub));
  ringHolen({ teil: band.teil, punkt: arr(p), normale: arr(n), ort: 'rand' }, 'rand');
}

// Ebene
function ebeneNormale() {
  const n = new THREE.Vector3(); n.setComponent(einst.ebAchse, 1);
  const a = new THREE.Vector3(), b = new THREE.Vector3();
  a.setComponent((einst.ebAchse + 1) % 3, 1); b.setComponent((einst.ebAchse + 2) % 3, 1);
  n.applyAxisAngle(a, THREE.MathUtils.degToRad(einst.ebKippA)).applyAxisAngle(b, THREE.MathUtils.degToRad(einst.ebKippB));
  return n.normalize();
}
function ebenePlanen() {
  const t = teilInfo(auswahl); if (!t || werkzeug !== 'ebene') return;
  const c = v3(t.min).add(v3(t.max)).multiplyScalar(0.5); c.setComponent(einst.ebAchse, einst.ebPos);
  const n = ebeneNormale();
  ebenenVorschau = [ebeneFlaeche(c.clone().add(versatz(t.nr)), n, Math.max(...t.groesse) * 1.15)];
  ringeZeigen();
  ringHolen({ teil: t.nr, punkt: arr(c), normale: arr(n), ort: 'alle' }, 'alle');
}

// Mehrfach
function mehrfachVorschau() {
  const t = teilInfo(auswahl); if (!t) return;
  ebenenVorschau = []; ringDaten = null;
  const off = versatz(t.nr);
  for (let ax = 0; ax < 3; ax++) {
    const k = einst.mf[ax];
    for (let i = 1; i < k; i++) {
      const c = v3(t.min).add(v3(t.max)).multiplyScalar(0.5);
      c.setComponent(ax, t.min[ax] + (t.max[ax] - t.min[ax]) * i / k);
      const n = new THREE.Vector3(); n.setComponent(ax, 1);
      ebenenVorschau.push(ebeneFlaeche(c.add(off), n, Math.max(...t.groesse) * 1.1));
    }
  }
  ringeZeigen(); knoepfe();
}

// ───────── Zeiger ─────────
const rc = new THREE.Raycaster();
function treffer(e) {
  const r = cv.getBoundingClientRect();
  rc.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), cam);
  const h = rc.intersectObjects([...teilObj.values()], false)[0];
  if (!h) return null;
  const nr = h.object.userData.nr;
  return { nr, punkt: h.point.clone().sub(h.object.position), sn: h.face.normal.clone(), index: h.faceIndex };
}

let unten = null, malt = false, linie = null, pinselWelt = 5;
cv.addEventListener('pointerdown', e => {
  if (!sid || e.button !== 0) return;
  unten = { x: e.clientX, y: e.clientY };
  if (e.pointerType === 'touch') return;
  if (werkzeug === 'malen') {
    const h = treffer(e); if (!h) return;
    if (h.nr !== auswahl) waehlen(h.nr);
    malt = true; cv.setPointerCapture(e.pointerId); pinsel(e);
  } else if (werkzeug === 'linie') {
    const r = cv.getBoundingClientRect();
    linie = { a: [e.clientX - r.left, e.clientY - r.top], b: [e.clientX - r.left, e.clientY - r.top], zieht: true };
    cv.setPointerCapture(e.pointerId); linieMalen();
  }
});
cv.addEventListener('pointerleave', () => { if (werkzeug === 'malen' && !malt) $('#overlay').innerHTML = ''; });
cv.addEventListener('pointermove', e => {
  if (werkzeug === 'malen' && e.pointerType !== 'touch') {
    const r = cv.getBoundingClientRect();
    $('#overlay').innerHTML = `<circle cx="${e.clientX - r.left}" cy="${e.clientY - r.top}" r="${einst.pinselPx}" fill="rgba(0,174,66,.12)" stroke="#00AE42" stroke-width="1.5"/>`;
  }
  if (malt) pinsel(e);
  else if (linie?.zieht) { const r = cv.getBoundingClientRect(); linie.b = [e.clientX - r.left, e.clientY - r.top]; linieMalen(); }
});
cv.addEventListener('pointerup', e => {
  if (malt) { malt = false; nahtAusFarbe(); return; }
  if (linie?.zieht) { linie.zieht = false; linieFertig(); return; }
  if (!unten || e.button !== 0) return;
  const weit = Math.hypot(e.clientX - unten.x, e.clientY - unten.y); unten = null;
  if (weit > 5) return;
  const h = treffer(e);
  if (!h) return;
  if (werkzeug === 'band') { if (h.nr !== auswahl) waehlen(h.nr); bandSetzen(h.nr, h.punkt, h.sn); }
  else if (['ebene', 'mehrfach', 'auto', 'farben'].includes(werkzeug)) { waehlen(h.nr); werkzeugOptionen(); }
});

// Bemalen
// Pinsel wirkt durch das ganze Glied: alles im Zylinder um den Blickstrahl zwischen Ein- und Austritt
function pinsel(e) {
  const radieren = e.shiftKey;
  const m = teilObj.get(auswahl); if (!m) return;
  const r = cv.getBoundingClientRect();
  rc.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), cam);
  const hits = rc.intersectObject(m, false);
  if (!hits.length) return;
  const o = rc.ray.origin.clone().sub(m.position), d = rc.ray.direction;
  const t0 = hits[0].distance, t1 = hits[1] ? hits[1].distance : t0;
  const proPx = 2 * t0 * Math.tan(THREE.MathUtils.degToRad(cam.fov / 2)) / r.height;
  pinselWelt = einst.pinselPx * proPx;
  const g = m.geometry, pos = g.getAttribute('position');
  const n = pos.count / 3;
  if (!m.userData.gemalt) {
    m.userData.gemalt = new Uint8Array(n);
    const c = new Float32Array(pos.count * 3);
    const grau = new THREE.Color(GRAU);
    for (let i = 0; i < pos.count; i++) c.set([grau.r, grau.g, grau.b], i * 3);
    g.setAttribute('color', new THREE.BufferAttribute(c, 3));
    if (!m.userData.mitten) {
      const mi = new Float32Array(n * 3), a = pos.array;
      for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) mi[i * 3 + k] = (a[i * 9 + k] + a[i * 9 + 3 + k] + a[i * 9 + 6 + k]) / 3;
      m.userData.mitten = mi;
    }
    faerben();
  }
  const r2 = pinselWelt * pinselWelt, mi = m.userData.mitten, gem = m.userData.gemalt, col = g.getAttribute('color');
  const gr = new THREE.Color(GRUEN), grau = new THREE.Color(GRAU);
  let geaendert = false;
  const rr = pinselWelt;
  for (let i = 0; i < n; i++) {
    const vx = mi[i * 3] - o.x, vy = mi[i * 3 + 1] - o.y, vz = mi[i * 3 + 2] - o.z;
    const t = vx * d.x + vy * d.y + vz * d.z;
    if (t < t0 - rr || t > t1 + rr) continue;
    if (vx * vx + vy * vy + vz * vz - t * t > r2) continue;
    const soll = radieren ? 0 : 1;
    if (gem[i] === soll) continue;
    gem[i] = soll; geaendert = true;
    const f = soll ? gr : grau;
    for (let k = 0; k < 3; k++) col.setXYZ(i * 3 + k, f.r, f.g, f.b);
  }
  if (geaendert) col.needsUpdate = true;
}
// Ebene, die bemalte und unbemalte Dreiecke am besten trennt (wenig Fehler, viel Abstand)
function nahtAusFarbe() {
  const m = teilObj.get(auswahl); if (!m?.userData.gemalt) return;
  const gem = m.userData.gemalt, mi = m.userData.mitten, n = gem.length;
  const box = new THREE.Box3(); let anz = 0;
  for (let i = 0; i < n; i++) if (gem[i]) { box.expandByPoint(new THREE.Vector3(mi[i * 3], mi[i * 3 + 1], mi[i * 3 + 2])); anz++; }
  if (anz < 3) { plan = null; ringDaten = null; ringeZeigen(); knoepfe(); return; }
  const rand = box.getSize(new THREE.Vector3()).length() * 0.35 + pinselWelt * 2;
  box.expandByScalar(rand);
  const P = [], U = [];
  for (let i = 0; i < n; i++) {
    const x = mi[i * 3], y = mi[i * 3 + 1], z = mi[i * 3 + 2];
    if (gem[i]) P.push(x, y, z); else if (box.containsPoint({ x, y, z })) U.push(x, y, z);
  }
  if (!U.length) { meldung(['Es ist alles bemalt – bitte nur das Stück anmalen, das ab soll.']); return; }
  const dünn = (a, max) => { const k = Math.ceil(a.length / 3 / max); if (k <= 1) return a; const o = []; for (let i = 0; i < a.length; i += 3 * k) o.push(a[i], a[i + 1], a[i + 2]); return o; };
  const p = dünn(P, 2500), u = dünn(U, 3500);
  const np = p.length / 3, nu = u.length / 3;
  const werte = new Float64Array(np + nu), art = new Uint8Array(np + nu), idx = new Uint32Array(np + nu);
  const bewerten = (nx, ny, nz) => {
    for (let i = 0; i < np; i++) { werte[i] = p[i * 3] * nx + p[i * 3 + 1] * ny + p[i * 3 + 2] * nz; art[i] = 1; }
    for (let i = 0; i < nu; i++) { werte[np + i] = u[i * 3] * nx + u[i * 3 + 1] * ny + u[i * 3 + 2] * nz; art[np + i] = 0; }
    for (let i = 0; i < idx.length; i++) idx[i] = i;
    idx.sort((a, b) => werte[a] - werte[b]);
    // bemalt soll oberhalb der Schwelle liegen: Fehler = bemalt darunter + unbemalt darüber
    let fehler = np, best = { f: Infinity, t: 0, rand: -Infinity };
    let ub = 0; // unbemalt bisher (unterhalb)
    let pb = 0; // bemalt bisher (unterhalb)
    for (let k = 0; k <= idx.length; k++) {
      const f = pb + (nu - ub);
      if (k > 0 && k < idx.length) {
        const t = (werte[idx[k - 1]] + werte[idx[k]]) / 2, abst = werte[idx[k]] - werte[idx[k - 1]];
        if (f < best.f || f === best.f && abst > best.rand) best = { f, t, rand: abst };
      }
      if (k < idx.length) { if (art[idx[k]]) pb++; else ub++; }
    }
    return best;
  };
  const richtungen = [];
  const N = 600, gold = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) { const y = 1 - (i + 0.5) / N * 2, r = Math.sqrt(1 - y * y), th = gold * i; richtungen.push([Math.cos(th) * r, y, Math.sin(th) * r]); }
  let sieger = null;
  const pruefe = d => { const b = bewerten(d[0], d[1], d[2]); const sc = b.f * 1000 - b.rand; if (!sieger || sc < sieger.sc) sieger = { sc, d, t: b.t, f: b.f }; };
  richtungen.forEach(pruefe);
  // verfeinern
  for (let runde = 0, w = 0.08; runde < 3; runde++, w *= 0.4) {
    const [x, y, z] = sieger.d;
    for (let a = -2; a <= 2; a++) for (let c = -2; c <= 2; c++) {
      const v = new THREE.Vector3(x, y, z), q = new THREE.Vector3(...(Math.abs(x) < 0.9 ? [1, 0, 0] : [0, 1, 0])).cross(v).normalize(), r2 = new THREE.Vector3().crossVectors(v, q);
      v.addScaledVector(q, a * w).addScaledVector(r2, c * w).normalize();
      pruefe([v.x, v.y, v.z]);
    }
  }
  const nn = new THREE.Vector3(...sieger.d);
  // Punkt: Mitte der bemalten Fläche nahe der Ebene, auf die Ebene geschoben
  const nah = new THREE.Vector3(); let k = 0;
  for (let i = 0; i < np; i++) {
    const v = p[i * 3] * nn.x + p[i * 3 + 1] * nn.y + p[i * 3 + 2] * nn.z;
    if (v - sieger.t < pinselWelt * 2 + 2) { nah.x += p[i * 3]; nah.y += p[i * 3 + 1]; nah.z += p[i * 3 + 2]; k++; }
  }
  if (!k) for (let i = 0; i < np; i++) { nah.x += p[i * 3]; nah.y += p[i * 3 + 1]; nah.z += p[i * 3 + 2]; k++; }
  nah.multiplyScalar(1 / k);
  nah.addScaledVector(nn, sieger.t - nah.dot(nn));
  if (sieger.f > (np + nu) * 0.1) meldung(['Die bemalte Fläche lässt sich nicht sauber mit einer Ebene trennen – das Stück lieber ganz umrunden.']);
  ringHolen({ teil: auswahl, punkt: arr(nah), normale: arr(nn), ort: 'innen' }, 'innen');
}

// Linie
function linieMalen() {
  if (!linie) { $('#overlay').innerHTML = ''; return; }
  const [a, b] = [linie.a, linie.b];
  $('#overlay').innerHTML = `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#00AE42" stroke-width="2.5" stroke-dasharray="7 4"/>` +
    `<circle cx="${a[0]}" cy="${a[1]}" r="4" fill="#00AE42"/><circle cx="${b[0]}" cy="${b[1]}" r="4" fill="#00AE42"/>`;
}
function linieFertig() {
  const [a, b] = [linie.a, linie.b];
  if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 12) { linie = null; linieMalen(); return; }
  const w = cv.clientWidth, h = cv.clientHeight;
  const strahl = p => { rc.setFromCamera(new THREE.Vector2(p[0] / w * 2 - 1, -p[1] / h * 2 + 1), cam); return rc.ray.clone(); };
  const r1 = strahl(a), r2 = strahl(b);
  // Teil: das unter der Linie (Mitte, sonst Enden), sonst die Auswahl
  let nr = auswahl;
  for (const t of [0.5, 0.3, 0.7, 0.15, 0.85]) {
    const p = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    rc.setFromCamera(new THREE.Vector2(p[0] / w * 2 - 1, -p[1] / h * 2 + 1), cam);
    const hit = rc.intersectObjects([...teilObj.values()], false)[0];
    if (hit) { nr = hit.object.userData.nr; break; }
  }
  if (nr !== auswahl) { auswahl = nr; faerben(); liste(); }
  const dist = cam.position.distanceTo(ctl.target);
  const p1 = r1.at(dist, new THREE.Vector3()), p2 = r2.at(dist, new THREE.Vector3());
  const blickR = r1.direction.clone().add(r2.direction).normalize();
  const n = new THREE.Vector3().subVectors(p2, p1).cross(blickR).normalize();
  const p = p1.sub(versatz(nr));
  const off = versatz(nr);
  ringHolen({ teil: nr, punkt: arr(p), normale: arr(n), ort: 'linie', linie: [arr(p1), arr(p2.clone().sub(off)), arr(blickR)] }, 'linie');
}

// ───────── Schneiden ─────────
async function schneiden() {
  if (!sid) return;
  const t0 = performance.now();
  try {
    let r;
    if (werkzeug === 'mehrfach') r = await api(`${sid}/mehrfach`, { teil: auswahl, anzahl: einst.mf, verbindung: verbindung() }, 'Schneide …');
    else if (werkzeug === 'auto') r = await api(`${sid}/auto`, { teil: auswahl, drucker: drucker(), rand: +einst.rand || 0, verbindung: verbindung() }, 'Teile fürs Druckbett …');
    else if (plan) r = await api(`${sid}/schneiden`, { ...plan, verbindung: verbindung() }, 'Schneide …');
    else return;
    letzteDauer = performance.now() - t0;
    nahtWeg();
    const alt = new Set(stand.teile.map(t => t.nr));
    const neu = r.teile.filter(t => !alt.has(t.nr)).sort((a, b) => a.volumen - b.volumen);
    if (neu.length) auswahl = neu[0].nr; // kleineres neues Stück auswählen (z. B. den abgetrennten Arm)
    await zeigen(r);
    meldung(r.hinweise || []);
  } catch (e) { meldung([e.message], true); }
}
$('#schneidenOben').onclick = schneiden;
$('#schneidenUnten').onclick = schneiden;
addEventListener('keydown', e => {
  if (e.target.matches('input, select')) return;
  if (e.key === 'Enter') schneiden();
  if (e.key === 'Escape') nahtWeg();
  if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.preventDefault(); $('#zurueck').click(); }
});
$('#zurueck').onclick = async () => { try { nahtWeg(); await zeigen(await api(`${sid}/zurueck`, {}, 'Rückgängig …')); } catch (e) { meldung([e.message], true); } };

// ───────── Export ─────────
async function laden_runter(art) {
  try {
    const r = await api(`${sid}/export`, { art, drucker: drucker(), rand: +einst.rand || 5 }, art === 'projekt' ? 'Speichere Projekt …' : 'Erzeuge Dateien …');
    const blob = await r.blob();
    const name = (r.headers.get('content-disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'formwerk.3mf';
    speichern(blob, name);
  } catch (e) { meldung([e.message], true); }
}
function speichern(blob, name) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
$$('[data-ex]').forEach(b => b.onclick = () => laden_runter(b.dataset.ex));
$('#speichern').onclick = () => laden_runter('projekt');

// ───────── Beschriftung im Bild ─────────
function beschriftungen(kamera, breite, hoehe, nurTeile) {
  const out = [];
  if (!stand) return out;
  for (const t of stand.teile) {
    if (nurTeile && !nurTeile.has(t.nr)) continue;
    const m = teilObj.get(t.nr); if (!m || !m.visible) continue;
    const c = v3(t.min).add(v3(t.max)).multiplyScalar(0.5).add(m.position);
    out.push({ p: c, text: String(t.nr), fuge: false });
  }
  for (const f of stand.fugen) {
    if (nurTeile && !(nurTeile.has(f.a) && nurTeile.has(f.b))) continue;
    const off = versatz(f.a).add(versatz(f.b)).multiplyScalar(0.5);
    out.push({ p: v3(f.punkt).add(off), text: String(f.nr), fuge: true });
  }
  return out.map(o => {
    const s = o.p.clone().project(kamera);
    return { ...o, x: (s.x + 1) / 2 * breite, y: (1 - s.y) / 2 * hoehe, sichtbar: s.z < 1 && Math.abs(s.x) < 1.05 && Math.abs(s.y) < 1.05 };
  });
}
function labelsZeichnen() {
  const box = $('#labels');
  if (!einst.labels || !stand) { box.innerHTML = ''; return; }
  const l = beschriftungen(cam, view.clientWidth, view.clientHeight).filter(x => x.sichtbar);
  box.innerHTML = l.map(x => `<div class="lbl ${x.fuge ? 'f' : ''}" style="left:${x.x}px;top:${x.y}px">${x.text}</div>`).join('');
}

function schleife() {
  requestAnimationFrame(schleife);
  renderer.render(scene, cam);
  labelsZeichnen();
}
maus(); werkzeugOptionen(); schleife();

// ───────── Montage-PDF ─────────
function jpegBytes(canvas) {
  const b64 = canvas.toDataURL('image/jpeg', 0.88).split(',')[1];
  const s = atob(b64), u = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  return u;
}

/** Bild rendern: sichtbare Teile, Farben, Versatz je Teil, Blickrichtung */
function foto({ sichtbar, farben, versaetze, richtung, nurTeile }) {
  const W = 1400, H = 950;
  const alt = { w: view.clientWidth, h: view.clientHeight, pos: cam.position.clone(), ziel: ctl.target.clone(), near: cam.near, far: cam.far };
  const merk = new Map();
  for (const [nr, m] of teilObj) {
    merk.set(nr, { vis: m.visible, pos: m.position.clone(), col: m.material.color.getHex(), vc: m.material.vertexColors });
    m.visible = !sichtbar || sichtbar.has(nr);
    if (versaetze?.has(nr)) m.position.copy(versaetze.get(nr));
    m.material.vertexColors = false;
    m.material.color.set(farben?.get(nr) ?? GRAU);
  }
  const hv = hilfGrp.visible, bv = bettGrp.visible; hilfGrp.visible = false; bettGrp.visible = false;
  const box = new THREE.Box3();
  for (const m of teilObj.values()) if (m.visible) box.expandByObject(m);
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() * 0.5;
  renderer.setSize(W, H, false); cam.aspect = W / H;
  const dist = r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2)) * 0.95;
  cam.position.copy(c).add(richtung.clone().normalize().multiplyScalar(dist)); cam.lookAt(c);
  cam.near = Math.max(0.5, dist / 500); cam.far = dist * 20; cam.updateProjectionMatrix();
  const bg = scene.background; scene.background = new THREE.Color(0xffffff);
  renderer.render(scene, cam);
  const can = document.createElement('canvas'); can.width = W; can.height = H;
  const g = can.getContext('2d'); g.drawImage(cv, 0, 0, W, H);
  for (const l of beschriftungen(cam, W, H, nurTeile)) {
    if (!l.sichtbar) continue;
    const rad = l.fuge ? 17 : 21;
    g.fillStyle = l.fuge ? '#00AE42' : '#262E30';
    g.beginPath(); g.arc(l.x, l.y, rad + (l.text.length - 1) * 5, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#fff'; g.font = `bold ${l.fuge ? 19 : 22}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(l.text, l.x, l.y + 1);
  }
  const bytes = jpegBytes(can);
  // zurückstellen
  scene.background = bg; hilfGrp.visible = hv; bettGrp.visible = bv;
  for (const [nr, m] of teilObj) { const s = merk.get(nr); m.visible = s.vis; m.position.copy(s.pos); m.material.color.setHex(s.col); m.material.vertexColors = s.vc; m.material.needsUpdate = true; }
  renderer.setSize(alt.w, alt.h, false); cam.aspect = alt.w / alt.h;
  cam.position.copy(alt.pos); cam.near = alt.near; cam.far = alt.far; cam.updateProjectionMatrix(); ctl.target.copy(alt.ziel); ctl.update();
  return { jpg: bytes, w: W, h: H };
}

function pdfBauen(seiten) {
  const map = { 0x2013: 0x96, 0x2014: 0x97, 0x201e: 0x84, 0x201c: 0x93, 0x2022: 0x95, 0x2026: 0x85, 0x2192: 0x3e };
  const enc = s => { const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); a[i] = c < 256 ? c : (map[c] || 0x3f); } return a; };
  const pesc = s => s.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
  const objs = [];
  let n = 4; const kids = [];
  for (const s of seiten) {
    const pn = ++n, cn = ++n; kids.push(pn);
    const bilder = s.bilder.map(b => ({ ...b, nr: ++n }));
    let ops = '';
    for (const r of s.rechtecke || []) ops += `${r.farbe} rg ${r.x} ${r.y} ${r.w} ${r.h} re f\n`;
    bilder.forEach((b, i) => { ops += `q ${b.bw} 0 0 ${b.bh} ${b.x} ${b.y} cm /Im${i} Do Q\n`; });
    for (const t of s.texte) ops += `BT ${t.farbe || '0.15 0.18 0.19'} rg /${t.fett ? 'F2' : 'F1'} ${t.s} Tf ${t.x} ${t.y} Td (${pesc(t.t)}) Tj ET\n`;
    const cb = enc(ops);
    objs[cn - 1] = [`<< /Length ${cb.length} >>\nstream\n`, cb, '\nendstream'];
    for (const b of bilder) objs[b.nr - 1] = [`<< /Type /XObject /Subtype /Image /Width ${b.w} /Height ${b.h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${b.jpg.length} >>\nstream\n`, b.jpg, '\nendstream'];
    objs[pn - 1] = [`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << ${bilder.map((b, i) => `/Im${i} ${b.nr} 0 R`).join(' ')} >> >> /Contents ${cn} 0 R >>`];
  }
  objs[0] = ['<< /Type /Catalog /Pages 2 0 R >>'];
  objs[1] = [`<< /Type /Pages /Kids [${kids.map(k => k + ' 0 R').join(' ')}] /Count ${kids.length} >>`];
  objs[2] = ['<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'];
  objs[3] = ['<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'];
  const teile = []; let len = 0; const offs = [];
  const push = x => { const b = typeof x === 'string' ? enc(x) : x; teile.push(b); len += b.length; };
  push('%PDF-1.4\n%âãÏÓ\n');
  objs.forEach((o, i) => { offs.push(len); push(`${i + 1} 0 obj\n`); o.forEach(push); push('\nendobj\n'); });
  const xs = len;
  push(`xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join(''));
  push(`trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xs}\n%%EOF`);
  return new Blob(teile, { type: 'application/pdf' });
}

function anleitungsText(f) {
  const a = teilInfo(f.a), b = teilInfo(f.b);
  const z = [];
  z.push(`Teil ${f.a} „${a?.name ?? ''}“ mit Teil ${f.b} „${b?.name ?? ''}“ verbinden.`);
  if (!f.anzahl) z.push('Ohne Verbinder – Flächen verkleben.');
  else if (f.verbinder.startsWith('lose')) z.push(`${f.anzahl}× ${f.verbinder}: Zapfen in Teil ${f.a} einkleben, dann Teil ${f.b} aufstecken.`);
  else if (f.verbinder.startsWith('Magnet')) z.push(`${f.anzahl * 2}× ${f.verbinder} einkleben (${f.anzahl} je Seite) – auf die Polung achten!`);
  else z.push(`${f.anzahl}× ${f.verbinder}: Zapfen sitzt an Teil ${f.a}, Tasche in Teil ${f.b}.`);
  z.push(`Auf beiden Schnittflächen ist die Nummer ${f.nr} eingraviert.`);
  return z;
}

$('#pdf').onclick = async () => {
  if (!stand) return;
  busy(true, 'Erzeuge Anleitung …');
  await new Promise(r => setTimeout(r, 30));
  try {
    const seiten = [];
    const kopf = (titel, sub) => ({
      rechtecke: [{ farbe: '0 0.682 0.259', x: 0, y: 800, w: 595, h: 42 }],
      texte: [{ x: 36, y: 815, s: 17, t: titel, fett: true, farbe: '1 1 1' }, ...(sub ? [{ x: 400, y: 816, s: 10, t: sub, farbe: '1 1 1' }] : [])],
    });
    // Übersicht in Explosionsansicht
    const box = gesamtBox(), mitte = box.getCenter(new THREE.Vector3());
    const ex = new Map();
    for (const t of stand.teile) ex.set(t.nr, v3(t.min).add(v3(t.max)).multiplyScalar(0.5).sub(mitte).multiplyScalar(0.45));
    const ueb = foto({ versaetze: ex, richtung: new THREE.Vector3(0.6, -1, 0.65) });
    const s1 = kopf(`Montageanleitung – ${stand.name}`, `Formwerk · ${new Date().toLocaleDateString('de-DE')}`);
    s1.bilder = [{ ...ueb, x: 36, y: 400, bw: 523, bh: 523 * ueb.h / ueb.w }];
    s1.texte.push({ x: 36, y: 375, s: 12, t: `${stand.teile.length} Teile · ${stand.fugen.length} Fugen · ${stand.fugen.reduce((s, f) => s + f.anzahl, 0)} Verbinder${stand.lose ? ` · ${stand.lose} lose Zapfen drucken` : ''}`, fett: true });
    let y = 350;
    s1.texte.push({ x: 36, y, s: 10, t: 'Nr.', fett: true }, { x: 70, y, s: 10, t: 'Teil', fett: true }, { x: 380, y, s: 10, t: 'Größe (mm)', fett: true });
    for (const t of stand.teile) {
      y -= 15; if (y < 40) break;
      s1.texte.push({ x: 36, y, s: 10, t: String(t.nr) }, { x: 70, y, s: 10, t: t.name.slice(0, 55) }, { x: 380, y, s: 10, t: t.groesse.map(Math.round).join(' × ') });
    }
    seiten.push(s1);
    // Schritte: zwei je Seite
    const fugen = [...stand.fugen].sort((a, b) => a.nr - b.nr);
    for (let i = 0; i < fugen.length; i += 2) {
      const s = kopf('Zusammenbau', `Schritt ${i + 1}${fugen[i + 1] ? '–' + (i + 2) : ''} von ${fugen.length}`);
      s.bilder = [];
      fugen.slice(i, i + 2).forEach((f, k) => {
        const n = v3(f.normale), gr = v3(teilInfo(f.a)?.groesse || [50, 50, 50]).length() * 0.12 + 8;
        const ver = new Map([[f.a, n.clone().multiplyScalar(-gr)], [f.b, n.clone().multiplyScalar(gr)]]);
        let seitlich = new THREE.Vector3().crossVectors(n, new THREE.Vector3(0, 0, 1));
        if (seitlich.lengthSq() < 0.05) seitlich = new THREE.Vector3(0, -1, 0);
        const richtung = seitlich.normalize().add(new THREE.Vector3(0, 0, 0.45)).add(n.clone().multiplyScalar(0.25));
        const bild = foto({ sichtbar: new Set([f.a, f.b]), farben: new Map([[f.a, 0xf08a3c], [f.b, 0x5b8def]]), versaetze: ver, richtung, nurTeile: new Set([f.a, f.b]) });
        const top = k === 0 ? 780 : 420;
        const bh = 250, bw = bh * bild.w / bild.h;
        s.bilder.push({ ...bild, x: 36, y: top - bh, bw: Math.min(bw, 330), bh: Math.min(bw, 330) * bild.h / bild.w });
        const tx = 380;
        s.texte.push({ x: tx, y: top - 20, s: 15, t: `Schritt ${i + k + 1}`, fett: true }, { x: tx, y: top - 38, s: 11, t: `Fuge ${f.nr}`, fett: true, farbe: '0 0.55 0.2' });
        let yy = top - 60;
        for (const zl of anleitungsText(f)) {
          for (const teil of umbrechen(zl, 34)) { s.texte.push({ x: tx, y: yy, s: 10, t: teil }); yy -= 14; }
          yy -= 4;
        }
        s.texte.push({ x: tx, y: yy - 6, s: 9, t: 'Orange = Zapfenseite · Blau = Taschenseite', farbe: '0.42 0.42 0.42' });
      });
      seiten.push(s);
    }
    speichern(pdfBauen(seiten), `${(stand.name || 'formwerk').replace(/[^\w\-äöüÄÖÜß]+/g, '_')}_Montage.pdf`);
  } catch (e) { meldung(['PDF: ' + e.message], true); } finally { busy(false); }
};
function umbrechen(t, n) {
  const w = t.split(' '), out = []; let z = '';
  for (const x of w) { if ((z + ' ' + x).trim().length > n) { if (z) out.push(z); z = x; } else z = (z + ' ' + x).trim(); }
  if (z) out.push(z);
  return out;
}
