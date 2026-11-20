//! Formwerk: Modelle aufs Druckbett zerlegen (angelehnt an LuBan „Mesh → Cut“).
use crate::export::{self, PlatePart};
use crate::mesh::{Mesh, V3};
use crate::section::{self, P2, Pocket, Poly};
use anyhow::Result;
use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct Printer {
    pub name: String,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    #[serde(default = "one")]
    pub speed: f64,
}
fn one() -> f64 {
    1.0
}

#[derive(Deserialize, Debug, Clone)]
#[serde(default)]
pub struct Params {
    pub printers: Vec<Printer>,
    /// Abstand zum Bettrand (mm)
    pub margin: f64,
    /// Maßstab in Prozent
    pub scale: f64,
    /// alternativ: größte Kante (mm), 0 = aus
    pub size: f64,
    pub connector: String,
    pub dowel_d: f64,
    pub depth_ratio: f64,
    pub tolerance: f64,
    pub magnet_d: f64,
    pub magnet_h: f64,
}

impl Default for Params {
    fn default() -> Self {
        Params {
            printers: vec![Printer { name: "Bambu Lab H2C".into(), x: 325.0, y: 320.0, z: 325.0, speed: 1.0 }],
            margin: 5.0,
            scale: 100.0,
            size: 0.0,
            connector: "dowel".into(),
            dowel_d: 5.0,
            depth_ratio: 2.0,
            tolerance: -0.2,
            magnet_d: 6.0,
            magnet_h: 3.0,
        }
    }
}

#[derive(Serialize, Default)]
pub struct Output {
    /// (Dateiname, Inhalt)
    #[serde(skip)]
    pub files: Vec<(String, Vec<u8>)>,
    /// Vorschau-Netze (Name, Netz, Platte)
    #[serde(skip)]
    pub preview: Vec<(String, Mesh)>,
    pub summary: Vec<(String, String)>,
    pub warnings: Vec<String>,
    pub plates: usize,
}

impl Output {
    fn stat(&mut self, k: &str, v: impl ToString) {
        self.summary.push((k.into(), v.to_string()));
    }
}

fn main_printer(p: &Params) -> Printer {
    p.printers.first().cloned().unwrap_or(Printer { name: "Drucker".into(), x: 256.0, y: 256.0, z: 256.0, speed: 1.0 })
}

/// Teile (Name, Netz) als STL + Bambu-3MF ausgeben, Teile mehreren Druckern zuteilen
fn emit_parts(out: &mut Output, parts: Vec<(String, Mesh)>, p: &Params, prefix: &str) {
    if parts.is_empty() {
        out.warnings.push("Es sind keine Teile entstanden.".into());
        return;
    }
    let printers = if p.printers.is_empty() { vec![main_printer(p)] } else { p.printers.clone() };
    // Zuteilung: größte Teile zuerst auf den Drucker, der als Erster fertig wäre und in den das Teil passt
    let mut load = vec![0.0f64; printers.len()];
    let mut assign: Vec<Vec<(String, Mesh)>> = vec![Vec::new(); printers.len()];
    let mut order: Vec<(String, Mesh)> = parts;
    order.sort_by(|a, b| b.1.volume().abs().partial_cmp(&a.1.volume().abs()).unwrap());
    let mut too_big = 0;
    for (name, m) in order {
        let s = m.bbox().size();
        let fits = |pr: &Printer| {
            let (bx, by) = (pr.x - 2.0 * p.margin, pr.y - 2.0 * p.margin);
            s[2] <= pr.z + 1e-6 && ((s[0] <= bx + 1e-6 && s[1] <= by + 1e-6) || (s[1] <= bx + 1e-6 && s[0] <= by + 1e-6))
        };
        let vol = m.volume().abs().max(1.0);
        let mut best: Option<usize> = None;
        for (i, pr) in printers.iter().enumerate() {
            if fits(pr) {
                let finish = load[i] + vol / pr.speed.max(0.01);
                if best.is_none_or(|b| finish < load[b] + vol / printers[b].speed.max(0.01)) {
                    best = Some(i);
                }
            }
        }
        let i = match best {
            Some(i) => i,
            None => {
                too_big += 1;
                0
            }
        };
        load[i] += vol / printers[i].speed.max(0.01);
        assign[i].push((name, m));
    }
    if too_big > 0 {
        out.warnings.push(format!("{too_big} Teil(e) größer als die Platte."));
    }
    let multi = printers.len() > 1;
    let mut total_plates = 0;
    for (pi, (pr, list)) in printers.iter().zip(assign).enumerate() {
        if list.is_empty() {
            continue;
        }
        let tag = if multi { format!("P{} ", pi + 1) } else { String::new() };
        for (name, m) in &list {
            out.files.push((format!("stl/{}{}.stl", tag.replace(' ', "_"), name), m.to_stl(name)));
        }
        let arranged: Vec<PlatePart> = export::arrange_on_plates(
            list.into_iter().map(|(n, m)| (format!("{tag}{n}"), m)).collect(),
            [pr.x, pr.y],
            p.margin,
            0,
        );
        let n_pl = arranged.iter().map(|a| a.plate + 1).max().unwrap_or(0);
        total_plates += n_pl;
        let names: Vec<String> = (0..n_pl).map(|i| format!("{}{} – Platte {}", tag, pr.name, i + 1)).collect();
        let file = if multi { format!("{prefix}_P{}_{}.3mf", pi + 1, sanitize(&pr.name)) } else { format!("{prefix}.3mf") };
        out.files.push((file, export::bambu_3mf(&arranged, [pr.x, pr.y], &names)));
        if multi {
            out.stat(&format!("P{} {}", pi + 1, pr.name), format!("{} {}", n_pl, if n_pl == 1 { "Platte" } else { "Platten" }));
        }
    }
    out.plates = total_plates;
}

