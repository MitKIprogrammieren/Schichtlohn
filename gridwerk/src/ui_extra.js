// ---------- Logos (eigene Bilder als Icon) ----------
const logoCache = new Map();
function logoStempel() { return S.logos.map(l => l.id + ':' + l.schwelle + ':' + (l.umkehren ? 1 : 0)).join('|'); }
async function bildLaden(src) {
  return new Promise((ok, fehler) => { const im = new Image(); im.onload = () => ok(im); im.onerror = fehler; im.src = src; });
}
// Bild → Schwarzweiß-Raster → Umrisse (Pixelkanten, Vordergrund links) → vereinfachte Polygone, y nach oben
async function logoUmrisse(logo) {
  const key = logo.id + ':' + logo.schwelle + ':' + (logo.umkehren ? 1 : 0);
  if (logoCache.has(key)) return logoCache.get(key);
  const im = await bildLaden(logo.bild);
  const max = 220, sk = Math.min(1, max / Math.max(im.width, im.height));
  const w = Math.max(2, Math.round(im.width * sk)), h = Math.max(2, Math.round(im.height * sk));
  const cv = document.createElement('canvas'); cv.width = w + 2; cv.height = h + 2;
  const cx = cv.getContext('2d'); cx.drawImage(im, 1, 1, w, h);
  const d = cx.getImageData(0, 0, w + 2, h + 2).data, W = w + 2, H = h + 2;
  const voll = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) {
    const a = d[i * 4 + 3], l = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];
    let v = a > 128 && l < logo.schwelle;
    if (logo.umkehren) v = a > 128 && !v;
    voll[i] = v ? 1 : 0;
  }
  const polys = umrisseAusRaster(voll, W, H).map(p => vereinfachen(p, 0.7)).filter(p => p.length > 2).map(p => p.map(([x, y]) => [x, H - y]));
  logoCache.set(key, polys);
  return polys;
}
function umrisseAusRaster(v, W, H) {
  const an = (x, y) => x >= 0 && y >= 0 && x < W && y < H && v[y * W + x];
  const kanten = new Map(); // "x,y" -> [nach...]
  const add = (x1, y1, x2, y2) => { const k = x1 + ',' + y1; if (!kanten.has(k)) kanten.set(k, []); kanten.get(k).push([x2, y2]); };
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (an(x, y)) {
    // Bildkoordinaten (y nach unten); Kanten so gerichtet, dass nach dem Spiegeln der Vordergrund links liegt
    if (!an(x, y - 1)) add(x + 1, y, x, y);
    if (!an(x - 1, y)) add(x, y, x, y + 1);
    if (!an(x, y + 1)) add(x, y + 1, x + 1, y + 1);
    if (!an(x + 1, y)) add(x + 1, y + 1, x + 1, y);
  }
  const polys = [];
  for (const [start, liste] of kanten) {
    while (liste.length) {
      const [sx, sy] = start.split(',').map(Number);
      const poly = [[sx, sy]];
      let [px, py] = [sx, sy], [nx, ny] = liste.pop();
      let schutz = 0;
      while (!(nx === sx && ny === sy) && schutz++ < 1e6) {
        poly.push([nx, ny]);
        const weiter = kanten.get(nx + ',' + ny);
        if (!weiter || !weiter.length) break;
        let wahl = 0;
        if (weiter.length > 1) { // an Sattelpunkten rechts abbiegen, damit sich nichts kreuzt
          const dx = nx - px, dy = ny - py;
          wahl = weiter.findIndex(([qx, qy]) => (qx - nx) === -dy && (qy - ny) === dx);
          if (wahl < 0) wahl = 0;
        }
        const n2 = weiter.splice(wahl, 1)[0];
        px = nx; py = ny; nx = n2[0]; ny = n2[1];
      }
      if (poly.length > 2) polys.push(poly);
    }
  }
  return polys;
}
function vereinfachen(p, tol) {
  if (p.length < 5) return p;
  const dp = (a, s, e, out) => {
    let m = 0, mi = -1; const [x1, y1] = a[s], [x2, y2] = a[e], L = Math.hypot(x2 - x1, y2 - y1) || 1;
    for (let i = s + 1; i < e; i++) { const dd = Math.abs((x2 - x1) * (y1 - a[i][1]) - (x1 - a[i][0]) * (y2 - y1)) / L; if (dd > m) { m = dd; mi = i; } }
    if (m > tol && mi > 0) { dp(a, s, mi, out); dp(a, mi, e, out); } else out.push(a[s]);
  };
  const out = []; const h = Math.floor(p.length / 2);
  dp(p, 0, h, out); dp(p, h, p.length - 1, out); out.push(p[p.length - 1]);
  return out;
}
async function logoHochladen(datei) {
  const url = await new Promise(ok => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(datei); });
  const im = await bildLaden(url);
  const max = 400, sk = Math.min(1, max / Math.max(im.width || max, im.height || max));
  const cv = document.createElement('canvas'); cv.width = Math.max(1, Math.round((im.width || max) * sk)); cv.height = Math.max(1, Math.round((im.height || max) * sk));
  cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height);
  const logo = { id: neueId(), name: datei.name.replace(/\.[^.]+$/, '').slice(0, 30), bild: cv.toDataURL('image/png'), schwelle: 140, umkehren: false };
  S.logos.push(logo);
  return logo;
}

