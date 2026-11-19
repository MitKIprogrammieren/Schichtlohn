// Gridwerk – Gridfinity-Grundplatten (Baseplates), Schubladen-Zuschnitt und Aufteilung nach Druckbett

export const PLATTE_STANDARD = {
  modus: 'schublade', gx: 4, gy: 3, schubB: 300, schubT: 200, spiel: 0.5,
  ausX: 'mitte', ausY: 'mitte', stil: 'leicht', teilen: true, belegung: [],
};

export function makePlatten(wasm) {
  const { Manifold, CrossSection: C } = wasm;
  const G = 42, E = 0.001, H_TASCHE = 4.65;
  const rr2 = (w, d, r) => {
    r = Math.max(0.01, Math.min(r, w / 2 - 0.01, d / 2 - 0.01));
    return C.square([w - 2 * r, d - 2 * r], true).offset(r, 'Round', 2, 40);
  };
  const scheibe = (w, d, r, z) => Manifold.extrude(rr2(w, d, r), E).translate([0, 0, z]);

  // Raster und Randausgleich aus den Einstellungen
  function raster(p) {
    if (p.modus !== 'schublade') return { nx: Math.max(1, p.gx | 0), ny: Math.max(1, p.gy | 0), padL: 0, padR: 0, padV: 0, padH: 0 };
    const nutzB = Math.max(G, +p.schubB - 2 * +p.spiel), nutzT = Math.max(G, +p.schubT - 2 * +p.spiel);
    const nx = Math.max(1, Math.floor(nutzB / G + 1e-6)), ny = Math.max(1, Math.floor(nutzT / G + 1e-6));
    const restX = Math.max(0, nutzB - nx * G), restY = Math.max(0, nutzT - ny * G);
    const teile = (rest, a) => a === 'links' || a === 'vorn' ? [0, rest] : a === 'rechts' || a === 'hinten' ? [rest, 0] : [rest / 2, rest / 2];
    const [padL, padR] = teile(restX, p.ausX), [padV, padH] = teile(restY, p.ausY);
    return { nx, ny, padL, padR, padV, padH };
  }

  // Aufteilung einer Achse in Stücke, die aufs Druckbett passen
  function aufteilen(n, padA, padB, bett) {
    for (let k = 1; k <= n; k++) {
      const basis = Math.floor(n / k), extra = n % k, stuecke = [];
      for (let i = 0; i < k; i++) stuecke.push(basis + (i < extra ? 1 : 0));
      const breiten = stuecke.map((u, i) => u * G + (i === 0 ? padA : 0) + (i === k - 1 ? padB : 0));
      if (Math.max(...breiten) <= bett) return stuecke;
    }
    return Array(n).fill(1);
  }

  function tasche() {
    // Gegenstück zum Behälterfuß (gridfinity-rebuilt Baseplate-Profil)
    const pr = [[2.85, -0.5], [2.85, 0], [2.15, 0.7], [2.15, 2.5], [0, H_TASCHE + 0.3]];
    const t = [];
    for (let i = 0; i < pr.length - 1; i++) {
      const [e1, z1] = pr[i], [e2, z2] = pr[i + 1];
      t.push(Manifold.hull([scheibe(G - 2 * e1, G - 2 * e1, 4 - e1, z1), scheibe(G - 2 * e2, G - 2 * e2, 4 - e2, z2 - E)]));
    }
    return Manifold.union(t);
  }

  // Ein Plattenstück in globalen Koordinaten [xa,xb]×[ya,yb]; Zellen ab (zx0, zy0) Mittelpunkt der ersten Zelle
  function stueck(xa, xb, ya, yb, zellen, gesW, gesD, stil) {
    const unten = stil === 'leicht' ? 0 : stil === 'magnete' ? 2.6 : 4.4;
    const H = H_TASCHE + unten;
    const umriss = rr2(gesW, gesD, 4).intersect(C.square([xb - xa, yb - ya]).translate([xa, ya]));
    let k = Manifold.extrude(umriss, H);
    const t = tasche(), cuts = [];
    for (const [cx, cy] of zellen) {
      cuts.push(t.translate([cx, cy, unten]));
      if (stil === 'leicht') cuts.push(Manifold.extrude(rr2(G - 5.7, G - 5.7, 1.15), unten + 1).translate([cx, cy, -0.5]));
      else for (const sx of [-13, 13]) for (const sy of [-13, 13]) {
        cuts.push(Manifold.cylinder(2.5, 3.25, 3.25, 40).translate([cx + sx, cy + sy, unten - 2.4]));
        if (stil === 'schrauben') {
          cuts.push(Manifold.cylinder(unten + 1, 1.6, 1.6, 24).translate([cx + sx, cy + sy, -0.5]));
          cuts.push(Manifold.cylinder(1.6, 3.2, 1.6, 32).translate([cx + sx, cy + sy, -0.01]));
        }
      }
    }
    k = k.subtract(Manifold.union(cuts));
    const mx = (xa + xb) / 2, my = (ya + yb) / 2;
    return { koerper: k.translate([-mx, -my, 0]), W: xb - xa, D: yb - ya, H, x: mx, y: my };
  }

  // Ganze Platte (ggf. in Stücke geteilt). bett = nutzbare Druckbettbreite in mm.
  function platte(p, bett = 250) {
    const r = raster(p), stil = p.stil || 'leicht';
    const sx = p.teilen ? aufteilen(r.nx, r.padL, r.padR, bett) : [r.nx];
    const sy = p.teilen ? aufteilen(r.ny, r.padV, r.padH, bett) : [r.ny];
    const gesW = r.nx * G + r.padL + r.padR, gesD = r.ny * G + r.padV + r.padH;
    const teile = [];
    let ix = 0, xa = -gesW / 2;
    sx.forEach((ux, i) => {
      const xb = xa + ux * G + (i === 0 ? r.padL : 0) + (i === sx.length - 1 ? r.padR : 0);
      let iy = 0, ya = -gesD / 2;
      sy.forEach((uy, j) => {
        const yb = ya + uy * G + (j === 0 ? r.padV : 0) + (j === sy.length - 1 ? r.padH : 0);
        const zellen = [];
        for (let a = 0; a < ux; a++) for (let b = 0; b < uy; b++) { const m = zellMitte(r, gesW, gesD, ix + a, iy + b); zellen.push([m.x, m.y]); }
        teile.push({ ...stueck(xa, xb, ya, yb, zellen, gesW, gesD, stil), name: `Platte ${i + 1}-${j + 1} (${ux}×${uy})` });
        ya = yb; iy += uy;
      });
      xa = xb; ix += ux;
    });
    return { teile, raster: r, gesW, gesD, H: teile[0]?.H ?? H_TASCHE, stueckeX: sx, stueckeY: sy };
  }

  // Mittelpunkt einer Rasterzelle (Zelle 0,0 = vorn links) in Plattenkoordinaten
  function zellMitte(r, gesW, gesD, ix, iy, w = 1, d = 1) {
    return { x: -gesW / 2 + r.padL + (ix + w / 2) * G, y: -gesD / 2 + r.padV + (iy + d / 2) * G };
  }

  return { platte, raster, zellMitte, H_TASCHE };
}