fn sanitize(s: &str) -> String {
    s.chars().map(|c| if c.is_alphanumeric() || c == '-' { c } else { '_' }).collect()
}

// ───────────────────────── Teilen aufs Druckbett ─────────────────────────

type M3 = [[f64; 3]; 3];
const IDENT: M3 = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];

fn mat_mul(a: &M3, b: &M3) -> M3 {
    let mut o = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            o[i][j] = (0..3).map(|k| a[i][k] * b[k][j]).sum();
        }
    }
    o
}
fn mat_t(a: &M3) -> M3 {
    let mut o = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            o[i][j] = a[j][i];
        }
    }
    o
}
fn apply(m: &M3, p: V3) -> V3 {
    [
        m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2],
        m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2],
        m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2],
    ]
}
fn rot(axis: usize, deg: f64) -> M3 {
    let (s, c) = deg.to_radians().sin_cos();
    match axis {
        0 => [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]],
        1 => [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]],
        _ => [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]],
    }
}
fn rotated(m: &Mesh, r: &M3) -> Mesh {
    let mut o = m.clone();
    o.map(|p| apply(r, p));
    o
}
/// Hüllquader-Maße nach Drehung (ohne das Netz zu kopieren)
fn dims_after(m: &Mesh, r: &M3) -> V3 {
    let mut mn = [f64::MAX; 3];
    let mut mx = [f64::MIN; 3];
    for t in &m.tris {
        for p in t {
            let q = apply(r, *p);
            for i in 0..3 {
                mn[i] = mn[i].min(q[i]);
                mx[i] = mx[i].max(q[i]);
            }
        }
    }
    [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]]
}

/// Passt ein Quader in den Bauraum, wenn man ihn beliebig achsparallel dreht?
fn fits_any(d: V3, bed: V3) -> bool {
    let mut a = d;
    let mut b = bed;
    a.sort_by(|x, y| y.partial_cmp(x).unwrap());
    b.sort_by(|x, y| y.partial_cmp(x).unwrap());
    (0..3).all(|i| a[i] <= b[i] + 1e-6)
}
/// Passt in dieser Lage aufs Bett (nur Drehung um Z erlaubt)?
fn fits_upright(d: V3, pr: &Printer, margin: f64) -> bool {
    let (bx, by) = (pr.x - 2.0 * margin, pr.y - 2.0 * margin);
    d[2] <= pr.z + 1e-6 && ((d[0] <= bx + 1e-6 && d[1] <= by + 1e-6) || (d[1] <= bx + 1e-6 && d[0] <= by + 1e-6))
}
/// Geschätzte Stückzahl (beste achsparallele Zuordnung)
fn est_pieces(d: V3, bed: V3) -> usize {
    let mut a = d;
    let mut b = bed;
    a.sort_by(|x, y| y.partial_cmp(x).unwrap());
    b.sort_by(|x, y| y.partial_cmp(x).unwrap());
    (0..3).map(|i| (a[i] / b[i]).ceil().max(1.0) as usize).product()
}

#[derive(Clone, Copy)]
struct Cap {
    axis: usize,
    val: f64,
    /// Richtung der Außennormale entlang der Achse (+1/-1)
    sign: f64,
    plug: bool,
}

struct Piece {
    mesh: Mesh,
    caps: Vec<Cap>,
    /// Bereiche mit Verbindern (min/max), die spätere Schnitte meiden
    feats: Vec<(V3, V3)>,
    node: usize,
}

enum Node {
    Leaf(String),
    Cut(Vec<usize>),
}

