//! Ebenenschnitte: Querschnitte, Teilen eines Netzes mit geschlossenen Schnittflächen, Dübeltaschen.
use crate::mesh::{Mesh, V3, cross, dot, sub};
use geo::{Coord, LineString, MultiPolygon, Polygon};
use std::collections::HashMap;

pub type P2 = [f64; 2];

/// 3D → 2D in der Schnittebene der Achse `axis`
pub fn to2(p: V3, axis: usize) -> P2 {
    match axis {
        0 => [p[1], p[2]],
        1 => [p[0], p[2]],
        _ => [p[0], p[1]],
    }
}
pub fn to3(p: P2, axis: usize, val: f64) -> V3 {
    match axis {
        0 => [val, p[0], p[1]],
        1 => [p[0], val, p[1]],
        _ => [p[0], p[1], val],
    }
}

/// Schnittpunkt einer Kante mit der Ebene – kanonisch, damit Nachbardreiecke exakt denselben Punkt bekommen.
fn edge_point(a: V3, b: V3, axis: usize, val: f64) -> V3 {
    let (a, b) = if (a[0], a[1], a[2]) <= (b[0], b[1], b[2]) { (a, b) } else { (b, a) };
    let t = (val - a[axis]) / (b[axis] - a[axis]);
    let mut p = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
    p[axis] = val;
    p
}

/// Ebene leicht verschieben, damit kein Eckpunkt genau darauf liegt
pub fn safe_value(mesh: &Mesh, axis: usize, mut val: f64) -> f64 {
    for _ in 0..20 {
        if !mesh.tris.iter().any(|t| t.iter().any(|p| (p[axis] - val).abs() < 1e-7)) {
            return val;
        }
        val += 1.37e-5;
    }
    val
}

fn key(p: P2) -> (i64, i64) {
    ((p[0] * 1e5).round() as i64, (p[1] * 1e5).round() as i64)
}

/// Schnittlinien-Segmente (orientiert) eines Netzes mit der Ebene
fn segments(mesh: &Mesh, axis: usize, val: f64) -> Vec<(P2, P2)> {
    let mut axisv = [0.0; 3];
    axisv[axis] = 1.0;
    let mut segs = Vec::new();
    for t in &mesh.tris {
        let d = [t[0][axis] - val, t[1][axis] - val, t[2][axis] - val];
        let pos = d.iter().filter(|x| **x > 0.0).count();
        if pos == 0 || pos == 3 {
            continue;
        }
        let mut pts = Vec::with_capacity(2);
        for i in 0..3 {
            let j = (i + 1) % 3;
            if (d[i] > 0.0) != (d[j] > 0.0) {
                pts.push(edge_point(t[i], t[j], axis, val));
            }
        }
        if pts.len() != 2 {
            continue;
        }
        let n = cross(sub(t[1], t[0]), sub(t[2], t[0]));
        let dir = cross(n, axisv);
        let (a, b) = if dot(sub(pts[1], pts[0]), dir) >= 0.0 { (pts[0], pts[1]) } else { (pts[1], pts[0]) };
        let (a2, b2) = (to2(a, axis), to2(b, axis));
        if key(a2) != key(b2) {
            segs.push((a2, b2));
        }
    }
    segs
}

/// Segmente zu geschlossenen Schleifen verketten
fn chain(segs: Vec<(P2, P2)>) -> Vec<Vec<P2>> {
    let mut by_start: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
    for (i, s) in segs.iter().enumerate() {
        by_start.entry(key(s.0)).or_default().push(i);
    }
    let mut used = vec![false; segs.len()];
    let mut loops = Vec::new();
    for start in 0..segs.len() {
        if used[start] {
            continue;
        }
        used[start] = true;
        let mut lp = vec![segs[start].0];
        let first = key(segs[start].0);
        let mut end = segs[start].1;
        loop {
            if key(end) == first {
                break;
            }
            let next = by_start.get(&key(end)).and_then(|v| v.iter().copied().find(|i| !used[*i]));
            match next {
                Some(i) => {
                    used[i] = true;
                    lp.push(segs[i].0);
                    end = segs[i].1;
                }
                None => break, // offen – wird trotzdem geschlossen
            }
        }
        if lp.len() >= 3 {
            loops.push(lp);
        }
    }
    loops
}

pub fn ring_area(r: &[P2]) -> f64 {
    let mut a = 0.0;
    for i in 0..r.len() {
        let p = r[i];
        let q = r[(i + 1) % r.len()];
        a += p[0] * q[1] - q[0] * p[1];
    }
    a * 0.5
}

