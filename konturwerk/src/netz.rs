//! Dreiecksnetz, Lofts, Stufenkörper (2,5D) und STL-Ausgabe.
use geo::{BooleanOps, Coord, LineString, MultiPolygon, Orient, Polygon, orient::Direction};
use std::collections::HashMap;

pub type P2 = [f64; 2];
pub type V3 = [f64; 3];

#[derive(Clone, Default)]
pub struct Netz {
    pub tris: Vec<[V3; 3]>,
}

impl Netz {
    pub fn add(&mut self, a: V3, b: V3, c: V3) {
        self.tris.push([a, b, c]);
    }
    pub fn quad(&mut self, a: V3, b: V3, c: V3, d: V3) {
        self.add(a, b, c);
        self.add(a, c, d);
    }
    pub fn anhaengen(&mut self, o: &Netz) {
        self.tris.extend_from_slice(&o.tris);
    }
    pub fn verschieben(&mut self, d: V3) {
        for t in &mut self.tris {
            for v in t.iter_mut() {
                v[0] += d[0];
                v[1] += d[1];
                v[2] += d[2];
            }
        }
    }
    pub fn grenzen(&self) -> (V3, V3) {
        let mut mn = [f64::MAX; 3];
        let mut mx = [f64::MIN; 3];
        for t in &self.tris {
            for v in t {
                for k in 0..3 {
                    mn[k] = mn[k].min(v[k]);
                    mx[k] = mx[k].max(v[k]);
                }
            }
        }
        (mn, mx)
    }
    pub fn stl(&self, name: &str) -> Vec<u8> {
        let mut out = Vec::with_capacity(84 + self.tris.len() * 50);
        let mut head = [0u8; 80];
        let n = name.as_bytes();
        head[..n.len().min(80)].copy_from_slice(&n[..n.len().min(80)]);
        out.extend_from_slice(&head);
        out.extend_from_slice(&(self.tris.len() as u32).to_le_bytes());
        for t in &self.tris {
            let nrm = normale(t);
            for k in 0..3 {
                out.extend_from_slice(&(nrm[k] as f32).to_le_bytes());
            }
            for v in t {
                for k in 0..3 {
                    out.extend_from_slice(&(v[k] as f32).to_le_bytes());
                }
            }
            out.extend_from_slice(&[0, 0]);
        }
        out
    }
    /// Eckpunkte zusammenführen (Index-Netz), Punkte näher als 0,5 µm gelten als gleich
    pub fn indiziert(&self) -> (Vec<V3>, Vec<[usize; 3]>) {
        const TOL: f64 = 5e-4;
        let zelle = |v: f64| (v / TOL).floor() as i64;
        let mut gitter: HashMap<(i64, i64, i64), Vec<usize>> = HashMap::new();
        let mut verts: Vec<V3> = Vec::new();
        let mut finde = |p: V3, verts: &mut Vec<V3>| -> usize {
            let (cx, cy, cz) = (zelle(p[0]), zelle(p[1]), zelle(p[2]));
            for dx in -1..=1 {
                for dy in -1..=1 {
                    for dz in -1..=1 {
                        if let Some(l) = gitter.get(&(cx + dx, cy + dy, cz + dz)) {
                            for &i in l {
                                let q = verts[i];
                                if (q[0] - p[0]).abs() <= TOL && (q[1] - p[1]).abs() <= TOL && (q[2] - p[2]).abs() <= TOL {
                                    return i;
                                }
                            }
                        }
                    }
                }
            }
            verts.push(p);
            gitter.entry((cx, cy, cz)).or_default().push(verts.len() - 1);
            verts.len() - 1
        };
        let mut tris = Vec::new();
        for t in &self.tris {
            let tri = [finde(t[0], &mut verts), finde(t[1], &mut verts), finde(t[2], &mut verts)];
            if tri[0] != tri[1] && tri[1] != tri[2] && tri[0] != tri[2] {
                tris.push(tri);
            }
        }
        // Paare deckungsgleicher, entgegengesetzter Dreiecke (Nullvolumen) entfernen
        let mut zaehl: HashMap<[usize; 3], usize> = HashMap::new();
        let norm = |t: &[usize; 3]| { let mut s = *t; s.sort(); s };
        for t in &tris {
            *zaehl.entry(norm(t)).or_default() += 1;
        }
        tris.retain(|t| zaehl[&norm(t)] == 1);
        (verts, tris)
    }
    /// T-Stellen beseitigen: Dreieckskanten an Punkten teilen, die genau auf ihnen liegen
    pub fn reparieren(&mut self) {
        let (verts, tris) = self.indiziert();
        let zelle = 2.0;
        let key = |p: &V3| ((p[0] / zelle).floor() as i64, (p[1] / zelle).floor() as i64, (p[2] / zelle).floor() as i64);
        let mut gitter: HashMap<(i64, i64, i64), Vec<usize>> = HashMap::new();
        for (i, v) in verts.iter().enumerate() {
            gitter.entry(key(v)).or_default().push(i);
        }
        let auf_kante = |a: usize, b: usize| -> Vec<(f64, usize)> {
            let (pa, pb) = (verts[a], verts[b]);
            let d = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]];
            let l2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
            let mut out = Vec::new();
            if l2 < 1e-12 {
                return out;
            }
            let (ka, kb) = (key(&pa), key(&pb));
            for x in ka.0.min(kb.0)..=ka.0.max(kb.0) {
                for y in ka.1.min(kb.1)..=ka.1.max(kb.1) {
                    for z in ka.2.min(kb.2)..=ka.2.max(kb.2) {
                        if let Some(l) = gitter.get(&(x, y, z)) {
                            for &i in l {
                                if i == a || i == b {
                                    continue;
                                }
                                let p = verts[i];
                                let t = ((p[0] - pa[0]) * d[0] + (p[1] - pa[1]) * d[1] + (p[2] - pa[2]) * d[2]) / l2;
                                if t <= 1e-6 || t >= 1.0 - 1e-6 {
                                    continue;
                                }
                                let q = [pa[0] + d[0] * t - p[0], pa[1] + d[1] * t - p[1], pa[2] + d[2] * t - p[2]];
                                if q[0] * q[0] + q[1] * q[1] + q[2] * q[2] < 4e-8 {
                                    out.push((t, i));
                                }
                            }
                        }
                    }
                }
            }
            out.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
            out
        };
        let mut stapel = tris;
        let mut fertig = Vec::new();
        let mut runden = 0usize;
        while let Some(t) = stapel.pop() {
            runden += 1;
            let mut geteilt = false;
            if runden < 5_000_000 {
                for k in 0..3 {
                    let (a, b, c) = (t[k], t[(k + 1) % 3], t[(k + 2) % 3]);
                    let pk = auf_kante(a, b);
                    if !pk.is_empty() {
                        let mut kette = vec![a];
                        kette.extend(pk.iter().map(|x| x.1));
                        kette.push(b);
                        for w in kette.windows(2) {
                            stapel.push([w[0], w[1], c]);
                        }
                        geteilt = true;
                        break;
                    }
                }
            }
            if !geteilt {
                fertig.push(t);
            }
        }
        self.tris = fertig.into_iter().map(|t| [verts[t[0]], verts[t[1]], verts[t[2]]]).collect();
        // flache Null-Dreiecke (kollineare Punkte) entfernen
        self.tris.retain(|t| {
            let u = [t[1][0] - t[0][0], t[1][1] - t[0][1], t[1][2] - t[0][2]];
            let v = [t[2][0] - t[0][0], t[2][1] - t[0][1], t[2][2] - t[0][2]];
            let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
            n[0] * n[0] + n[1] * n[1] + n[2] * n[2] > 1e-14
        });
    }
    /// Anzahl offener/falscher Kanten (0 = wasserdicht)
    #[allow(dead_code)]
    pub fn offene_kanten(&self) -> usize {
        let (_, tris) = self.indiziert();
        let mut m: HashMap<(usize, usize), i32> = HashMap::new();
        for t in &tris {
            for k in 0..3 {
                let a = t[k];
                let b = t[(k + 1) % 3];
                *m.entry((a, b)).or_default() += 1;
            }
        }
        m.iter().filter(|(k, c)| m.get(&(k.1, k.0)).copied().unwrap_or(0) != **c).count()
    }
}

