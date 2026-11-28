//! Farben herauslösen: Bambu-/Prusa-Bemalung lesen und jede gemalte Fläche zu einem festen,
//! einzeln druckbaren Teil machen. Der Grundkörper bekommt dafür passende Taschen.
use crate::mesh::{Mesh, V3, add, cross, dot, len, mul, norm, sub};
use anyhow::{Result, bail};
use std::collections::{HashMap, HashSet};

/// Bemalte Oberfläche eines Teils (wie geladen), Filamente 1-basiert
#[derive(Clone, Default)]
pub struct Bemalung {
    pub teil: u32,
    /// Grundfarbe (größte Fläche)
    pub basis: u32,
    /// Oberfläche, fein zerlegt nach der Bemalung
    pub tris: Vec<([V3; 3], u32)>,
    /// eigenständige, unbemalte Körper in anderer Farbe (mehrteilige 3MF)
    pub koerper: Vec<(String, Mesh, u32)>,
    /// je Farbe: Flächen der zusammenhängenden Bereiche (mm²), für die Anzeige
    pub bereiche: Vec<(u32, Vec<f64>)>,
}

// ───────────────────────── Bemalung lesen ─────────────────────────

/// Ein Dreieck samt Bemalungscode (TriangleSelector-Format von PrusaSlicer/Bambu Studio) zerlegen.
/// `grund` = Filament für unbemalte Stellen. Bei gespiegelten Objekten liegt das Dreieck mit
/// vertauschter Reihenfolge vor – dann `gespiegelt` setzen.
pub fn dekodieren(t: [V3; 3], code: Option<&str>, grund: u32, gespiegelt: bool, out: &mut Vec<([V3; 3], u32)>) {
    let Some(code) = code.filter(|c| !c.is_empty()) else {
        out.push((t, grund));
        return;
    };
    let nib: Vec<u8> = code.bytes().rev().filter_map(|c| (c as char).to_digit(16).map(|d| d as u8)).collect();
    // Datei-Reihenfolge wiederherstellen
    let v = if gespiegelt { [t[0], t[2], t[1]] } else { t };
    let start = out.len();
    let mut i = 0usize;
    rek(&nib, &mut i, v, grund, out, 0);
    if gespiegelt {
        for e in &mut out[start..] {
            e.0.swap(1, 2);
        }
    }
}

fn mitte(a: V3, b: V3) -> V3 {
    mul(add(a, b), 0.5)
}

fn rek(nib: &[u8], i: &mut usize, v: [V3; 3], grund: u32, out: &mut Vec<([V3; 3], u32)>, tiefe: u32) {
    if *i >= nib.len() || tiefe > 24 {
        out.push((v, grund));
        return;
    }
    let code = nib[*i];
    *i += 1;
    let geteilt = (code & 3) as usize;
    if geteilt == 0 {
        let mut st = (code >> 2) as u32;
        if st == 3 {
            st = nib.get(*i).copied().unwrap_or(0) as u32 + 3;
            *i += 1;
        }
        out.push((v, if st == 0 { grund } else { st }));
        return;
    }
    let s = (code >> 2) as usize % 3;
    let w = [v[s], v[(s + 1) % 3], v[(s + 2) % 3]];
    let kinder: Vec<[V3; 3]> = match geteilt {
        1 => {
            let m = mitte(w[1], w[2]);
            vec![[w[0], w[1], m], [m, w[2], w[0]]]
        }
        2 => {
            let m01 = mitte(w[0], w[1]);
            let m02 = mitte(w[0], w[2]);
            vec![[w[0], m01, m02], [m01, w[1], m02], [w[1], w[2], m02]]
        }
        _ => {
            let m01 = mitte(w[0], w[1]);
            let m12 = mitte(w[1], w[2]);
            let m20 = mitte(w[2], w[0]);
            vec![[w[0], m01, m20], [m01, w[1], m12], [m12, w[2], m20], [m01, m12, m20]]
        }
    };
    // gespeichert in umgekehrter Reihenfolge der Kinder
    for k in (0..kinder.len()).rev() {
        rek(nib, i, kinder[k], grund, out, tiefe + 1);
    }
}