pub fn point_in_ring(p: P2, r: &[P2]) -> bool {
    let mut inside = false;
    let n = r.len();
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (r[i], r[j]);
        if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0] {
            inside = !inside;
        }
        j = i;
    }
    inside
}

pub fn dist_to_ring(p: P2, r: &[P2]) -> f64 {
    let mut best = f64::MAX;
    for i in 0..r.len() {
        let a = r[i];
        let b = r[(i + 1) % r.len()];
        let ab = [b[0] - a[0], b[1] - a[1]];
        let l2 = ab[0] * ab[0] + ab[1] * ab[1];
        let t = if l2 > 0.0 { (((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / l2).clamp(0.0, 1.0) } else { 0.0 };
        let q = [a[0] + ab[0] * t - p[0], a[1] + ab[1] * t - p[1]];
        best = best.min((q[0] * q[0] + q[1] * q[1]).sqrt());
    }
    best
}

/// Fläche mit Löchern
#[derive(Clone, Debug)]
pub struct Poly {
    pub outer: Vec<P2>,
    pub holes: Vec<Vec<P2>>,
}

impl Poly {
    pub fn contains(&self, p: P2) -> bool {
        point_in_ring(p, &self.outer) && !self.holes.iter().any(|h| point_in_ring(p, h))
    }
    pub fn boundary_dist(&self, p: P2) -> f64 {
        self.holes.iter().map(|h| dist_to_ring(p, h)).fold(dist_to_ring(p, &self.outer), f64::min)
    }
    pub fn area(&self) -> f64 {
        ring_area(&self.outer).abs() - self.holes.iter().map(|h| ring_area(h).abs()).sum::<f64>()
    }
    pub fn bbox(&self) -> (P2, P2) {
        let mut mn = [f64::MAX; 2];
        let mut mx = [f64::MIN; 2];
        for p in &self.outer {
            mn[0] = mn[0].min(p[0]);
            mn[1] = mn[1].min(p[1]);
            mx[0] = mx[0].max(p[0]);
            mx[1] = mx[1].max(p[1]);
        }
        (mn, mx)
    }
    pub fn to_geo(&self) -> Polygon<f64> {
        let ls = |r: &Vec<P2>| {
            let mut v: Vec<Coord<f64>> = r.iter().map(|p| Coord { x: p[0], y: p[1] }).collect();
            if let Some(f) = v.first().cloned() {
                v.push(f);
            }
            LineString::new(v)
        };
        Polygon::new(ls(&self.outer), self.holes.iter().map(ls).collect())
    }
    pub fn from_geo(p: &Polygon<f64>) -> Poly {
        let conv = |ls: &LineString<f64>| {
            let mut v: Vec<P2> = ls.0.iter().map(|c| [c.x, c.y]).collect();
            if v.len() > 1 && v.first() == v.last() {
                v.pop();
            }
            v
        };
        Poly { outer: conv(p.exterior()), holes: p.interiors().iter().map(conv).collect() }
    }
    /// Dreiecke (2D) per Earcut
    pub fn triangulate(&self) -> Vec<[P2; 3]> {
        let mut flat: Vec<f64> = Vec::new();
        let mut pts: Vec<P2> = Vec::new();
        let mut holes_idx = Vec::new();
        for p in &self.outer {
            flat.extend_from_slice(p);
            pts.push(*p);
        }
        for h in &self.holes {
            holes_idx.push(pts.len());
            for p in h {
                flat.extend_from_slice(p);
                pts.push(*p);
            }
        }
        let idx = earcutr::earcut(&flat, &holes_idx, 2).unwrap_or_default();
        let tris: Vec<[P2; 3]> = idx.chunks(3).map(|c| [pts[c[0]], pts[c[1]], pts[c[2]]]).collect();
        // Earcut lässt Punkte auf Geraden weg, und Kanten können über Punkte anderer Ringe laufen → T-Stöße.
        // Alle Eckpunkte prüfen, die auf einer Dreieckskante liegen, und dort einbauen (nach x sortiert für schnelle Suche).
        let mut dropped: Vec<P2> = pts.clone();
        dropped.sort_by(|a, b| a[0].partial_cmp(&b[0]).unwrap());
        dropped.dedup_by(|a, b| (a[0] - b[0]).abs() < 1e-12 && (a[1] - b[1]).abs() < 1e-12);
        let on_edge = |a: P2, b: P2, p: P2| -> Option<f64> {
            let ab = [b[0] - a[0], b[1] - a[1]];
            let l2 = ab[0] * ab[0] + ab[1] * ab[1];
            if l2 < 1e-18 {
                return None;
            }
            let t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / l2;
            if t <= 1e-9 || t >= 1.0 - 1e-9 {
                return None;
            }
            let cr = (ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])).abs() / l2.sqrt();
            if cr < 1e-6 { Some(t) } else { None }
        };
        let mut out = Vec::with_capacity(tris.len() + dropped.len() * 3);
        for t in tris {
            let mut ring: Vec<P2> = Vec::new();
            let mut extra = false;
            for e in 0..3 {
                let (a, b) = (t[e], t[(e + 1) % 3]);
                ring.push(a);
                let (x0, x1) = (a[0].min(b[0]) - 1e-6, a[0].max(b[0]) + 1e-6);
                let start = dropped.partition_point(|p| p[0] < x0);
                let mut on: Vec<(f64, P2)> = dropped[start..].iter().take_while(|p| p[0] <= x1).filter_map(|p| on_edge(a, b, *p).map(|s| (s, *p))).collect();
                if !on.is_empty() {
                    extra = true;
                    on.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
                    ring.extend(on.into_iter().map(|x| x.1));
                }
            }
            if !extra {
                out.push(t);
                continue;
            }
            let c = [(t[0][0] + t[1][0] + t[2][0]) / 3.0, (t[0][1] + t[1][1] + t[2][1]) / 3.0];
            for i in 0..ring.len() {
                out.push([c, ring[i], ring[(i + 1) % ring.len()]]);
            }
        }
        out
    }
}

