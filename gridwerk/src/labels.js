// Gridwerk – Gridfinity-Clip-Etiketten (Port von "Custom label generator" von Laurens Guijt, OpenSCAD)
// Erzeugt pro Etikett zwei Körper: Grundplatte und Inhalt (Icon + Text) – getrennt für zwei Farben.

export const KATALOG = {
  Bolt:      { de: 'Schraube' },
  Nut:       { de: 'Mutter', typen: ['Standard', 'Tall', 'Square', 'Lock', 'Castle', 'Cap', 'Eye', 'Disc', 'Wing', 'Slide-in T-nut', 'Hammer'] },
  Washer:    { de: 'Scheibe', typen: ['Standard', 'Spring', 'Spacer'] },
  Standoff:  { de: 'Abstandshalter', typen: ['Male-female', 'Female-female', 'Male-male'] },
  Furniture: { de: 'Möbelbeschlag', typen: ['Wooden dowel', 'Expansion sleeve', 'Cam lock nut', 'Cam lock bolt'] },
  Other:     { de: 'Sonstiges', typen: ['Wall anchor', 'Heat set insert', 'Threaded rod', 'Compression spring', 'Custom text', 'None'] },
  Electronics: { de: 'Elektronik', typen: ['Resistor', 'Electrolytic', 'Ceramic cap', 'LED', 'Diode', 'Fuse', 'Pin header', 'Ring terminal', 'Ferrule', 'Heat shrink', 'Cable tie', 'Battery', 'Coin cell'] },
  Tools:     { de: 'Werkzeug & Zubehör', typen: ['Bit', 'Drill', 'Magnet', 'Spring clip', 'O-ring', 'Rivet'] },
};
export const KOEPFE = ['Socket head', 'Pan head', 'Mushroom head', 'Flat head', 'Countersunk', 'Raised countersunk', 'Wafer head', 'Hex head', 'Hex flange', 'Grub screw'];
export const ANTRIEBE = ['Hex socket', 'Phillips', 'Pozidriv', 'Torx', 'Torx TR', 'AW', 'RW', 'Slotted'];
export const SPITZEN = ['Machine', 'Wood', 'Drill'];
export const GEWINDE = ['Full', 'Partial'];
export const DE = {
  'Socket head': 'Zylinderkopf', 'Pan head': 'Linsenkopf', 'Mushroom head': 'Flachrundkopf', 'Flat head': 'Flachkopf',
  'Countersunk': 'Senkkopf', 'Raised countersunk': 'Linsensenkkopf', 'Wafer head': 'Tellerkopf', 'Hex head': 'Sechskant', 'Hex flange': 'Sechskant mit Bund', 'Grub screw': 'Gewindestift',
  'Pozidriv': 'Pozidriv (PZ)', 'AW': 'AW (Würth)', 'RW': 'RW (Würth ASSY 4.0)', 'Drill': 'Bohrspitze', 'Full': 'Vollgewinde', 'Partial': 'Teilgewinde',
  'Hex socket': 'Innensechskant', 'Phillips': 'Kreuzschlitz', 'Torx': 'Torx', 'Torx TR': 'Torx TR', 'Slotted': 'Schlitz',
  'Machine': 'stumpf (metrisch)', 'Wood': 'Spitze (Holz)',
  'Standard': 'Standard', 'Tall': 'Hoch (DIN 6330)', 'Square': 'Vierkant', 'Lock': 'Sicherungsmutter', 'Castle': 'Kronenmutter',
  'Cap': 'Hutmutter', 'Eye': 'Ringmutter', 'Disc': 'Tellermutter', 'Wing': 'Flügelmutter', 'Slide-in T-nut': 'Nutenstein (Schiebe)', 'Hammer': 'Hammermutter',
  'Spring': 'Federring', 'Spacer': 'Distanzhülse',
  'Male-female': 'Außen-Innen', 'Female-female': 'Innen-Innen', 'Male-male': 'Außen-Außen',
  'Wooden dowel': 'Holzdübel', 'Expansion sleeve': 'Spreizhülse', 'Cam lock nut': 'Exzenter', 'Cam lock bolt': 'Verbindungsbolzen',
  'Wall anchor': 'Dübel', 'Heat set insert': 'Gewindeeinsatz', 'Threaded rod': 'Gewindestange', 'Compression spring': 'Druckfeder',
  'Custom text': 'Eigener Text', 'None': 'Ohne Icon',
  'Resistor': 'Widerstand', 'Electrolytic': 'Elko', 'Ceramic cap': 'Keramik-Kondensator', 'LED': 'LED', 'Diode': 'Diode', 'Fuse': 'Sicherung',
  'Pin header': 'Stiftleiste', 'Ring terminal': 'Ringkabelschuh', 'Ferrule': 'Aderendhülse', 'Heat shrink': 'Schrumpfschlauch', 'Cable tie': 'Kabelbinder',
  'Battery': 'Batterie', 'Coin cell': 'Knopfzelle', 'Bit': 'Bit', 'Drill': 'Bohrer', 'Magnet': 'Magnet', 'Spring clip': 'Sicherungsring', 'O-ring': 'O-Ring', 'Rivet': 'Niete',
};