// ───────────────────────── Netz mit Nachbarschaft ─────────────────────────

fn key(p: V3) -> [u64; 3] {
    [p[0].to_bits(), p[1].to_bits(), p[2].to_bits()]
}

struct Netz {
    p: Vec<V3>,
    t: Vec<[usize; 3]>,
    f: Vec<u32>,
    /// gerichtete Kante → Dreieck
    kante: HashMap<(usize, usize), usize>,
}

impl Netz {
    fn neu(tris: &[([V3; 3], u32)]) -> Netz {
        let mut idx: HashMap<[u64; 3], usize> = HashMap::new();
        let mut p: Vec<V3> = Vec::new();
        let mut t = Vec::with_capacity(tris.len());
        let mut f = Vec::with_capacity(tris.len());
        for (tri, farbe) in tris {
            let mut k = [0usize; 3];
            for j in 0..3 {
                let n = p.len();
                k[j] = *idx.entry(key(tri[j])).or_insert_with(|| {
                    p.push(tri[j]);
                    n
                });
            }
            if k[0] != k[1] && k[1] != k[2] && k[0] != k[2] {
                t.push(k);
                f.push(*farbe);
            }
        }
        // T-Stellen schließen: wo ein Nachbar fein zerlegt ist, die Kante am Mittelpunkt teilen
        for _ in 0..40 {
            let kanten: HashSet<(usize, usize)> = t.iter().flat_map(|k| [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])]).collect();
            let mut nt = Vec::with_capacity(t.len());
            let mut nf = Vec::with_capacity(t.len());
            let mut geaendert = false;
            for (k, &farbe) in t.iter().zip(&f) {
                let mut fertig = false;
                for (x, y, z) in [(k[0], k[1], k[2]), (k[1], k[2], k[0]), (k[2], k[0], k[1])] {
                    if kanten.contains(&(y, x)) {
                        continue;
                    }
                    if let Some(&m) = idx.get(&key(mitte(p[x], p[y]))) {
                        if m != x && m != y && m != z {
                            nt.push([x, m, z]);
                            nt.push([m, y, z]);
                            nf.push(farbe);
                            nf.push(farbe);
                            fertig = true;
                            geaendert = true;
                            break;
                        }
                    }
                }
                if !fertig {
                    nt.push(*k);
                    nf.push(farbe);
                }
            }
            t = nt;
            f = nf;
            if !geaendert {
                break;
            }
        }
        let mut kante = HashMap::with_capacity(t.len() * 3);
        for (i, k) in t.iter().enumerate() {
            for (x, y) in [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])] {
                kante.insert((x, y), i);
            }
        }
        Netz { p, t, f, kante }
    }

    fn flaeche(&self, i: usize) -> f64 {
        let k = self.t[i];
        0.5 * len(cross(sub(self.p[k[1]], self.p[k[0]]), sub(self.p[k[2]], self.p[k[0]])))
    }

    fn nachbar(&self, x: usize, y: usize) -> Option<usize> {
        self.kante.get(&(y, x)).copied()
    }

    /// Zusammenhängende Bereiche gleicher Farbe (ohne `basis`)
    fn bereiche(&self, basis: u32) -> Vec<Vec<usize>> {
        let n = self.t.len();
        let mut g: Vec<usize> = (0..n).collect();
        fn wurzel(g: &mut [usize], mut i: usize) -> usize {
            while g[i] != i {
                g[i] = g[g[i]];
                i = g[i];
            }
            i
        }
        for i in 0..n {
            if self.f[i] == basis {
                continue;
            }
            let k = self.t[i];
            for (x, y) in [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])] {
                if let Some(j) = self.nachbar(x, y) {
                    if self.f[j] == self.f[i] {
                        let (a, b) = (wurzel(&mut g, i), wurzel(&mut g, j));
                        if a != b {
                            g[a] = b;
                        }
                    }
                }
            }
        }
        let mut grp: HashMap<usize, Vec<usize>> = HashMap::new();
        for i in 0..n {
            if self.f[i] != basis {
                let r = wurzel(&mut g, i);
                grp.entry(r).or_default().push(i);
            }
        }
        let mut v: Vec<Vec<usize>> = grp.into_values().collect();
        v.sort_by_key(|b| b[0]);
        v
    }

    /// Eckennormalen (winkelgewichtet)
    fn normalen(&self) -> Vec<V3> {
        let mut n = vec![[0.0; 3]; self.p.len()];
        for k in &self.t {
            let fn_ = norm(cross(sub(self.p[k[1]], self.p[k[0]]), sub(self.p[k[2]], self.p[k[0]])));
            for j in 0..3 {
                let a = self.p[k[j]];
                let e1 = norm(sub(self.p[k[(j + 1) % 3]], a));
                let e2 = norm(sub(self.p[k[(j + 2) % 3]], a));
                let w = dot(e1, e2).clamp(-1.0, 1.0).acos();
                n[k[j]] = add(n[k[j]], mul(fn_, w));
            }
        }
        n.into_iter().map(norm).collect()
    }
}

