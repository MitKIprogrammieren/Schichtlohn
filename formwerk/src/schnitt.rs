//! Teilen nach Art von ModelSplitter: freie Schnittebenen, örtliche Schnitte (Band, Bemalen),
//! Verbinder in sechs Formen, eingravierte Fugennummern, Rückgängig, Auto-Zerlegen fürs Druckbett.
use crate::export::{self, PlatePart};
use crate::mesh::{self, Mesh, V3, add, cross, dot, mul, norm, sub};
use crate::section::{self, P2, Poly, dist_to_ring, point_in_ring, push_facing, ring_area, to3};
use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Instant;

// ───────────────────────── Rahmen: Schnittebene als z = konst. ─────────────────────────

#[derive(Clone, Copy, Debug)]
pub struct Rahmen {
    u: V3,
    v: V3,
    n: V3,
}

impl Rahmen {
    pub fn neu(n: V3) -> Self {
        let n = norm(n);
        let a = if n[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
        let u = norm(cross(a, n));
        let v = cross(n, u);
        Rahmen { u, v, n }
    }
    fn hin(&self, p: V3) -> V3 {
        [dot(p, self.u), dot(p, self.v), dot(p, self.n)]
    }
    fn her(&self, q: V3) -> V3 {
        add(add(mul(self.u, q[0]), mul(self.v, q[1])), mul(self.n, q[2]))
    }
    fn netz_hin(&self, m: &Mesh) -> Mesh {
        Mesh { tris: m.tris.iter().map(|t| t.map(|p| self.hin(p))).collect() }
    }
    fn netz_her(&self, m: &Mesh) -> Mesh {
        Mesh { tris: m.tris.iter().map(|t| t.map(|p| self.her(p))).collect() }
    }
}

// ───────────────────────── Schnittschleifen mit Dreiecken ─────────────────────────

struct Schleife {
    pts: Vec<P2>,
    tris: Vec<usize>,
}

fn kp(p: P2) -> (i64, i64) {
    ((p[0] * 1e5).round() as i64, (p[1] * 1e5).round() as i64)
}

/// Schleifen der Ebene z = val (Netz im Rahmen). Zusätzlich winzige Segmente (Punkt, Dreieck).
fn schleifen(m: &Mesh, val: f64) -> (Vec<Schleife>, Vec<(P2, usize)>) {
    let mut segs: Vec<(P2, P2, usize)> = Vec::new();
    let mut winzig = Vec::new();
    for (i, t) in m.tris.iter().enumerate() {
        let d = [t[0][2] - val, t[1][2] - val, t[2][2] - val];
        let pos = d.iter().filter(|x| **x > 0.0).count();
        if pos == 0 || pos == 3 {
            continue;
        }
        let mut pts = Vec::with_capacity(2);
        for k in 0..3 {
            let j = (k + 1) % 3;
            if (d[k] > 0.0) != (d[j] > 0.0) {
                pts.push(section::edge_point(t[k], t[j], 2, val));
            }
        }
        if pts.len() != 2 {
            continue;
        }
        let nrm = cross(sub(t[1], t[0]), sub(t[2], t[0]));
        let dir = cross(nrm, [0.0, 0.0, 1.0]);
        let (a, b) = if dot(sub(pts[1], pts[0]), dir) >= 0.0 { (pts[0], pts[1]) } else { (pts[1], pts[0]) };
        let (a2, b2) = ([a[0], a[1]], [b[0], b[1]]);
        if kp(a2) == kp(b2) {
            winzig.push((a2, i));
        } else {
            segs.push((a2, b2, i));
        }
    }
    let mut by_start: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
    for (i, s) in segs.iter().enumerate() {
        by_start.entry(kp(s.0)).or_default().push(i);
    }
    let mut used = vec![false; segs.len()];
    let mut out = Vec::new();
    for start in 0..segs.len() {
        if used[start] {
            continue;
        }
        used[start] = true;
        let mut pts = vec![segs[start].0];
        let mut tris = vec![segs[start].2];
        let first = kp(segs[start].0);
        let mut end = segs[start].1;
        loop {
            if kp(end) == first {
                break;
            }
            let next = by_start.get(&kp(end)).and_then(|v| v.iter().copied().find(|i| !used[*i]));
            match next {
                Some(i) => {
                    used[i] = true;
                    pts.push(segs[i].0);
                    tris.push(segs[i].2);
                    end = segs[i].1;
                }
                None => break,
            }
        }
        out.push(Schleife { pts, tris });
    }
    (out, winzig)
}

/// Wo geschnitten wird
#[derive(Clone, Copy, Debug)]
pub enum Ort {
    /// ganze Ebene, alle Körper
    Alle,
    /// Fläche, in der der Punkt liegt (z. B. Mitte einer bemalten Naht)
    Innen(P2),
    /// Fläche, deren Rand durch den Punkt geht (Band: Klick auf die Oberfläche)
    Rand(P2),
    /// alle Flächen, die eine gezogene Linie überquert: Start a, Richtung e, Blickrichtung d (in der Ebene)
    Streifen(P2, P2, P2),
}

/// Ort aus der Anfrage bauen (im Rahmen)
fn ort_bauen(rf: &Rahmen, q2: P2, art: &str, linie: Option<[V3; 3]>) -> Ort {
    match (art, linie) {
        ("rand", _) => Ort::Rand(q2),
        ("innen", _) => Ort::Innen(q2),
        ("linie", Some([a, b, d])) => {
            let (a, b, d) = (rf.hin(a), rf.hin(b), rf.hin(d));
            Ort::Streifen([a[0], a[1]], [b[0] - a[0], b[1] - a[1]], [d[0], d[1]])
        }
        _ => Ort::Alle,
    }
}

struct Wahl {
    polys: Vec<Poly>,
    tris: HashSet<usize>,
}

fn waehlen(sl: &[Schleife], winzig: &[(P2, usize)], ort: Ort) -> Option<Wahl> {
    let idx: Vec<usize> = (0..sl.len()).filter(|&i| sl[i].pts.len() >= 3 && ring_area(&sl[i].pts).abs() > 1e-4).collect();
    if idx.is_empty() {
        return None;
    }
    let n = idx.len();
    let area: Vec<f64> = idx.iter().map(|&i| ring_area(&sl[i].pts).abs()).collect();
    let mut depth = vec![0usize; n];
    let mut parent: Vec<Option<usize>> = vec![None; n];
    for a in 0..n {
        let p = sl[idx[a]].pts[0];
        for b in 0..n {
            if a != b && area[b] > area[a] && point_in_ring(p, &sl[idx[b]].pts) {
                depth[a] += 1;
                if parent[a].is_none_or(|q| area[b] < area[q]) {
                    parent[a] = Some(b);
                }
            }
        }
    }
    if let Ort::Alle = ort {
        let polys = section::loops_to_polys(idx.iter().map(|&i| sl[i].pts.clone()).collect());
        let mut tris: HashSet<usize> = sl.iter().flat_map(|s| s.tris.iter().copied()).collect();
        tris.extend(winzig.iter().map(|w| w.1));
        return Some(Wahl { polys, tris });
    }
    if let Ort::Streifen(a, e, d) = ort {
        let det = e[0] * d[1] - e[1] * d[0];
        let s_von = |p: P2| ((p[0] - a[0]) * d[1] - (p[1] - a[1]) * d[0]) / det;
        if det.abs() < 1e-9 {
            return waehlen(sl, winzig, Ort::Alle);
        }
        let trifft = |k: usize| {
            let (mut lo, mut hi) = (f64::MAX, f64::MIN);
            for p in &sl[idx[k]].pts {
                let v = s_von(*p);
                lo = lo.min(v);
                hi = hi.max(v);
            }
            hi >= 0.0 && lo <= 1.0
        };
        let aussen: Vec<usize> = (0..n).filter(|&k| depth[k] % 2 == 0 && trifft(k)).collect();
        if aussen.is_empty() {
            return None;
        }
        let mut polys = Vec::new();
        let mut tris: HashSet<usize> = HashSet::new();
        for &o in &aussen {
            let holes: Vec<usize> = (0..n).filter(|&k| parent[k] == Some(o) && depth[k] == depth[o] + 1).collect();
            polys.push(Poly { outer: sl[idx[o]].pts.clone(), holes: holes.iter().map(|&k| sl[idx[k]].pts.clone()).collect() });
            tris.extend(sl[idx[o]].tris.iter().copied());
            for &k in &holes {
                tris.extend(sl[idx[k]].tris.iter().copied());
            }
        }
        for (p, t) in winzig {
            if polys.iter().any(|q| dist_to_ring(*p, &q.outer) < 1e-3 || q.holes.iter().any(|h| dist_to_ring(*p, h) < 1e-3)) {
                tris.insert(*t);
            }
        }
        return Some(Wahl { polys, tris });
    }
    let (q, innen) = match ort {
        Ort::Innen(q) => (q, true),
        Ort::Rand(q) => (q, false),
        _ => unreachable!(),
    };
    let mut o: Option<usize> = None;
    if innen {
        o = (0..n).filter(|&k| depth[k] % 2 == 0 && point_in_ring(q, &sl[idx[k]].pts)).min_by(|a, b| area[*a].partial_cmp(&area[*b]).unwrap());
    }
    if o.is_none() {
        let k = (0..n).min_by(|a, b| dist_to_ring(q, &sl[idx[*a]].pts).partial_cmp(&dist_to_ring(q, &sl[idx[*b]].pts)).unwrap())?;
        o = Some(if depth[k] % 2 == 1 { parent[k].unwrap_or(k) } else { k });
    }
    let o = o?;
    let holes: Vec<usize> = (0..n).filter(|&k| parent[k] == Some(o) && depth[k] == depth[o] + 1).collect();
    let poly = Poly { outer: sl[idx[o]].pts.clone(), holes: holes.iter().map(|&k| sl[idx[k]].pts.clone()).collect() };
    let mut tris: HashSet<usize> = sl[idx[o]].tris.iter().copied().collect();
    for &k in &holes {
        tris.extend(sl[idx[k]].tris.iter().copied());
    }
    for (p, t) in winzig {
        if dist_to_ring(*p, &poly.outer) < 1e-3 || poly.holes.iter().any(|h| dist_to_ring(*p, h) < 1e-3) {
            tris.insert(*t);
        }
    }
    Some(Wahl { polys: vec![poly], tris })
}

// ───────────────────────── Verbinder ─────────────────────────

#[derive(Deserialize, Clone, Debug)]
#[serde(default)]
pub struct Verbindung {
    /// fest | lose | magnet | steck | keine
    pub art: String,
    /// rund | eckig | kegel | kreuz | stern | sechs
    pub form: String,
    /// Durchmesser in mm, 0 = automatisch
    pub d: f64,
    /// Spiel in mm
    pub spiel: f64,
    /// Anzahl je Fuge, 0 = automatisch
    pub anzahl: usize,
    pub magnet_d: f64,
    pub magnet_h: f64,
    /// Fugennummern eingravieren
    pub nummern: bool,
}

impl Default for Verbindung {
    fn default() -> Self {
        Verbindung { art: "fest".into(), form: "rund".into(), d: 0.0, spiel: 0.15, anzahl: 0, magnet_d: 6.0, magnet_h: 3.0, nummern: true }
    }
}

/// Umriss einer Zapfenform mit Radius r, um g vergrößert (Spiel)
fn form_ring(form: &str, c: P2, r: f64, g: f64) -> Vec<P2> {
    let rot = |pts: Vec<P2>| -> Vec<P2> {
        let (s, k) = 0.003f64.sin_cos();
        pts.into_iter().map(|q| [c[0] + q[0] * k - q[1] * s, c[1] + q[0] * s + q[1] * k]).collect()
    };
    match form {
        "eckig" | "kegel" => {
            let h = r + g;
            rot(vec![[-h, -h], [h, -h], [h, h], [-h, h]])
        }
        "kreuz" => {
            let a = r + g;
            let w = r * 0.38 + g;
            rot(vec![[w, -a], [w, -w], [a, -w], [a, w], [w, w], [w, a], [-w, a], [-w, w], [-a, w], [-a, -w], [-w, -w], [-w, -a]])
        }
        "stern" => {
            let mut v = Vec::new();
            for i in 0..10 {
                let rr = if i % 2 == 0 { r + g } else { r * 0.5 + g };
                let a = std::f64::consts::FRAC_PI_2 + i as f64 * std::f64::consts::PI / 5.0;
                v.push([rr * a.cos(), rr * a.sin()]);
            }
            rot(v)
        }
        "sechs" => {
            let rr = r + g * 1.155;
            rot((0..6).map(|i| {
                let a = i as f64 * std::f64::consts::PI / 3.0;
                [rr * a.cos(), rr * a.sin()]
            })
            .collect())
        }
        _ => section::circle(c, r + g, 32),
    }
}

/// Größter Abstand der Form vom Mittelpunkt
fn form_ausdehnung(form: &str, r: f64) -> f64 {
    match form {
        "eckig" | "kegel" => r * 1.415,
        "kreuz" => r * 1.07,
        _ => r,
    }
}

fn form_name(form: &str) -> &'static str {
    match form {
        "eckig" => "Vierkant",
        "kegel" => "Kegel-Vierkant",
        "kreuz" => "Kreuz",
        "stern" => "Stern",
        "sechs" => "Sechskant",
        _ => "rund",
    }
}