// [Kategorie, Typ, Icon-Länge fest, Textart]
const PARTS = [
  ['Bolt', '*', 16, 'size'], ['Nut', '*', undefined, 'diameter'], ['Washer', '*', undefined, 'diameter'],
  ['Washer', 'Spacer', 5, 'size'], ['Standoff', '*', 10, 'size'], ['Furniture', '*', 16, 'size'],
  ['Other', 'Wall anchor', undefined, 'size'], ['Other', 'Heat set insert', undefined, 'size'],
  ['Other', 'Threaded rod', 1000, 'optional'], ['Other', 'Compression spring', 16, 'size'],
  ['Other', 'Custom text', undefined, 'custom'], ['Other', 'None', undefined, 'centered'],
  ['Electronics', '*', undefined, 'optional'], ['Tools', '*', undefined, 'optional'],
];
const partRow = (c, t) => PARTS.find(p => p[0] === c && p[1] === t) || PARTS.find(p => p[0] === c && p[1] === '*');

export const laengeAusY = y => ({ 1: 35.8, 2: 77.8, 3: 119.8 }[y] || 35.8);

export function makeLabels(wasm) {
  const { Manifold, CrossSection: C } = wasm;
  const LEER = () => new C([]);
  const U = (...a) => { const l = a.flat().filter(Boolean); return l.length ? C.union(l) : LEER(); };
  const ci = (d, fn = 64, x = 0, y = 0) => C.circle(d / 2, fn).translate([x, y]);
  const re = (x, y, w, h) => (w > 1e-6 && h > 1e-6) ? C.square([w, h]).translate([x, y]) : null;
  const po = pts => new C([pts], 'NonZero');
  const hull = (...a) => C.hull(a.flat().filter(Boolean));
  const ring = (a, b) => ci(a).subtract(ci(b));
  const hex = d => ci(d, 6);

  function labelGeo(o, ein, nur2D = false) {
    const Y = o.Y_units || ein.Y_units || 1, length = laengeAusY(Y);
    const width = +o.width || 11.5, height = +o.height || 0.8, ch = Math.min(Math.max(+(o.champfer ?? 0.2), 0), height / 2 - 0.05);
    const radius = Math.max(+(o.radius ?? 0.9), ch + 0.05);
    const maxLen = 20 * Y;

    const stem = (len, x, y, th = 2.5) => {
      if (len > maxLen) { const seg = (maxLen - 2) / 2; return U(re(x, y, seg, th), re(x + seg + 2, y, seg, th)); }
      return U(re(x, y, len, th));
    };
    const chamf = (x, h, s, dir) => U(po([[x, h], [x + dir * s, h], [x, h - s]]), po([[x, -h], [x + dir * s, -h], [x, -h + s]]));
    const phillips = () => U(re(-0.5, -2, 1, 4), re(-2, -0.5, 4, 1));
    const torx = () => {
      const d = 15 * Math.PI / 180, l = 2, p = [];
      const spitze = hull(ci(0.1, 12), ci(0.1, 12, Math.sin(d) * l, Math.cos(d) * l), ci(0.1, 12, -Math.sin(d) * l, Math.cos(d) * l)).translate([0, -l]);
      for (let i = 0; i < 6; i++) p.push(spitze.rotate(i * 60));
      return U(p);
    };
    const sechsrund = (ri, rl, dl) => U(ci(ri * 2), ...[0, 60, 120, 180, 240, 300].map(a => ci(rl * 2, 32, dl * Math.cos(a * Math.PI / 180), dl * Math.sin(a * Math.PI / 180))));
    const pozi = () => U(phillips(), ...[45, 135, 225, 315].map(a => re(-0.13, 0.55, 0.26, 1.0).rotate(a)));
    const stroke = (pts, th) => U(pts.slice(0, -1).map((p, i) => hull(ci(th, 12, p[0], p[1]), ci(th, 12, pts[i + 1][0], pts[i + 1][1]))));

    const icons = {
      'Nut/Standard': () => U(hex(5).subtract(ci(3)), re(4, -2.5, 2.8, 5)).translate([-2.5, 0]),
      'Nut/Tall': () => U(hex(5).subtract(ci(3)), U(re(4, -2.5, 5.6, 5)).subtract(U(re(4, -1.05, 5.6, 0.4), re(4, 0.65, 5.6, 0.4)))).translate([-3.9, 0]),
      'Nut/Square': () => U(re(-2.2, -2.2, 4.4, 4.4).subtract(ci(2.6)), re(4, -2.2, 2.8, 4.4)).translate([-2.5, 0]),
      'Nut/Lock': () => U(hex(5).subtract(ci(3)), re(4, -2.5, 2.8, 5), re(4, -2, 3.5, 4)).translate([-2.5, 0]),
      'Nut/Castle': () => U(
        hex(5).subtract(ci(2.4)).subtract(U([0, 60, 120].map(a => re(-2.1, -0.35, 4.2, 0.7).rotate(a)))),
        re(4, -2.5, 2.2, 5), re(6.2, -2.1, 2.2, 4.2).subtract(re(7.2, -0.4, 1.2, 0.8))).translate([-3.3, 0]),
      'Nut/Cap': () => U(hex(5).subtract(ring(3.8, 2.8)), re(4, -2.5, 2.2, 5), ci(4).intersect(re(0, -2, 2, 4)).translate([6.2, 0])).translate([-2.5, 0]),
      'Nut/Eye': () => U(ring(5, 3.8), re(-0.6, -2.5, 1.2, 5), hull(re(4, -2, 1.2, 4), re(5.2, -1, 1, 2)), ring(5, 2.8).translate([8.2, 0])).translate([-4, 0]),
      'Nut/Disc': () => U(ci(5.6).subtract(hex(4.8)), hex(4).subtract(ci(2.2)), re(4, -2.8, 0.8, 5.6), re(4.8, -2, 2.2, 4)).translate([-3, 0]),
      'Nut/Wing': () => {
        const fl = hull(re(0.9, -2.2, 0.5, 1.5), ci(1.2, 24, 2.8, 1.9));
        return U(U(ci(3.2), hull(ci(1, 24, -3, 0), ci(1, 24, 3, 0))).subtract(ci(1.8)),
          U(po([[-1.5, -2.5], [1.5, -2.5], [1.1, 0.3], [-1.1, 0.3]]), fl, fl.mirror([1, 0])).translate([8.5, 0])).translate([-4.25, 0]);
      },
      'Nut/Slide-in T-nut': () => U(re(-3.5, -2, 7, 4).subtract(ci(2.5)), re(5, -2.5, 6, 2), re(6.75, -0.5, 2.5, 1.5)).translate([-4, 0]),
      'Nut/Hammer': () => U(hull(ci(4, 64, 1.5, 0), ci(4, 64, -1.5, 0), re(3, -2, 0.5, 0.5), re(-3.5, 1.5, 0.5, 0.5)).subtract(ci(2.5)),
        po([[6.5, -2.5], [9.5, -2.5], [11, 0.5], [5, 0.5]]), re(6.75, 0.5, 2.5, 1.5)).translate([-4, 0]),
      'Washer/Standard': () => U(ring(5, 3), re(4, -2.5, 1, 5)).translate([-1.5, 0]),
      'Washer/Spring': () => U(ring(5, 3).subtract(re(0, 0, 5, 0.8)), re(4, -2.5, 1, 5)).translate([-1.5, 0]),
      'Washer/Spacer': L => { const dl = Math.min(L, maxLen); return U(ring(5, 3), stem(L, 4, -2.5, 5)).translate([-(dl + 1.5) / 2, 0]); },
      'Standoff': (L, typ) => {
        const dl = Math.min(L, maxLen), st = 2.5, ms = typ === 'Male-male', me = typ !== 'Female-female';
        const bx = 4 + (ms ? st : 0), rechts = bx + dl + (me ? st : 0);
        return U(hex(5).subtract(ci(ms ? 3.4 : 2.6)), ms && ci(2.4),
          stem(L, bx, -2, 4).subtract(U(re(bx, -1.05, dl, 0.4), re(bx, 0.65, dl, 0.4))),
          ms && re(bx - st, -1, st, 2), me && re(bx + dl, -1, st, 2)).translate([-(rechts - 2.5) / 2, 0]);
      },
      'Other/Compression spring': L => {
        const turns = 7, rx = 1.3, ry = 2.25, gap = 0.25, dl = Math.min(L, maxLen);
        const pitch = Math.max((dl - 2 * (gap + 2 * rx)) / turns, 0.9);
        const sx = -turns * pitch / 2, ex = sx + turns * pitch, lt = sx - gap - rx, rt = ex + gap + rx, cxo = rx * 0.5, cy = -ry * 0.87;
        const ell = cx => Array.from({ length: 37 }, (_, i) => { const t = 2 * Math.PI * i / 36; return [cx + rx * Math.cos(t), ry * Math.sin(t)]; });
        const helix = Array.from({ length: turns * 20 + 1 }, (_, i) => { const t = 2 * Math.PI * turns * i / (turns * 20); return [sx + pitch * t / (2 * Math.PI) + rx * Math.sin(t), -ry * Math.cos(t)]; });
        return U(stroke(ell(lt), 0.6), stroke([[lt + cxo, cy], [sx, -ry]], 0.6), stroke(helix, 0.6), stroke([[ex, -ry], [rt - cxo, cy]], 0.6), stroke(ell(rt), 0.6));
      },
      'Other/Heat set insert': () => U(U(ci(5, 5), ci(5, 5).rotate(36)).subtract(ci(3, 80)),
        re(4, -2, 1, 4), re(5, -2.5, 2, 5), re(7, -2, 1, 4), re(8, -2.5, 2, 5)).translate([-4, 0]),
      'Other/Threaded rod': L => {
        const rl = L > 0 ? L : 1000, dl = Math.min(rl, maxLen), pitch = 1.2, k = [];
        for (let x = 4 + pitch / 2; x <= 4 + dl - pitch / 2 + 1e-9; x += pitch) for (const y of [-1.5, 1]) k.push(re(x - 0.25, y, 0.5, 0.5));
        return U(ci(5).subtract(ring(4.2, 3.4)), stem(rl, 4, -1.5, 3).subtract(U(k))).translate([-(dl + 1.5) / 2, 0]);
      },
      'Other/Wall anchor': () => {
        const z = [[0, 2], [-1.5, 1.5], [-1.5, -1.5], [0, -2]];
        return U(po([[0, 2], [-2, 1], [-2, -1], [0, -2]]).translate([-2, 0]), ...[-0.5, 1, 2.5, 4].map(x => po(z).translate([x, 0])),
          re(4, -1.5, 7, 3), re(11, -2, 1, 4)).subtract(re(-4, -0.25, 10, 0.5)).translate([-4, 0]);
      },
      'Furniture/Wooden dowel': L => {
        const dl = Math.min(L, maxLen), fl = Math.min(L, maxLen), be = 4 + fl, flute = fl > 3 ? fl - 2 : 0;
        return U(ci(5).subtract(ring(4.4, 3.6)),
          stem(L, 4, -2, 4).subtract(U(chamf(4, 2, 0.7, 1), chamf(be, 2, 0.7, -1), flute && re(5, 0.6, flute, 0.4), flute && re(5, -1, flute, 0.4)))).translate([-dl / 2 - 2, 0]);
      },
      'Furniture/Expansion sleeve': L => {
        const dl = Math.min(L, maxLen), fl = Math.min(L, maxLen), be = 4 + fl, ss = 4 + fl * 0.4;
        return U(ci(5).subtract(ci(2.6)), U(re(3, -2.5, 1.2, 5), stem(L, 4, -2, 4)).subtract(U(re(ss, -0.5, be - ss, 1), chamf(be, 2, 0.7, -1)))).translate([-dl / 2 - 2, 0]);
      },
      'Furniture/Cam lock nut': () => U(ci(5).subtract(phillips()), U(re(0, 0, 4, 5)).subtract(U(ci(2.4, 64, 2, 2.5), re(1.4, 0, 1.2, 2.5))).translate([4, -2.5])).translate([-3, 0]),
      'Furniture/Cam lock bolt': L => {
        const dl = Math.min(L, maxLen);
        return U(ci(5).subtract(phillips()), ci(5).subtract(re(0, -2.5, 4, 5)).translate([5.5, 0]), re(5.5, -0.9, 1.2, 1.8), re(6.7, -2.2, 1, 4.4), stem(L, 7.7, -1.25)).translate([-dl / 2 - 2, 0]);
      },
// ---- Elektronik ----
      'Electronics/Resistor': () => U(re(-10, -0.3, 20, 0.6), C.square([10, 3.4], true).offset(0, 'Round').subtract(U(re(-3.1, -2, 0.7, 4), re(-1.3, -2, 0.7, 4), re(0.5, -2, 0.7, 4), re(2.6, -2, 0.7, 4)))
        .intersect(hull(ci(3.4, 32, -3.4, 0), ci(3.4, 32, 3.4, 0)))),
      'Electronics/Electrolytic': () => U(hull(ci(1.4, 24, -6.3, 2.3), ci(1.4, 24, -6.3, -2.3), ci(1.4, 24, 2.3, 2.3), ci(1.4, 24, 2.3, -2.3)).subtract(U(re(0.6, -3, 0.7, 6), re(-5.6, -0.25, 2, 0.5))), re(3, 1.2, 7, 0.6), re(3, -1.8, 5.5, 0.6)),
      'Electronics/Ceramic cap': () => U(ci(5.2, 48, -5, 0).subtract(ci(2.2, 32, -5, 0).subtract(re(-6.2, -0.3, 2.4, 0.6))), re(-2.6, 0.9, 11, 0.6), re(-2.6, -1.5, 11, 0.6)),
      'Electronics/LED': () => U(hull(ci(3.6, 40, -4, 0), re(-4, -1.8, 4.5, 3.6)), re(0.5, -2.4, 0.8, 4.8), re(1.3, 0.6, 8.5, 0.6), re(1.3, -1.2, 7, 0.6)).translate([-0.5, 0]),
      'Electronics/Diode': () => U(re(-10, -0.3, 20, 0.6), re(-4, -1.6, 8, 3.2).subtract(re(1.9, -2, 0.9, 4))),
      'Electronics/Fuse': () => U(re(-7, -1.7, 2.6, 3.4), re(4.4, -1.7, 2.6, 3.4), re(-4.4, -1.4, 8.8, 2.8).subtract(re(-4.4, -0.9, 8.8, 1.8)), po([[-4.4, -0.2], [-1.5, -0.2], [0, 0.6], [1.5, -0.2], [4.4, -0.2], [4.4, 0.2], [1.6, 0.2], [0, 1], [-1.6, 0.2], [-4.4, 0.2]])),
      'Electronics/Pin header': () => { const p = [re(-9, -1.2, 18, 2.4)]; for (let i = 0; i < 7; i++) { const x = -7.62 + i * 2.54; p.push(re(x - 0.32, 1.2, 0.64, 1.3), re(x - 0.32, -2.5, 0.64, 1.3)); } return U(p); },
      'Electronics/Ring terminal': () => U(ci(5, 48, -7, 0).subtract(ci(2.2, 32, -7, 0)), po([[-5, -1.1], [-2.6, -1.4], [-2.6, 1.4], [-5, 1.1]]), re(-2.6, -1.4, 6, 2.8).subtract(re(0.2, -1.6, 0.5, 3.2)), re(3.4, -1, 5.6, 2)),
      'Electronics/Ferrule': () => U(po([[-3.5, -2.3], [-1.8, -1.3], [-1.8, 1.3], [-3.5, 2.3]]), re(-1.8, -1.1, 6.5, 2.2), re(-9.5, -1.2, 6, 2.4).subtract(U(re(-9.5, -0.5, 6, 0.25), re(-9.5, 0.3, 6, 0.25))), re(4.7, -0.7, 4, 1.4).subtract(U(re(4.7, -0.15, 4, 0.3)))),
      'Electronics/Heat shrink': () => U(re(-8, -1.6, 15, 3.2).subtract(re(-6, -0.3, 11, 0.6)), ci(3.2, 40, -8, 0).subtract(ci(2, 32, -8, 0)).subtract(re(-8, -2, 3, 4)).add(ci(3.2, 40, -8, 0).subtract(ci(2, 32, -8, 0)).intersect(re(-10, -2, 2, 4)))),
      'Electronics/Cable tie': () => { const z = []; for (let x = -8.5; x < 5.5; x += 1.1) z.push(re(x, 0.25, 0.5, 0.4)); return U(re(-10, -0.65, 16, 1.3).subtract(U(z)), re(6, -2, 3.6, 4).subtract(re(7, -0.9, 1.6, 1.8))); },
      'Electronics/Battery': () => U(hull(ci(1.2, 24, -8, 1.9), ci(1.2, 24, -8, -1.9), ci(1.2, 24, 6.4, 1.9), ci(1.2, 24, 6.4, -1.9)).subtract(U(re(1.6, -0.3, 3, 0.6), re(2.8, -1.5, 0.6, 3), re(-6.2, -0.3, 3, 0.6))), re(7, -0.9, 1.3, 1.8)),
      'Electronics/Coin cell': () => U(ci(5.4, 64, -6, 0).subtract(ci(4.2, 64, -6, 0)), ci(3.2, 48, -6, 0).subtract(U(re(-7, -0.25, 2, 0.5), re(-6.25, -1, 0.5, 2))), re(-1.6, -2.7, 9.5, 1.1), re(-1.6, 1.6, 9.5, 1.1), re(-1.6, -1.6, 9.5, 3.2).subtract(re(-1.6, -1.2, 9.5, 2.4))),
      // ---- Werkzeug & Zubehör ----
      'Tools/Bit': () => U(hull(re(-10, -1.7, 9, 3.4), re(-10.3, -1.4, 0.3, 2.8)).subtract(re(-6.5, -2, 1, 4).subtract(re(-6.5, -1.2, 1, 2.4))), po([[-1, -1.2], [5, -0.7], [8, 0], [5, 0.7], [-1, 1.2]])),
      'Tools/Drill': () => { const n = []; for (let x = -1; x < 7.5; x += 1.6) n.push(re(x, -3, 0.55, 6).rotate(-25).translate([0, 0])); const fl = re(-2, -1.3, 9.6, 2.6).subtract(U(n.map((r, i) => re(-2 + i * 1.6, -3, 0.5, 6).rotate(25).translate([1.2, 0])))); return U(re(-10, -1.3, 8, 2.6), fl, po([[7.6, -1.3], [9.6, 0], [7.6, 1.3]])); },
      'Tools/Magnet': () => U(ci(5, 48, -2, 0).subtract(ci(2.4, 40, -2, 0)).subtract(re(-2, -3, 6, 6)), re(-2, 1.2, 6, 1.3), re(-2, -2.5, 6, 1.3), re(4, 1.2, 1.8, 1.3), re(4, -2.5, 1.8, 1.3)).translate([-1.5, 0]),
      'Tools/Spring clip': () => U(ci(5, 64).subtract(ci(3.4, 64)).subtract(po([[0, 0], [3, -1.2], [3, 1.2]])), ci(1.3, 24, 1.85, 0.95).subtract(ci(0.5, 16, 1.85, 0.95)), ci(1.3, 24, 1.85, -0.95).subtract(ci(0.5, 16, 1.85, -0.95)), re(4.5, -0.5, 6, 1)).translate([-3.5, 0]),
      'Tools/O-ring': () => U(ci(5, 64, -4, 0).subtract(ci(3.2, 64, -4, 0)), re(1, -0.9, 9, 1.8).subtract(re(1.5, -0.3, 8, 0.6))),
      'Tools/Rivet': () => U(hull(ci(1.6, 24, -6.5, 1.6), ci(1.6, 24, -6.5, -1.6), re(-5.7, -2.4, 0.8, 4.8)), re(-4.9, -1.1, 7.5, 2.2), re(-4.9, -0.35, 13, 0.7), ci(1.2, 24, 8.1, 0)),
      'Bolt': (L, head, drive, tip, gewinde) => {
        const dl = Math.min(L, maxLen), t = [];
        if (head === 'Hex head') t.push(hex(5));
        else {
          const rec = drive === 'Phillips' ? phillips() : drive === 'Pozidriv' ? pozi() : (drive === 'Torx' || drive === 'Torx TR') ? torx()
            : drive === 'AW' ? sechsrund(1.25, 0.5, 1.4) : drive === 'RW' ? sechsrund(1.35, 0.42, 1.5) : drive === 'Slotted' ? U(re(-0.5, -2, 1, 4)) : ci(3.2, 6);
          t.push(ci(5).subtract(rec));
          if (drive === 'Torx TR') t.push(ci(1.2));
          if (drive === 'AW') t.push(ci(0.8));
        }
        if (head === 'Grub screw') t.push(stem(L, 4, -2, 4).subtract(U(re(4, -0.8, 1.5, 1.6))));
        else {
          const sx = { 'Socket head': 7, 'Countersunk': 5, 'Raised countersunk': 5, 'Hex flange': 6.6 }[head] || 6;
          const kopf = {
            'Socket head': () => re(3, -2.5, 4, 5),
            'Hex head': () => re(3, -2.5, 3, 5),
            'Hex flange': () => U(re(3, -2, 3, 4), re(6, -2.7, 0.6, 5.4)),
            'Wafer head': () => hull(re(4.4, -3, 0.5, 6), re(4.9, -1.5, 1.1, 3)),
            'Raised countersunk': () => U(ci(6, 3).translate([5, 0]), ci(5.2, 48).scale([0.3, 1]).intersect(re(-1, -3, 1, 6)).translate([3.5, 0])),
            'Countersunk': () => ci(6, 3).translate([5, 0]),
            'Pan head': () => ci(5).subtract(re(0, -2.5, 4, 5)).translate([6, 0]),
            'Mushroom head': () => ci(5).scale([0.55, 1.1]).subtract(re(0, -3, 4, 6)).translate([6, 0]),
            'Flat head': () => hull(ci(0.6, 24, 0.3, 0.3), ci(0.6, 24, 0.3, 5.2), re(1, 0, 0.4, 5.5)).translate([4.6, -2.75]),
          }[head];
          if (kopf) t.push(kopf());
          let schaft, sl = L;
          if (tip === 'Wood') {
            sl = Math.max(L - 1.5, 0);
            schaft = U(stem(sl, sx, -1.25), po([[0, 1.25], [2, 0], [0, -1.25]]).translate([sx + Math.min(sl, maxLen), 0]));
          } else if (tip === 'Drill') {
            sl = Math.max(L - 3, 0);
            schaft = U(stem(sl, sx, -1.25), po([[0, 0.9], [1.4, 0.9], [3, 0], [1.4, -0.9], [0, -0.9]]).translate([sx + Math.min(sl, maxLen), 0]));
          } else schaft = stem(L, sx, -1.25);
          if (gewinde === 'Partial') {
            // glatter Schaft unter dem Kopf, Gewinde mit Kerben im vorderen Teil
            const dsl = Math.min(sl, maxLen), grenze = sx + dsl * 0.45, k = [];
            for (let x = grenze + 0.5; x <= sx + dsl - 0.4; x += 1.0) for (const y of [-1.25, 0.9]) k.push(re(x - 0.2, y, 0.4, 0.35));
            schaft = schaft.subtract(U(re(sx, 0.95, grenze - sx, 0.4), re(sx, -1.35, grenze - sx, 0.4), ...k));
          }
          t.push(schaft);
        }
        return U(t).translate([-dl / 2 - 2, 0]);
      },
    };

    const kat = ein.kat, typ = ein.typ;
    const row = partRow(kat, typ);
    const iconLen = (o.Icon_length === 'Real length' || !row || row[2] === undefined) ? (+ein.laenge || 0) : row[2];
    let icon = null;
    if (kat === 'Bolt') icon = icons.Bolt(iconLen, ein.kopf || 'Pan head', ein.antrieb || 'Hex socket', ein.spitze || 'Machine', ein.gewinde || 'Full');
    else if (kat === 'Standoff') icon = icons.Standoff(iconLen, typ);
    else if (icons[kat + '/' + typ]) icon = icons[kat + '/' + typ](iconLen);
    if (ein.logoPolys && ein.logoPolys.length) {
      // eigenes Logo statt Icon: in die Icon-Fläche (oder bei „groß“ in die ganze Fläche) einpassen
      let lg = new C(ein.logoPolys, 'Positive');
      const b = lg.bounds(), lw = b.max[0] - b.min[0], lh = b.max[1] - b.min[1];
      const bw = length - 6, bh = ein.logoGross ? width - 2 : 5.2;
      const sk = Math.min(bw / lw, bh / lh);
      icon = lg.translate([-(b.min[0] + b.max[0]) / 2, -(b.min[1] + b.max[1]) / 2]).scale([sk, sk]);
      if (ein.logoGross) icon = icon.translate([0, -2.5]);
    }
    if (ein.ohneIcon) icon = null;
    if (icon) icon = icon.translate([0, 2.5]);

    // Text
    const d = String(ein.durchmesser ?? ''), L = +ein.laenge || 0;
    const groesse = `${d}x${fmt(L)}`;
    const zeilen = [];
    const stil = row ? row[3] : 'none';
    const eigen = (ein.text || '').trim();
    if (stil === 'custom') {
      const l1 = (ein.zeile1 || '').trim(), l2 = (ein.zeile2 || '').trim();
      if (l1 && l2) zeilen.push([l1, 2.5], [l2, -3]); else if (l1 || l2) zeilen.push([l1 || l2, 0]);
    } else if (eigen) zeilen.push([eigen, icon ? -3 : 0]);
    else if (stil === 'size') zeilen.push([groesse, -3]);
    else if (stil === 'diameter') zeilen.push([d, -3]);
    else if (stil === 'optional') zeilen.push([L > 0 ? groesse : d, -3]);
    else if (stil === 'centered') zeilen.push([groesse, 0]);

    if (ein.logoGross && ein.logoPolys && ein.logoPolys.length) zeilen.length = 0;
    const textCS = ein.ohneText ? [] : zeilen.filter(z => z[0]).map(([s, y]) => textZeile(o.font, s, o.text_size || 4.2, length - 5, o.fontFallback, y === 0 ? width - 1.4 : 4.7).translate([0, y]));
    let inhalt = U(icon, ...textCS);
    // QR-Code rechts (hell mit dunklen Modulen = Löcher), übriger Inhalt wird links eingepasst
    const info = {};
    if (ein.qr && String(ein.qr).trim() && o.qrcode && !ein.ohneText) {
      try {
        const q = o.qrcode(0, 'L'); q.addData(String(ein.qr).trim()); q.make();
        const n = q.getModuleCount(), rand = 1;
        const mod = Math.min(+o.qrModul || 0.5, (width - 2 * ch - 0.1) / (n + 2 * rand));
        const sQ = (n + 2 * rand) * mod, cxq = length / 2 - 2.2 - sQ / 2;
        const dunkel = [];
        for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c))
          dunkel.push(C.square([mod + 0.002, mod + 0.002]).translate([cxq - sQ / 2 + (c + rand) * mod - 0.001, sQ / 2 - (r + rand + 1) * mod - 0.001]));
        const qrCS = C.square([sQ, sQ], true).translate([cxq, 0]).subtract(U(dunkel));
        Object.assign(info, { qrModul: mod, qrModule: n });
        if (!inhalt.isEmpty()) {
          const b = inhalt.bounds(), x0 = -length / 2 + 2.3, x1 = cxq - sQ / 2 - 0.8;
          const w = b.max[0] - b.min[0], sk = Math.min(1, (x1 - x0) / w);
          inhalt = inhalt.translate([-(b.min[0] + b.max[0]) / 2, 0]).scale([sk, sk]).translate([(x0 + x1) / 2, 0]);
        }
        inhalt = U(inhalt, qrCS);
      } catch (e) { info.qrFehler = 'Link zu lang für einen QR-Code'; }
    }
    if (nur2D) return { cs: inhalt, length, info };

    // Grundplatte
    const slab = (w, h, r, ins, z) => {
      const rr = r - ins;
      const cs = rr > 0.02 ? C.square([w - 2 * r, h - 2 * r], true).offset(rr, 'Round', 2, 32) : C.square([w - 2 * ins, h - 2 * ins], true);
      return Manifold.extrude(cs, 0.001).translate([0, 0, z]);
    };
    const form = (w, h, r) => Manifold.hull([slab(w, h, r, ch, 0), slab(w, h, r, 0, ch), slab(w, h, r, 0, height - ch - 0.001), slab(w, h, r, ch, height - 0.001)]);
    let basis = Manifold.union(form(length + 2, 5.7, 0.2), form(length, width, radius));
    const loch = Manifold.cylinder(height + 1, 0.75, 0.75, 32).translate([0, 0, -0.5]);
    basis = basis.subtract(Manifold.union(loch.translate([(length - 1) / 2, 0, 0]), loch.translate([-(length - 1) / 2, 0, 0])));

    let inh = null;
    if (!inhalt.isEmpty()) {
      if (o.text_type === 'Flush Skin') {
        // wie im Original: 0,01 mm dünne Haut oben auf dem Etikett
        inh = Manifold.extrude(inhalt, 0.01).translate([0, 0, height]);
      } else if (o.text_type === 'Flush Text') {
        const t = Math.min(o.flush_tiefe ?? 0.4, height - 0.2);
        const k = Manifold.extrude(inhalt, t).translate([0, 0, height - t]);
        basis = basis.subtract(k);
        inh = k;
      } else {
        inh = Manifold.extrude(inhalt, (o.raised_text_height ?? 0.2) + 0.001).translate([0, 0, height - 0.001]);
      }
    }
    return { basis, inhalt: inh, length, info };
  }

  // Text wie OpenSCAD text(valign=center, halign=center): Versalhöhe ≈ 1.048 × size
  function textZeile(font, s, size, maxW, fb, maxH) {
    s = String(s).replace(/\u2126/g, '\u03A9');
    const capH = (font.tables.os2 && font.tables.os2.sCapHeight) || font.charToGlyph('H').getBoundingBox().y2 || 0.7 * font.unitsPerEm;
    const em = size * 1.016 / (capH / font.unitsPerEm);
    const fehlt = fb && [...s].some(ch => ch.trim() && font.charToGlyph(ch).index === 0);
    let polys;
    if (!fehlt) polys = pfadZuPolys(font.getPath(s, 0, 0, em));
    else {
      // Zeichen einzeln setzen, fehlende (z. B. Ω) aus der Ersatzschrift
      polys = []; let x = 0;
      const capFb = (fb.tables.os2 && fb.tables.os2.sCapHeight) || 0.714 * fb.unitsPerEm;
      const emFb = size * 1.016 / (capFb / fb.unitsPerEm);
      for (const ch of s) {
        let f = font, g = font.charToGlyph(ch), gr = em;
        if (g.index === 0 && ch.trim()) { f = fb; g = fb.charToGlyph(ch); gr = emFb; }
        polys.push(...pfadZuPolys(g.getPath(x, 0, gr)));
        x += g.advanceWidth * gr / f.unitsPerEm;
      }
    }
    polys = polys.map(pl => pl.map(([x, y]) => [x, -y]));
    if (!polys.length) return LEER();
    let cs = new C(polys, 'NonZero');
    const b = cs.bounds();
    cs = cs.translate([-(b.min[0] + b.max[0]) / 2, -(b.min[1] + b.max[1]) / 2]);
    const w = b.max[0] - b.min[0], h = b.max[1] - b.min[1];
    const sk = Math.min(maxW && w > maxW ? maxW / w : 1, maxH && h > maxH ? maxH / h : 1);
    if (sk < 1) cs = cs.scale([sk, sk]);
    return cs;
  }

  return { labelGeo };
}