// ───────────────────────── Wandstärke messen ─────────────────────────

struct Gitter {
    min: V3,
    h: f64,
    zellen: HashMap<[i64; 3], Vec<usize>>,
}

impl Gitter {
    fn neu(n: &Netz, h: f64) -> Gitter {
        let mut min = [f64::MAX; 3];
        for p in &n.p {
            for k in 0..3 {
                min[k] = min[k].min(p[k]);
            }
        }
        let mut g = Gitter { min, h, zellen: HashMap::new() };
        for (i, k) in n.t.iter().enumerate() {
            let (mut lo, mut hi) = ([i64::MAX; 3], [i64::MIN; 3]);
            for &v in k {
                let c = g.zelle(n.p[v]);
                for a in 0..3 {
                    lo[a] = lo[a].min(c[a]);
                    hi[a] = hi[a].max(c[a]);
                }
            }
            for x in lo[0]..=hi[0] {
                for y in lo[1]..=hi[1] {
                    for z in lo[2]..=hi[2] {
                        g.zellen.entry([x, y, z]).or_default().push(i);
                    }
                }
            }
        }
        g
    }
    fn zelle(&self, p: V3) -> [i64; 3] {
        [0, 1, 2].map(|k| ((p[k] - self.min[k]) / self.h).floor() as i64)
    }
}

/// Abstand von Ecke `v` entlang `d` bis zur nächsten Wand (höchstens `l`)
fn strahl(n: &Netz, g: &Gitter, v: usize, d: V3, l: f64) -> f64 {
    let o = n.p[v];
    let e = add(o, mul(d, l));
    let (ca, cb) = (g.zelle(o), g.zelle(e));
    let mut best = l;
    let mut gesehen = HashSet::new();
    for x in ca[0].min(cb[0])..=ca[0].max(cb[0]) {
        for y in ca[1].min(cb[1])..=ca[1].max(cb[1]) {
            for z in ca[2].min(cb[2])..=ca[2].max(cb[2]) {
                let Some(liste) = g.zellen.get(&[x, y, z]) else { continue };
                for &ti in liste {
                    if !gesehen.insert(ti) {
                        continue;
                    }
                    let k = n.t[ti];
                    if k.contains(&v) {
                        continue;
                    }
                    let (a, b, c) = (n.p[k[0]], n.p[k[1]], n.p[k[2]]);
                    let e1 = sub(b, a);
                    let e2 = sub(c, a);
                    let pv = cross(d, e2);
                    let det = dot(e1, pv);
                    if det.abs() < 1e-12 {
                        continue;
                    }
                    let inv = 1.0 / det;
                    let tv = sub(o, a);
                    let u = dot(tv, pv) * inv;
                    if !(-1e-9..=1.0 + 1e-9).contains(&u) {
                        continue;
                    }
                    let q = cross(tv, e1);
                    let w = dot(d, q) * inv;
                    if w < -1e-9 || u + w > 1.0 + 1e-9 {
                        continue;
                    }
                    let t = dot(e2, q) * inv;
                    if t > 1e-6 && t < best {
                        best = t;
                    }
                }
            }
        }
    }
    best
}