pub fn multi_to_polys(m: &MultiPolygon<f64>) -> Vec<Poly> {
    m.0.iter().map(Poly::from_geo).filter(|p| p.outer.len() >= 3).collect()
}
/// Schleifen zu Flächen mit Löchern (gerade Verschachtelungstiefe = außen)
pub fn loops_to_polys(loops: Vec<Vec<P2>>) -> Vec<Poly> {
    let loops: Vec<Vec<P2>> = loops.into_iter().filter(|l| ring_area(l).abs() > 1e-4).collect();
    let n = loops.len();
    let areas: Vec<f64> = loops.iter().map(|l| ring_area(l).abs()).collect();
    let mut parent: Vec<Option<usize>> = vec![None; n];
    let mut depth = vec![0usize; n];
    for i in 0..n {
        let p = loops[i][0];
        let mut best: Option<usize> = None;
        for j in 0..n {
            if i != j && areas[j] > areas[i] && point_in_ring(p, &loops[j]) {
                depth[i] += 1;
                if best.is_none_or(|b| areas[j] < areas[b]) {
                    best = Some(j);
                }
            }
        }
        parent[i] = best;
    }
    let mut polys: Vec<Poly> = Vec::new();
    let mut index: HashMap<usize, usize> = HashMap::new();
    for i in 0..n {
        if depth[i] % 2 == 0 {
            index.insert(i, polys.len());
            polys.push(Poly { outer: loops[i].clone(), holes: vec![] });
        }
    }
    for i in 0..n {
        if depth[i] % 2 == 1 {
            if let Some(pi) = parent[i].and_then(|p| index.get(&p)) {
                polys[*pi].holes.push(loops[i].clone());
            }
        }
    }
    polys
}

/// Querschnitt als Flächen. Überlappende Körper werden vereinigt (Nonzero-Regel).
pub fn section(mesh: &Mesh, axis: usize, val: f64) -> Vec<Poly> {
    use geo::algorithm::bool_ops::{BooleanOps, FillRule, OpType};
    let v = safe_value(mesh, axis, val);
    let loops: Vec<Vec<P2>> = chain(segments(mesh, axis, v)).into_iter().filter(|l| ring_area(l).abs() > 1e-4).collect();
    if loops.is_empty() {
        return vec![];
    }
    let simple = loops_to_polys(loops.clone());
    let as_polys = MultiPolygon::new(loops.iter().map(|l| Poly { outer: l.clone(), holes: vec![] }.to_geo()).collect());
    let united = as_polys.boolean_op_with_fill_rule(&MultiPolygon::new(vec![]), OpType::Union, FillRule::NonZero);
    let polys = multi_to_polys(&united);
    let a_simple: f64 = simple.iter().map(|p| p.area()).sum();
    let a_union: f64 = polys.iter().map(|p| p.area()).sum();
    // Falls die Orientierung nicht stimmt (Fläche bricht ein), die einfache Variante nehmen
    if polys.is_empty() || a_union < a_simple * 0.5 { simple } else { polys }
}

/// Fläche des Querschnitts (schnell, ohne Vereinigung)
pub fn section_area(mesh: &Mesh, axis: usize, val: f64) -> f64 {
    let v = safe_value(mesh, axis, val);
    loops_to_polys(chain(segments(mesh, axis, v))).iter().map(|p| p.area()).sum()
}

