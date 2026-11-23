//! Dreiecksnetze erzeugen (Extrusion, Drehung, Bohrwerkzeuge) und boolesch verknüpfen.
use crate::profil::{dreiecke, Flaeche, P2};
use boolmesh::prelude::*;

#[derive(Debug, Clone, Default)]
pub struct Netz {
    pub pos: Vec<[f64; 3]>,
    pub idx: Vec<[usize; 3]>,
}

/// Ebene im Raum: Ursprung o, Achsen u, v, Normale n.
#[derive(Debug, Clone, Copy)]
pub struct Rahmen { pub o: [f64; 3], pub u: [f64; 3], pub v: [f64; 3], pub n: [f64; 3] }
impl Rahmen {
    pub fn welt(&self, x: f64, y: f64, z: f64) -> [f64; 3] {
        [0, 1, 2].map(|i| self.o[i] + self.u[i] * x + self.v[i] * y + self.n[i] * z)
    }
}

impl Netz {
    pub fn volumen(&self) -> f64 {
        self.idx.iter().map(|t| { let a = self.pos[t[0]]; let b = self.pos[t[1]]; let c = self.pos[t[2]]; dot(a, kreuz(b, c)) }).sum::<f64>() / 6.0
    }
    /// Dreiecke so drehen, dass das Volumen positiv ist (Normalen zeigen nach außen).
    pub fn ausrichten(mut self) -> Self {
        if self.volumen() < 0.0 { for t in self.idx.iter_mut() { t.swap(1, 2); } }
        self
    }
    pub fn transformiert(mut self, r: &Rahmen) -> Self {
        for p in self.pos.iter_mut() { *p = r.welt(p[0], p[1], p[2]); }
        self
    }
    pub fn anhaengen(&mut self, o: &Netz) {
        let off = self.pos.len();
        self.pos.extend_from_slice(&o.pos);
        self.idx.extend(o.idx.iter().map(|t| [t[0] + off, t[1] + off, t[2] + off]));
    }
    pub fn leer(&self) -> bool { self.idx.is_empty() }
    pub fn grenzen(&self) -> ([f64; 3], [f64; 3]) {
        let mut a = [f64::INFINITY; 3]; let mut b = [f64::NEG_INFINITY; 3];
        for p in &self.pos { for i in 0..3 { a[i] = a[i].min(p[i]); b[i] = b[i].max(p[i]); } }
        (a, b)
    }
}

pub fn dot(a: [f64; 3], b: [f64; 3]) -> f64 { a[0] * b[0] + a[1] * b[1] + a[2] * b[2] }
pub fn kreuz(a: [f64; 3], b: [f64; 3]) -> [f64; 3] { [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]] }

/// Flächen von z0 bis z1 (lokal) extrudieren.
pub fn extrusion(flaechen: &[Flaeche], z0: f64, z1: f64) -> Netz {
    let mut n = Netz::default();
    for fl in flaechen {
        let basis = n.pos.len();
        let anzahl: usize = fl.iter().map(|k| k.len()).sum();
        for k in fl { for p in k { n.pos.push([p[0], p[1], z0]); } }
        for k in fl { for p in k { n.pos.push([p[0], p[1], z1]); } }
        // Deckel
        for t in dreiecke(fl) {
            n.idx.push([basis + anzahl + t[0], basis + anzahl + t[1], basis + anzahl + t[2]]);
            n.idx.push([basis + t[0], basis + t[2], basis + t[1]]);
        }
        // Seiten
        let mut off = 0;
        for k in fl {
            let m = k.len();
            for i in 0..m {
                let j = (i + 1) % m;
                let (bi, bj, ti, tj) = (basis + off + i, basis + off + j, basis + anzahl + off + i, basis + anzahl + off + j);
                n.idx.push([bi, bj, tj]);
                n.idx.push([bi, tj, ti]);
            }
            off += m;
        }
    }
    n.ausrichten()
}