#[derive(Clone)]
struct Merkmal {
    center: P2,
    ring_lo: Vec<P2>,
    ring_hi: Vec<P2>,
    /// > 0 Tasche, < 0 Zapfen; Länge
    ext_lo: f64,
    ext_hi: f64,
    es_lo: f64,
    es_hi: f64,
    ausdehnung: f64,
}

/// Größter Randabstand innerhalb der Fläche
fn innen_radius(poly: &Poly) -> f64 {
    let (mn, mx) = poly.bbox();
    let step = ((mx[0] - mn[0]).max(mx[1] - mn[1]) / 40.0).max(0.3);
    let mut best: f64 = 0.0;
    let mut y = mn[1] + step * 0.5;
    while y < mx[1] {
        let mut x = mn[0] + step * 0.5;
        while x < mx[0] {
            if poly.contains([x, y]) {
                best = best.max(poly.boundary_dist([x, y]));
            }
            x += step;
        }
        y += step;
    }
    best
}

fn stellen(poly: &Poly, clear: f64, want: usize) -> Vec<P2> {
    let (mn, mx) = poly.bbox();
    let span = (mx[0] - mn[0]).max(mx[1] - mn[1]);
    let step = (span / 40.0).max(0.3);
    let mut cands: Vec<(f64, P2)> = Vec::new();
    let mut y = mn[1] + step * 0.5;
    while y < mx[1] {
        let mut x = mn[0] + step * 0.5;
        while x < mx[0] {
            let q = [x, y];
            if poly.contains(q) {
                let d = poly.boundary_dist(q);
                if d >= clear {
                    cands.push((d, q));
                }
            }
            x += step;
        }
        y += step;
    }
    cands.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    let min_gap = (clear * 2.6).max(span / (want as f64 + 1.0));
    let mut chosen: Vec<P2> = Vec::new();
    for (_, q) in &cands {
        if chosen.len() >= want {
            break;
        }
        if chosen.iter().all(|c| ((c[0] - q[0]).powi(2) + (c[1] - q[1]).powi(2)).sqrt() >= min_gap) {
            chosen.push(*q);
        }
    }
    // weniger Platz als gewünscht: mit kleinerem Abstand nachfüllen
    if chosen.len() < want {
        for (_, q) in &cands {
            if chosen.len() >= want {
                break;
            }
            if chosen.iter().all(|c| ((c[0] - q[0]).powi(2) + (c[1] - q[1]).powi(2)).sqrt() >= clear * 2.2) {
                chosen.push(*q);
            }
        }
    }
    chosen
}

/// Abstand von der Schnittebene bis zur nächsten Oberfläche entlang ±z (s = Richtung)
fn strahl(m: &Mesh, q: P2, val: f64, s: f64) -> f64 {
    let mut best = f64::INFINITY;
    for t in &m.tris {
        let (a, b, c) = (t[0], t[1], t[2]);
        let det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
        if det.abs() < 1e-12 {
            continue;
        }
        let l1 = ((q[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (q[1] - a[1])) / det;
        let l2 = ((b[0] - a[0]) * (q[1] - a[1]) - (q[0] - a[0]) * (b[1] - a[1])) / det;
        if l1 < -1e-9 || l2 < -1e-9 || l1 + l2 > 1.0 + 1e-9 {
            continue;
        }
        let z = a[2] + l1 * (b[2] - a[2]) + l2 * (c[2] - a[2]);
        let d = (z - val) * s;
        if d > 1e-6 && d < best {
            best = d;
        }
    }
    best
}

fn zapfen_planen(poly: &Poly, vb: &Verbindung, lo: &Mesh, hi: &Mesh, val: f64) -> (Vec<Merkmal>, Vec<Mesh>, Option<String>) {
    if vb.art == "keine" {
        return (vec![], vec![], None);
    }
    let ir = innen_radius(poly);
    let g = vb.spiel.clamp(0.0, 1.0);
    let magnet = vb.art == "magnet";
    let r = if magnet { vb.magnet_d.max(1.0) / 2.0 + g.max(0.1) } else if vb.d > 0.0 { vb.d / 2.0 } else { (ir * 0.28).clamp(1.5, 5.0) };
    let form = if magnet { "rund" } else { vb.form.as_str() };
    let ext = form_ausdehnung(form, r) + g + 1.2;
    if ir < ext {
        return (vec![], vec![], Some("Schnittfläche zu schmal für Verbinder".into()));
    }
    let want = if vb.anzahl > 0 { vb.anzahl.min(12) } else { ((poly.area() / 2500.0).sqrt().ceil() as usize).clamp(1, 6) };
    let spots = stellen(poly, ext, want);
    let mut mm = Vec::new();
    let mut lose = Vec::new();
    let mut zu_duenn = false;
    let len0 = (2.0 * r + 3.0).clamp(4.0, 14.0);
    for c in spots {
        let av_lo = strahl(lo, c, val, -1.0);
        let av_hi = strahl(hi, c, val, 1.0);
        let m = match vb.art.as_str() {
            "magnet" => {
                let dep = vb.magnet_h.max(0.5) + 0.2;
                if av_lo < dep + 0.8 || av_hi < dep + 0.8 {
                    zu_duenn = true;
                    continue;
                }
                let ring = section::circle(c, r, 32);
                Merkmal { center: c, ring_lo: ring.clone(), ring_hi: ring, ext_lo: dep, ext_hi: dep, es_lo: 1.0, es_hi: 1.0, ausdehnung: r }
            }
            "lose" => {
                let dep = len0.min(av_lo - 1.5).min(av_hi - 1.5);
                if dep < 2.5 {
                    zu_duenn = true;
                    continue;
                }
                let ring = form_ring(form, c, r, g);
                let pin = form_ring(form, [0.0, 0.0], r, 0.0);
                lose.push(export::extrude(&[Poly { outer: pin, holes: vec![] }], 2.0 * dep, &|q, z| [q[0], q[1], z]));
                Merkmal { center: c, ring_lo: ring.clone(), ring_hi: ring, ext_lo: dep + 0.3, ext_hi: dep + 0.3, es_lo: 1.0, es_hi: 1.0, ausdehnung: form_ausdehnung(form, r) + g }
            }
            _ => {
                // fest / steck: Zapfen am unteren Teil, Tasche im oberen
                let steck = vb.art == "steck";
                let gg = if steck { g * 0.5 } else { g };
                let len = len0.min(av_hi - 1.2 - 0.4);
                if len < 2.5 {
                    zu_duenn = true;
                    continue;
                }
                let k = if form == "kegel" { 0.6 } else if steck { 0.92 } else { 1.0 };
                let es_hi = (r * k + gg) / (r + gg);
                Merkmal {
                    center: c,
                    ring_lo: form_ring(form, c, r, 0.0),
                    ring_hi: form_ring(form, c, r, gg),
                    ext_lo: -len,
                    ext_hi: len + 0.4,
                    es_lo: k,
                    es_hi,
                    ausdehnung: form_ausdehnung(form, r) + gg,
                }
            }
        };
        mm.push(m);
    }
    let hinweis = if mm.is_empty() && zu_duenn { Some("Teil zu dünn für Verbinder".into()) } else { None };
    (mm, lose, hinweis)
}

// ───────────────────────── Nummern ─────────────────────────

/// Ziffern im Siebensegment-Stil als Flächen, zentriert um (0,0)
fn ziffern(text: &str, h: f64) -> (Vec<Poly>, f64) {
    use geo::BooleanOps;
    use geo::MultiPolygon;
    let w = 0.56 * h;
    let t = 0.18 * h;
    let gap = 0.3 * h;
    let n = text.chars().count().max(1);
    let total = n as f64 * w + (n as f64 - 1.0) * gap;
    let rect = |x0: f64, y0: f64, x1: f64, y1: f64| Poly { outer: vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]], holes: vec![] };
    let mut out = Vec::new();
    for (i, ch) in text.chars().enumerate() {
        let segs = match ch {
            '0' => "abcdef",
            '1' => "bc",
            '2' => "abged",
            '3' => "abgcd",
            '4' => "fgbc",
            '5' => "afgcd",
            '6' => "afgedc",
            '7' => "abc",
            '8' => "abcdefg",
            '9' => "abcdfg",
            _ => "",
        };
        let x = i as f64 * (w + gap) - total / 2.0;
        let y = -h / 2.0;
        let mut acc = MultiPolygon::<f64>::new(vec![]);
        for s in segs.chars() {
            let r = match s {
                'a' => rect(x, y + h - t, x + w, y + h),
                'd' => rect(x, y, x + w, y + t),
                'g' => rect(x, y + h / 2.0 - t / 2.0, x + w, y + h / 2.0 + t / 2.0),
                'f' => rect(x, y + h / 2.0 - t / 2.0, x + t, y + h),
                'b' => rect(x + w - t, y + h / 2.0 - t / 2.0, x + w, y + h),
                'e' => rect(x, y, x + t, y + h / 2.0 + t / 2.0),
                _ => rect(x + w - t, y, x + w, y + h / 2.0 + t / 2.0),
            };
            acc = acc.union(&MultiPolygon::new(vec![r.to_geo()]));
        }
        out.extend(section::multi_to_polys(&acc));
    }
    (out, total)
}