// Etikett-Daten für die Geometrie: Typ, Logo-Umrisse, QR-Inhalt
async function ausEin(e) {
  const n = normal(e);
  if (e.logo) { const l = S.logos.find(x => x.id === e.logo); if (l) n.logoPolys = await logoUmrisse(l); }
  n.qr = qrInhalt(e);
  return n;
}
function qrInhalt(e) {
  if (!e.qr || !String(e.qr).trim()) return '';
  if (e.qrKurz) { if (!e.qrCode) e.qrCode = Math.random().toString(36).slice(2, 5); return (location.origin + '/q/' + e.qrCode).toUpperCase(); }
  return String(e.qr).trim();
}

// ---------- Schublade (Grundplatte + Planer) ----------
const NEU_PLATTE = () => ({ id: neueId(), name: 'Schublade', ...PLATTE_STANDARD, belegung: [] });
const PLATTEN_STIL = { leicht: 'leicht (ohne Boden)', magnete: 'mit Magneten', schrauben: 'Magnete + Senkschrauben' };
function bettBreite() { const dr = DRUCKER[S.einst.drucker] || DRUCKER.p; return dr.b; }
function platteTitel(p) { const r = platteRaster(p); return `${p.name || 'Schublade'} · ${r.nx} × ${r.ny}`; }
function platteBeschr(p) {
  const n = (p.belegung || []).length;
  return [p.modus === 'schublade' ? `${p.schubB} × ${p.schubT} mm` : 'Rastermaß', PLATTEN_STIL[p.stil] || '', n ? `${n} Behälter` : ''].filter(Boolean).join(' · ');
}
function platteSvgMini(p) {
  const r = platteRaster(p), gw = r.nx * 42 + r.padL + r.padR, gd = r.ny * 42 + r.padV + r.padH;
  const s = 56 / Math.max(gw, gd), ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  let inner = `<rect x="${32 - gw * s / 2}" y="${32 - gd * s / 2}" width="${gw * s}" height="${gd * s}" rx="2" fill="#9aa198"/>`;
  for (let i = 0; i < r.nx; i++) for (let j = 0; j < r.ny; j++) inner += `<rect x="${32 - gw * s / 2 + (r.padL + i * 42 + 2) * s}" y="${32 + gd * s / 2 - (r.padV + (j + 1) * 42 - 2) * s}" width="${38 * s}" height="${38 * s}" rx="${3 * s}" fill="#d9ddd6"/>`;
  for (const b of p.belegung || []) {
    const bin = S.bins.find(x => x.id === b.binId); if (!bin) continue;
    const w = (b.gedreht ? bin.Bin_Depth : bin.Bin_Width) * 42, d = (b.gedreht ? bin.Bin_Width : bin.Bin_Depth) * 42;
    inner += `<rect x="${32 - gw * s / 2 + (r.padL + b.x * 42 + 1) * s}" y="${32 + gd * s / 2 - (r.padV + b.y * 42 + d - 1) * s}" width="${(w - 2) * s}" height="${(d - 2) * s}" rx="${2 * s}" fill="${S.binEinst.Bin_Color}"/>`;
  }
  svg.setAttribute('viewBox', '0 0 64 64'); svg.setAttribute('class', 'binsvg'); svg.innerHTML = inner;
  return svg;
}
function zeichnePlattenListe() {
  const box = $('#eintraege'); box.innerHTML = '';
  for (const p of S.platten) {
    box.append(el('div', { class: 'eintrag' + (p.id === S.platteSel ? ' aktiv' : ''), onclick: () => { S.platteSel = p.id; planerAuswahl = null; zeichnePlattenListe(); zeichnePlattenEditor(); zeigePlatte3D(); } },
      platteSvgMini(p), el('div', { class: 'info' }, el('b', {}, platteTitel(p)), platteBeschr(p))));
  }
  if (!S.platten.length) box.append(el('p', { class: 'hinweis', style: 'padding:14px' }, 'Noch keine Schublade – „+ Schublade“ antippen.'));
  $('#zaehler').textContent = `${S.platten.length} Schublade${S.platten.length === 1 ? '' : 'n'}`;
}
const binMasse = (bin, gedreht) => ({ w: +(gedreht ? bin.Bin_Depth : bin.Bin_Width), d: +(gedreht ? bin.Bin_Width : bin.Bin_Depth) });
function belegungPruefen(p) {
  const r = platteRaster(p), probleme = new Set();
  const rechtecke = (p.belegung || []).map((b, i) => { const bin = S.bins.find(x => x.id === b.binId); if (!bin) return null; const m = binMasse(bin, b.gedreht); return { i, x0: b.x, y0: b.y, x1: b.x + m.w, y1: b.y + m.d }; }).filter(Boolean);
  for (const a of rechtecke) {
    if (a.x0 < -1e-6 || a.y0 < -1e-6 || a.x1 > r.nx + 1e-6 || a.y1 > r.ny + 1e-6) probleme.add(a.i);
    for (const b of rechtecke) if (a !== b && a.x0 < b.x1 - 1e-6 && b.x0 < a.x1 - 1e-6 && a.y0 < b.y1 - 1e-6 && b.y0 < a.y1 - 1e-6) probleme.add(a.i);
  }
  return probleme;
}
function freierPlatz(p, bin) {
  const r = platteRaster(p);
  for (const gedreht of [false, true]) {
    const m = binMasse(bin, gedreht);
    for (let y = 0; y + m.d <= r.ny + 1e-6; y += 0.5) for (let x = 0; x + m.w <= r.nx + 1e-6; x += 0.5) {
      const probe = { ...p, belegung: [...(p.belegung || []), { binId: bin.id, x, y, gedreht }] };
      if (!belegungPruefen(probe).has(probe.belegung.length - 1)) return { x, y, gedreht };
    }
  }
  return null;
}
let planerAuswahl = null;
function planerSvg(p) {
  const r = platteRaster(p), gw = r.nx * 42 + r.padL + r.padR, gd = r.ny * 42 + r.padV + r.padH;
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `-4 -4 ${gw + 8} ${gd + 8}`); svg.setAttribute('class', 'planer');
  const Y = yy => gd - yy; // Planer: y nach oben (vorn = unten)
  let inner = `<rect x="0" y="0" width="${gw}" height="${gd}" rx="4" fill="var(--planerRand)"/>`;
  for (let i = 0; i < r.nx; i++) for (let j = 0; j < r.ny; j++) inner += `<rect x="${r.padL + i * 42 + 1.5}" y="${Y(r.padV + (j + 1) * 42) + 1.5}" width="39" height="39" rx="4" fill="var(--planerZelle)"/>`;
  inner += `<text x="${gw / 2}" y="${gd + 3.2}" font-size="5" text-anchor="middle" fill="var(--grau)">vorn</text>`;
  svg.innerHTML = inner;
  const probleme = belegungPruefen(p);
  (p.belegung || []).forEach((b, i) => {
    const bin = S.bins.find(x => x.id === b.binId); if (!bin) return;
    const m = binMasse(bin, b.gedreht);
    const g = document.createElementNS(ns, 'g'); g.setAttribute('class', 'planerBin' + (planerAuswahl === i ? ' aktiv' : ''));
    const x = r.padL + b.x * 42, y = Y(r.padV + (b.y + m.d) * 42);
    g.setAttribute('transform', `translate(${x} ${y})`);
    g.innerHTML = `<rect x="1" y="1" width="${m.w * 42 - 2}" height="${m.d * 42 - 2}" rx="4" fill="${probleme.has(i) ? '#e5484d' : S.binEinst.Bin_Color}" stroke="${planerAuswahl === i ? 'var(--text)' : 'none'}" stroke-width="1.5"/>`
      + `<text x="${m.w * 21}" y="${m.d * 21 + 2}" font-size="${Math.min(9, m.w * 6)}" text-anchor="middle" fill="#fff" font-weight="700">${bin.Bin_Width}×${bin.Bin_Depth}</text>`;
    g.addEventListener('pointerdown', ev => {
      ev.preventDefault(); planerAuswahl = i;
      const pt = svg.createSVGPoint(), umrechnen = e2 => { pt.x = e2.clientX; pt.y = e2.clientY; return pt.matrixTransform(svg.getScreenCTM().inverse()); };
      const start = umrechnen(ev), bx = b.x, by = b.y; let bewegt = false;
      const move = e2 => {
        const q = umrechnen(e2), dx = (q.x - start.x) / 42, dy = -(q.y - start.y) / 42;
        if (Math.abs(dx) + Math.abs(dy) > 0.1) bewegt = true;
        b.x = Math.round((bx + dx) * 2) / 2; b.y = Math.round((by + dy) * 2) / 2;
        g.setAttribute('transform', `translate(${r.padL + b.x * 42} ${Y(r.padV + (b.y + m.d) * 42)})`);
      };
      const hoch = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', hoch); aenderung(true); };
      window.addEventListener('pointermove', move); window.addEventListener('pointerup', hoch);
      zeichnePlanerLeiste(p);
      svg.querySelectorAll('.planerBin rect').forEach((rc, k) => rc.setAttribute('stroke', 'none'));
      g.querySelector('rect').setAttribute('stroke', 'var(--text)');
    });
    svg.append(g);
  });
  return svg;
}
function zeichnePlanerLeiste(p) {
  const l = $('#planerLeiste'); if (!l) return; l.innerHTML = '';
  const b = (p.belegung || [])[planerAuswahl];
  if (b) {
    const bin = S.bins.find(x => x.id === b.binId);
    l.append(el('span', { class: 'hinweis' }, `Gewählt: ${bin ? binTitel(bin) : '?'}`),
      el('button', { class: 'klein', type: 'button', onclick: () => { b.gedreht = !b.gedreht; aenderung(true); } }, '⟳ Drehen'),
      el('button', { class: 'klein gefahr', type: 'button', onclick: () => { p.belegung.splice(planerAuswahl, 1); planerAuswahl = null; aenderung(true); } }, 'Entfernen'));
  } else l.append(el('span', { class: 'hinweis' }, 'Behälter antippen zum Auswählen, ziehen zum Verschieben.'));
}
function platteRaster(p) { return platteGeo.raster({ ...PLATTE_STANDARD, ...p }); }
function zeichnePlattenEditor() {
  const ed = $('#editor'); ed.innerHTML = '';
  const p = S.platten.find(x => x.id === S.platteSel);
  if (!p) { ed.append(el('p', { class: 'hinweis' }, 'Keine Schublade gewählt.')); return; }
  const neu = (k, v, voll) => { p[k] = v; aenderung(voll); };
  ed.append(el('h3', {}, 'Schublade'));
  ed.append(feld('Name', el('input', { value: p.name || '' }), ev => neu('name', ev.target.value)));
  ed.append(feld('Maße angeben als', sel(['schublade', 'raster'], p.modus, v => v === 'schublade' ? 'Innenmaß der Schublade (mm)' : 'Anzahl Raster'), ev => neu('modus', ev.target.value, true)));
  if (p.modus === 'schublade') {
    ed.append(zahl('Breite innen (mm)', p.schubB, { step: 1, min: 42, max: 2000 }, v => neu('schubB', v, true)));
    ed.append(zahl('Tiefe innen (mm)', p.schubT, { step: 1, min: 42, max: 2000 }, v => neu('schubT', v, true)));
    ed.append(zahl('Spiel je Seite (mm)', p.spiel, { step: 0.1, min: 0, max: 5 }, v => neu('spiel', v, true)));
    ed.append(feld('Rest links/rechts', sel(['mitte', 'links', 'rechts'], p.ausX, v => ({ mitte: 'gleich verteilen', links: 'Raster links, Rest rechts', rechts: 'Raster rechts, Rest links' })[v]), ev => neu('ausX', ev.target.value, true)));
    ed.append(feld('Rest vorn/hinten', sel(['mitte', 'vorn', 'hinten'], p.ausY, v => ({ mitte: 'gleich verteilen', vorn: 'Raster vorn, Rest hinten', hinten: 'Raster hinten, Rest vorn' })[v]), ev => neu('ausY', ev.target.value, true)));
  } else {
    ed.append(zahl('Raster breit', p.gx, { step: 1, min: 1, max: 40 }, v => neu('gx', Math.round(v), true)));
    ed.append(zahl('Raster tief', p.gy, { step: 1, min: 1, max: 40 }, v => neu('gy', Math.round(v), true)));
  }
  ed.append(feld('Grundplatte', sel(Object.keys(PLATTEN_STIL), p.stil, v => PLATTEN_STIL[v]), ev => neu('stil', ev.target.value, true)));
  ed.append(haken('für das Druckbett in Stücke teilen', p.teilen, v => neu('teilen', v, true)));
  const r = platteRaster(p), pl = platteGeo.platte({ ...PLATTE_STANDARD, ...p, belegung: [] }, bettBreite());
  const rest = [r.padL, r.padR, r.padV, r.padH].some(v => v > 0.01) ? ` · Randausgleich links ${r.padL.toFixed(1)}, rechts ${r.padR.toFixed(1)}, vorn ${r.padV.toFixed(1)}, hinten ${r.padH.toFixed(1)} mm` : '';
  ed.append(el('div', { class: 'hinweis', style: 'grid-column:1/-1' }, `${r.nx} × ${r.ny} Raster · Platte ${pl.gesW.toFixed(1)} × ${pl.gesD.toFixed(1)} mm${rest} · ${pl.teile.length} Stück${pl.teile.length > 1 ? 'e' : ''} zum Drucken`));
  pl.teile.forEach(t => t.koerper.delete());
  // Planer
  ed.append(el('h3', {}, 'Behälter einplanen'));
  const palette = el('div', { class: 'aktionen' });
  if (!S.bins.length) palette.append(el('span', { class: 'hinweis' }, 'Lege zuerst im Bereich „Behälter“ Behälter an.'));
  for (const bin of S.bins) palette.append(el('button', { class: 'klein', type: 'button', onclick: () => {
    const platz = freierPlatz(p, bin);
    p.belegung = p.belegung || [];
    p.belegung.push(platz ? { binId: bin.id, ...platz } : { binId: bin.id, x: 0, y: 0, gedreht: false });
    planerAuswahl = p.belegung.length - 1; aenderung(true);
  } }, '+ ' + binTitel(bin)));
  ed.append(palette);
  ed.append(el('div', { class: 'planerBox' }, planerSvg(p)));
  ed.append(el('div', { class: 'aktionen', id: 'planerLeiste' }));
  setTimeout(() => zeichnePlanerLeiste(p));
  const probleme = belegungPruefen(p);
  if (probleme.size) ed.append(el('div', { class: 'warnung' }, `${probleme.size} Behälter überlappen oder ragen aus der Schublade (rot markiert).`));
  ed.append(el('div', { class: 'aktionen' },
    el('button', { class: 'klein', onclick: () => { const k = { ...p, id: neueId(), name: (p.name || 'Schublade') + ' Kopie', belegung: (p.belegung || []).map(b => ({ ...b })) }; S.platten.push(k); S.platteSel = k.id; aenderung(true); } }, 'Duplizieren'),
    el('button', { class: 'klein gefahr', onclick: () => { const i = S.platten.indexOf(p); S.platten.splice(i, 1); S.platteSel = (S.platten[i] || S.platten[i - 1] || {}).id; aenderung(true); } }, 'Löschen')));
}
const binGeoCache = new Map();
function binGeometrie(b) {
  const key = JSON.stringify(binOpts({ ...b, id: 0, anzahl: 0, etiketten: 0 }));
  if (binGeoCache.has(key)) return binGeoCache.get(key);
  const r = binGeo(binOpts(b));
  const g = { koerper: geo3(r.koerper), band: r.band ? geo3(r.band) : null, meta: { topZ: r.topZ, zsmall: r.zsmall, reihen: r.reihen, gy: r.gy, oben: r.oben } };
  r.koerper.delete(); r.band && r.band.delete();
  if (binGeoCache.size > 40) binGeoCache.clear();
  binGeoCache.set(key, g);
  return g;
}
async function etikettFuerReihe(b, j) {
  const id = (b.etiketten || [])[j];
  return S.liste.find(x => x.id === id) || (S.binEinst.etikettZeigen ? S.liste.find(x => x.id === S.sel) : null);
}
async function etikettenEinsetzen(gruppeZiel, b, meta, versatz = [0, 0, 0], drehung = 0) {
  if (!b.Label_Holder || meta.zsmall || ![1, 2, 3].includes(+b.Bin_Width)) return;
  const mat = c => new THREE.MeshStandardMaterial({ color: c, roughness: .6 });
  const lagen = etikettLagen(meta);
  for (let j = 0; j < lagen.length; j++) {
    const e = await etikettFuerReihe(b, j); if (!e) continue;
    const lg = labelGeo({ ...(await opts()), Y_units: +b.Bin_Width }, await ausEin(e));
    const grp = new THREE.Group();
    const m1 = new THREE.Mesh(geo3(lg.basis), mat(S.einst.farbeEtikett)); grp.add(m1);
    if (lg.inhalt) grp.add(new THREE.Mesh(geo3(lg.inhalt), mat(S.einst.farbeInhalt)));
    grp.position.set(lagen[j].x, lagen[j].y, lagen[j].z);
    const huelle = new THREE.Group(); huelle.add(grp); huelle.rotation.z = drehung; huelle.position.set(...versatz);
    gruppeZiel.add(huelle);
    lg.basis.delete(); lg.inhalt && lg.inhalt.delete();
  }
}
async function zeigePlatte3D() {
  const p = S.platten.find(x => x.id === S.platteSel);
  gruppe.clear();
  if (!p) return;
  const t0 = performance.now();
  const pl = platteGeo.platte({ ...PLATTE_STANDARD, ...p }, bettBreite());
  const mat = c => new THREE.MeshStandardMaterial({ color: c, roughness: .7 });
  for (const t of pl.teile) {
    const m = new THREE.Mesh(geo3(t.koerper), mat(S.platteEinst.farbe));
    const fuge = pl.teile.length > 1 ? 1.2 : 0;
    m.position.set(t.x + Math.sign(t.x) * fuge, t.y + Math.sign(t.y) * fuge, 0); gruppe.add(m);
    t.koerper.delete();
  }
  const unten = pl.H - platteGeo.H_TASCHE;
  let n = 0;
  for (const b of p.belegung || []) {
    const bin = S.bins.find(x => x.id === b.binId); if (!bin || n++ > 30) continue;
    const g = binGeometrie(bin), m = binMasse(bin, b.gedreht);
    const c = platteGeo.zellMitte(pl.raster, pl.gesW, pl.gesD, b.x, b.y, m.w, m.d);
    const grp = new THREE.Group();
    grp.add(new THREE.Mesh(g.koerper, mat(S.binEinst.Bin_Color)));
    if (g.band) grp.add(new THREE.Mesh(g.band, mat(S.binEinst.Top_Edge_Color)));
    grp.rotation.z = b.gedreht ? Math.PI / 2 : 0;
    grp.position.set(c.x, c.y, unten);
    gruppe.add(grp);
    await etikettenEinsetzen(gruppe, bin, { ...g.meta, gy: +bin.Bin_Depth }, [c.x, c.y, unten], b.gedreht ? Math.PI / 2 : 0);
  }
  const groesse3 = Math.max(pl.gesW, pl.gesD), sig = 'p' + groesse3.toFixed(0);
  if (letzteLaenge !== sig) {
    letzteLaenge = sig;
    const d = groesse3 * 1.5 + 60;
    cam.position.set(-d * 0.25, -d * 0.85, d * 0.85); ctr.target.set(0, 0, 0);
  }
  $('#status').textContent = `Platte ${pl.gesW.toFixed(1)} × ${pl.gesD.toFixed(1)} × ${pl.H.toFixed(2)} mm · ${pl.teile.length} Stück${pl.teile.length > 1 ? 'e' : ''} · ${Math.round(performance.now() - t0)} ms`;
}
// Etiketten-Objekte für den Export (Etikett + Inhalt)
async function etikettObjekt(e, yUnits) {
  const lg = labelGeo({ ...(await opts()), Y_units: yUnits }, await ausEin(e));
  const teile = [{ name: 'Etikett', extruder: 1, mesh: meshDaten(lg.basis) }];
  if (lg.inhalt) teile.push({ name: 'Inhalt', extruder: 2, mesh: meshDaten(lg.inhalt) });
  lg.basis.delete(); lg.inhalt && lg.inhalt.delete();
  return { name: 'Etikett ' + titel(e), teile, w: laengeAusY(yUnits) + 2, d: +S.einst.width || 11.5 };
}
async function binObjekt(b) {
  const r = binGeo(binOpts(b));
  const teile = [{ name: 'Behälter', extruder: 1, mesh: meshDaten(r.koerper) }];
  if (r.band) teile.push({ name: 'Rand', extruder: 2, mesh: meshDaten(r.band) });
  r.koerper.delete(); r.band && r.band.delete();
  return { name: 'Behälter ' + binTitel(b), teile, w: b.Bin_Width * 42 - 0.5, d: b.Bin_Depth * 42 - 0.5, reihen: r.reihen };
}
async function zugeordneteEtiketten(b) {
  const out = [];
  if (!b.Label_Holder || ![1, 2, 3].includes(+b.Bin_Width)) return out;
  const reihen = Math.max(1, +b.Compartments_Front_To_Back | 0);
  for (let j = 0; j < reihen; j++) { const e = S.liste.find(x => x.id === (b.etiketten || [])[j]); if (e) out.push(await etikettObjekt(e, +b.Bin_Width)); }
  return out;
}
async function packen(objs) {
  const dr = DRUCKER[S.einst.drucker] || DRUCKER.p;
  const a = anordnenBoxen(objs.map(o => [o.w, o.d]), dr.b);
  if (a.tiefe > dr.t + 10 && !confirm(`Die ${objs.length} Teile passen nicht auf eine Platte. Trotzdem exportieren? (In Bambu Studio dann „Anordnen“ nutzen – es verteilt auf mehrere Platten.)`)) return null;
  objs.forEach((o, i) => { o.x = a.pos[i].x; o.y = a.pos[i].y; });
  return { objs, mitte: dr.mitte };
}
async function erzeugeSchublade() {
  const p = S.platten.find(x => x.id === S.platteSel); if (!p) return null;
  const objs = [], E = S.platteEinst;
  $('#status').textContent = 'Erzeuge Grundplatte …'; await new Promise(r => setTimeout(r));
  const pl = platteGeo.platte({ ...PLATTE_STANDARD, ...p }, bettBreite());
  for (const t of pl.teile) { objs.push({ name: t.name, teile: [{ name: 'Grundplatte', extruder: 1, mesh: meshDaten(t.koerper) }], w: t.W, d: t.D }); t.koerper.delete(); }
  if (E.binsMit) for (const [i, b] of (p.belegung || []).entries()) {
    const bin = S.bins.find(x => x.id === b.binId); if (!bin) continue;
    $('#status').textContent = `Erzeuge Behälter ${i + 1} / ${p.belegung.length} …`; await new Promise(r => setTimeout(r));
    objs.push(await binObjekt(bin));
    if (E.etikettenMit) objs.push(...await zugeordneteEtiketten(bin));
  }
  $('#status').textContent = `${objs.length} Teile erzeugt`;
  return packen(objs);
}
function zeichnePlattenEinst(b) {
  const E = S.platteEinst, neuP = (k, v) => { E[k] = v; speichern(); };
  b.append(feld('Drucker (Druckbett & Plattenmitte)', sel(Object.keys(DRUCKER), S.einst.drucker, k => DRUCKER[k].name), ev => { S.einst.drucker = ev.target.value; aenderung(true); }));
  b.append(feld('Farbe Grundplatte (nur Vorschau)', el('input', { type: 'color', value: E.farbe }), ev => neuP('farbe', ev.target.value)));
  b.append(haken('eingeplante Behälter mitexportieren', E.binsMit, v => neuP('binsMit', v)));
  b.append(haken('zugeordnete Etiketten mitexportieren', E.etikettenMit, v => neuP('etikettenMit', v)));
}