/// Kegelstumpf/Zylinder entlang z von z0 (Radius r0) nach z1 (Radius r1) um (x, y).
pub fn kegel(x: f64, y: f64, z0: f64, z1: f64, r0: f64, r1: f64) -> Netz {
    let seg = crate::profil::segmente_fuer_radius(r0.max(r1), std::f64::consts::TAU);
    let mut n = Netz::default();
    for (z, r) in [(z0, r0), (z1, r1)] {
        for i in 0..seg { let a = i as f64 / seg as f64 * std::f64::consts::TAU; n.pos.push([x + r * a.cos(), y + r * a.sin(), z]); }
    }
    n.pos.push([x, y, z0]); n.pos.push([x, y, z1]);
    let (u, o) = (2 * seg, 2 * seg + 1);
    for i in 0..seg {
        let j = (i + 1) % seg;
        n.idx.push([i, j, seg + j]); n.idx.push([i, seg + j, seg + i]);
        n.idx.push([u, j, i]); n.idx.push([o, seg + i, seg + j]);
    }
    n.ausrichten()
}

/// Flächen (in der Skizzenebene) um die Achse a→b drehen.
pub fn drehung(flaechen: &[Flaeche], a: P2, b: P2, winkel_grad: f64) -> Result<Netz, String> {
    let d = [b[0] - a[0], b[1] - a[1]];
    let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
    if l < 1e-9 { return Err("Drehachse hat keine Länge".into()); }
    let dir = [d[0] / l, d[1] / l];
    let mut senk = [-dir[1], dir[0]];
    // Seite der Achse wählen, auf der das Profil liegt
    let summe: f64 = flaechen.iter().flatten().flatten().map(|p| (p[0] - a[0]) * senk[0] + (p[1] - a[1]) * senk[1]).sum();
    if summe < 0.0 { senk = [-senk[0], -senk[1]]; }
    let w = winkel_grad.to_radians().clamp(1e-3, std::f64::consts::TAU);
    let voll = (w - std::f64::consts::TAU).abs() < 1e-6;
    // in Achs-Koordinaten (s entlang Achse, r Abstand); Teil auf der negativen Seite verwerfen
    let mut achsflaechen: Vec<Flaeche> = vec![];
    for fl in flaechen {
        let f2: Flaeche = fl.iter().map(|k| k.iter().map(|p| { let q = [p[0] - a[0], p[1] - a[1]]; [q[0] * dir[0] + q[1] * dir[1], q[0] * senk[0] + q[1] * senk[1]] }).collect()).collect();
        achsflaechen.push(f2);
    }
    let alle: Vec<Vec<P2>> = achsflaechen.into_iter().flatten().collect();
    let gross = 1e6;
    let halb: Vec<Vec<P2>> = vec![vec![[-gross, 0.0], [gross, 0.0], [gross, gross], [-gross, gross]]];
    use i_overlay::core::fill_rule::FillRule;
    use i_overlay::core::overlay_rule::OverlayRule;
    use i_overlay::float::single::SingleFloatOverlay;
    let mut geschnitten = alle.overlay(&halb, OverlayRule::Intersect, FillRule::EvenOdd);
    crate::profil::ausrichten(&mut geschnitten);
    if geschnitten.is_empty() { return Err("Profil liegt nicht neben der Drehachse".into()); }
    let r_max = geschnitten.iter().flatten().flatten().fold(0.0f64, |m, p| m.max(p[1]));
    let seg = ((crate::profil::segmente_fuer_radius(r_max, std::f64::consts::TAU) as f64 * w / std::f64::consts::TAU).ceil() as usize).max(3);
    let ringe = if voll { seg } else { seg + 1 };
    let ort = |s: f64, r: f64, t: f64| -> [f64; 3] {
        let (c, sn) = (t.cos(), t.sin());
        [a[0] + dir[0] * s + senk[0] * r * c, a[1] + dir[1] * s + senk[1] * r * c, r * sn]
    };
    let mut n = Netz::default();
    for fl in &geschnitten {
        // Indextabelle: Punkt k in Ring i
        let pts: Vec<P2> = fl.iter().flatten().cloned().collect();
        let mut tab = vec![vec![0usize; ringe]; pts.len()];
        for (k, p) in pts.iter().enumerate() {
            if p[1].abs() < 1e-9 {
                let id = n.pos.len(); n.pos.push(ort(p[0], 0.0, 0.0));
                for i in 0..ringe { tab[k][i] = id; }
            } else {
                for i in 0..ringe { tab[k][i] = n.pos.len(); n.pos.push(ort(p[0], p[1], w * i as f64 / seg as f64)); }
            }
        }
        let mut off = 0;
        for k in fl {
            let m = k.len();
            for i in 0..seg {
                let i2 = if voll { (i + 1) % seg } else { i + 1 };
                for e in 0..m {
                    let (p, q) = (off + e, off + (e + 1) % m);
                    let (a0, b0, b1, a1) = (tab[p][i], tab[q][i], tab[q][i2], tab[p][i2]);
                    for t in [[a0, b0, b1], [a0, b1, a1]] { if t[0] != t[1] && t[1] != t[2] && t[0] != t[2] { n.idx.push(t); } }
                }
            }
            off += m;
        }
        if !voll {
            for t in dreiecke(fl) {
                n.idx.push([tab[t[0]][0], tab[t[2]][0], tab[t[1]][0]]);
                n.idx.push([tab[t[0]][seg], tab[t[1]][seg], tab[t[2]][seg]]);
            }
        }
    }
    Ok(n.ausrichten())
}