fn normale(t: &[V3; 3]) -> V3 {
    let u = [t[1][0] - t[0][0], t[1][1] - t[0][1], t[1][2] - t[0][2]];
    let v = [t[2][0] - t[0][0], t[2][1] - t[0][1], t[2][2] - t[0][2]];
    let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    let l = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt().max(1e-12);
    [n[0] / l, n[1] / l, n[2] / l]
}

/// Abgerundetes Rechteck (gegen den Uhrzeigersinn), feste Punktzahl je Ecke
pub fn rrect(x0: f64, y0: f64, w: f64, h: f64, r: f64, seg: usize) -> Vec<P2> {
    let r = r.max(0.01).min(w / 2.0 - 1e-3).min(h / 2.0 - 1e-3);
    let mut out = Vec::with_capacity(seg * 4 + 4);
    let ecken = [
        (x0 + w - r, y0 + r, -0.5f64),
        (x0 + w - r, y0 + h - r, 0.0),
        (x0 + r, y0 + h - r, 0.5),
        (x0 + r, y0 + r, 1.0),
    ];
    for (cx, cy, a0) in ecken {
        for i in 0..=seg {
            let a = (a0 + 0.5 * i as f64 / seg as f64) * std::f64::consts::PI;
            out.push([cx + r * a.cos(), cy + r * a.sin()]);
        }
    }
    out
}