/// Platz für die Nummer suchen (weit weg vom Rand und von Verbindern)
fn nummer_platz(poly: &Poly, mm: &[Merkmal], halb: f64) -> Option<P2> {
    let (mn, mx) = poly.bbox();
    let step = ((mx[0] - mn[0]).max(mx[1] - mn[1]) / 40.0).max(0.3);
    let mut best: Option<(f64, P2)> = None;
    let mut y = mn[1] + step * 0.5;
    while y < mx[1] {
        let mut x = mn[0] + step * 0.5;
        while x < mx[0] {
            let q = [x, y];
            if poly.contains(q) {
                let mut s = poly.boundary_dist(q) - halb;
                for m in mm {
                    s = s.min(((q[0] - m.center[0]).powi(2) + (q[1] - m.center[1]).powi(2)).sqrt() - m.ausdehnung - halb);
                }
                if s > 0.6 && best.is_none_or(|b| s > b.0) {
                    best = Some((s, q));
                }
            }
            x += step;
        }
        y += step;
    }
    best.map(|b| b.1)
}

/// Vertiefung (Gravur) mit beliebigem Umriss. s = Richtung ins Teil hinein.
fn gravur(m: &mut Mesh, g: &Poly, val: f64, s: f64, tiefe: f64) {
    let boden = val + s * tiefe;
    for tri in g.triangulate() {
        push_facing(m, to3(tri[0], 2, boden), to3(tri[1], 2, boden), to3(tri[2], 2, boden), [0.0, 0.0, -s]);
    }
    let mut rings = vec![&g.outer];
    rings.extend(g.holes.iter());
    for r in rings {
        let n = r.len();
        for i in 0..n {
            let (a, b) = (r[i], r[(i + 1) % n]);
            let e = [b[0] - a[0], b[1] - a[1]];
            let l = (e[0] * e[0] + e[1] * e[1]).sqrt().max(1e-12);
            let perp = [-e[1] / l, e[0] / l];
            let mid = [(a[0] + b[0]) * 0.5 + perp[0] * 1e-3, (a[1] + b[1]) * 0.5 + perp[1] * 1e-3];
            let dir = if g.contains(mid) { perp } else { [-perp[0], -perp[1]] };
            let want = [dir[0], dir[1], 0.0];
            let (a0, b0, a1, b1) = (to3(a, 2, val), to3(b, 2, val), to3(a, 2, boden), to3(b, 2, boden));
            push_facing(m, a0, b0, b1, want);
            push_facing(m, a0, b1, a1, want);
        }
    }
}

/// Schnittflächen mit Verbindern und Nummer schließen
fn deckel(lo: &mut Mesh, hi: &mut Mesh, poly: &Poly, val: f64, mm: &[Merkmal], glyph: Option<(&[Poly], P2)>) {
    let mut plo = vec![poly.clone()];
    let mut phi = vec![poly.clone()];
    for m in mm {
        plo[0].holes.push(m.ring_lo.clone());
        phi[0].holes.push(m.ring_hi.clone());
    }
    let mut g_lo: Vec<Poly> = Vec::new();
    let mut g_hi: Vec<Poly> = Vec::new();
    if let Some((gl, at)) = glyph {
        for g in gl {
            let mv = |r: &Vec<P2>, sx: f64| r.iter().map(|p| [at[0] + p[0] * sx, at[1] + p[1]]).collect::<Vec<P2>>();
            g_lo.push(Poly { outer: mv(&g.outer, 1.0), holes: g.holes.iter().map(|h| mv(h, 1.0)).collect() });
            // oben spiegeln, damit die Zahl von außen lesbar ist
            g_hi.push(Poly { outer: mv(&g.outer, -1.0), holes: g.holes.iter().map(|h| mv(h, -1.0)).collect() });
        }
        for g in &g_lo {
            plo[0].holes.push(g.outer.clone());
            plo.extend(g.holes.iter().map(|h| Poly { outer: h.clone(), holes: vec![] }));
        }
        for g in &g_hi {
            phi[0].holes.push(g.outer.clone());
            phi.extend(g.holes.iter().map(|h| Poly { outer: h.clone(), holes: vec![] }));
        }
    }
    for p in &plo {
        for tri in p.triangulate() {
            push_facing(lo, to3(tri[0], 2, val), to3(tri[1], 2, val), to3(tri[2], 2, val), [0.0, 0.0, 1.0]);
        }
    }
    for p in &phi {
        for tri in p.triangulate() {
            push_facing(hi, to3(tri[0], 2, val), to3(tri[1], 2, val), to3(tri[2], 2, val), [0.0, 0.0, -1.0]);
        }
    }
    for m in mm {
        // unten: Tasche geht nach -z, Zapfen nach +z
        let plug = m.ext_lo < 0.0;
        section::feature(lo, &m.ring_lo, m.center, 2, val, if plug { 1.0 } else { -1.0 }, m.ext_lo.abs(), m.es_lo, plug);
        let plug = m.ext_hi < 0.0;
        section::feature(hi, &m.ring_hi, m.center, 2, val, if plug { -1.0 } else { 1.0 }, m.ext_hi.abs(), m.es_hi, plug);
    }
    for g in &g_lo {
        gravur(lo, g, val, -1.0, 0.6);
    }
    for g in &g_hi {
        gravur(hi, g, val, 1.0, 0.6);
    }
}

// ───────────────────────── Der Schnitt ─────────────────────────

/// Eine neu entstandene Fuge (Schnittfläche) – Teile als Index in `lo` / `hi`
struct NeueFuge {
    punkt: V3,
    ring: Vec<V3>,
    lo: usize,
    hi: usize,
    zapfen: usize,
    hinweis: Option<String>,
}

struct Schnitt {
    lo: Vec<Mesh>,
    hi: Vec<Mesh>,
    fugen: Vec<NeueFuge>,
    lose: Vec<Mesh>,
}

#[derive(Clone, Copy, PartialEq)]
enum S {
    Lo,
    Hi,
    Off,
}