const fmt = v => (Math.round(v * 10) / 10).toString();

function pfadZuPolys(path) {
  const polys = []; let cur = [], px = 0, py = 0;
  const N = 6;
  for (const c of path.commands) {
    if (c.type === 'M') { if (cur.length > 2) polys.push(cur); cur = [[c.x, c.y]]; px = c.x; py = c.y; }
    else if (c.type === 'L') { cur.push([c.x, c.y]); px = c.x; py = c.y; }
    else if (c.type === 'Q') {
      for (let i = 1; i <= N; i++) { const t = i / N, u = 1 - t; cur.push([u * u * px + 2 * u * t * c.x1 + t * t * c.x, u * u * py + 2 * u * t * c.y1 + t * t * c.y]); }
      px = c.x; py = c.y;
    } else if (c.type === 'C') {
      for (let i = 1; i <= N; i++) { const t = i / N, u = 1 - t;
        cur.push([u*u*u*px + 3*u*u*t*c.x1 + 3*u*t*t*c.x2 + t*t*t*c.x, u*u*u*py + 3*u*u*t*c.y1 + 3*u*t*t*c.y2 + t*t*t*c.y]); }
      px = c.x; py = c.y;
    } else if (c.type === 'Z') { if (cur.length > 2) polys.push(cur); cur = []; }
  }
  if (cur.length > 2) polys.push(cur);
  return polys;
}