/// Dreieck so einfügen, dass die Normale in Richtung `want` zeigt
pub fn push_facing(m: &mut Mesh, a: V3, b: V3, c: V3, want: V3) {
    if dot(cross(sub(b, a), sub(c, a)), want) >= 0.0 {
        m.push(a, b, c);
    } else {
        m.push(a, c, b);
    }
}

/// Eine Seite eines Verbinders: Tasche ins Teil hinein (ext > 0) oder Zapfen aus dem Teil heraus (ext < 0)
#[derive(Clone, Copy, Debug)]
pub struct Side {
    pub radius: f64,
    pub ext: f64,
    /// Maßstab des Endrings (1 = gerade, < 1 = kegelig)
    pub end_scale: f64,
}

/// Verbinder in der Schnittebene: untere Seite (lo) und obere Seite (hi)
#[derive(Clone, Copy, Debug)]
pub struct Pocket {
    pub center: P2,
    pub square: bool,
    pub lo: Side,
    pub hi: Side,
}

impl Pocket {
    pub fn max_radius(&self) -> f64 {
        self.lo.radius.max(self.hi.radius)
    }
}

pub fn ring_for(c: P2, r: f64, square: bool) -> Vec<P2> {
    if square {
        vec![[c[0] - r, c[1] - r], [c[0] + r, c[1] - r], [c[0] + r, c[1] + r], [c[0] - r, c[1] + r]]
    } else {
        circle(c, r, 32)
    }
}