fn schneide(mesh: &Mesh, punkt: V3, normale: V3, ort_art: &str, linie: Option<[V3; 3]>, vb: &Verbindung, erste_nr: u32) -> Result<Schnitt> {
    let rf = Rahmen::neu(normale);
    let loc = rf.netz_hin(mesh);
    let q = rf.hin(punkt);
    let val = section::safe_value(&loc, 2, q[2]);
    let (sl, winzig) = schleifen(&loc, val);
    let ort = ort_bauen(&rf, [q[0], q[1]], ort_art, linie);
    let Some(wahl) = waehlen(&sl, &winzig, ort) else { bail!("Die Schnittebene trifft das Teil hier nicht.") };
    let lokal = !matches!(ort, Ort::Alle);
    let zusammen = matches!(ort, Ort::Rand(_) | Ort::Innen(_));

    // Dreiecke an der Naht teilen
    let mut out: Vec<[V3; 3]> = Vec::with_capacity(loc.tris.len() + wahl.tris.len() * 2);
    let mut tag: Vec<S> = Vec::with_capacity(out.capacity());
    for (i, t) in loc.tris.iter().enumerate() {
        if !wahl.tris.contains(&i) {
            out.push(*t);
            tag.push(S::Off);
            continue;
        }
        let pos = [t[0][2] > val, t[1][2] > val, t[2][2] > val];
        let np = pos.iter().filter(|x| **x).count();
        if np == 0 || np == 3 {
            out.push(*t);
            tag.push(if np == 3 { S::Hi } else { S::Lo });
            continue;
        }
        let lone = (0..3).find(|&i| pos[i] != pos[(i + 1) % 3] && pos[i] != pos[(i + 2) % 3]).unwrap();
        let l = t[lone];
        let a = t[(lone + 1) % 3];
        let b = t[(lone + 2) % 3];
        let p = section::edge_point(l, a, 2, val);
        let qq = section::edge_point(l, b, 2, val);
        let (s1, s2) = if pos[lone] { (S::Hi, S::Lo) } else { (S::Lo, S::Hi) };
        out.push([l, p, qq]);
        tag.push(s1);
        out.push([p, a, b]);
        tag.push(s2);
        out.push([p, b, qq]);
        tag.push(s2);
    }

    // Seiten bestimmen
    let mut seite = vec![false; out.len()]; // true = oben
    if lokal {
        type K = (i64, i64, i64);
        let k3 = |p: V3| -> K { ((p[0] * 1e5).round() as i64, (p[1] * 1e5).round() as i64, (p[2] * 1e5).round() as i64) };
        let mut kanten: HashMap<(K, K), Vec<u32>> = HashMap::with_capacity(out.len() * 2);
        let kante = |a: V3, b: V3| -> Option<(K, K)> {
            if a[2] == val && b[2] == val {
                return None; // Naht = Grenze
            }
            let (ka, kb) = (k3(a), k3(b));
            Some(if ka < kb { (ka, kb) } else { (kb, ka) })
        };
        for (i, t) in out.iter().enumerate() {
            for k in 0..3 {
                if let Some(e) = kante(t[k], t[(k + 1) % 3]) {
                    kanten.entry(e).or_default().push(i as u32);
                }
            }
        }
        let mut seen = vec![false; out.len()];
        let mut qu: VecDeque<usize> = VecDeque::new();
        for (i, s) in tag.iter().enumerate() {
            if *s == S::Hi {
                seen[i] = true;
                qu.push_back(i);
            }
        }
        while let Some(i) = qu.pop_front() {
            let t = out[i];
            for k in 0..3 {
                if let Some(e) = kante(t[k], t[(k + 1) % 3]) {
                    if let Some(v) = kanten.get(&e) {
                        for &j in v {
                            let j = j as usize;
                            if !seen[j] {
                                seen[j] = true;
                                qu.push_back(j);
                            }
                        }
                    }
                }
            }
        }
        if tag.iter().zip(&seen).any(|(s, r)| *s == S::Lo && *r) {
            bail!("Die Naht trennt das Teil hier nicht vollständig ab – bitte an einer schmaleren Stelle ansetzen oder die Ebene benutzen.");
        }
        if seen.iter().all(|x| *x) {
            bail!("Die Naht trennt hier nichts ab.");
        }
        seite = seen;
    } else {
        for (i, s) in tag.iter().enumerate() {
            seite[i] = match s {
                S::Hi => true,
                S::Lo => false,
                S::Off => out[i][0][2] > val,
            };
        }
    }
    let mut lo = Mesh::new();
    let mut hi = Mesh::new();
    for (t, s) in out.iter().zip(&seite) {
        if *s { hi.tris.push(*t) } else { lo.tris.push(*t) }
    }
    if lo.is_empty() || hi.is_empty() {
        bail!("Die Schnittebene liegt außerhalb des Teils.");
    }

    // Fugen: Verbinder planen (vor dem Schließen), dann Deckel
    let mut plan = Vec::new();
    let mut lose = Vec::new();
    for poly in &wahl.polys {
        let (mm, l, h) = if poly.area() >= 4.0 { zapfen_planen(poly, vb, &lo, &hi, val) } else { (vec![], vec![], None) };
        lose.extend(l);
        plan.push((mm, h));
    }
    let mut nr = erste_nr;
    let mut fugen_lokal: Vec<(Vec<P2>, P2, u32, usize, Option<String>)> = Vec::new();
    for (poly, (mm, h)) in wahl.polys.iter().zip(&plan) {
        let gross = poly.area() >= 4.0;
        let mut glyph = None;
        let mut ref_p: Option<P2> = None;
        if gross && vb.nummern {
            let ir = innen_radius(poly);
            let mut hh = (ir * 0.7).clamp(2.5, 9.0);
            while hh >= 2.5 {
                let (g, w) = ziffern(&nr.to_string(), hh);
                let halb = 0.5 * (w * w + hh * hh).sqrt() + 0.4;
                if let Some(at) = nummer_platz(poly, mm, halb) {
                    glyph = Some((g, at));
                    break;
                }
                hh *= 0.8;
            }
        }
        if ref_p.is_none() {
            ref_p = nummer_platz(poly, mm, 0.2).or(Some(poly.outer[0]));
        }
        deckel(&mut lo, &mut hi, poly, val, mm, glyph.as_ref().map(|(g, at)| (g.as_slice(), *at)));
        if gross {
            fugen_lokal.push((poly.outer.clone(), ref_p.unwrap(), nr, mm.len(), h.clone()));
            nr += 1;
        }
    }

    // Teile bilden
    // Teile bilden: berührte Körper sind neue Teile, unberührte bleiben bei dem, womit sie sich überlappen
    let beruehrt = |c: &Mesh| c.tris.iter().any(|t| t.iter().all(|p| p[2] == val));
    let mut frei: Vec<Mesh> = Vec::new();
    let mut seiten: Vec<Vec<Mesh>> = Vec::new();
    for m in [&lo, &hi] {
        let mut b = Vec::new();
        for c in section::split_components(m) {
            if beruehrt(&c) { b.push(c) } else { frei.push(c) }
        }
        seiten.push(if zusammen {
            let mut x = Mesh::new();
            for c in &b {
                x.extend(c);
            }
            vec![x]
        } else {
            gruppieren(b)
        });
    }
    let mut hi_teile = seiten.pop().unwrap_or_default();
    let mut lo_teile = seiten.pop().unwrap_or_default();
    for grp in gruppen(&frei) {
        let mut best: (f64, usize, usize) = (0.0, 0, 0);
        for (si, liste) in [&lo_teile, &hi_teile].iter().enumerate() {
            for (k, t) in liste.iter().enumerate() {
                let a: f64 = grp.iter().map(|&i| bb_ueberlapp(&frei[i], t)).sum();
                if a > best.0 {
                    best = (a, si, k);
                }
            }
        }
        if best.0 == 0.0 {
            // nichts überlappt: zum größten Stück
            for (si, liste) in [&lo_teile, &hi_teile].iter().enumerate() {
                for (k, t) in liste.iter().enumerate() {
                    let v = bb_vol(t);
                    if v > best.0 {
                        best = (v, si, k);
                    }
                }
            }
        }
        let ziel = if best.1 == 0 { &mut lo_teile[best.2] } else { &mut hi_teile[best.2] };
        for &i in &grp {
            ziel.extend(&frei[i]);
        }
    }
    let finde = |teile: &[Mesh], ring: &[P2]| -> usize {
        teile
            .iter()
            .position(|m| {
                m.tris.iter().any(|t| {
                    t.iter().all(|p| p[2] == val) && point_in_ring([(t[0][0] + t[1][0] + t[2][0]) / 3.0, (t[0][1] + t[1][1] + t[2][1]) / 3.0], ring)
                })
            })
            .unwrap_or(0)
    };
    let mut fugen = Vec::new();
    for (ring, rp, _nr, z, h) in &fugen_lokal {
        fugen.push(NeueFuge {
            punkt: rf.her(to3(*rp, 2, val)),
            ring: ring.iter().map(|p| rf.her(to3(*p, 2, val))).collect(),
            lo: finde(&lo_teile, ring),
            hi: finde(&hi_teile, ring),
            zapfen: *z,
            hinweis: h.clone(),
        });
    }
    Ok(Schnitt {
        lo: lo_teile.iter().map(|m| rf.netz_her(m)).collect(),
        hi: hi_teile.iter().map(|m| rf.netz_her(m)).collect(),
        fugen,
        lose,
    })
}

fn bb_ueberlapp(a: &Mesh, b: &Mesh) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let (x, y) = (a.bbox(), b.bbox());
    (0..3).map(|i| (x.max[i].min(y.max[i]) - x.min[i].max(y.min[i])).max(0.0)).product()
}

fn bb_vol(m: &Mesh) -> f64 {
    if m.is_empty() {
        return 0.0;
    }
    let s = m.bbox().size();
    s[0] * s[1] * s[2]
}

/// Gruppen sich überlappender Körper (Indizes)
fn gruppen(comps: &[Mesh]) -> Vec<Vec<usize>> {
    let n = comps.len();
    let vol: Vec<f64> = comps.iter().map(bb_vol).collect();
    let mut g: Vec<usize> = (0..n).collect();
    fn root(g: &mut Vec<usize>, mut i: usize) -> usize {
        while g[i] != i {
            g[i] = g[g[i]];
            i = g[i];
        }
        i
    }
    if n <= 400 {
        for i in 0..n {
            for j in i + 1..n {
                if bb_ueberlapp(&comps[i], &comps[j]) > 0.02 * vol[i].min(vol[j]) {
                    let (a, b) = (root(&mut g, i), root(&mut g, j));
                    g[b] = a;
                }
            }
        }
    }
    let mut map: HashMap<usize, Vec<usize>> = HashMap::new();
    let mut order = Vec::new();
    for i in 0..n {
        let r = root(&mut g, i);
        if !map.contains_key(&r) {
            order.push(r);
        }
        map.entry(r).or_default().push(i);
    }
    order.into_iter().filter_map(|r| map.remove(&r)).collect()
}

/// Sich überlappende Körper zu einem Teil zusammenfassen
fn gruppieren(comps: Vec<Mesh>) -> Vec<Mesh> {
    let n = comps.len();
    if n <= 1 || n > 400 {
        return comps;
    }
    let vol: Vec<f64> = comps.iter().map(|c| { let s = c.bbox().size(); s[0] * s[1] * s[2] }).collect();
    let mut g: Vec<usize> = (0..n).collect();
    fn root(g: &mut Vec<usize>, mut i: usize) -> usize {
        while g[i] != i {
            g[i] = g[g[i]];
            i = g[i];
        }
        i
    }
    for i in 0..n {
        for j in i + 1..n {
            if bb_ueberlapp(&comps[i], &comps[j]) > 0.05 * vol[i].min(vol[j]) {
                let (a, b) = (root(&mut g, i), root(&mut g, j));
                g[b] = a;
            }
        }
    }
    let mut map: HashMap<usize, Mesh> = HashMap::new();
    let mut order = Vec::new();
    for (i, c) in comps.into_iter().enumerate() {
        let r = root(&mut g, i);
        if !map.contains_key(&r) {
            order.push(r);
        }
        map.entry(r).or_default().extend(&c);
    }
    order.into_iter().filter_map(|r| map.remove(&r)).collect()
}