/// Überlappende Teilkörper (Hüllquader) zu einem Teil zusammenfassen
fn group_overlapping(comps: Vec<Mesh>) -> Vec<Mesh> {
    let boxes: Vec<_> = comps.iter().map(|c| c.bbox()).collect();
    let mut g: Vec<usize> = (0..comps.len()).collect();
    fn root(g: &mut Vec<usize>, mut i: usize) -> usize {
        while g[i] != i {
            g[i] = g[g[i]];
            i = g[i];
        }
        i
    }
    for i in 0..comps.len() {
        for j in i + 1..comps.len() {
            let (a, b) = (&boxes[i], &boxes[j]);
            if (0..3).all(|k| a.min[k] < b.max[k] - 0.05 && b.min[k] < a.max[k] - 0.05) && really_overlap(&comps[i], &comps[j]) {
                let (ri, rj) = (root(&mut g, i), root(&mut g, j));
                g[rj] = ri;
            }
        }
    }
    let mut merged: std::collections::BTreeMap<usize, Mesh> = Default::default();
    for (i, c) in comps.into_iter().enumerate() {
        let r = root(&mut g, i);
        merged.entry(r).or_default().extend(&c);
    }
    merged.into_values().collect()
}

/// Liegt ein Punkt im geschlossenen Netz? (Strahl in +X, Schnitte zählen)
fn point_inside(m: &Mesh, p: V3) -> bool {
    let mut n = 0;
    for t in &m.tris {
        let (a, b, c) = (t[0], t[1], t[2]);
        if (a[1] > p[1]) == (b[1] > p[1]) && (b[1] > p[1]) == (c[1] > p[1]) {
            continue;
        }
        if (a[2] > p[2]) == (b[2] > p[2]) && (b[2] > p[2]) == (c[2] > p[2]) {
            continue;
        }
        // Schnitt des Strahls (y, z fest) mit dem Dreieck in der YZ-Projektion
        let d = (b[1] - a[1]) * (c[2] - a[2]) - (c[1] - a[1]) * (b[2] - a[2]);
        if d.abs() < 1e-12 {
            continue;
        }
        let u = ((p[1] - a[1]) * (c[2] - a[2]) - (c[1] - a[1]) * (p[2] - a[2])) / d;
        let v = ((b[1] - a[1]) * (p[2] - a[2]) - (p[1] - a[1]) * (b[2] - a[2])) / d;
        if u < 0.0 || v < 0.0 || u + v > 1.0 {
            continue;
        }
        let x = a[0] + u * (b[0] - a[0]) + v * (c[0] - a[0]);
        if x > p[0] {
            n += 1;
        }
    }
    n % 2 == 1
}

/// Stecken zwei Körper wirklich ineinander (nicht nur die Hüllquader)?
fn really_overlap(a: &Mesh, b: &Mesh) -> bool {
    let probe = |small: &Mesh, big: &Mesh| -> bool {
        let step = (small.tris.len() / 6).max(1);
        small.tris.iter().step_by(step).take(6).any(|t| {
            // Punkt leicht ins Innere des kleinen Körpers versetzt (Dreiecksmitte)
            let c = [(t[0][0] + t[1][0] + t[2][0]) / 3.0, (t[0][1] + t[1][1] + t[2][1]) / 3.0, (t[0][2] + t[1][2] + t[2][2]) / 3.0];
            point_inside(big, [c[0] + 1.3e-4, c[1] + 0.7e-4, c[2] + 0.3e-4])
        })
    };
    probe(a, b) || probe(b, a)
}

fn is_tiny(m: &Mesh, ref_vol: f64) -> bool {
    let s = m.bbox().size();
    let v = m.volume().abs();
    let (mx, mn) = (s[0].max(s[1]).max(s[2]), s[0].min(s[1]).min(s[2]));
    mx < 20.0 || mn < 4.0 || v < (ref_vol * 0.002).max(3000.0)
}