// ---------- Boolesche Operationen ----------
pub fn zu_manifold(n: &Netz) -> Result<Manifold, String> {
    let pos: Vec<f64> = n.pos.iter().flat_map(|p| p.iter().cloned()).collect();
    let idx: Vec<usize> = n.idx.iter().flat_map(|t| t.iter().cloned()).collect();
    Manifold::new(&pos, &idx).map_err(|e| format!("Körper nicht geschlossen: {}", e))
}
pub fn von_manifold(m: &Manifold) -> Netz {
    let pos = m.ps.iter().map(|p| [p.x, p.y, p.z]).collect();
    let tails: Vec<usize> = m.hs.iter().map(|h| h.tail).collect();
    let idx = tails.chunks(3).map(|c| [c[0], c[1], c[2]]).collect();
    Netz { pos, idx }
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Op { Vereinigen, Abziehen, Schneiden }

pub fn boolesch(a: &Netz, b: &Netz, op: Op) -> Result<Netz, String> {
    if b.leer() { return Ok(if op == Op::Schneiden { Netz::default() } else { a.clone() }); }
    if a.leer() { return Ok(if op == Op::Vereinigen { b.clone() } else { Netz::default() }); }
    let ma = zu_manifold(a)?;
    let mb = zu_manifold(b)?;
    let o = match op { Op::Vereinigen => OpType::Add, Op::Abziehen => OpType::Subtract, Op::Schneiden => OpType::Intersect };
    let r = compute_boolean(&ma, &mb, o)?;
    Ok(von_manifold(&r))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn extrusion_und_bohrung() {
        let fl = crate::profil::flaechen(&[vec![[0.0, 0.0], [60.0, 0.0], [60.0, 40.0], [0.0, 40.0]]]);
        let k = extrusion(&fl, 0.0, 10.0);
        assert!((k.volumen() - 24000.0).abs() < 1e-6);
        let b = kegel(20.0, 20.0, -5.0, 15.0, 2.0, 2.0);
        let r = boolesch(&k, &b, Op::Abziehen).unwrap();
        assert!(r.volumen() < 24000.0 && r.volumen() > 23800.0, "{}", r.volumen());
    }
    #[test]
    fn drehung_voll() {
        let fl = crate::profil::flaechen(&[vec![[5.0, 0.0], [10.0, 0.0], [10.0, 20.0], [5.0, 20.0]]]);
        let n = drehung(&fl, [0.0, 0.0], [0.0, 1.0], 360.0).unwrap();
        let soll = std::f64::consts::PI * (100.0 - 25.0) * 20.0;
        assert!((n.volumen() - soll).abs() / soll < 0.01, "{} vs {}", n.volumen(), soll);
        zu_manifold(&n).unwrap();
    }
}