/// Ringe (Welt) der gewählten Fläche – für die Vorschau
pub fn ringe(mesh: &Mesh, punkt: V3, normale: V3, ort_art: &str, linie: Option<[V3; 3]>) -> Vec<Vec<V3>> {
    let rf = Rahmen::neu(normale);
    let loc = rf.netz_hin(mesh);
    let q = rf.hin(punkt);
    let val = section::safe_value(&loc, 2, q[2]);
    let (sl, winzig) = schleifen(&loc, val);
    let ort = ort_bauen(&rf, [q[0], q[1]], ort_art, linie);
    let Some(w) = waehlen(&sl, &winzig, ort) else { return vec![] };
    let mut out = Vec::new();
    for p in &w.polys {
        out.push(p.outer.iter().map(|x| rf.her(to3(*x, 2, val))).collect());
        for h in &p.holes {
            out.push(h.iter().map(|x| rf.her(to3(*x, 2, val))).collect());
        }
    }
    out
}

/// Band: beste Richtung um einen Oberflächenpunkt (kürzester Umfang um das Glied)
pub fn band_richtung(mesh: &Mesh, punkt: V3, flaeche_n: V3, kipp: f64) -> Option<V3> {
    let sn = norm(flaeche_n);
    let a = if sn[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
    let t1 = norm(cross(sn, a));
    let t2 = cross(sn, t1);
    let mut best: Option<(f64, V3)> = None;
    let kipps = [0.0f64, -15.0, 15.0];
    for &phi in &kipps {
        for i in 0..36 {
            let th = i as f64 * 5.0f64.to_radians();
            let dir = add(mul(t1, th.cos()), mul(t2, th.sin()));
            let n = norm(add(mul(dir, phi.to_radians().cos()), mul(sn, phi.to_radians().sin())));
            let rf = Rahmen::neu(n);
            let q = rf.hin(punkt);
            // nur Dreiecke, die die Ebene schneiden – direkt im Rahmen
            let mut seg_mesh = Mesh::new();
            for t in &mesh.tris {
                let d0 = dot(t[0], n) - q[2];
                let d1 = dot(t[1], n) - q[2];
                let d2 = dot(t[2], n) - q[2];
                if (d0 > 0.0) == (d1 > 0.0) && (d1 > 0.0) == (d2 > 0.0) {
                    continue;
                }
                seg_mesh.tris.push(t.map(|p| rf.hin(p)));
            }
            let val = section::safe_value(&seg_mesh, 2, q[2]);
            let (sl, winzig) = schleifen(&seg_mesh, val);
            let Some(w) = waehlen(&sl, &winzig, Ort::Rand([q[0], q[1]])) else { continue };
            let p = &w.polys[0];
            if dist_to_ring([q[0], q[1]], &p.outer) > 1.5 && !p.holes.iter().any(|h| dist_to_ring([q[0], q[1]], h) <= 1.5) {
                continue;
            }
            let umfang: f64 = (0..p.outer.len()).map(|k| {
                let (x, y) = (p.outer[k], p.outer[(k + 1) % p.outer.len()]);
                ((x[0] - y[0]).powi(2) + (x[1] - y[1]).powi(2)).sqrt()
            }).sum();
            if best.is_none_or(|b| umfang < b.0) {
                best = Some((umfang, n));
            }
        }
    }
    let n = best?.1;
    if kipp.abs() < 1e-6 {
        return Some(n);
    }
    // zusätzlich um die Flächennormale kippen
    let ax = norm(cross(n, sn));
    let k = kipp.to_radians();
    Some(norm(add(mul(n, k.cos()), mul(cross(ax, n), k.sin()))))
}

/// Ebene durch Randpunkte einer bemalten Fläche (Schwerpunkt, Normale = kleinste Streuung)
pub fn ebene_aus_punkten(pts: &[V3]) -> Option<(V3, V3)> {
    if pts.len() < 3 {
        return None;
    }
    let mut c = [0.0; 3];
    for p in pts {
        c = add(c, *p);
    }
    let c = mul(c, 1.0 / pts.len() as f64);
    let mut m = [[0.0f64; 3]; 3];
    for p in pts {
        let d = sub(*p, c);
        for i in 0..3 {
            for j in 0..3 {
                m[i][j] += d[i] * d[j];
            }
        }
    }
    let tr = m[0][0] + m[1][1] + m[2][2];
    if tr <= 0.0 {
        return None;
    }
    // kleinster Eigenvektor von m = größter von (tr·I − m)
    let mut b = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            b[i][j] = if i == j { tr } else { 0.0 } - m[i][j];
        }
    }
    let mut v = [0.577, 0.577, 0.577];
    for _ in 0..200 {
        let w = [dot(b[0], v), dot(b[1], v), dot(b[2], v)];
        v = norm(w);
    }
    Some((c, v))
}

// ───────────────────────── Sitzung ─────────────────────────

#[derive(Clone)]
pub struct Teil {
    pub nr: u32,
    pub name: String,
    pub mesh: Arc<Mesh>,
    /// Außennormalen der Schnittflächen (zum Hinlegen beim Export)
    pub flaechen: Vec<V3>,
    /// Filament (1-basiert), 0 = keine Angabe
    pub farbe: u32,
    /// > 0: gehört mit allen Teilen gleicher Gruppe zu einem Objekt (passgenau, AMS)
    pub gruppe: u32,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Fuge {
    pub nr: u32,
    /// unteres Teil (Zapfen) und oberes Teil (Tasche)
    pub a: u32,
    pub b: u32,
    pub punkt: V3,
    /// zeigt von a nach b
    pub normale: V3,
    pub ring: Vec<V3>,
    pub verbinder: String,
    pub anzahl: usize,
}

#[derive(Clone, Default)]
pub struct Stand {
    pub teile: Vec<Teil>,
    pub fugen: Vec<Fuge>,
    pub lose: Vec<Arc<Mesh>>,
    pub next_teil: u32,
    pub next_fuge: u32,
    /// Bemalung aus der geladenen 3MF (nur solange das Teil unverändert ist)
    pub bemalung: Vec<Arc<crate::farben::Bemalung>>,
    /// Filamentfarben aus der Datei (#RRGGBB)
    pub filamente: Vec<String>,
}

struct Sitzung {
    zeit: Instant,
    name: String,
    verlauf: Vec<Stand>,
}

fn sitzungen() -> &'static Mutex<HashMap<String, Sitzung>> {
    static S: OnceLock<Mutex<HashMap<String, Sitzung>>> = OnceLock::new();
    S.get_or_init(Default::default)
}

pub fn neu(name: String, stand: Stand) -> String {
    let mut s = sitzungen().lock().unwrap();
    s.retain(|_, v| v.zeit.elapsed().as_secs() < 6 * 3600);
    while s.len() >= 20 {
        let alt = s.iter().min_by_key(|(_, v)| v.zeit).map(|(k, _)| k.clone()).unwrap();
        s.remove(&alt);
    }
    let sid = uuid::Uuid::new_v4().simple().to_string()[..16].to_string();
    s.insert(sid.clone(), Sitzung { zeit: Instant::now(), name, verlauf: vec![stand] });
    sid
}

pub fn aktuell(sid: &str) -> Option<(String, Stand, bool)> {
    let mut s = sitzungen().lock().unwrap();
    let e = s.get_mut(sid)?;
    e.zeit = Instant::now();
    Some((e.name.clone(), e.verlauf.last().cloned().unwrap_or_default(), e.verlauf.len() > 1))
}

pub fn setzen(sid: &str, st: Stand) {
    let mut s = sitzungen().lock().unwrap();
    if let Some(e) = s.get_mut(sid) {
        e.verlauf.push(st);
        if e.verlauf.len() > 30 {
            e.verlauf.remove(0);
        }
    }
}

pub fn zurueck(sid: &str) -> bool {
    let mut s = sitzungen().lock().unwrap();
    match s.get_mut(sid) {
        Some(e) if e.verlauf.len() > 1 => {
            e.verlauf.pop();
            true
        }
        _ => false,
    }
}

pub fn stand_aus_objekten(objs: Vec<(String, Mesh)>) -> Stand {
    let mut st = Stand { next_teil: 1, next_fuge: 1, ..Default::default() };
    let viele = objs.len() > 1;
    for (name, m) in objs {
        let nr = st.next_teil;
        st.next_teil += 1;
        st.teile.push(Teil { nr, name: if viele { name } else { format!("Teil {nr}") }, mesh: Arc::new(m), flaechen: vec![], farbe: 0, gruppe: 0 });
    }
    st
}

/// Gemalte Farben eines Teils zu eigenen Teilen machen (Grundkörper bekommt Taschen)
pub fn farben_herausloesen(st: &mut Stand, nr: u32, o: &crate::farben::Optionen, hinweise: &mut Vec<String>) -> Result<()> {
    let Some(pos) = st.teile.iter().position(|t| t.nr == nr) else { bail!("Teil {nr} gibt es nicht mehr.") };
    let Some(bem) = st.bemalung.iter().find(|b| b.teil == nr).cloned() else {
        bail!("Dieses Teil hat keine Bemalung (mehr). Farben bitte vor dem Schneiden herauslösen – oder eine bemalte 3MF aus Bambu Studio öffnen.")
    };
    let e = crate::farben::herausloesen(&bem, o)?;
    let alt = st.teile.remove(pos);
    st.bemalung.retain(|b| b.teil != nr);
    let basis_name = if alt.name.starts_with("Teil ") { "Grundkörper".to_string() } else { alt.name.clone() };
    let gruppe = if o.stecken { 0 } else { st.next_teil };
    let mut neue = Vec::new();
    let mut nimm = |st: &mut Stand, name: String, mesh: Mesh, farbe: u32, flaechen: Vec<V3>| {
        let tnr = st.next_teil;
        st.next_teil += 1;
        neue.push(Teil { nr: tnr, name, mesh: Arc::new(mesh), flaechen, farbe, gruppe });
    };
    nimm(st, basis_name, e.koerper, e.basis, alt.flaechen.clone());
    let mut zaehler: HashMap<u32, usize> = HashMap::new();
    for t in e.teile {
        let k = zaehler.entry(t.farbe).or_default();
        *k += 1;
        let name = if t.bereiche > 1 { format!("Filament {} · {} Bereiche", t.farbe, t.bereiche) } else { format!("Filament {} · {}", t.farbe, k) };
        // Sichtseite nach unten aufs Bett (glatte Oberfläche)
        nimm(st, name, t.mesh, t.farbe, vec![t.normale]);
    }
    for (n, m, f) in &bem.koerper {
        nimm(st, if n.is_empty() { format!("Filament {f}") } else { n.clone() }, m.clone(), *f, vec![]);
    }
    let anzahl = neue.len() - 1;
    st.teile.splice(pos..pos, neue);
    hinweise.push(format!("{anzahl} Farbteile herausgelöst."));
    if e.weggelassen > 0 {
        hinweise.push(format!("{} kleine Flecken unter der Mindestfläche bleiben im Grundkörper.", e.weggelassen));
    }
    if e.flacher > 0 {
        hinweise.push("An dünnen Stellen sind die Farbteile flacher, damit die Wand nicht durchbricht.".into());
    }
    Ok(())
}