pub fn split(objects: &[(String, Mesh)], p: &Params) -> Result<Output> {
    let mut out = Output::default();
    let printers = if p.printers.is_empty() { vec![main_printer(p)] } else { p.printers.clone() };
    let big = printers.iter().cloned().max_by(|a, b| (a.x * a.y * a.z).partial_cmp(&(b.x * b.y * b.z)).unwrap()).unwrap();
    let bed: V3 = [big.x - 2.0 * p.margin, big.y - 2.0 * p.margin, big.z];

    // Maßstab: größte Kante aller Objekte zusammen oder Prozent
    let mut all = Mesh::new();
    for (_, m) in objects {
        all.extend(m);
    }
    let s0 = all.bbox().size();
    let k = if p.size > 0.0 { p.size / s0[0].max(s0[1]).max(s0[2]).max(1e-9) } else { p.scale.max(0.1) / 100.0 };
    out.stat("Modellgröße", format!("{:.0} × {:.0} × {:.0} mm", s0[0] * k, s0[1] * k, s0[2] * k));
    if objects.len() > 1 {
        out.stat("Objekte", objects.len());
    }

    // Verbinder
    let kind = p.connector.as_str();
    let magnet = kind == "magnet";
    let use_conn = kind != "none" && if magnet { p.magnet_d > 0.0 && p.magnet_h > 0.0 } else { p.dowel_d > 0.0 && p.depth_ratio > 0.0 };
    let square = kind.ends_with("_sq");
    let r = p.dowel_d * 0.5;
    let clr = (-p.tolerance).max(0.0) * 0.5;
    let depth = if magnet { p.magnet_h + 0.1 } else { p.dowel_d * p.depth_ratio * 0.5 };
    let proto = |c: P2| -> Pocket {
        let side = |radius, ext, end_scale| section::Side { radius, ext, end_scale };
        match kind {
            "plug" | "plug_sq" => Pocket { center: c, square, lo: side(r, -depth, 1.0), hi: side(r + clr, depth + 0.4, 1.0) },
            "cone" => {
                let top = r * 0.45;
                Pocket { center: c, square: false, lo: side(r, -depth, top / r), hi: side(r + clr, depth + 0.4, (top + clr) / (r + clr)) }
            }
            "magnet" => {
                let mr = p.magnet_d * 0.5 + clr.max(0.1);
                Pocket { center: c, square: false, lo: side(mr, depth, 1.0), hi: side(mr, depth, 1.0) }
            }
            _ => {
                let hr = (p.dowel_d - p.tolerance) * 0.5;
                Pocket { center: c, square, lo: side(hr, depth, 1.0), hi: side(hr, depth, 1.0) }
            }
        }
    };
    let hole_r = proto([0.0, 0.0]).max_radius() * if square { 1.42 } else { 1.0 };
    let lo_has_plug = matches!(kind, "plug" | "plug_sq" | "cone");

    let mut parts: Vec<(String, Mesh)> = Vec::new();
    let mut preview: Vec<(String, Mesh)> = Vec::new();
    let mut n_conn = 0usize;
    let mut n_cuts = 0usize;
    let mut n_tiny = 0usize;
    let mut montage = String::from("Formwerk – Montage\n");
    let multi_obj = objects.len() > 1;

    for (oi, (oname, omesh)) in objects.iter().enumerate() {
        let mut m = omesh.clone();
        m.scale(k);
        let d0 = m.bbox().size();
        let label = if oname.trim().is_empty() { format!("Objekt {}", oi + 1) } else { oname.trim().to_string() };
        // passt schon? → nur auflegen
        if printers.iter().any(|pr| fits_upright(d0, pr, p.margin)) {
            preview.push((label.clone(), m.clone()));
            parts.push((label, m));
            continue;
        }
        // beste Drehung suchen (möglichst wenige Teile, gerne unverändert)
        let mut best: (usize, f64, M3) = (est_pieces(d0, bed), 0.0, IDENT);
        for base in [IDENT, rot(0, 90.0), rot(1, 90.0)] {
            for step in 0..12 {
                let ang = step as f64 * 7.5;
                if step == 0 && base == IDENT {
                    continue;
                }
                for ax in 0..3 {
                    let rr = mat_mul(&rot(ax, ang), &base);
                    let n = est_pieces(dims_after(&m, &rr), bed);
                    if n < best.0 {
                        best = (n, ang, rr);
                    }
                }
            }
        }
        let rmat = best.2;
        let back = mat_t(&rmat);
        let work = rotated(&m, &rmat);
        let ref_vol = work.volume().abs();

        // schrittweise schneiden
        let mut nodes: Vec<Node> = vec![Node::Cut(vec![])];
        let mut queue: Vec<Piece> = group_overlapping(section::split_components(&work))
            .into_iter()
            .map(|c| Piece { mesh: c, caps: vec![], feats: vec![], node: 0 })
            .collect();
        // Wurzel enthält die Startkörper
        let mut start_nodes = Vec::new();
        for pc in queue.iter_mut() {
            nodes.push(Node::Cut(vec![]));
            pc.node = nodes.len() - 1;
            start_nodes.push(pc.node);
        }
        nodes[0] = Node::Cut(start_nodes);
        let mut leaves: Vec<Piece> = Vec::new();
        let mut guard = 0;
        while let Some(pc) = queue.pop() {
            guard += 1;
            let bb = pc.mesh.bbox();
            let d = bb.size();
            if fits_any(d, bed) || guard > 400 {
                leaves.push(pc);
                continue;
            }
            // Kandidaten-Achsen: alle, die (in sortierter Zuordnung) zu lang sind, die längste zuerst
            let mut order: Vec<usize> = vec![0, 1, 2];
            order.sort_by(|&a, &b| d[b].partial_cmp(&d[a]).unwrap());
            let mut bs = bed;
            bs.sort_by(|x, y| y.partial_cmp(x).unwrap());
            let mut axes: Vec<(f64, usize, f64)> = (0..3)
                .filter(|&i| d[order[i]] > bs[i] + 1e-6)
                .map(|i| (d[order[i]] / bs[i], order[i], bs[i]))
                .collect();
            if axes.is_empty() {
                axes.push((1.0, order[0], bs[0]));
            }
            axes.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
            // Fenster je Achse: genau so viele Teile wie nötig; zweiter Versuch mit einem Teil mehr
            let window = |axis: usize, cell: f64, extra: bool| -> (f64, f64) {
                let (a0, len) = (bb.min[axis], d[axis]);
                let n = (len / cell).ceil().max(2.0) + if extra { 1.0 } else { 0.0 };
                let min_len = (cell * 0.15).max(15.0).min(len * 0.25);
                let mut lo_w = a0 + (len - (n - 1.0) * cell).max(min_len);
                let mut hi_w = a0 + cell.min(len - min_len);
                if extra {
                    // zweiter Versuch: überall schneiden, ein Stück darf dann noch einmal geteilt werden
                    return (a0 + min_len, a0 + len - min_len);
                }
                if lo_w > hi_w {
                    lo_w = a0 + (len - (n - 1.0) * cell).max(0.0);
                    hi_w = a0 + cell.min(len);
                }
                (lo_w, hi_w)
            };
            let mut chosen: Option<(usize, f64)> = None;
            let mut fallback: Option<(usize, f64, f64)> = None;
            'search: for extra in [false, true] {
                for &(_, axis, cell) in &axes {
                    let (lo_w, hi_w) = window(axis, cell, extra);
                    let mid = (lo_w + hi_w) * 0.5;
                    let mut cands: Vec<(f64, f64)> = (0..=32)
                        .map(|i| lo_w + (hi_w - lo_w) * i as f64 / 32.0)
                        .filter(|v| !pc.feats.iter().any(|(mn, mx)| *v > mn[axis] - 1.5 && *v < mx[axis] + 1.5))
                        .map(|v| {
                            let bias = 1.0 + 0.15 * ((v - mid).abs() / ((hi_w - lo_w) * 0.5 + 1e-9));
                            (section::section_area(&pc.mesh, axis, v) * bias, v)
                        })
                        .collect();
                    cands.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
                    let mut best_here: Option<(f64, f64)> = None;
                    for &(score, v) in cands.iter().take(16) {
                        let (lo, hi) = section::cut_bodies(&pc.mesh, axis, v, &[]);
                        let lc = group_overlapping(section::split_components(&lo));
                        let hc = group_overlapping(section::split_components(&hi));
                        if std::env::var("FORMWERK_DEBUG").is_ok() {
                            for c in lc.iter().chain(hc.iter()).filter(|c| is_tiny(c, ref_vol)) {
                                let b = c.bbox();
                                eprintln!("   Achse {axis} bei {v:.1}: Kleinteil {:.1}×{:.1}×{:.1} Vol {:.0}", b.size()[0], b.size()[1], b.size()[2], c.volume());
                            }
                        }
                        if !lc.iter().chain(hc.iter()).any(|c| is_tiny(c, ref_vol)) {
                            // Teile, die fertig wären, aber nicht flach auf einer Schnittfläche liegen können, kosten extra
                            let mut not_flat = 0;
                            for (list, sign) in [(&lc, 1.0), (&hc, -1.0)] {
                                for c in list.iter() {
                                    if !fits_any(c.bbox().size(), bed) {
                                        continue;
                                    }
                                    let cb = c.bbox();
                                    let mut caps: Vec<Cap> = pc.caps.iter().filter(|k| if k.sign > 0.0 { (cb.max[k.axis] - k.val).abs() < 0.01 } else { (cb.min[k.axis] - k.val).abs() < 0.01 }).cloned().collect();
                                    caps.push(Cap { axis, val: v, sign, plug: false });
                                    if !lies_flat(c, &caps, &printers, p.margin) {
                                        not_flat += 1;
                                    }
                                }
                            }
                            let s = score * (1.0 + 0.6 * not_flat as f64);
                            if best_here.is_none_or(|b| s < b.0) {
                                best_here = Some((s, v));
                            }
                            continue;
                        }
                        let worst_small = lc.iter().chain(hc.iter()).map(|c| c.volume().abs()).fold(f64::MAX, f64::min);
                        if !extra && fallback.is_none_or(|f| worst_small > f.2) {
                            fallback = Some((axis, v, worst_small));
                        }
                    }
                    if let Some((_, v)) = best_here {
                        chosen = Some((axis, v));
                        break 'search;
                    }
                }
            }
            if std::env::var("FORMWERK_DEBUG").is_ok() {
                eprintln!("Stück {:.0}×{:.0}×{:.0}: gewählt {:?}, Notlösung {:?}", d[0], d[1], d[2], chosen, fallback);
            }
            let (axis, v) = match (chosen, fallback) {
                (Some(c), _) => c,
                (None, Some(f)) => (f.0, f.1),
                (None, None) => {
                    let (lo_w, hi_w) = window(axes[0].1, axes[0].2, false);
                    (axes[0].1, (lo_w + hi_w) * 0.5)
                }
            };
            // Verbinder für diesen Schnitt
            let mut pockets = Vec::new();
            if use_conn {
                let polys = section::section(&pc.mesh, axis, v);
                let below = section::section(&pc.mesh, axis, v - depth - 0.5);
                let above = section::section(&pc.mesh, axis, v + depth + 0.5);
                let clear = hole_r + 2.0;
                for poly in &polys {
                    for c in pick_spots(poly, clear, &|q: P2| {
                        below.iter().any(|b| b.contains(q) && b.boundary_dist(q) > hole_r + 0.8)
                            && above.iter().any(|b| b.contains(q) && b.boundary_dist(q) > hole_r + 0.8)
                    }) {
                        pockets.push(proto(c));
                    }
                }
            }
            // Zapfen auf die Seite, die schon eine andere flache Schnittfläche hat (dann liegt sie darauf)
            let flat_on = |lower: bool| {
                pc.caps.iter().any(|c| !c.plug && if c.axis == axis { (c.val < v) == lower } else { true })
            };
            let plugs_on_hi = lo_has_plug && !flat_on(true) && flat_on(false);
            if plugs_on_hi {
                for pk in pockets.iter_mut() {
                    std::mem::swap(&mut pk.lo, &mut pk.hi);
                }
            }
            let (lo, hi) = section::cut_bodies(&pc.mesh, axis, v, &pockets);
            n_cuts += 1;
            n_conn += pockets.len();
            let mut feats = pc.feats.clone();
            for pk in &pockets {
                let rr = pk.max_radius() * 1.42 + 1.0;
                let c3 = section::to3(pk.center, axis, v);
                let mut mn = [c3[0] - rr, c3[1] - rr, c3[2] - rr];
                let mut mx = [c3[0] + rr, c3[1] + rr, c3[2] + rr];
                mn[axis] = v - depth - 1.0;
                mx[axis] = v + depth + 1.0;
                feats.push((mn, mx));
            }
            let mut children = Vec::new();
            for (half, sign) in [(lo, 1.0), (hi, -1.0)] {
                for comp in group_overlapping(section::split_components(&half)) {
                    let cb = comp.bbox();
                    let touches = |c: &Cap| {
                        if c.sign > 0.0 { (cb.max[c.axis] - c.val).abs() < 0.01 } else { (cb.min[c.axis] - c.val).abs() < 0.01 }
                    };
                    let mut caps: Vec<Cap> = pc.caps.iter().filter(|c| touches(c)).cloned().collect();
                    let plug_here = lo_has_plug && !pockets.is_empty() && ((sign > 0.0) != plugs_on_hi);
                    let new_cap = Cap { axis, val: v, sign, plug: plug_here };
                    if touches(&new_cap) {
                        caps.push(new_cap);
                    }
                    nodes.push(Node::Cut(vec![]));
                    let id = nodes.len() - 1;
                    children.push(id);
                    queue.push(Piece { mesh: comp, caps, feats: feats.clone(), node: id });
                }
            }
            nodes[pc.node] = Node::Cut(children);
        }

        // Blätter benennen, zum Drucken drehen
        leaves.sort_by(|a, b| {
            let (ca, cb) = (a.mesh.bbox(), b.mesh.bbox());
            (ca.min[2], ca.min[1], ca.min[0]).partial_cmp(&(cb.min[2], cb.min[1], cb.min[0])).unwrap()
        });
        let many = leaves.len() > 1;
        for (li, leaf) in leaves.into_iter().enumerate() {
            let tiny = is_tiny(&leaf.mesh, ref_vol);
            if tiny {
                n_tiny += 1;
            }
            let name = if !many {
                label.clone()
            } else if multi_obj {
                format!("{label} Teil {:02}", li + 1)
            } else {
                format!("Teil_{:02}", li + 1)
            };
            nodes[leaf.node] = Node::Leaf(name.clone());
            // Vorschau in Originallage
            preview.push((name.clone(), rotated(&leaf.mesh, &back)));
            parts.push((name, orient_for_print(&leaf.mesh, &leaf.caps, &printers, p.margin)));
        }
        // Montage: umgekehrte Schnittfolge
        if many {
            montage.push_str(&format!("\n{label}:\n"));
            let mut step = 1;
            let mut group_no = 0;
            fn walk(nodes: &[Node], i: usize, step: &mut usize, group_no: &mut usize, txt: &mut String) -> String {
                match &nodes[i] {
                    Node::Leaf(n) => n.clone(),
                    Node::Cut(ch) => {
                        let names: Vec<String> = ch.iter().map(|c| walk(nodes, *c, step, group_no, txt)).collect();
                        if names.len() == 1 {
                            return names[0].clone();
                        }
                        *group_no += 1;
                        let g = format!("Gruppe {}", group_no);
                        txt.push_str(&format!("  {}. {} verbinden → {}\n", step, names.join(" + "), g));
                        *step += 1;
                        g
                    }
                }
            }
            walk(&nodes, 0, &mut step, &mut group_no, &mut montage);
        }
    }

    let n_parts = parts.len();
    out.stat("Teile", n_parts);
    out.stat("Schnitte", n_cuts);
    if n_tiny > 0 {
        out.warnings.push(format!("{n_tiny} sehr kleine(s) Teil(e) ließ sich nicht vermeiden."));
    }
    if n_cuts == 0 {
        out.warnings.push("Alles passt ohne Schnitt auf die Platte – es wurde nur angeordnet.".into());
    }
    let conn_text = if use_conn && n_conn > 0 {
        match kind {
            "dowel" | "dowel_sq" => {
                let pin_l = (2.0 * depth - 1.0).max(1.0);
                let mut pin = if square { export::extrude(&[rect_poly(-r, -r, r, r)], pin_l, &|q, z| [q[0], q[1], z]) } else { cylinder(r, pin_l, 32) };
                pin.place_on_origin();
                out.files.push(("duebel.stl".into(), pin.to_stl("Duebel")));
                out.stat("Dübel", n_conn);
                let form = if square { format!("{:.1} × {:.1}", p.dowel_d, p.dowel_d) } else { format!("Ø {:.1}", p.dowel_d) };
                out.stat("Dübel je", format!("{form} × {:.1} mm", pin_l).replace('.', ","));
                format!("Dübel: {n_conn} Stück, siehe duebel.stl. Tipp: Filament Ø 1,75 mm geht als Dübel, wenn die Dübelgröße 1,7 mm ist.")
            }
            "plug" | "plug_sq" | "cone" => {
                out.stat(if kind == "cone" { "Kegelzapfen" } else { "Steckzapfen" }, n_conn);
                format!("{n_conn} Zapfen sind direkt angedruckt.")
            }
            "magnet" => {
                out.stat("Magnete", format!("{} ({} Paare)", n_conn * 2, n_conn));
                format!("Magnete: {} Stück Ø {:.0} × {:.0} mm ({} Paare). Vor dem Einkleben die Polung prüfen – gegenüberliegende Magnete müssen sich anziehen!", n_conn * 2, p.magnet_d, p.magnet_h, n_conn)
            }
            _ => String::new(),
        }
    } else {
        String::new()
    };
    if !conn_text.is_empty() {
        montage.push_str(&format!("\n{conn_text}\n"));
    }
    if n_cuts > 0 {
        out.files.push(("montage.txt".into(), montage.into_bytes()));
    }
    // Vorschau leicht auseinandergezogen
    let total = mesh_center(&preview);
    for (name, pm) in preview.iter_mut() {
        let c = mesh_center(&[(String::new(), pm.clone())]);
        pm.translate([(c[0] - total[0]) * 0.12, (c[1] - total[1]) * 0.12, (c[2] - total[2]) * 0.12]);
        let _ = name;
    }
    out.preview = preview;
    emit_parts(&mut out, parts, p, "teile");
    Ok(out)
}