// ───────────────────────── Übersicht ─────────────────────────

/// Bemalung eines Teils vorbereiten: Grundfarbe und Bereiche je Farbe bestimmen
pub fn vorbereiten(teil: u32, tris: Vec<([V3; 3], u32)>, koerper: Vec<(String, Mesh, u32)>) -> Bemalung {
    let n = Netz::neu(&tris);
    let mut fl: HashMap<u32, f64> = HashMap::new();
    for i in 0..n.t.len() {
        *fl.entry(n.f[i]).or_default() += n.flaeche(i);
    }
    let basis = fl.iter().max_by(|a, b| a.1.partial_cmp(b.1).unwrap()).map(|(k, _)| *k).unwrap_or(1);
    let mut je: HashMap<u32, Vec<f64>> = HashMap::new();
    for b in n.bereiche(basis) {
        let a: f64 = b.iter().map(|&i| n.flaeche(i)).sum();
        je.entry(n.f[b[0]]).or_default().push(a);
    }
    for (_, _, f) in &koerper {
        je.entry(*f).or_default();
    }
    let mut bereiche: Vec<(u32, Vec<f64>)> = je.into_iter().collect();
    for b in &mut bereiche {
        b.1.sort_by(|x, y| y.partial_cmp(x).unwrap());
    }
    bereiche.sort_by_key(|b| b.0);
    Bemalung { teil, basis, tris, koerper, bereiche }
}

// ───────────────────────── Herauslösen ─────────────────────────

pub struct Optionen {
    /// true: Farbteile mit Spiel zum Einstecken; false: passgenau als Teile eines Objekts (AMS)
    pub stecken: bool,
    pub tiefe: f64,
    pub spiel: f64,
    pub min_flaeche: f64,
    /// gleiche Farbe zu einem Teil zusammenfassen
    pub zusammen: bool,
}

pub struct Farbteil {
    pub farbe: u32,
    pub mesh: Mesh,
    /// mittlere Außennormale (Sichtseite)
    pub normale: V3,
    pub bereiche: usize,
}

pub struct Ergebnis {
    pub koerper: Mesh,
    pub basis: u32,
    pub teile: Vec<Farbteil>,
    /// Ecken, an denen die Tiefe wegen dünner Wand verringert wurde
    pub flacher: usize,
    pub weggelassen: usize,
}