/// Liegt eine Fuge (noch) auf diesem Netz?
fn hat_fuge(m: &Mesh, f: &Fuge) -> bool {
    let rf = Rahmen::neu(f.normale);
    let val = dot(f.punkt, rf.n);
    let ring: Vec<P2> = f.ring.iter().map(|p| {
        let q = rf.hin(*p);
        [q[0], q[1]]
    })
    .collect();
    m.tris.iter().any(|t| {
        if !t.iter().all(|p| (dot(*p, rf.n) - val).abs() < 1e-4) {
            return false;
        }
        let c = rf.hin(mul(add(add(t[0], t[1]), t[2]), 1.0 / 3.0));
        point_in_ring([c[0], c[1]], &ring)
    })
}

/// Teil `nr` schneiden und den Stand fortschreiben. Liefert die neuen Teilnummern.
pub fn teil_schneiden(st: &mut Stand, nr: u32, punkt: V3, normale: V3, ort: &str, linie: Option<[V3; 3]>, vb: &Verbindung, hinweise: &mut Vec<String>) -> Result<Vec<u32>> {
    let Some(pos) = st.teile.iter().position(|t| t.nr == nr) else { bail!("Teil {nr} gibt es nicht mehr.") };
    let alt = st.teile[pos].clone();
    let sch = schneide(&alt.mesh, punkt, normale, ort, linie, vb, st.next_fuge)?;
    let n = norm(normale);
    let mut neue: Vec<Teil> = Vec::new();
    let mut lo_nr = Vec::new();
    let mut hi_nr = Vec::new();
    for (ist_hi, liste) in [(false, &sch.lo), (true, &sch.hi)] {
        for m in liste {
            let tnr = st.next_teil;
            st.next_teil += 1;
            let mut fl = alt.flaechen.clone();
            fl.push(if ist_hi { mul(n, -1.0) } else { n });
            let basis = alt.name.split(" · ").next().unwrap_or("Teil");
            let name = if basis.starts_with("Teil ") { format!("Teil {tnr}") } else { format!("{basis} · {tnr}") };
            neue.push(Teil { nr: tnr, name, mesh: Arc::new(m.clone()), flaechen: fl, farbe: alt.farbe, gruppe: 0 });
            if ist_hi { hi_nr.push(tnr) } else { lo_nr.push(tnr) }
        }
    }
    // alte Fugen dieses Teils umhängen
    for f in st.fugen.iter_mut() {
        for seite in [0, 1] {
            let wer = if seite == 0 { f.a } else { f.b };
            if wer != nr {
                continue;
            }
            if let Some(t) = neue.iter().find(|t| hat_fuge(&t.mesh, f)) {
                if seite == 0 { f.a = t.nr } else { f.b = t.nr }
            }
        }
    }
    let art = match vb.art.as_str() {
        "keine" => "ohne Verbinder".to_string(),
        "magnet" => format!("Magnet {}×{} mm", vb.magnet_d, vb.magnet_h),
        "lose" => format!("loser Zapfen {}", form_name(&vb.form)),
        "steck" => format!("Steckzapfen {}", form_name(&vb.form)),
        _ => format!("fester Zapfen {}", form_name(&vb.form)),
    };
    for (i, f) in sch.fugen.iter().enumerate() {
        let fnr = st.next_fuge + i as u32;
        if let Some(h) = &f.hinweis {
            hinweise.push(format!("Fuge {fnr}: {h}."));
        }
        st.fugen.push(Fuge {
            nr: fnr,
            a: lo_nr[f.lo.min(lo_nr.len() - 1)],
            b: hi_nr[f.hi.min(hi_nr.len() - 1)],
            punkt: f.punkt,
            normale: n,
            ring: f.ring.clone(),
            verbinder: if f.zapfen == 0 { "ohne Verbinder".into() } else { art.clone() },
            anzahl: f.zapfen,
        });
    }
    st.next_fuge += sch.fugen.len() as u32;
    st.lose.extend(sch.lose.into_iter().map(Arc::new));
    st.teile.splice(pos..pos + 1, neue.clone());
    Ok(neue.iter().map(|t| t.nr).collect())
}

/// Mehrere Ebenen entlang der Achsen
pub fn mehrfach(st: &mut Stand, nr: u32, anz: [usize; 3], vb: &Verbindung, hinweise: &mut Vec<String>) -> Result<()> {
    let Some(t) = st.teile.iter().find(|t| t.nr == nr) else { bail!("Teil {nr} gibt es nicht mehr.") };
    let bb = t.mesh.bbox();
    let mut aktiv = vec![nr];
    for ax in 0..3 {
        let k = anz[ax].clamp(1, 12);
        for i in 1..k {
            let pos = bb.min[ax] + (bb.max[ax] - bb.min[ax]) * i as f64 / k as f64;
            let mut neu = Vec::new();
            for &tn in &aktiv {
                let Some(t) = st.teile.iter().find(|t| t.nr == tn) else { continue };
                let b = t.mesh.bbox();
                if b.min[ax] + 0.3 < pos && pos < b.max[ax] - 0.3 {
                    let mut p = [0.0; 3];
                    p[ax] = pos;
                    let mut n = [0.0; 3];
                    n[ax] = 1.0;
                    match teil_schneiden(st, tn, p, n, "alle", None, vb, hinweise) {
                        Ok(v) => neu.extend(v),
                        Err(e) => {
                            hinweise.push(e.to_string());
                            neu.push(tn);
                        }
                    }
                } else {
                    neu.push(tn);
                }
            }
            aktiv = neu;
        }
    }
    Ok(())
}

fn passt(s: V3, bett: V3) -> bool {
    let mut a = s;
    let mut b = bett;
    a.sort_by(|x, y| y.partial_cmp(x).unwrap());
    b.sort_by(|x, y| y.partial_cmp(x).unwrap());
    a.iter().zip(&b).all(|(x, y)| x <= y)
}

/// Automatisch so zerlegen, dass jedes Teil aufs Bett passt (möglichst wenige Teile)
pub fn auto(st: &mut Stand, nr: u32, bett: V3, rand: f64, vb: &Verbindung, hinweise: &mut Vec<String>) -> Result<usize> {
    let nutz = [bett[0] - 2.0 * rand, bett[1] - 2.0 * rand, bett[2]];
    let mut offen = vec![nr];
    let mut schnitte = 0;
    while let Some(tn) = offen.pop() {
        if st.teile.len() > 80 {
            hinweise.push("Abgebrochen: mehr als 80 Teile.".into());
            break;
        }
        let Some(t) = st.teile.iter().find(|t| t.nr == tn) else { continue };
        let bb = t.mesh.bbox();
        let s = bb.size();
        if passt(s, nutz) {
            continue;
        }
        let ax = (0..3).max_by(|a, b| s[*a].partial_cmp(&s[*b]).unwrap()).unwrap();
        let groesst = nutz[0].max(nutz[1]).max(nutz[2]) * 0.97;
        let k = (s[ax] / groesst).ceil().max(2.0);
        let ziel = bb.min[ax] + s[ax] / k;
        // schmalste Stelle um das Ziel herum (nicht über die Bettgröße hinaus)
        let spanne = s[ax] / k * 0.15;
        let mesh = t.mesh.clone();
        let mut best = (f64::MAX, ziel);
        for i in 0..=24 {
            let p = (ziel - spanne + 2.0 * spanne * i as f64 / 24.0).min(bb.min[ax] + groesst);
            let a = section::section_area(&mesh, ax, p);
            if a > 1e-6 && a < best.0 * 0.97 {
                best = (a, p);
            }
        }
        let mut p = [0.0; 3];
        p[ax] = best.1;
        let mut n = [0.0; 3];
        n[ax] = 1.0;
        let neu = teil_schneiden(st, tn, p, n, "alle", None, vb, hinweise)?;
        schnitte += 1;
        offen.extend(neu);
    }
    Ok(schnitte)
}

// ───────────────────────── Export ─────────────────────────

fn drehung(a: V3, b: V3) -> [[f64; 3]; 3] {
    // dreht a auf b (Rodrigues)
    let a = norm(a);
    let b = norm(b);
    let v = cross(a, b);
    let c = dot(a, b);
    if c < -0.999999 {
        let ax = if a[0].abs() < 0.9 { norm(cross(a, [1.0, 0.0, 0.0])) } else { norm(cross(a, [0.0, 1.0, 0.0])) };
        let mut r = [[0.0; 3]; 3];
        for i in 0..3 {
            for j in 0..3 {
                r[i][j] = 2.0 * ax[i] * ax[j] - if i == j { 1.0 } else { 0.0 };
            }
        }
        return r;
    }
    let k = 1.0 / (1.0 + c);
    [
        [v[0] * v[0] * k + c, v[0] * v[1] * k - v[2], v[0] * v[2] * k + v[1]],
        [v[1] * v[0] * k + v[2], v[1] * v[1] * k + c, v[1] * v[2] * k - v[0]],
        [v[2] * v[0] * k - v[1], v[2] * v[1] * k + v[0], v[2] * v[2] * k + c],
    ]
}

fn drehen(m: &Mesh, r: &[[f64; 3]; 3]) -> Mesh {
    Mesh { tris: m.tris.iter().map(|t| t.map(|p| [dot(r[0], p), dot(r[1], p), dot(r[2], p)])).collect() }
}