/// Tasche oder Zapfen an einen Ring in der Ebene anbauen. `s` = Richtung entlang der Achse (+1/-1).
fn feature(m: &mut Mesh, ring: &[P2], center: P2, axis: usize, val: f64, s: f64, len: f64, end_scale: f64, plug: bool) {
    let end = val + s * len;
    let mut axv = [0.0; 3];
    axv[axis] = 1.0;
    let cap_dir = if plug { s } else { -s };
    let want_cap = [axv[0] * cap_dir, axv[1] * cap_dir, axv[2] * cap_dir];
    let n = ring.len();
    let endp = |q: P2| [center[0] + (q[0] - center[0]) * end_scale, center[1] + (q[1] - center[1]) * end_scale];
    let ce = to3(center, axis, end);
    for i in 0..n {
        let (a, b) = (ring[i], ring[(i + 1) % n]);
        let p0 = to3(a, axis, val);
        let p1 = to3(b, axis, val);
        let q0 = to3(endp(a), axis, end);
        let q1 = to3(endp(b), axis, end);
        let mid = [(a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5];
        let mut rad2 = [mid[0] - center[0], mid[1] - center[1]];
        if !plug {
            rad2 = [-rad2[0], -rad2[1]];
        }
        let rad = sub(to3(rad2, axis, 0.0), to3([0.0, 0.0], axis, 0.0));
        push_facing(m, p0, p1, q1, rad);
        push_facing(m, p0, q1, q0, rad);
        push_facing(m, ce, q0, q1, want_cap);
    }
}

pub fn circle(c: P2, r: f64, n: usize) -> Vec<P2> {
    (0..n)
        .map(|i| {
            let a = i as f64 / n as f64 * std::f64::consts::TAU;
            [c[0] + r * a.cos(), c[1] + r * a.sin()]
        })
        .collect()
}

/// Netz an der Ebene teilen, beide Hälften geschlossen. Rückgabe (unten, oben).
pub fn cut(mesh: &Mesh, axis: usize, val: f64, pockets: &[Pocket]) -> (Mesh, Mesh) {
    let val = safe_value(mesh, axis, val);
    let mut lo = Mesh::new();
    let mut hi = Mesh::new();
    for t in &mesh.tris {
        let d = [t[0][axis] - val, t[1][axis] - val, t[2][axis] - val];
        let pos: Vec<bool> = d.iter().map(|x| *x > 0.0).collect();
        let np = pos.iter().filter(|x| **x).count();
        if np == 0 {
            lo.tris.push(*t);
            continue;
        }
        if np == 3 {
            hi.tris.push(*t);
            continue;
        }
        // einsamer Eckpunkt
        let lone = (0..3).find(|&i| pos[i] != pos[(i + 1) % 3] && pos[i] != pos[(i + 2) % 3]).unwrap();
        let l = t[lone];
        let a = t[(lone + 1) % 3];
        let b = t[(lone + 2) % 3];
        let p = edge_point(l, a, axis, val);
        let q = edge_point(l, b, axis, val);
        let (lone_side, other) = if pos[lone] { (&mut hi, &mut lo) } else { (&mut lo, &mut hi) };
        lone_side.push(l, p, q);
        other.push(p, a, b);
        other.push(p, b, q);
    }
    // Deckel (unten und oben getrennt, weil Taschen und Zapfen verschieden groß sein können)
    let base = loops_to_polys(chain(segments(mesh, axis, val)));
    let mut polys_lo = base.clone();
    let mut polys_hi = base.clone();
    let mut used: Vec<(Pocket, Vec<P2>, Vec<P2>)> = Vec::new();
    for pk in pockets {
        if let Some(i) = base.iter().position(|p| p.contains(pk.center) && p.boundary_dist(pk.center) > pk.max_radius() * if pk.square { 1.42 } else { 1.0 } + 0.3) {
            let rl = ring_for(pk.center, pk.lo.radius, pk.square);
            let rh = ring_for(pk.center, pk.hi.radius, pk.square);
            polys_lo[i].holes.push(rl.clone());
            polys_hi[i].holes.push(rh.clone());
            used.push((*pk, rl, rh));
        }
    }
    let mut up = [0.0; 3];
    up[axis] = 1.0;
    let down = [-up[0], -up[1], -up[2]];
    for poly in &polys_lo {
        for tri in poly.triangulate() {
            push_facing(&mut lo, to3(tri[0], axis, val), to3(tri[1], axis, val), to3(tri[2], axis, val), up);
        }
    }
    for poly in &polys_hi {
        for tri in poly.triangulate() {
            push_facing(&mut hi, to3(tri[0], axis, val), to3(tri[1], axis, val), to3(tri[2], axis, val), down);
        }
    }
    // Taschen und Zapfen
    for (pk, rl, rh) in &used {
        for (m, side, ring, side_sign) in [(&mut lo, pk.lo, rl, -1.0), (&mut hi, pk.hi, rh, 1.0)] {
            if side.ext == 0.0 {
                continue;
            }
            let plug = side.ext < 0.0;
            let s = if plug { -side_sign } else { side_sign };
            feature(m, ring, pk.center, axis, val, s, side.ext.abs(), side.end_scale, plug);
        }
    }
    (lo, hi)
}

/// Wie `cut`, aber jeder zusammenhängende Körper einzeln (überlappende Körper bleiben geschlossen)
pub fn cut_bodies(mesh: &Mesh, axis: usize, val: f64, pockets: &[Pocket]) -> (Mesh, Mesh) {
    let mut lo = Mesh::new();
    let mut hi = Mesh::new();
    for body in split_components(mesh) {
        let b = body.bbox();
        if b.max[axis] <= val {
            lo.extend(&body);
        } else if b.min[axis] >= val {
            hi.extend(&body);
        } else {
            let (l, h) = cut(&body, axis, val, pockets);
            lo.extend(&l);
            hi.extend(&h);
        }
    }
    (lo, hi)
}

/// Netz in zusammenhängende Teile zerlegen (über gemeinsame Eckpunkte)
pub fn split_components(mesh: &Mesh) -> Vec<Mesh> {
    let kp = |p: &V3| ((p[0] * 1e4).round() as i64, (p[1] * 1e4).round() as i64, (p[2] * 1e4).round() as i64);
    let mut ids: HashMap<(i64, i64, i64), usize> = HashMap::new();
    let mut tv: Vec<[usize; 3]> = Vec::with_capacity(mesh.tris.len());
    for t in &mesh.tris {
        let mut idx = [0; 3];
        for i in 0..3 {
            let n = ids.len();
            idx[i] = *ids.entry(kp(&t[i])).or_insert(n);
        }
        tv.push(idx);
    }
    let mut parent: Vec<usize> = (0..ids.len()).collect();
    fn find(p: &mut Vec<usize>, mut x: usize) -> usize {
        while p[x] != x {
            p[x] = p[p[x]];
            x = p[x];
        }
        x
    }
    for t in &tv {
        let a = find(&mut parent, t[0]);
        for k in 1..3 {
            let b = find(&mut parent, t[k]);
            if a != b {
                parent[b] = a;
            }
        }
    }
    let mut groups: HashMap<usize, Mesh> = HashMap::new();
    for (i, t) in tv.iter().enumerate() {
        let r = find(&mut parent, t[0]);
        groups.entry(r).or_default().tris.push(mesh.tris[i]);
    }
    let mut v: Vec<Mesh> = groups.into_values().collect();
    v.sort_by(|a, b| b.tris.len().cmp(&a.tris.len()));
    v
}