/// Kann das Teil auf einer flachen Schnittfläche (ohne Zapfen) liegen und passt dann aufs Bett?
fn lies_flat(m: &Mesh, caps: &[Cap], printers: &[Printer], margin: f64) -> bool {
    caps.iter().filter(|c| !c.plug).any(|c| printers.iter().any(|pr| fits_upright(dims_after(m, &down_mat(c.axis, c.sign)), pr, margin)))
}

fn down_mat(axis: usize, sign: f64) -> M3 {
    match (axis, sign > 0.0) {
        (2, true) => [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]],
        (2, false) => IDENT,
        (0, true) => [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]],
        (0, false) => [[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
        (1, true) => [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]],
        _ => [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
    }
}

/// Teil so drehen, dass eine Schnittfläche (ohne Zapfen, möglichst groß) unten liegt
fn orient_for_print(m: &Mesh, caps: &[Cap], printers: &[Printer], margin: f64) -> Mesh {
    let down = down_mat;
    let fits = |r: &M3| printers.iter().any(|pr| fits_upright(dims_after(m, r), pr, margin));
    if std::env::var("FORMWERK_DEBUG").is_ok() {
        let s = m.bbox();
        eprintln!("Teil {:.0}×{:.0}×{:.0}: Flächen {:?}", s.size()[0], s.size()[1], s.size()[2], caps.iter().map(|c| (c.axis, c.sign, c.plug, (c.val - if c.sign > 0.0 { s.max[c.axis] } else { s.min[c.axis] }).abs() < 0.01, fits(&down(c.axis, c.sign)))).collect::<Vec<_>>());
    }
    // flache Schnittflächen nach unten; Flächen mit Zapfen nach oben (dann liegt die Gegenseite unten)
    let mut cands: Vec<(bool, f64, M3)> = caps
        .iter()
        .map(|c| {
            let area = section::section_area(m, c.axis, c.val - c.sign * 0.05);
            if c.plug { (true, area, down(c.axis, -c.sign)) } else { (false, area, down(c.axis, c.sign)) }
        })
        .collect();
    cands.sort_by(|a, b| a.0.cmp(&b.0).then(b.1.partial_cmp(&a.1).unwrap()));
    for (_, _, r) in &cands {
        if fits(r) {
            return rotated(m, r);
        }
    }
    if fits(&IDENT) {
        return m.clone();
    }
    for (ax, s) in [(0, 1.0), (0, -1.0), (1, 1.0), (1, -1.0), (2, 1.0)] {
        let r = down(ax, s);
        if fits(&r) {
            return rotated(m, &r);
        }
    }
    m.clone()
}