/// Teil zum Drucken hinlegen: möglichst mit einer großen Schnittfläche nach unten
pub fn hinlegen(m: &Mesh, flaechen: &[V3], bett: V3) -> Mesh {
    let mut kand: Vec<V3> = flaechen.to_vec();
    kand.extend([[0.0, 0.0, -1.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -1.0, 0.0]]);
    let mut best: Option<(f64, Mesh)> = None;
    for (i, d) in kand.iter().enumerate() {
        let r = drehung(*d, [0.0, 0.0, -1.0]);
        let g = drehen(m, &r);
        let bb = g.bbox();
        if !(bb.size()[2] <= bett[2] && passt([bb.size()[0], bb.size()[1], 0.0], [bett[0], bett[1], 0.0])) {
            continue;
        }
        let mut flach = 0.0;
        for t in &g.tris {
            if t.iter().all(|p| p[2] - bb.min[2] < 0.05) {
                flach += 0.5 * mesh::len(cross(sub(t[1], t[0]), sub(t[2], t[0])));
            }
        }
        // Schnittflächen bevorzugen
        let w = flach * if i < flaechen.len() { 1.5 } else { 1.0 };
        if best.as_ref().is_none_or(|b| w > b.0) {
            best = Some((w, g));
        }
    }
    best.map(|b| b.1).unwrap_or_else(|| m.clone())
}