pub fn herausloesen(b: &Bemalung, o: &Optionen) -> Result<Ergebnis> {
    let tiefe = o.tiefe.clamp(0.2, 20.0);
    let spiel = if o.stecken { o.spiel.clamp(0.0, 1.0) } else { 0.0 };
    let n = Netz::neu(&b.tris);
    let basis = b.basis;
    // Bereiche, zu kleine fallen dem Grundkörper zu
    let mut ber = n.bereiche(basis);
    let vorher = ber.len();
    ber.retain(|r| r.iter().map(|&i| n.flaeche(i)).sum::<f64>() >= o.min_flaeche.max(0.0));
    let weggelassen = vorher - ber.len();
    // Teile: je Bereich oder je Farbe
    let mut gruppen: Vec<(u32, Vec<Vec<usize>>)> = Vec::new();
    for r in ber {
        let f = n.f[r[0]];
        match gruppen.iter_mut().find(|g| o.zusammen && g.0 == f) {
            Some(g) => g.1.push(r),
            None => gruppen.push((f, vec![r])),
        }
    }
    if gruppen.is_empty() && b.koerper.is_empty() {
        bail!("Keine bemalten Bereiche gefunden (oder alle kleiner als die Mindestfläche).");
    }
    // Teil-Nummer je Dreieck (usize::MAX = Grundkörper)
    let mut gid = vec![usize::MAX; n.t.len()];
    for (g, (_, rs)) in gruppen.iter().enumerate() {
        for r in rs {
            for &i in r {
                gid[i] = g;
            }
        }
    }
    let raus = |i: usize| gid[i] != usize::MAX;

    // Tiefe je Ecke – an dünnen Wänden flacher, damit nichts durchbricht
    let nv = n.normalen();
    let mut beteiligt = vec![false; n.p.len()];
    for i in 0..n.t.len() {
        if raus(i) {
            for &v in &n.t[i] {
                beteiligt[v] = true;
            }
        }
    }
    let probe = tiefe / 0.45;
    let bb = {
        let mut m = Mesh::new();
        m.tris = n.t.iter().map(|k| [n.p[k[0]], n.p[k[1]], n.p[k[2]]]).collect();
        m.bbox()
    };
    let diag = len(bb.size()).max(1.0);
    let gitter = Gitter::neu(&n, (probe * 1.05).max(diag / 64.0));
    let mut innen = n.p.clone();
    let mut flacher = 0usize;
    for v in 0..n.p.len() {
        if !beteiligt[v] {
            continue;
        }
        let d = mul(nv[v], -1.0);
        let wand = strahl(&n, &gitter, v, d, probe);
        let t = tiefe.min(0.45 * wand);
        if t < tiefe - 1e-6 {
            flacher += 1;
        }
        innen[v] = add(n.p[v], mul(d, t));
    }

    // Grundkörper: unbemalte Oberfläche + Taschenboden + Taschenwände
    let mut koerper = Mesh::new();
    for (i, k) in n.t.iter().enumerate() {
        if !raus(i) {
            koerper.push(n.p[k[0]], n.p[k[1]], n.p[k[2]]);
            continue;
        }
        koerper.push(innen[k[0]], innen[k[1]], innen[k[2]]);
        for (x, y) in [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])] {
            if let Some(j) = n.nachbar(x, y) {
                if !raus(j) {
                    koerper.push(n.p[x], n.p[y], innen[y]);
                    koerper.push(n.p[x], innen[y], innen[x]);
                }
            }
        }
    }

    // Farbteile
    let mut teile = Vec::new();
    for (g, (farbe, rs)) in gruppen.iter().enumerate() {
        let tris: Vec<usize> = rs.iter().flatten().copied().collect();
        // Spiel: Rand-Ecken (zum Grundkörper hin) seitlich nach innen ziehen
        let mut rich: HashMap<usize, V3> = HashMap::new();
        let mut kurz: HashMap<usize, f64> = HashMap::new();
        if spiel > 0.0 {
            for &i in &tris {
                let k = n.t[i];
                let fnorm = norm(cross(sub(n.p[k[1]], n.p[k[0]]), sub(n.p[k[2]], n.p[k[0]])));
                for (x, y) in [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])] {
                    let l = len(sub(n.p[y], n.p[x]));
                    for v in [x, y] {
                        let e = kurz.entry(v).or_insert(f64::MAX);
                        *e = e.min(l);
                    }
                    let gegen_grund = n.nachbar(x, y).map(|j| !raus(j)).unwrap_or(false);
                    if gegen_grund {
                        let links = norm(cross(fnorm, sub(n.p[y], n.p[x])));
                        for v in [x, y] {
                            let e = rich.entry(v).or_insert([0.0; 3]);
                            *e = add(*e, links);
                        }
                    }
                }
            }
        }
        let schieb = |v: usize| -> V3 {
            match rich.get(&v) {
                Some(r) => {
                    let t = sub(*r, mul(nv[v], dot(*r, nv[v])));
                    let l = len(t);
                    if l < 1e-9 {
                        return [0.0; 3];
                    }
                    let s = spiel.min(0.4 * kurz.get(&v).copied().unwrap_or(spiel));
                    mul(t, s / l)
                }
                None => [0.0; 3],
            }
        };
        let mut m = Mesh::new();
        let mut nsum = [0.0; 3];
        let mut aussen: HashMap<usize, (V3, V3)> = HashMap::new();
        let mut punkt = |v: usize| -> (V3, V3) {
            *aussen.entry(v).or_insert_with(|| {
                let s = schieb(v);
                (add(n.p[v], s), add(innen[v], s))
            })
        };
        for &i in &tris {
            let k = n.t[i];
            let (a, b, c) = (punkt(k[0]), punkt(k[1]), punkt(k[2]));
            m.push(a.0, b.0, c.0);
            m.push(a.1, c.1, b.1);
            nsum = add(nsum, cross(sub(n.p[k[1]], n.p[k[0]]), sub(n.p[k[2]], n.p[k[0]])));
            for (x, y) in [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])] {
                let fremd = n.nachbar(x, y).map(|j| gid[j] != g).unwrap_or(true);
                if fremd {
                    let (px, py) = (punkt(x), punkt(y));
                    m.push(py.0, px.0, px.1);
                    m.push(py.0, px.1, py.1);
                }
            }
        }
        teile.push(Farbteil { farbe: *farbe, mesh: m, normale: norm(nsum), bereiche: rs.len() });
    }
    Ok(Ergebnis { koerper, basis, teile, flacher, weggelassen })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn geschlossen(m: &Mesh) -> bool {
        let mut k: HashMap<([u64; 3], [u64; 3]), i32> = HashMap::new();
        for t in &m.tris {
            for j in 0..3 {
                let (a, b) = (key(t[j]), key(t[(j + 1) % 3]));
                *k.entry((a, b)).or_default() += 1;
                *k.entry((b, a)).or_default() -= 1;
            }
        }
        k.values().all(|&v| v == 0)
    }

    /// Quader, Oberseite in 4×4 Dreieckspaare zerlegt, mittleres Feld bemalt (Filament 2)
    fn platte() -> Vec<([V3; 3], u32)> {
        let mut out = Vec::new();
        let (w, h) = (40.0, 6.0);
        let n = 4;
        let s = w / n as f64;
        for i in 0..n {
            for j in 0..n {
                let (x0, y0) = (i as f64 * s, j as f64 * s);
                let f = if (1..3).contains(&i) && (1..3).contains(&j) { 2 } else { 1 };
                let a = [x0, y0, h];
                let b = [x0 + s, y0, h];
                let c = [x0 + s, y0 + s, h];
                let d = [x0, y0 + s, h];
                out.push(([a, b, c], f));
                out.push(([a, c, d], f));
            }
        }
        // Unterseite und Seiten, passend am Rand unterteilt
        for i in 0..n {
            for j in 0..n {
                let (x0, y0) = (i as f64 * s, j as f64 * s);
                let a = [x0, y0, 0.0];
                let b = [x0 + s, y0, 0.0];
                let c = [x0 + s, y0 + s, 0.0];
                let d = [x0, y0 + s, 0.0];
                out.push(([a, c, b], 1));
                out.push(([a, d, c], 1));
            }
        }
        for i in 0..n {
            let (u0, u1) = (i as f64 * s, (i + 1) as f64 * s);
            // y = 0
            out.push(([[u0, 0.0, 0.0], [u1, 0.0, 0.0], [u1, 0.0, h]], 1));
            out.push(([[u0, 0.0, 0.0], [u1, 0.0, h], [u0, 0.0, h]], 1));
            // y = w
            out.push(([[u1, w, 0.0], [u0, w, 0.0], [u0, w, h]], 1));
            out.push(([[u1, w, 0.0], [u0, w, h], [u1, w, h]], 1));
            // x = 0
            out.push(([[0.0, u1, 0.0], [0.0, u0, 0.0], [0.0, u0, h]], 1));
            out.push(([[0.0, u1, 0.0], [0.0, u0, h], [0.0, u1, h]], 1));
            // x = w
            out.push(([[w, u0, 0.0], [w, u1, 0.0], [w, u1, h]], 1));
            out.push(([[w, u0, 0.0], [w, u1, h], [w, u0, h]], 1));
        }
        out
    }

    #[test]
    fn grundplatte_ist_dicht() {
        let mut m = Mesh::new();
        for (t, _) in platte() {
            m.push(t[0], t[1], t[2]);
        }
        assert!(geschlossen(&m));
        assert!(m.volume() > 0.0);
    }

    #[test]
    fn feld_wird_teil_mit_tasche() {
        let b = vorbereiten(1, platte(), vec![]);
        assert_eq!(b.basis, 1);
        assert_eq!(b.bereiche.len(), 1);
        for stecken in [false, true] {
            let e = herausloesen(&b, &Optionen { stecken, tiefe: 1.5, spiel: 0.15, min_flaeche: 1.0, zusammen: false }).unwrap();
            assert_eq!(e.teile.len(), 1);
            assert!(geschlossen(&e.koerper), "Grundkörper offen");
            assert!(geschlossen(&e.teile[0].mesh), "Farbteil offen");
            let vt = e.teile[0].mesh.volume();
            let soll = 20.0 * 20.0 * 1.5;
            if stecken {
                assert!(vt < soll && vt > soll * 0.9, "Volumen {vt}");
            } else {
                assert!((vt - soll).abs() < 1e-6, "Volumen {vt}");
            }
            let vk = e.koerper.volume();
            assert!((vk - (40.0 * 40.0 * 6.0 - soll)).abs() < 1e-6, "Körper {vk}");
            assert!(e.teile[0].normale[2] > 0.99);
        }
    }

    #[test]
    fn bemalung_dekodieren() {
        // Wurzel geteilt in 4 (Code 3, Seite 0), Kinder rückwärts: 4. Kind Filament 2 (Code 8), Rest unbemalt
        // Nibbles in Lesereihenfolge: 3, 0, 0, 0, 8 → Zeichenkette rückwärts
        let s: String = [3u8, 8, 0, 0, 0].iter().rev().map(|d| format!("{d:X}")).collect();
        let mut out = Vec::new();
        dekodieren([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]], Some(&s), 1, false, &mut out);
        assert_eq!(out.len(), 4);
        // zuerst gelesen wird das letzte Kind: das mittlere Dreieck (m01, m12, m20)
        assert_eq!(out[0].1, 2);
        assert_eq!(out[0].0, [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]);
        assert!(out[1..].iter().all(|e| e.1 == 1));
        // Zustand ≥ 3: Code C + Zusatz-Nibble
        let mut out = Vec::new();
        dekodieren([[0.0; 3], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], Some("2C"), 1, false, &mut out);
        assert_eq!(out[0].1, 5);
    }

    #[test]
    fn halbe_bemalung_t_stellen() {
        // Zwei Dreiecke eines Quadrats; eines in 4 zerlegt (mittleres bemalt) – die Nachbarkante bekommt einen T-Punkt
        let s: String = [3u8, 8, 0, 0, 0].iter().rev().map(|d| format!("{d:X}")).collect();
        let mut out = Vec::new();
        let (a, b, c, d) = ([0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [0.0, 2.0, 0.0]);
        dekodieren([a, b, c], Some(&s), 1, false, &mut out);
        dekodieren([a, c, d], None, 1, false, &mut out);
        let n = Netz::neu(&out);
        // Kante a–c ist bei Dreieck 2 jetzt am Mittelpunkt geteilt
        assert_eq!(n.t.len(), 6);
        let rand = n.t.iter().flat_map(|k| [(k[0], k[1]), (k[1], k[2]), (k[2], k[0])]).filter(|&(x, y)| n.nachbar(x, y).is_none()).count();
        assert_eq!(rand, 6); // nur der Quadratrand (4 Kanten, zwei davon geteilt)
    }
}