fn mesh_center(parts: &[(String, Mesh)]) -> V3 {
    let mut mn = [f64::MAX; 3];
    let mut mx = [f64::MIN; 3];
    for (_, m) in parts {
        let b = m.bbox();
        for i in 0..3 {
            mn[i] = mn[i].min(b.min[i]);
            mx[i] = mx[i].max(b.max[i]);
        }
    }
    [(mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, (mn[2] + mx[2]) * 0.5]
}

/// Bis zu einige gut verteilte Punkte mit Randabstand ≥ `clear`
fn pick_spots(poly: &Poly, clear: f64, ok: &dyn Fn(P2) -> bool) -> Vec<P2> {
    let (mn, mx) = poly.bbox();
    let span = (mx[0] - mn[0]).max(mx[1] - mn[1]);
    let step = (span / 30.0).max(1.0);
    let mut cands: Vec<(f64, P2)> = Vec::new();
    let mut y = mn[1] + step * 0.5;
    while y < mx[1] {
        let mut x = mn[0] + step * 0.5;
        while x < mx[0] {
            let q = [x, y];
            if poly.contains(q) {
                let d = poly.boundary_dist(q);
                if d >= clear && ok(q) {
                    cands.push((d, q));
                }
            }
            x += step;
        }
        y += step;
    }
    cands.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    let area = poly.area();
    let want = ((area / 2500.0).sqrt().ceil() as usize).clamp(1, 6);
    let min_gap = (clear * 4.0).max(span / 4.0);
    let mut chosen: Vec<P2> = Vec::new();
    for (_, q) in cands {
        if chosen.len() >= want {
            break;
        }
        if chosen.iter().all(|c| ((c[0] - q[0]).powi(2) + (c[1] - q[1]).powi(2)).sqrt() >= min_gap) {
            chosen.push(q);
        }
    }
    chosen
}

pub fn cylinder(r: f64, h: f64, n: usize) -> Mesh {
    let ring = section::circle([0.0, 0.0], r, n);
    export::extrude(&[Poly { outer: ring, holes: vec![] }], h, &|q, z| [q[0], q[1], z])
}


fn rect_poly(x0: f64, y0: f64, x1: f64, y1: f64) -> Poly {
    Poly { outer: vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]], holes: vec![] }
}

/// Teil größer als Bogen → in Stücke teilen

impl Mesh {
    /// Orientierung eines kleinen, geschlossenen Teilkörpers korrigieren (Volumen relativ zum eigenen Schwerpunkt)
    pub fn fix_orientation_local(&mut self) {
        let mut c = [0.0; 3];
        let mut n = 0.0;
        for t in &self.tris {
            for p in t {
                c = crate::mesh::add(c, *p);
                n += 1.0;
            }
        }
        if n == 0.0 {
            return;
        }
        let c = crate::mesh::mul(c, 1.0 / n);
        let vol: f64 = self
            .tris
            .iter()
            .map(|t| crate::mesh::dot(crate::mesh::sub(t[0], c), crate::mesh::cross(crate::mesh::sub(t[1], c), crate::mesh::sub(t[2], c))))
            .sum();
        if vol < 0.0 {
            self.flip();
        }
    }
}