#[derive(Deserialize, Clone)]
pub struct Drucker {
    pub name: String,
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

pub fn export_teile(st: &Stand, dr: &Drucker) -> Vec<(String, Mesh)> {
    einheiten(st, dr).into_iter().flat_map(|(_, teile)| teile.into_iter().map(|(n, m, _)| (n, m))).collect()
}

/// Export-Einheit: Name und Teile (Name, Netz, Filament). Teile einer Gruppe bleiben an Ort und Stelle zueinander.
type Einheit = (String, Vec<(String, Mesh, u32)>);

fn einheiten(st: &Stand, dr: &Drucker) -> Vec<Einheit> {
    let bett = [dr.x, dr.y, dr.z];
    let mut out: Vec<Einheit> = Vec::new();
    let mut gruppen: Vec<(u32, usize)> = Vec::new();
    for t in &st.teile {
        if t.gruppe == 0 {
            out.push((t.name.clone(), vec![(t.name.clone(), hinlegen(&t.mesh, &t.flaechen, bett), t.farbe)]));
            continue;
        }
        match gruppen.iter().find(|g| g.0 == t.gruppe) {
            Some(&(_, i)) => out[i].1.push((t.name.clone(), (*t.mesh).clone(), t.farbe)),
            None => {
                gruppen.push((t.gruppe, out.len()));
                out.push((t.name.clone(), vec![(t.name.clone(), (*t.mesh).clone(), t.farbe)]));
            }
        }
    }
    for (i, z) in st.lose.iter().enumerate() {
        let n = format!("Zapfen {}", i + 1);
        out.push((n.clone(), vec![(n, (**z).clone(), 0)]));
    }
    out
}

/// Einheiten auf Platten verteilen; liefert (Platte, Einheit) mit Netzen in Plattenkoordinaten
fn platzieren(einh: Vec<Einheit>, bed: [f64; 2], gap: f64) -> Vec<(usize, Einheit)> {
    let mut einh = einh;
    let box_von = |t: &Vec<(String, Mesh, u32)>| {
        let mut m = Mesh::new();
        for (_, x, _) in t {
            m.extend(x);
        }
        m.bbox()
    };
    for (_, t) in einh.iter_mut() {
        let b = box_von(t);
        for (_, m, _) in t.iter_mut() {
            m.translate([-b.min[0], -b.min[1], -b.min[2]]);
        }
    }
    let sizes: Vec<(f64, f64)> = einh.iter().map(|(_, t)| {
        let s = box_von(t).size();
        (s[0], s[1])
    }).collect();
    let pl = export::shelf_pack(&sizes, bed[0] - 2.0 * gap, bed[1] - 2.0 * gap, gap);
    einh.into_iter()
        .zip(pl)
        .map(|((n, mut t), (plate, x, y, r))| {
            if r {
                for (_, m, _) in t.iter_mut() {
                    m.map(|p| [p[1], -p[0], p[2]]);
                }
                let b = box_von(&t);
                for (_, m, _) in t.iter_mut() {
                    m.translate([-b.min[0], -b.min[1], -b.min[2]]);
                }
            }
            for (_, m, _) in t.iter_mut() {
                m.translate([x + gap, y + gap, 0.0]);
            }
            (plate, (n, t))
        })
        .collect()
}

pub fn bambu(st: &Stand, dr: &Drucker, rand: f64) -> Vec<u8> {
    let farbig = st.teile.iter().any(|t| t.farbe > 0 || t.gruppe > 0);
    if farbig {
        let objs: Vec<crate::prep::Obj> = platzieren(einheiten(st, dr), [dr.x, dr.y], rand.max(2.0))
            .into_iter()
            .map(|(plate, (name, teile))| crate::prep::Obj {
                name,
                plate,
                x: 0.0,
                y: 0.0,
                stuetzen: None,
                rand: None,
                teile: teile.into_iter().map(|(n, m, f)| {
                    let k = m.tris.len();
                    (n, f.max(1), m.tris, vec![None; k], vec![None; k])
                }).collect(),
            })
            .collect();
        if let Ok(b) = crate::prep::bambu_objekte(&objs, [dr.x, dr.y], &dr.name, "Formwerk") {
            return b;
        }
    }
    let teile = export_teile(st, dr);
    let pp: Vec<PlatePart> = export::arrange_on_plates(teile, [dr.x, dr.y], rand.max(2.0), 0);
    let n = pp.iter().map(|p| p.plate + 1).max().unwrap_or(1);
    export::bambu_3mf(&pp, [dr.x, dr.y], &vec![dr.name.clone(); n])
}

pub fn stl_zip(st: &Stand, dr: &Drucker) -> Vec<u8> {
    let sicher = |n: &str| -> String { n.chars().map(|c| if c.is_alphanumeric() || c == ' ' || c == '-' { c } else { '_' }).collect::<String>().trim().to_string() };
    let mut files: Vec<(String, Vec<u8>)> = Vec::new();
    for (name, teile) in einheiten(st, dr) {
        let mehr = teile.len() > 1;
        // Teile einer Gruppe behalten ihre Lage zueinander (gemeinsamer Nullpunkt)
        let mut ges = Mesh::new();
        for (_, m, _) in &teile {
            ges.extend(m);
        }
        let b = ges.bbox();
        for (n, mut m, f) in teile {
            m.translate([-b.min[0], -b.min[1], -b.min[2]]);
            let mut datei = if mehr { format!("{} - {}", sicher(&name), sicher(&n)) } else { sicher(&n) };
            if f > 0 {
                datei.push_str(&format!(" (Filament {f})"));
            }
            files.push((format!("{datei}.stl"), m.to_stl(&n)));
        }
    }
    export::zip_files(&files)
}

/// Projekt: einfache 3MF mit allen Teilen an Ort und Stelle + Fugen als JSON
pub fn projekt(st: &Stand) -> Vec<u8> {
    use std::fmt::Write as _;
    let mut model = String::from(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"millimeter\" xml:lang=\"de-DE\" xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\">\n <metadata name=\"Application\">Formwerk</metadata>\n <resources>\n",
    );
    for (i, t) in st.teile.iter().enumerate() {
        let name: String = t.name.replace('&', "&amp;").replace('<', "&lt;").replace('"', "&quot;");
        let _ = write!(model, "  <object id=\"{}\" name=\"{}\" type=\"model\"><mesh><vertices>\n", i + 1, name);
        let mut idx: HashMap<(u64, u64, u64), usize> = HashMap::new();
        let mut tri_s = String::new();
        let mut vs = String::new();
        for tr in &t.mesh.tris {
            let mut id = [0usize; 3];
            for k in 0..3 {
                let p = tr[k];
                let key = (p[0].to_bits(), p[1].to_bits(), p[2].to_bits());
                let n = idx.len();
                id[k] = *idx.entry(key).or_insert_with(|| {
                    let _ = writeln!(vs, "<vertex x=\"{:.5}\" y=\"{:.5}\" z=\"{:.5}\"/>", p[0], p[1], p[2]);
                    n
                });
            }
            let _ = writeln!(tri_s, "<triangle v1=\"{}\" v2=\"{}\" v3=\"{}\"/>", id[0], id[1], id[2]);
        }
        model.push_str(&vs);
        model.push_str("</vertices><triangles>\n");
        model.push_str(&tri_s);
        model.push_str("</triangles></mesh></object>\n");
    }
    model.push_str(" </resources>\n <build>\n");
    for i in 0..st.teile.len() {
        let _ = writeln!(model, "  <item objectid=\"{}\"/>", i + 1);
    }
    model.push_str(" </build>\n</model>\n");
    let meta = serde_json::json!({
        "teile": st.teile.iter().map(|t| serde_json::json!({"nr": t.nr, "name": t.name, "flaechen": t.flaechen, "farbe": t.farbe, "gruppe": t.gruppe})).collect::<Vec<_>>(),
        "fugen": st.fugen,
        "next_teil": st.next_teil,
        "next_fuge": st.next_fuge,
        "filamente": st.filamente,
    });
    let files = vec![
        ("[Content_Types].xml".to_string(), br#"<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="json" ContentType="application/json"/></Types>"#.to_vec()),
        ("_rels/.rels".to_string(), br#"<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>"#.to_vec()),
        ("3D/3dmodel.model".to_string(), model.into_bytes()),
        ("Metadata/formwerk_teilen.json".to_string(), serde_json::to_vec(&meta).unwrap_or_default()),
    ];
    export::zip_files(&files)
}

/// Gespeichertes Projekt wiederherstellen (Teile + Fugen), falls die 3MF eins enthält
pub fn projekt_laden(bytes: &[u8], objs: Vec<(String, Mesh)>) -> Stand {
    use std::io::Read;
    let meta: Option<serde_json::Value> = (|| {
        let mut z = zip::ZipArchive::new(std::io::Cursor::new(bytes)).ok()?;
        let mut f = z.by_name("Metadata/formwerk_teilen.json").ok()?;
        let mut s = String::new();
        f.read_to_string(&mut s).ok()?;
        serde_json::from_str(&s).ok()
    })();
    let Some(meta) = meta else { return stand_aus_objekten(objs) };
    let teile = meta["teile"].as_array().cloned().unwrap_or_default();
    if teile.len() != objs.len() {
        return stand_aus_objekten(objs);
    }
    let mut st = Stand {
        next_teil: meta["next_teil"].as_u64().unwrap_or(1) as u32,
        next_fuge: meta["next_fuge"].as_u64().unwrap_or(1) as u32,
        fugen: serde_json::from_value(meta["fugen"].clone()).unwrap_or_default(),
        filamente: serde_json::from_value(meta["filamente"].clone()).unwrap_or_default(),
        ..Default::default()
    };
    for (t, (_, m)) in teile.iter().zip(objs) {
        st.teile.push(Teil {
            nr: t["nr"].as_u64().unwrap_or(0) as u32,
            name: t["name"].as_str().unwrap_or("Teil").to_string(),
            mesh: Arc::new(m),
            flaechen: serde_json::from_value(t["flaechen"].clone()).unwrap_or_default(),
            farbe: t["farbe"].as_u64().unwrap_or(0) as u32,
            gruppe: t["gruppe"].as_u64().unwrap_or(0) as u32,
        });
    }
    st
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Würfel bzw. Quader als geschlossenes Netz
    fn quader(min: V3, max: V3) -> Mesh {
        let poly = Poly { outer: vec![[min[0], min[1]], [max[0], min[1]], [max[0], max[1]], [min[0], max[1]]], holes: vec![] };
        let mut m = export::extrude(&[poly], max[2] - min[2], &|q, z| [q[0], q[1], z + min[2]]);
        m.fix_orientation();
        m
    }

    fn figur() -> Mesh {
        // Rumpf mit einem waagrechten Arm (L-Form, ein Körper)
        let mut m = Mesh::new();
        m.extend(&quader([0.0, 0.0, 0.0], [40.0, 30.0, 100.0]));
        m
    }

    fn geschlossen(m: &Mesh) -> bool {
        let mut kanten: HashMap<((i64, i64, i64), (i64, i64, i64)), i32> = HashMap::new();
        let k = |p: V3| ((p[0] * 1e4).round() as i64, (p[1] * 1e4).round() as i64, (p[2] * 1e4).round() as i64);
        for t in &m.tris {
            for i in 0..3 {
                let (a, b) = (k(t[i]), k(t[(i + 1) % 3]));
                if a == b {
                    continue;
                }
                *kanten.entry((a, b)).or_default() += 1;
                *kanten.entry((b, a)).or_default() -= 1;
            }
        }
        kanten.values().all(|v| *v == 0)
    }

    #[test]
    fn ebene_schraeg_mit_allen_formen() {
        for form in ["rund", "eckig", "kegel", "kreuz", "stern", "sechs"] {
            for art in ["fest", "lose", "magnet", "steck"] {
                let mut st = stand_aus_objekten(vec![("x".into(), figur())]);
                let vb = Verbindung { form: form.into(), art: art.into(), ..Default::default() };
                let mut h = vec![];
                let neu = teil_schneiden(&mut st, 1, [20.0, 15.0, 50.0], [0.2, 0.1, 1.0], "alle", None, &vb, &mut h).unwrap();
                assert_eq!(neu.len(), 2, "{form} {art}");
                for t in &st.teile {
                    assert!(geschlossen(&t.mesh), "nicht geschlossen: {form} {art}");
                    assert!(t.mesh.volume() > 0.0);
                }
                assert_eq!(st.fugen.len(), 1);
                assert!(st.fugen[0].anzahl >= 1, "{form} {art}: {h:?}");
                let vol: f64 = st.teile.iter().map(|t| t.mesh.volume()).sum();
                assert!((vol - 120000.0).abs() < 120000.0 * 0.05, "Volumen {vol} {form} {art}");
            }
        }
    }

    #[test]
    fn band_trennt_nur_den_arm() {
        // Rumpf + Arm als ein zusammenhängender Körper (Vereinigung über gemeinsame Fläche nachgebaut):
        // U-Form aus einem extrudierten Umriss
        let umriss = Poly { outer: vec![[0.0, 0.0], [40.0, 0.0], [40.0, 60.0], [90.0, 60.0], [90.0, 75.0], [0.0, 75.0]], holes: vec![] };
        let mut m = export::extrude(&[umriss], 20.0, &|q, z| [q[0], z, q[1]]);
        m.fix_orientation();
        assert!(geschlossen(&m));
        let mut st = stand_aus_objekten(vec![("x".into(), m)]);
        let vb = Verbindung::default();
        let mut h = vec![];
        // Klick oben auf den Arm bei x = 70 → Band senkrecht zum Arm
        let n = band_richtung(&st.teile[0].mesh, [70.0, 10.0, 75.0], [0.0, 0.0, 1.0], 0.0).unwrap();
        assert!(n[0].abs() > 0.95, "Richtung {n:?}");
        teil_schneiden(&mut st, 1, [70.0, 10.0, 75.0], n, "rand", None, &vb, &mut h).unwrap();
        assert_eq!(st.teile.len(), 2);
        let mut sizes: Vec<f64> = st.teile.iter().map(|t| t.mesh.bbox().size()[0]).collect();
        sizes.sort_by(|a, b| a.partial_cmp(b).unwrap());
        assert!((sizes[0] - 20.0).abs() < 1.0 || sizes[0] > 15.0, "{sizes:?}");
        for t in &st.teile {
            assert!(geschlossen(&t.mesh));
        }
        // Gleiche Ebene als ganzer Schnitt würde den Rumpf nicht treffen – Band darf nur den Arm treffen
        assert!(st.teile.iter().any(|t| t.mesh.bbox().max[0] > 85.0 && t.mesh.bbox().min[0] > 60.0));
    }

    #[test]
    fn auto_passt_aufs_bett() {
        let m = quader([0.0, 0.0, 0.0], [600.0, 100.0, 80.0]);
        let mut st = stand_aus_objekten(vec![("x".into(), m)]);
        let mut h = vec![];
        auto(&mut st, 1, [256.0, 256.0, 256.0], 5.0, &Verbindung::default(), &mut h).unwrap();
        assert_eq!(st.teile.len(), 3, "{h:?}");
        for t in &st.teile {
            assert!(passt(t.mesh.bbox().size(), [246.0, 246.0, 256.0]));
            assert!(geschlossen(&t.mesh));
        }
        assert_eq!(st.fugen.len(), 2);
        let bytes = bambu(&st, &Drucker { name: "P2S".into(), x: 256.0, y: 256.0, z: 256.0 }, 5.0);
        assert!(bytes.len() > 1000);
        let p = projekt(&st);
        let objs = crate::mesh::load(&p, "a.3mf").unwrap();
        let st2 = projekt_laden(&p, objs);
        assert_eq!(st2.teile.len(), 3);
        assert_eq!(st2.fugen.len(), 2);
    }

    #[test]
    fn bemalen_ebene() {
        let pts: Vec<V3> = (0..20).map(|i| {
            let a = i as f64 / 20.0 * std::f64::consts::TAU;
            [10.0 * a.cos(), 50.0 + 0.01 * a.sin(), 10.0 * a.sin()]
        })
        .collect();
        let (c, n) = ebene_aus_punkten(&pts).unwrap();
        assert!((c[1] - 50.0).abs() < 0.1);
        assert!(n[1].abs() > 0.99);
    }
}

#[cfg(test)]
mod tests_rund {
    use super::*;

    fn zylinder_x(c: V3, r: f64, l: f64, n: usize) -> Mesh {
        let ring = section::circle([0.0, 0.0], r, n);
        let mut m = export::extrude(&[Poly { outer: ring, holes: vec![] }], l, &|q, z| [c[0] + z, c[1] + q[0], c[2] + q[1]]);
        // fein unterteilen entlang der Länge: in Scheiben schneiden ist nicht nötig, extrude reicht für den Test
        m.fix_orientation();
        m
    }

    #[test]
    fn band_an_rundem_arm_mit_ueberlappung() {
        // Rumpf (Quader) + Arm (Zylinder) als getrennte, überlappende Körper – wie bei vielen Figuren-STLs
        let mut m = Mesh::new();
        let rumpf = {
            let p = Poly { outer: vec![[0.0, 0.0], [40.0, 0.0], [40.0, 30.0], [0.0, 30.0]], holes: vec![] };
            let mut r = export::extrude(&[p], 100.0, &|q, z| [q[0], q[1], z]);
            r.fix_orientation();
            r
        };
        m.extend(&rumpf);
        m.extend(&zylinder_x([30.0, 15.0, 80.0], 8.0, 70.0, 48));
        let mut st = stand_aus_objekten(vec![("Figur".into(), m)]);
        let p = [75.0, 15.0, 88.0]; // oben auf dem Arm
        let n = band_richtung(&st.teile[0].mesh, p, [0.0, 0.0, 1.0], 0.0).unwrap();
        println!("Richtung {n:?}");
        let mut h = vec![];
        teil_schneiden(&mut st, 1, p, n, "rand", None, &Verbindung { form: "stern".into(), ..Default::default() }, &mut h).unwrap();
        for t in &st.teile {
            let b = t.mesh.bbox();
            println!("{} min {:?} max {:?} vol {:.0}", t.name, b.min, b.max, t.mesh.volume());
        }
        println!("Fugen {:?} Hinweise {h:?}", st.fugen.iter().map(|f| (f.nr, f.a, f.b, f.anzahl, f.verbinder.clone())).collect::<Vec<_>>());
        assert_eq!(st.teile.len(), 2);
        let arm = st.teile.iter().find(|t| t.mesh.bbox().min[0] > 60.0).expect("Armstück");
        assert!(arm.mesh.bbox().max[0] > 99.0);
        assert_eq!(st.fugen[0].anzahl, 1);
        // Danach den Rumpf quer schneiden: alte Fuge muss am Rumpfteil bleiben
        let rumpf_nr = st.teile.iter().find(|t| t.mesh.bbox().min[0] < 1.0).unwrap().nr;
        teil_schneiden(&mut st, rumpf_nr, [20.0, 15.0, 40.0], [0.0, 0.0, 1.0], "alle", None, &Verbindung::default(), &mut h).unwrap();
        let oben = st.teile.iter().find(|t| t.mesh.bbox().min[2] > 39.0 && t.mesh.bbox().min[0] < 1.0).unwrap().nr;
        println!("Fugen {:?}", st.fugen.iter().map(|f| (f.nr, f.a, f.b)).collect::<Vec<_>>());
        assert!(st.fugen[0].a == oben || st.fugen[0].b == oben);
    }
}
