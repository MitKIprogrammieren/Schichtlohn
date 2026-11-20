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
    /// Modellgröße: größte Kante (mm)
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
            size: 600.0,
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
            out.stat(&format!("P{} {}", pi + 1, pr.name), format!("{} Platten", n_pl));
        }
    }
    out.plates = total_plates;
}

fn sanitize(s: &str) -> String {
    s.chars().map(|c| if c.is_alphanumeric() || c == '-' { c } else { '_' }).collect()
}

// ───────────────────────── Teilen aufs Druckbett ─────────────────────────

pub fn scaled(mesh: &Mesh, size: f64) -> Mesh {
    let mut m = mesh.clone();
    m.place_on_origin();
    let s = m.bbox().size();
    let k = size / s[0].max(s[1]).max(s[2]).max(1e-9);
    m.scale(k);
    m
}

fn even_cuts(len: f64, max: f64) -> Vec<f64> {
    let n = (len / max).ceil().max(1.0) as usize;
    (1..n).map(|i| len * i as f64 / n as f64).collect()
}

pub fn split(mesh: &Mesh, p: &Params) -> Result<Output> {
    let mut out = Output::default();
    let m = scaled(mesh, p.size);
    let s = m.bbox().size();
    // Zellgröße nach dem größten Drucker, damit jedes Teil wenigstens dort passt
    let big = p.printers.iter().cloned().max_by(|a, b| (a.x * a.y * a.z).partial_cmp(&(b.x * b.y * b.z)).unwrap()).unwrap_or(main_printer(p));
    let cell = [big.x - 2.0 * p.margin, big.y - 2.0 * p.margin, big.z];
    let cuts: [Vec<f64>; 3] = [even_cuts(s[0], cell[0]), even_cuts(s[1], cell[1]), even_cuts(s[2], cell[2])];
    let n_cells = (cuts[0].len() + 1) * (cuts[1].len() + 1) * (cuts[2].len() + 1);
    out.stat("Modellgröße", format!("{:.0} × {:.0} × {:.0} mm", s[0], s[1], s[2]));
    out.stat("Raster", format!("{} × {} × {}", cuts[0].len() + 1, cuts[1].len() + 1, cuts[2].len() + 1));
    if n_cells == 1 {
        out.warnings.push("Das Modell passt in einem Stück auf die Platte – es wird nicht geteilt.".into());
    }
    // Verbinder je Schnittebene vorab bestimmen
    let kind = p.connector.as_str();
    let magnet = kind == "magnet";
    let use_conn = kind != "none" && if magnet { p.magnet_d > 0.0 && p.magnet_h > 0.0 } else { p.dowel_d > 0.0 && p.depth_ratio > 0.0 };
    let square = kind.ends_with("_sq");
    let r = p.dowel_d * 0.5;
    let clr = (-p.tolerance).max(0.0) * 0.5; // Spiel je Seite
    let depth = if magnet { p.magnet_h + 0.1 } else { p.dowel_d * p.depth_ratio * 0.5 };
    let proto = |c: P2| -> Pocket {
        let side = |radius, ext, end_scale| section::Side { radius, ext, end_scale };
        match kind {
            "plug" | "plug_sq" => Pocket { center: c, square, lo: side(r, -depth, 1.0), hi: side(r + clr, depth + 0.4, 1.0) },
            "cone" => {
                let top = r * 0.45;
                let hs = (top + clr) / (r + clr);
                Pocket { center: c, square: false, lo: side(r, -depth, top / r), hi: side(r + clr, depth + 0.4, hs) }
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
    let mut pockets: Vec<Vec<Vec<Pocket>>> = vec![vec![]; 3];
    let mut n_pockets = 0usize;
    for a in 0..3 {
        for &v in &cuts[a] {
            let mut list = Vec::new();
            if use_conn {
                let polys = section::section(&m, a, v);
                let below = section::section(&m, a, v - depth - 0.5);
                let above = section::section(&m, a, v + depth + 0.5);
                // andere Schnittlinien in dieser Ebene meiden
                let (u_ax, v_ax) = match a {
                    0 => (1, 2),
                    1 => (0, 2),
                    _ => (0, 1),
                };
                let clear = hole_r + 2.0;
                for poly in &polys {
                    let spots = pick_spots(poly, clear, &|q: P2| {
                        cuts[u_ax].iter().all(|c| (q[0] - c).abs() > clear)
                            && cuts[v_ax].iter().all(|c| (q[1] - c).abs() > clear)
                            && below.iter().any(|b| b.contains(q) && b.boundary_dist(q) > hole_r + 0.8)
                            && above.iter().any(|b| b.contains(q) && b.boundary_dist(q) > hole_r + 0.8)
                    });
                    for c in spots {
                        list.push(proto(c));
                    }
                }
            }
            n_pockets += list.len();
            pockets[a].push(list);
        }
    }
    // Schneiden: jeden Körper einzeln (überlappende Körper bleiben so geschlossen), erst X, dann Y, dann Z
    let mut cells: std::collections::BTreeMap<(usize, usize, usize), Vec<Mesh>> = Default::default();
    for body in section::split_components(&m) {
        let mut pieces: Vec<(Mesh, [usize; 3])> = vec![(body, [0, 0, 0])];
        for a in 0..3 {
            let mut next = Vec::new();
            for (piece, idx) in pieces {
                let pb = piece.bbox();
                let mut rest = piece;
                for (k, &v) in cuts[a].iter().enumerate() {
                    if v <= pb.min[a] || v >= pb.max[a] {
                        if v >= pb.max[a] {
                            // ganz unterhalb dieser Ebene
                            let mut id = idx;
                            id[a] = k;
                            if !rest.is_empty() {
                                next.push((std::mem::take(&mut rest), id));
                            }
                            break;
                        }
                        continue;
                    }
                    let (lo, hi) = section::cut(&rest, a, v, &pockets[a][k]);
                    let mut id = idx;
                    id[a] = k;
                    if !lo.is_empty() {
                        next.push((lo, id));
                    }
                    rest = hi;
                }
                if !rest.is_empty() {
                    let mut id = idx;
                    id[a] = cuts[a].iter().filter(|&&c| c < rest.bbox().min[a] + 1e-9).count();
                    next.push((rest, id));
                }
            }
            pieces = next;
        }
        for (pm, id) in pieces {
            cells.entry((id[2], id[1], id[0])).or_default().extend(section::split_components(&pm));
        }
    }
    // Zusammenhängende Teile je Zelle: überlappende Körper (Hüllquader) zusammenfassen
    let mut parts: Vec<(String, Mesh)> = Vec::new();
    let mut tiny = 0;
    let mut grid_names: Vec<([usize; 3], String)> = Vec::new();
    let mut n = 0;
    for ((z, y, x), comps) in cells {
        let boxes: Vec<_> = comps.iter().map(|c| c.bbox()).collect();
        let mut group: Vec<usize> = (0..comps.len()).collect();
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
                let overlap = (0..3).all(|k| a.min[k] < b.max[k] - 0.05 && b.min[k] < a.max[k] - 0.05);
                if overlap {
                    let (ri, rj) = (root(&mut group, i), root(&mut group, j));
                    group[rj] = ri;
                }
            }
        }
        let mut merged: std::collections::BTreeMap<usize, Mesh> = Default::default();
        for (i, c) in comps.into_iter().enumerate() {
            let r = root(&mut group, i);
            merged.entry(r).or_default().extend(&c);
        }
        let mut list: Vec<Mesh> = merged.into_values().collect();
        list.sort_by(|a, b| b.volume().abs().partial_cmp(&a.volume().abs()).unwrap());
        for comp in list {
            let vol = comp.volume().abs();
            if vol < 20.0 {
                tiny += 1;
                if vol > 0.01 {
                    parts.push((format!("Klein_{tiny}"), comp));
                }
                continue;
            }
            n += 1;
            let name = format!("Teil_{n:02}");
            grid_names.push(([x, y, z], name.clone()));
            parts.push((name, comp));
        }
    }
    out.stat("Teile", n);
    if tiny > 0 {
        out.stat("Kleinstteile", tiny);
    }
    let conn_text = match kind {
        "dowel" | "dowel_sq" => {
            let pin_l = (2.0 * depth - 1.0).max(1.0);
            let mut pin = if square {
                export::extrude(&[rect_poly(-r, -r, r, r)], pin_l, &|q, z| [q[0], q[1], z])
            } else {
                cylinder(r, pin_l, 32)
            };
            pin.place_on_origin();
            out.files.push(("duebel.stl".into(), pin.to_stl("Duebel")));
            out.stat("Dübel", n_pockets);
            let form = if square { format!("{:.1} × {:.1}", p.dowel_d, p.dowel_d) } else { format!("Ø {:.1}", p.dowel_d) };
            out.stat("Dübel je", format!("{form} × {:.1} mm", pin_l).replace('.', ","));
            format!("Dübel: {n_pockets} Stück, siehe duebel.stl. Tipp: Filament Ø 1,75 mm geht als Dübel, wenn die Dübelgröße 1,7 mm ist.")
        }
        "plug" | "plug_sq" | "cone" => {
            out.stat(if kind == "cone" { "Kegelzapfen" } else { "Steckzapfen" }, n_pockets);
            format!("{n_pockets} Zapfen sind direkt angedruckt (immer am Teil links/vorne/unten der Schnittfläche). Zapfen nach oben drucken oder Stützen nutzen.")
        }
        "magnet" => {
            out.stat("Magnete", format!("{} ({} Paare)", n_pockets * 2, n_pockets));
            format!("Magnete: {} Stück Ø {:.0} × {:.0} mm ({} Paare). Vor dem Einkleben die Polung prüfen – gegenüberliegende Magnete müssen sich anziehen!", n_pockets * 2, p.magnet_d, p.magnet_h, n_pockets)
        }
        _ => String::new(),
    };
    // Vorschau: leicht auseinandergezogen
    let total = mesh_center(&parts);
    for (name, m) in &parts {
        let mut pm = m.clone();
        let c = mesh_center(&[(String::new(), m.clone())]);
        let d = [(c[0] - total[0]) * 0.12, (c[1] - total[1]) * 0.12, (c[2] - total[2]) * 0.12];
        pm.translate(d);
        out.preview.push((name.clone(), pm));
    }
    // Montagereihenfolge = umgekehrte Schnittreihenfolge
    let mut txt = String::from("Formwerk – Montagereihenfolge\n\nGeschnitten wurde erst entlang X, dann Y, dann Z.\nZusammengebaut wird umgekehrt:\n\n");
    let (nx, ny, nz) = (cuts[0].len() + 1, cuts[1].len() + 1, cuts[2].len() + 1);
    let names_at = |f: &dyn Fn(&[usize; 3]) -> bool| -> String {
        grid_names.iter().filter(|(id, _)| f(id)).map(|(_, n)| n.clone()).collect::<Vec<_>>().join(", ")
    };
    let mut step = 1;
    if nz > 1 {
        for x in 0..nx {
            for y in 0..ny {
                let s = names_at(&|id| id[0] == x && id[1] == y);
                if s.contains(',') {
                    txt.push_str(&format!("{step}. Säule übereinander (unten → oben): {s}\n"));
                    step += 1;
                }
            }
        }
    }
    if ny > 1 {
        for x in 0..nx {
            let s = names_at(&|id| id[0] == x);
            if s.contains(',') {
                txt.push_str(&format!("{step}. Scheibe X{} in Y-Richtung verbinden: {s}\n", x + 1));
                step += 1;
            }
        }
    }
    if nx > 1 {
        txt.push_str(&format!("{step}. Alle Scheiben in X-Richtung verbinden.\n"));
    }
    if use_conn && !conn_text.is_empty() {
        txt.push_str(&format!("\n{conn_text}\n"));
    }
    out.files.push(("montage.txt".into(), txt.into_bytes()));
    emit_parts(&mut out, parts, p, "teile");
    Ok(out)
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