// ---------- Export ----------
export function meshDaten(m) {
  const mesh = m.getMesh();
  const np = mesh.numProp, vp = mesh.vertProperties, n = vp.length / np;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { pos[i * 3] = vp[i * np]; pos[i * 3 + 1] = vp[i * np + 1]; pos[i * 3 + 2] = vp[i * np + 2]; }
  return { pos, idx: new Uint32Array(mesh.triVerts) };
}

export function stl(teile) {
  let tris = 0; for (const t of teile) tris += t.idx.length / 3;
  const buf = new ArrayBuffer(84 + tris * 50), dv = new DataView(buf);
  let o = 84; dv.setUint32(80, tris, true);
  for (const { pos, idx, dx = 0, dy = 0 } of teile) for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx, l = Math.hypot(nx, ny, nz) || 1;
    dv.setFloat32(o, nx / l, true); dv.setFloat32(o + 4, ny / l, true); dv.setFloat32(o + 8, nz / l, true); o += 12;
    for (const p of [a, b, c]) { dv.setFloat32(o, pos[p] + dx, true); dv.setFloat32(o + 4, pos[p + 1] + dy, true); dv.setFloat32(o + 8, pos[p + 2], true); o += 12; }
    o += 2;
  }
  return new Uint8Array(buf);
}

