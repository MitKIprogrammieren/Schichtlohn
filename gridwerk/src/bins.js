// Rasterwerk – Gridfinity-Behälter mit Pred-Clip-Etikettenhalter
// Port von "Gridfinity Bin with Pred-Style Snap-In Label Holder" (3DLG), Basis gridfinity-rebuilt (kennetek) / ABDELat.

export const BIN_STANDARD = {
  Bin_Width: 1, Bin_Depth: 1, Bin_Height: 6, Height_Mode: 0, Snap_Height_To_Grid: false,
  Compartments_Left_To_Right: 1, Compartments_Front_To_Back: 1,
  Top_Lip_Style: 0, Scoop_Size: 1, Corner_Holes_Only: false, Label_Holder: true, Base_Hole_Style: 0,
  Top_Edge_Color_Height: 1.0,
};

export function makeBins(wasm) {
  const { Manifold, CrossSection: C } = wasm;
  const L_GRID = 42, H_BASE = 5, R_BASE = 4, R_C1 = 0.8, R_C2 = 2.4, H_BOT = 2.2;
  const R_FO1 = 8.5, R_FO2 = 3.2, R_FO3 = 1.6, R_HOLE1 = 1.5, R_HOLE2 = 3.25, D_HOLE = 26, D_HOLE_SIDE = 8, H_HOLE = 2.4, H_SLIT = 0.2;
  const R_F2 = 2.8, D_DIV = 1.2, D_WALL = 0.95, D_CLEAR = 0.25, A_TAB = 36, H_LIP = 3.548;
  const KLAR = 0.35, BACK_OFF = 3.4, HALTER_RAND = 3.0, CUT_TIEFE = 1.0, POS_Y = 1.0;
  const D_TABH = Math.max(15.85, 11.5 + 2 * KLAR + HALTER_RAND);
  const D_WALL2 = R_BASE - R_C1 - D_CLEAR * Math.SQRT2;
  const D_MAGIC = -2 * D_CLEAR - 2 * D_WALL + D_DIV;
  const E = 0.001;

  const rr2 = (w, d, r) => {
    r = Math.max(0.01, Math.min(r, w / 2 - 0.01, d / 2 - 0.01));
    return C.square([w - 2 * r, d - 2 * r], true).offset(r, 'Round', 2, 40);
  };
  const rrBox = (w, d, h, r, z = 0) => Manifold.extrude(rr2(w, d, r), h).translate([0, 0, z]);
  const scheibe = (w, d, r, z) => rrBox(w, d, E, r, z);

  // Höhe wie in der SCAD (height()/hf())
  function binHoehe(o) {
    const z = +o.Bin_Height, d = +o.Height_Mode, l = +o.Top_Lip_Style;
    let hf = (d === 0 ? z * 7 : d === 1 ? H_BOT + z + H_BASE : z - (l === 1 ? H_LIP : 0)) + (l === 2 ? H_LIP : 0);
    if (o.Snap_Height_To_Grid && Math.abs(hf) % 7 > 1e-6) hf = hf + 7 - Math.abs(hf) % 7;
    return hf - H_BASE;
  }

  // Fuß einer Rasterzelle (block_base_solid) mit Löchern
  function fussZelle(stil, ohneLoecher) {
    const xx = L_GRID - 0.05;
    const a = xx - 2 * R_C2 - 2 * R_C1, b = xx - 2 * R_C2;
    let f = Manifold.union([
      Manifold.hull([scheibe(a, a, R_FO3 / 2, 0), scheibe(b, b, R_FO2 / 2, R_C1), scheibe(b, b, R_FO2 / 2, H_BASE - E)]),
      Manifold.hull([scheibe(b, b, R_FO2 / 2, H_BASE - R_C2), scheibe(xx, xx, R_FO1 / 2, H_BASE), scheibe(xx, xx, R_FO1 / 2, H_BASE + H_BOT / 2 - E)]),
    ]);
    if (stil > 0 && !ohneLoecher) {
      const l = [];
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) l.push(loch(stil).translate([sx * (L_GRID / 2 - D_HOLE_SIDE), sy * (L_GRID / 2 - D_HOLE_SIDE), 0]));
      f = f.subtract(Manifold.union(l));
    }
    return f;
  }
  function loch(stil) {
    let m = Manifold.cylinder(H_HOLE + (stil === 3 ? H_SLIT : 0) + 1, R_HOLE2, R_HOLE2, 48).translate([0, 0, -1]);
    if (stil === 3) {
      const weg = Manifold.cube([R_HOLE2 * 3, R_HOLE2 * 3, 10], false);
      m = m.subtract(Manifold.union([weg.translate([-1.5 * R_HOLE2, R_HOLE1 + 0.1, H_HOLE]), weg.translate([-1.5 * R_HOLE2, -R_HOLE1 - 0.1 - R_HOLE2 * 3, H_HOLE])]));
    }
    if (stil > 1) m = m.add(Manifold.cylinder(H_BASE + 1, R_HOLE1, R_HOLE1, 32).translate([0, 0, -1]));
    return m;
  }

  function basis(gx, gy, o) {
    const xx = gx * L_GRID - 0.5, yy = gy * L_GRID - 0.5, stil = +o.Base_Hole_Style;
    const nurEcken = !!o.Corner_Holes_Only && stil > 0;
    const zelle = fussZelle(stil, nurEcken), f = [];
    for (let i = 0; i < gx; i++) for (let j = 0; j < gy; j++)
      f.push(zelle.translate([(i - (gx - 1) / 2) * L_GRID, (j - (gy - 1) / 2) * L_GRID, 0]));
    let b = Manifold.union(f).intersect(rrBox(xx + 0.005, yy + 0.005, H_BASE + H_BOT * 5 + 1, R_FO1 / 2, -1));
    b = b.add(rrBox(xx + 0.002, yy + 0.002, H_BOT / 1.5, R_FO1 / 2, H_BASE));
    if (nurEcken) {
      const l = [], ax = ((gx - 1) * L_GRID + D_HOLE) / 2, ay = ((gy - 1) * L_GRID + D_HOLE) / 2;
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) l.push(loch(stil).translate([sx * ax, sy * ay, 0]));
      b = b.subtract(Manifold.union(l));
    }
    return b;
  }

  // Wand mit Stapelrand: Einzug W(z) von der Außenkante, z relativ zu H_BASE
  function wandProfil(dh, lippe) {
    if (!lippe) return [[D_WALL, -E], [D_WALL, dh + E]];
    const x1 = D_WALL / 2, x2 = D_WALL2 - D_CLEAR, d = D_CLEAR * Math.SQRT2;
    const p = [[x1, -E], [x1, dh - 1.2 - D_WALL2 + D_WALL / 2], [x2, dh - 1.2], [x2, dh]];
    const senk = 2.15 - D_CLEAR; // senkrechter Teil der Aufnahme
    const zA = dh + (x2 - senk);                 // 45°-Teil unten endet
    const zB = dh + 2.6 - (senk - (2.15 - d)) ;   // 45°-Teil oben beginnt
    p.push([senk, zA], [senk, zB]);
    const zEnde = dh + 4.2;
    p.push([Math.max(0.15, (2.15 - d) - (zEnde - dh - 2.6)), zEnde]);
    return p;
  }
  function wand(gx, gy, dh, lippe) {
    const W = gx * L_GRID - 0.5, D = gy * L_GRID - 0.5;
    const prof = wandProfil(dh, lippe);
    const oben = prof[prof.length - 1][1];
    const aussen = rrBox(W, D, oben, R_BASE, H_BASE);
    const teile = [];
    for (let i = 0; i < prof.length - 1; i++) {
      const [e1, z1] = prof[i], [e2, z2] = prof[i + 1];
      if (z2 - z1 < 1e-6) continue;
      teile.push(Manifold.hull([scheibe(W - 2 * e1, D - 2 * e1, R_BASE - e1, H_BASE + z1), scheibe(W - 2 * e2, D - 2 * e2, R_BASE - e2, H_BASE + z2 - E)]));
    }
    const [eo] = prof[prof.length - 1];
    teile.push(rrBox(W - 2 * eo, D - 2 * eo, 2, R_BASE - eo, H_BASE + oben - E));
    return { wand: aussen.subtract(Manifold.union(teile)), oben: H_BASE + oben };
  }

  // Punktwolke einer Kugel (für Hüllen statt Minkowski)
  const KUGEL = (() => { const p = [], n = 42; for (let i = 0; i < n; i++) { const y = 1 - 2 * (i + 0.5) / n, r = Math.sqrt(1 - y * y), t = i * 2.39996; p.push([Math.cos(t) * r, y, Math.sin(t) * r]); } p.push([0, 0, 1], [0, 0, -1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]); return p; })();
  const kugel = (c, r) => KUGEL.map(([x, y, z]) => [c[0] + x * r, c[1] + y * r, c[2] + z * r]);

  // Hohlraum eines Fachs: abgerundet (R_F2), vorn unten Griffmulde
  function fachHohlraum(xa, xb, yf, yb, zf, zt, mulde) {
    const r = R_F2, R = Math.max(r, Math.min(mulde + r, (yb - yf) - r, zt - zf - r));
    const pts = [];
    for (const xc of [xa + r, xb - r]) {
      pts.push(...kugel([xc, yb - r, zf + r], r), ...kugel([xc, yb - r, zt], r), ...kugel([xc, yf + r, zt], r));
      const n = R > r + 0.01 ? 10 : 1;
      for (let k = 0; k <= n; k++) {
        const t = (Math.PI / 2) * k / Math.max(1, n);
        pts.push(...kugel([xc, yf + R - (R - r) * Math.cos(t), zf + R - (R - r) * Math.sin(t)], r));
      }
    }
    return Manifold.hull(pts);
  }
  // Lasche hinten (Dreieck im y-z-Schnitt), über die Fachbreite extrudiert
  function lasche(xa, xb, yb, zTop, zOben, tiefe, winkel) {
    const fall = tiefe * Math.tan(winkel * Math.PI / 180);
    const sek = new C([[[yb + 2, zOben + 2], [yb - tiefe, zOben + 2], [yb - tiefe, zTop], [yb + 2, zTop - fall - 2 * Math.tan(winkel * Math.PI / 180)]]], 'NonZero');
    return Manifold.extrude(sek, xb - xa + 4).rotate([90, 0, 90]).translate([xa - 2, 0, 0]);
  }

  function etikettTasche(laenge, tiefe) {
    const k = KLAR;
    const cs = C.union([rr2(laenge + 2 * k, 11.5 + 2 * k, 0.9 + k), C.square([laenge + 2 + 2 * k, 6 + 2 * k], true)]);
    return Manifold.extrude(cs, tiefe);
  }

  function bin(o) {
    o = { ...BIN_STANDARD, ...o };
    const gx = Math.max(0.5, +o.Bin_Width), gy = Math.max(0.5, +o.Bin_Depth);
    const lipStil = +o.Top_Lip_Style, lippe = lipStil === 0;
    const dh = binHoehe(o);
    const topZ = dh + H_BASE;
    const nx = Math.max(0, o.Compartments_Left_To_Right | 0), ny = Math.max(0, o.Compartments_Front_To_Back | 0);

    // Boden-Block mit Fächern
    let block = rrBox(gx * L_GRID - 0.5 - D_WALL / 4, gy * L_GRID - 0.5 - D_WALL / 4, dh - 0.1, R_BASE + 0.01, H_BASE + 0.1);
    const zsmall = topZ / 7 < 3;
    const mitLasche = o.Label_Holder && !zsmall;
    if (nx > 0 && ny > 0) {
      const xx = gx * L_GRID + D_MAGIC, yy = gy * L_GRID + D_MAGIC;
      const zf = H_BASE + H_BOT, zt = topZ + 3;
      const scoop = Math.max(+o.Scoop_Size * dh / 2 - R_F2, 0);
      const cuts = [], voll = [];
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
        const cx = -xx / 2 + (i + 0.5) * xx / nx, cy = -yy / 2 + (j + 0.5) * yy / ny;
        const xlen = xx / nx - D_DIV, ylen = yy / ny - D_DIV;
        const xa = cx - xlen / 2, xb = cx + xlen / 2, yb = cy + ylen / 2;
        let yf = cy - ylen / 2;
        if (j === 0 && lippe && +o.Scoop_Size > 0) yf += D_WALL2 - D_WALL - D_CLEAR;
        let h = fachHohlraum(xa, xb, yf, yb, zf, zt, +o.Scoop_Size > 0 ? scoop : 0);
        if (mitLasche) h = h.subtract(lasche(xa, xb, yb, topZ, zt, D_TABH, A_TAB));
        else if (j === ny - 1 && lippe) h = h.subtract(lasche(xa, xb, yb, topZ, zt, D_WALL2 - D_WALL + 1.2, 45));
        cuts.push(h);
      }
      block = block.subtract(Manifold.union(cuts));
    }

    const { wand: rand, oben } = wand(gx, gy, dh, lippe);
    let koerper = Manifold.union([block, rand, basis(gx, gy, o)]);

    // Etikettenhalter-Taschen (eine pro Fachreihe, volle Breite)
    let taschen = null;
    if (o.Label_Holder) {
      const reihen = Math.max(1, ny), D = gy * L_GRID - 0.5, len = gx * L_GRID - 6.2, t = [];
      for (let j = 1; j <= reihen; j++) {
        const yEnde = -D / 2 + j * (D / reihen);
        const cy = yEnde - BACK_OFF - (11.5 + 2 * KLAR) / 2 + POS_Y;
        t.push(etikettTasche(len, CUT_TIEFE + 0.04).translate([0, cy, topZ - CUT_TIEFE - 0.02]));
      }
      taschen = Manifold.union(t);
      koerper = koerper.subtract(taschen);
    }

    // Farbrand: oberer Teil des Randes ab topZ - Top_Edge_Color_Height
    let band = null;
    if (o.randSeparat) {
      const zmin = topZ - +o.Top_Edge_Color_Height;
      const schnitt = Manifold.cube([gx * L_GRID * 2, gy * L_GRID * 2, 100], true).translate([0, 0, zmin + 50]);
      band = rand.intersect(schnitt);
      if (taschen) band = band.subtract(taschen);
      const sauber = m => { const t = m.decompose().filter(x => x.volume() > 1); return t.length ? Manifold.union(t) : null; };
      band = band.isEmpty() ? null : sauber(band);
      if (band) koerper = sauber(koerper.subtract(band));
    }
    return { koerper, band, dh, topZ, oben, zsmall, etikettLaenge: gx * L_GRID - 6.2, reihen: Math.max(1, ny), gx, gy };
  }

  // Lage der Etiketten (für die Vorschau): Mittelpunkte und Oberkante
  function etikettLagen(r) {
    const D = r.gy * L_GRID - 0.5, out = [];
    for (let j = 1; j <= r.reihen; j++) {
      const yEnde = -D / 2 + j * (D / r.reihen);
      out.push({ x: 0, y: yEnde - BACK_OFF - (11.5 + 2 * KLAR) / 2 + POS_Y, z: r.topZ - CUT_TIEFE });
    }
    return out;
  }

  return { bin, binHoehe, etikettLagen };
}