pub fn kreis(cx: f64, cy: f64, r: f64, n: usize) -> Vec<P2> {
    (0..n).map(|i| {
        let a = i as f64 / n as f64 * std::f64::consts::TAU;
        [cx + r * a.cos(), cy + r * a.sin()]
    }).collect()
}

/// Ringe gleicher Punktzahl zu einer geschlossenen Hülle verbinden (unten/oben gedeckelt)
pub fn loft(profile: &[(f64, Vec<P2>)]) -> Netz {
    let mut n = Netz::default();
    for w in profile.windows(2) {
        let (z0, a) = (&w[0].0, &w[0].1);
        let (z1, b) = (&w[1].0, &w[1].1);
        let m = a.len();
        for i in 0..m {
            let j = (i + 1) % m;
            n.quad([a[i][0], a[i][1], *z0], [a[j][0], a[j][1], *z0], [b[j][0], b[j][1], *z1], [b[i][0], b[i][1], *z1]);
        }
    }
    let (zb, ub) = &profile[0];
    deckel(&mut n, &[ub.clone()], *zb, false);
    let (zt, ut) = profile.last().unwrap();
    deckel(&mut n, &[ut.clone()], *zt, true);
    n
}

/// Fläche (Außenring + Löcher) triangulieren; nach oben oder unten gerichtet
pub fn deckel(n: &mut Netz, ringe: &[Vec<P2>], z: f64, oben: bool) {
    if ringe.is_empty() || ringe[0].len() < 3 {
        return;
    }
    let mut flat = Vec::new();
    let mut holes = Vec::new();
    for (i, r) in ringe.iter().enumerate() {
        if i > 0 {
            holes.push(flat.len() / 2);
        }
        for p in r {
            flat.push(p[0]);
            flat.push(p[1]);
        }
    }
    let Ok(idx) = earcutr::earcut(&flat, &holes, 2) else { return };
    let pt = |i: usize| [flat[2 * i], flat[2 * i + 1], z];
    // earcut liefert einheitlich orientierte Dreiecke – Richtung einmal für alle bestimmen
    let mut summe = 0.0;
    for t in idx.chunks(3) {
        let (a, b, c) = (pt(t[0]), pt(t[1]), pt(t[2]));
        summe += (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    }
    let umdrehen = (summe > 0.0) != oben;
    for t in idx.chunks(3) {
        let (a, b, c) = (pt(t[0]), pt(t[1]), pt(t[2]));
        if umdrehen { n.add(a, c, b) } else { n.add(a, b, c) }
    }
}

pub fn poly(ring: &[P2]) -> Polygon<f64> {
    let mut ls: Vec<Coord<f64>> = ring.iter().map(|p| Coord { x: p[0], y: p[1] }).collect();
    if let Some(f) = ls.first().copied() {
        ls.push(f);
    }
    Polygon::new(LineString::new(ls), vec![]).orient(Direction::Default)
}

pub fn ringe_von(mp: &MultiPolygon<f64>) -> Vec<Vec<Vec<P2>>> {
    mp.0.iter()
        .map(|p| {
            let p = p.orient(Direction::Default);
            let conv = |ls: &LineString<f64>| {
                let mut v: Vec<P2> = ls.0.iter().map(|c| [c.x, c.y]).collect();
                if v.len() > 1 && v.first() == v.last() {
                    v.pop();
                }
                v
            };
            let mut r = vec![conv(p.exterior())];
            r.extend(p.interiors().iter().map(conv));
            r
        })
        .filter(|r| r[0].len() >= 3)
        .collect()
}

/// Eine Schicht des Stufenkörpers: zwischen z0 und z1 hat der Körper den Querschnitt `region`
pub struct Schicht {
    pub z0: f64,
    pub z1: f64,
    pub region: MultiPolygon<f64>,
}

/// 2,5D-Körper aus übereinanderliegenden Schichten – wasserdicht (Wände werden an Deckelpunkten geteilt)
pub fn stufenkoerper(schichten: &[Schicht]) -> Netz {
    let mut n = Netz::default();
    if schichten.is_empty() {
        return n;
    }
    let leer = MultiPolygon::<f64>::new(vec![]);
    // Deckel je Höhe sammeln (mit ihren Punkten fürs Teilen der Wände)
    let mut deckel_punkte: Vec<(f64, Vec<P2>)> = Vec::new();
    for i in 0..=schichten.len() {
        let unten = if i == 0 { &leer } else { &schichten[i - 1].region };
        let oben = if i == schichten.len() { &leer } else { &schichten[i].region };
        let z = if i == schichten.len() { schichten[i - 1].z1 } else { schichten[i].z0 };
        let nach_oben = unten.difference(oben);
        let nach_unten = oben.difference(unten);
        let mut pkte = Vec::new();
        for (mp, up) in [(&nach_oben, true), (&nach_unten, false)] {
            for ringe in ringe_von(mp) {
                for r in &ringe {
                    pkte.extend_from_slice(r);
                }
                deckel(&mut n, &ringe, z, up);
            }
        }
        deckel_punkte.push((z, pkte));
    }
    // Wände
    for (i, s) in schichten.iter().enumerate() {
        let unten_p = &deckel_punkte[i].1;
        let oben_p = &deckel_punkte[i + 1].1;
        for ringe in ringe_von(&s.region) {
            for r in &ringe {
                let m = r.len();
                for k in 0..m {
                    let a = r[k];
                    let b = r[(k + 1) % m];
                    let tb = teilungen(a, b, unten_p);
                    let tt = teilungen(a, b, oben_p);
                    wand(&mut n, a, b, s.z0, s.z1, &tb, &tt);
                }
            }
        }
    }
    n.reparieren();
    n
}

/// Parameter t (0..1) aller Punkte, die auf der Strecke a-b liegen, inkl. 0 und 1
fn teilungen(a: P2, b: P2, pkte: &[P2]) -> Vec<f64> {
    let d = [b[0] - a[0], b[1] - a[1]];
    let l2 = d[0] * d[0] + d[1] * d[1];
    let mut ts = vec![0.0, 1.0];
    if l2 < 1e-14 {
        return ts;
    }
    let (mnx, mxx) = (a[0].min(b[0]) - 1e-4, a[0].max(b[0]) + 1e-4);
    let (mny, mxy) = (a[1].min(b[1]) - 1e-4, a[1].max(b[1]) + 1e-4);
    for p in pkte {
        if p[0] < mnx || p[0] > mxx || p[1] < mny || p[1] > mxy {
            continue;
        }
        let t = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2;
        if t <= 1e-6 || t >= 1.0 - 1e-6 {
            continue;
        }
        let q = [a[0] + d[0] * t - p[0], a[1] + d[1] * t - p[1]];
        if q[0] * q[0] + q[1] * q[1] < 1e-8 {
            ts.push(t);
        }
    }
    ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
    ts.dedup_by(|x, y| (*x - *y).abs() < 1e-7);
    ts
}

/// Senkrechte Wand a→b (Material links), unten/oben unterschiedlich geteilt (Reißverschluss)
fn wand(n: &mut Netz, a: P2, b: P2, z0: f64, z1: f64, tb: &[f64], tt: &[f64]) {
    let p = |t: f64, z: f64| [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, z];
    let (mut i, mut j) = (0usize, 0usize);
    while i + 1 < tb.len() || j + 1 < tt.len() {
        let unten_weiter = if i + 1 >= tb.len() { false } else if j + 1 >= tt.len() { true } else { tb[i + 1] <= tt[j + 1] };
        if unten_weiter {
            n.add(p(tb[i], z0), p(tb[i + 1], z0), p(tt[j], z1));
            i += 1;
        } else {
            n.add(p(tb[i], z0), p(tt[j + 1], z1), p(tt[j], z1));
            j += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stufen_dicht() {
        let o = MultiPolygon::new(vec![poly(&rrect(0.0, 0.0, 80.0, 40.0, 3.75, 6))]);
        let tasche = MultiPolygon::new(vec![poly(&kreis(20.0, 20.0, 8.0, 40))]).union(&MultiPolygon::new(vec![poly(&rrect(25.0, 10.0, 40.0, 15.0, 2.0, 4))]));
        let s = vec![
            Schicht { z0: 5.0, z1: 10.0, region: o.clone() },
            Schicht { z0: 10.0, z1: 20.0, region: o.difference(&tasche) },
        ];
        let n = stufenkoerper(&s);
        assert_eq!(n.offene_kanten(), 0);
        let l = loft(&[(0.0, rrect(0.0, 0.0, 30.0, 30.0, 1.0, 5)), (2.0, rrect(-2.0, -2.0, 34.0, 34.0, 3.0, 5))]);
        assert_eq!(l.offene_kanten(), 0);
    }
}
#[cfg(test)]
pub fn debug_offen(n: &Netz) {
    let (v, tris) = n.indiziert();
    let mut m: HashMap<(usize, usize), i32> = HashMap::new();
    for t in &tris { for k in 0..3 { *m.entry((t[k], t[(k + 1) % 3])).or_default() += 1; } }
    for (k, c) in &m { if m.get(&(k.1, k.0)).copied().unwrap_or(0) != *c { eprintln!("{:?} -> {:?} x{}", v[k.0], v[k.1], c); } }
}