// Bambu-Studio-3MF wie in den MakerWorld-Dateien: Objekt mit zwei Teilen (Etikett = Filament 1, Inhalt = Filament 2)
export function bambu3mf(objekte, zipSync, strToU8, mitte = [128, 128]) {
  const f = v => +v.toFixed(5);
  const esc = s => String(s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
  const uuid = (a, b) => `${a.toString(16).padStart(8, '0')}-61cb-4c03-9d28-${b.toString(16).padStart(12, '0')}`;
  const files = {};
  let sub = 1, top = '', build = '', cfg = '', plate = '', rels = '';
  const datum = new Date().toISOString().slice(0, 10);
  objekte.forEach((ob, n) => {
    const pfad = `/3D/Objects/object_${n + 1}.model`;
    let res = '', comps = '', parts = '';
    for (const t of ob.teile) {
      const { pos, idx } = t.mesh;
      const v = [], tr = [];
      for (let i = 0; i < pos.length; i += 3) v.push(`<vertex x="${f(pos[i])}" y="${f(pos[i + 1])}" z="${f(pos[i + 2])}"/>`);
      for (let i = 0; i < idx.length; i += 3) tr.push(`<triangle v1="${idx[i]}" v2="${idx[i + 1]}" v3="${idx[i + 2]}"/>`);
      res += `  <object id="${sub}" p:UUID="${uuid(0x10000 + sub, sub)}" type="model">\n   <mesh>\n    <vertices>\n${v.join('\n')}\n    </vertices>\n    <triangles>\n${tr.join('\n')}\n    </triangles>\n   </mesh>\n  </object>\n`;
      comps += `    <component p:path="${pfad}" objectid="${sub}" p:UUID="${uuid(0x20000 + sub, sub)}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n`;
      parts += `    <part id="${sub}" subtype="normal_part">\n      <metadata key="name" value="${esc(t.name)}"/>\n      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n      <metadata key="extruder" value="${t.extruder}"/>\n      <mesh_stat face_count="${idx.length / 3}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>\n`;
      sub++;
    }
    files[pfad.slice(1)] = strToU8(`<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n${res} </resources>\n <build/>\n</model>\n`);
    rels += ` <Relationship Target="${pfad}" Id="rel-${n + 1}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n`;
    const oid = 10000 + n;
    top += `  <object id="${oid}" p:UUID="${uuid(n + 1, oid)}" type="model">\n   <components>\n${comps}   </components>\n  </object>\n`;
    build += `  <item objectid="${oid}" p:UUID="${uuid(0x30000 + n, oid)}" transform="1 0 0 0 1 0 0 0 1 ${f(mitte[0] + ob.x)} ${f(mitte[1] + ob.y)} 0" printable="1"/>\n`;
    cfg += `  <object id="${oid}">\n    <metadata key="name" value="${esc(ob.name)}"/>\n    <metadata key="extruder" value="1"/>\n${parts}  </object>\n`;
    plate += `    <model_instance>\n      <metadata key="object_id" value="${oid}"/>\n      <metadata key="instance_id" value="0"/>\n      <metadata key="identify_id" value="${100 + n}"/>\n    </model_instance>\n`;
  });
  files['3D/3dmodel.model'] = strToU8(`<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="de-DE" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">BambuStudio-02.04.00.70</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="CreationDate">${datum}</metadata>
 <metadata name="ModificationDate">${datum}</metadata>
 <metadata name="Title">Rasterwerk Etiketten</metadata>
 <resources>
${top} </resources>
 <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
${build} </build>
</model>
`);
  files['3D/_rels/3dmodel.model.rels'] = strToU8(`<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n${rels}</Relationships>\n`);
  files['Metadata/model_settings.config'] = strToU8(`<?xml version="1.0" encoding="UTF-8"?>
<config>
${cfg}  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="Etiketten"/>
    <metadata key="locked" value="false"/>
${plate}  </plate>
  <assemble>
  </assemble>
</config>
`);
  files['[Content_Types].xml'] = strToU8(`<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>`);
  files['_rels/.rels'] = strToU8(`<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>`);
  return zipSync(files, { level: 6 });
}

// Anordnung auf der Platte (zentriert um 0,0)
export function anordnen(anzahl, laenge, plattenBreite = 240, breite = 11.5) {
  const dx = laenge + 2 + 3, dy = breite + 2.5;
  const spalten = Math.max(1, Math.min(anzahl, Math.floor(plattenBreite / dx)));
  const zeilen = Math.ceil(anzahl / spalten);
  return Array.from({ length: anzahl }, (_, i) => ({
    x: (i % spalten - (spalten - 1) / 2) * dx,
    y: ((zeilen - 1) / 2 - Math.floor(i / spalten)) * dy,
  }));
}
