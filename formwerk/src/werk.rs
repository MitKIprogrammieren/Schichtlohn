//! Die Formwerk-Generatoren (angelehnt an LuBan): Lithophane, Relief, Teilen, Stack, Hash, Wireframe.
use crate::export::{self, PlatePart, Sheet2D};
use crate::heightmap::{self, Grid};
use crate::mesh::{Mesh, V3};
use crate::section::{self, P2, Pocket, Poly};
use anyhow::{Result, bail};
use geo::{BooleanOps, Buffer, MultiPolygon};
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
    pub mode: String,
    pub printers: Vec<Printer>,
    /// Abstand zum Bettrand (mm)
    pub margin: f64,
    /// Modellgröße: größte Kante (mm)
    pub size: f64,
    // Lithophane / Relief
    pub min_t: f64,
    pub max_t: f64,
    pub resolution: f64,
    pub negative: bool,
    pub interior: bool,
    pub border_size: f64,
    pub border_t: f64,
    pub base_t: f64,
    pub relief_t: f64,
    pub bury: f64,
    pub direction: String,
    pub blur: usize,
    // Teilen
    pub connector: String,
    pub dowel_d: f64,
    pub depth_ratio: f64,
    pub tolerance: f64,
    pub magnet_d: f64,
    pub magnet_h: f64,
    pub puzzle: bool,
    // Stack / Hash
    pub axis: String,
    pub sheet_t: f64,
    pub sheet_w: f64,
    pub sheet_h: f64,
    pub ring_w: f64,
    pub engrave_next: bool,
    pub x_layers: usize,
    pub y_layers: usize,
    pub z_layers: usize,
    pub wire_t: f64,
}

impl Default for Params {
    fn default() -> Self {
        Params {
            mode: "lithophane".into(),
            printers: vec![Printer { name: "Bambu Lab H2C".into(), x: 256.0, y: 256.0, z: 256.0, speed: 1.0 }],
            margin: 5.0,
            size: 200.0,
            min_t: 0.6,
            max_t: 2.4,
            resolution: 0.2,
            negative: false,
            interior: false,
            border_size: 3.0,
            border_t: 3.0,
            base_t: 2.0,
            relief_t: 5.0,
            bury: 0.0,
            direction: "+Z".into(),
            blur: 0,
            connector: "dowel".into(),
            dowel_d: 5.0,
            depth_ratio: 2.0,
            tolerance: -0.2,
            magnet_d: 6.0,
            magnet_h: 3.0,
            puzzle: false,
            axis: "Z".into(),
            sheet_t: 3.0,
            sheet_w: 400.0,
            sheet_h: 300.0,
            ring_w: 0.0,
            engrave_next: true,
            x_layers: 8,
            y_layers: 0,
            z_layers: 8,
            wire_t: 2.0,
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
    pub sheets: usize,
}

impl Output {
    fn stat(&mut self, k: &str, v: impl ToString) {
        self.summary.push((k.into(), v.to_string()));
    }
}

fn fmt_tris(n: usize) -> String {
    if n > 1_000_000 { format!("{:.1} Mio", n as f64 / 1e6).replace('.', ",") } else { format!("{n}") }
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

// ───────────────────────── Lithophane ─────────────────────────

pub fn lithophane(img: &image::DynamicImage, p: &Params, relief: bool) -> Result<Output> {
    let mut out = Output::default();
    let (iw, ih) = (img.width() as f64, img.height() as f64);
    let (w, h) = if iw >= ih { (p.size, p.size * ih / iw) } else { (p.size * iw / ih, p.size) };
    let res = p.resolution.max(0.05);
    let nx = (w / res).round() as usize + 1;
    let ny = (h / res).round() as usize + 1;
    if nx * ny > 40_000_000 {
        bail!("Zu fein: {nx}×{ny} Punkte. Bitte die Auflösung erhöhen (größerer mm-Wert).");
    }
    let mut lum = heightmap::luminance(img, nx, ny);
    heightmap::box_blur(&mut lum, nx, ny, p.blur);
    let hgt: Vec<f64> = if relief {
        if p.relief_t <= 0.0 {
            bail!("Relief-Dicke muss > 0 sein.");
        }
        let base = p.base_t.max(0.4);
        lum.iter().map(|l| {
            let v = if p.negative { 1.0 - l } else { *l };
            base + v * p.relief_t
        }).collect()
    } else {
        if p.min_t <= 0.0 || p.max_t <= p.min_t {
            bail!("Dicke: min muss > 0 und kleiner als max sein.");
        }
        lum.iter().map(|l| {
            let dark = if p.negative { *l } else { 1.0 - l };
            p.min_t + dark * (p.max_t - p.min_t)
        }).collect()
    };
    let mut g = Grid { nx, ny, dx: w / (nx - 1) as f64, dy: h / (ny - 1) as f64, h: hgt };
    if p.border_size > 0.0 {
        let top = if relief { p.base_t.max(0.4) + p.border_t.max(0.0) } else { p.border_t.max(p.max_t * 1.05) };
        if !relief && p.border_t < p.max_t * 1.05 {
            out.warnings.push(format!("Randdicke auf {:.2} mm angehoben (mind. 5 % über max. Dicke).", top));
        }
        g.set_border(p.border_size, top);
    }
    if p.interior {
        g.mirror_x();
    }
    finish_grid(&mut out, g, p, if relief { "relief" } else { "lithophane" });
    Ok(out)
}

fn finish_grid(out: &mut Output, g: Grid, p: &Params, prefix: &str) {
    let pr = main_printer(p);
    let (mw, mh) = (pr.x - 2.0 * p.margin, pr.y - 2.0 * p.margin);
    let tiles = if p.puzzle && (g.width() > mw || g.height() > mh) { g.puzzle_tiles(mw, mh, 0.3) } else { g.tiles(mw, mh) };
    let cols = tiles.iter().map(|t| t.0 + 1).max().unwrap_or(1);
    let rows = tiles.iter().map(|t| t.1 + 1).max().unwrap_or(1);
    let tris: usize = tiles.iter().map(|t| t.2.tris.len()).sum();
    out.stat("Endgröße", format!("{:.0} × {:.0} × {:.1} mm", g.width(), g.height(), g.max_h()).replace('.', ","));
    out.stat("Raster", format!("{} × {} Punkte", g.nx, g.ny));
    out.stat("Kacheln", format!("{} ({} × {})", tiles.len(), cols, rows));
    out.stat("Dreiecke", fmt_tris(tris));
    out.stat("Dateigröße STL", format!("{:.0} MB", (tris * 50) as f64 / 1e6));
    let parts: Vec<(String, Mesh)> = tiles
        .into_iter()
        .map(|(c, r, m)| (if cols * rows == 1 { prefix.to_string() } else { format!("{prefix}_S{}_Z{}", c + 1, rows - r) }, m))
        .collect();
    // Vorschau aus verkleinertem Raster, gleiche Kachelung
    let small = g.downsample(250_000);
    let small_tiles = if p.puzzle && (g.width() > mw || g.height() > mh) { small.puzzle_tiles(mw, mh, 0.3) } else { small.tiles(mw, mh) };
    for (c, r, m) in small_tiles {
        out.preview.push((format!("Kachel {}-{}", c + 1, r + 1), m));
    }
    emit_parts(out, parts, p, prefix);
}

// ───────────────────────── Relief aus 3D-Modell ─────────────────────────

fn orient(dir: &str) -> fn(V3) -> V3 {
    match dir {
        "-Z" => |p| [p[0], -p[1], -p[2]],
        "+X" => |p| [p[1], p[2], p[0]],
        "-X" => |p| [-p[1], p[2], -p[0]],
        "+Y" => |p| [p[2], p[0], p[1]],
        "-Y" => |p| [-p[2], p[0], -p[1]],
        _ => |p| p,
    }
}

pub fn relief_mesh(mesh: &Mesh, p: &Params) -> Result<Output> {
    let mut out = Output::default();
    let mut m = mesh.clone();
    m.map(orient(&p.direction));
    m.place_on_origin();
    let s = m.bbox().size();
    let k = p.size / s[0].max(s[1]).max(1e-9);
    m.scale(k);
    let s = m.bbox().size();
    let res = p.resolution.max(0.05);
    let nx = (s[0] / res).ceil() as usize + 1;
    let ny = (s[1] / res).ceil() as usize + 1;
    if nx * ny > 40_000_000 {
        bail!("Zu fein: {nx}×{ny} Punkte. Bitte die Auflösung erhöhen.");
    }
    let mut zb = vec![f64::NAN; nx * ny];
    for t in &m.tris {
        let (a, b, c) = (t[0], t[1], t[2]);
        let minx = ((a[0].min(b[0]).min(c[0]) / res).floor().max(0.0)) as usize;
        let maxx = ((a[0].max(b[0]).max(c[0]) / res).ceil() as usize).min(nx - 1);
        let miny = ((a[1].min(b[1]).min(c[1]) / res).floor().max(0.0)) as usize;
        let maxy = ((a[1].max(b[1]).max(c[1]) / res).ceil() as usize).min(ny - 1);
        let den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
        if den.abs() < 1e-12 {
            continue;
        }
        for y in miny..=maxy {
            for x in minx..=maxx {
                let (px, py) = (x as f64 * res, y as f64 * res);
                let l1 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / den;
                let l2 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / den;
                let l3 = 1.0 - l1 - l2;
                if l1 >= -1e-9 && l2 >= -1e-9 && l3 >= -1e-9 {
                    let z = l1 * a[2] + l2 * b[2] + l3 * c[2];
                    let cell = &mut zb[y * nx + x];
                    if cell.is_nan() || z > *cell {
                        *cell = z;
                    }
                }
            }
        }
    }
    let (zmin, zmax) = zb.iter().filter(|z| !z.is_nan()).fold((f64::MAX, f64::MIN), |(a, b), z| (a.min(*z), b.max(*z)));
    if zmin > zmax {
        bail!("Das Modell konnte nicht abgetastet werden.");
    }
    let base = p.base_t.max(0.4);
    let bury = p.bury.clamp(0.0, 0.95);
    let hgt: Vec<f64> = zb
        .iter()
        .map(|z| {
            let v = if z.is_nan() { 0.0 } else { (((z - zmin) / (zmax - zmin).max(1e-9)) - bury).max(0.0) / (1.0 - bury) };
            if p.negative { base + (1.0 - v) * p.relief_t } else { base + v * p.relief_t }
        })
        .collect();
    let mut g = Grid { nx, ny, dx: res, dy: res, h: hgt };
    if p.border_size > 0.0 && p.border_t > 0.0 {
        g.set_border(p.border_size, base + p.border_t);
    }
    finish_grid(&mut out, g, p, "relief");
    Ok(out)
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

// ───────────────────────── Stack ─────────────────────────

fn axis_index(s: &str) -> usize {
    match s {
        "X" | "x" => 0,
        "Y" | "y" => 1,
        _ => 2,
    }
}

fn rect_poly(x0: f64, y0: f64, x1: f64, y1: f64) -> Poly {
    Poly { outer: vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]], holes: vec![] }
}

/// Teil größer als Bogen → in Stücke teilen
fn segment_to_sheet(polys: Vec<Poly>, w: f64, h: f64) -> Vec<Vec<Poly>> {
    let mut out = Vec::new();
    for poly in polys {
        let (mn, mx) = poly.bbox();
        let (pw, ph) = (mx[0] - mn[0], mx[1] - mn[1]);
        let fits = (pw <= w && ph <= h) || (ph <= w && pw <= h);
        if fits {
            out.push(vec![poly]);
            continue;
        }
        let cx = (pw / w).ceil().max(1.0) as usize;
        let cy = (ph / h).ceil().max(1.0) as usize;
        let g = MultiPolygon::new(vec![poly.to_geo()]);
        for i in 0..cx {
            for j in 0..cy {
                let r = rect_poly(
                    mn[0] + pw * i as f64 / cx as f64,
                    mn[1] + ph * j as f64 / cy as f64,
                    mn[0] + pw * (i + 1) as f64 / cx as f64,
                    mn[1] + ph * (j + 1) as f64 / cy as f64,
                );
                let piece = g.intersection(&MultiPolygon::new(vec![r.to_geo()]));
                for pp in section::multi_to_polys(&piece) {
                    if pp.area() > 1.0 {
                        out.push(vec![pp]);
                    }
                }
            }
        }
    }
    out
}

fn place_fn(axis: usize, at: f64) -> impl Fn(P2, f64) -> V3 {
    move |q: P2, t: f64| section::to3(q, axis, at + t)
}

pub fn stack(mesh: &Mesh, p: &Params) -> Result<Output> {
    let mut out = Output::default();
    let m = scaled(mesh, p.size);
    let a = axis_index(&p.axis);
    let b = m.bbox();
    let t = p.sheet_t.max(0.3);
    let n_layers = ((b.size()[a] / t).floor() as usize).max(1);
    if n_layers > 2000 {
        bail!("Zu viele Schichten ({n_layers}). Materialdicke erhöhen oder Modell verkleinern.");
    }
    // Querschnitte
    let mut layers: Vec<Vec<Poly>> = (0..n_layers).map(|i| section::section(&m, a, b.min[a] + t * (i as f64 + 0.5))).collect();
    // Ringe
    if p.ring_w > 0.0 {
        for l in layers.iter_mut() {
            let g = section::polys_to_multi(l);
            let inner = g.buffer(-p.ring_w);
            *l = section::multi_to_polys(&g.difference(&inner));
        }
    }
    // Dübellöcher zwischen Nachbarschichten
    let mut holes: Vec<Vec<P2>> = vec![Vec::new(); n_layers];
    let r = p.dowel_d * 0.5;
    if r > 0.0 {
        for i in 0..n_layers.saturating_sub(1) {
            let next = layers[i + 1].clone();
            for poly in &layers[i] {
                let spots = pick_spots(poly, r + 2.0, &|q| {
                    next.iter().any(|n| n.contains(q) && n.boundary_dist(q) > r + 2.0)
                });
                for s in spots.into_iter().take(2) {
                    holes[i].push(s);
                    holes[i + 1].push(s);
                }
            }
        }
    }
    let mut sheet_parts: Vec<Sheet2D> = Vec::new();
    let mut preview = Mesh::new();
    let mut preview_odd = Mesh::new();
    let mut parts3d: Vec<(String, Mesh)> = Vec::new();
    for i in 0..n_layers {
        let mut polys = layers[i].clone();
        if !holes[i].is_empty() {
            let mut hs: Vec<P2> = holes[i].clone();
            hs.dedup_by(|x, y| (x[0] - y[0]).abs() < 1e-6 && (x[1] - y[1]).abs() < 1e-6);
            let circles = MultiPolygon::new(hs.iter().map(|c| Poly { outer: section::circle(*c, r, 24), holes: vec![] }.to_geo()).collect());
            polys = section::multi_to_polys(&section::polys_to_multi(&polys).difference(&circles));
        }
        let at = b.min[a] + t * i as f64;
        let place = place_fn(a, at);
        if i % 2 == 0 { &mut preview } else { &mut preview_odd }.extend(&export::extrude(&polys, t, &place));
        let engrave: Vec<Vec<P2>> = if p.engrave_next && i + 1 < n_layers {
            layers[i + 1].iter().flat_map(|q| {
                let mut v = vec![q.outer.clone()];
                v.extend(q.holes.clone());
                v
            }).map(|mut r| {
                if let Some(f) = r.first().cloned() {
                    r.push(f);
                }
                r
            }).collect()
        } else {
            vec![]
        };
        for (j, poly) in polys.iter().enumerate() {
            let segs = segment_to_sheet(vec![poly.clone()], p.sheet_w - 10.0, p.sheet_h - 10.0);
            let multi = segs.len() > 1;
            for (k, seg) in segs.into_iter().enumerate() {
                let label = if multi { format!("{}.{}.{}", i + 1, j + 1, k + 1) } else { format!("{}.{}", i + 1, j + 1) };
                // Gravur nur innerhalb dieses Teils behalten (grob: Punkte innerhalb)
                let (mn, mx) = seg.iter().map(|q| q.bbox()).fold(([f64::MAX; 2], [f64::MIN; 2]), |acc, bb| {
                    ([acc.0[0].min(bb.0[0]), acc.0[1].min(bb.0[1])], [acc.1[0].max(bb.1[0]), acc.1[1].max(bb.1[1])])
                });
                let eng: Vec<Vec<P2>> = engrave
                    .iter()
                    .map(|l| l.iter().cloned().filter(|q| q[0] >= mn[0] && q[0] <= mx[0] && q[1] >= mn[1] && q[1] <= mx[1] && seg.iter().any(|s| s.contains(*q))).collect::<Vec<_>>())
                    .filter(|l| l.len() > 1)
                    .collect();
                let flat = export::extrude(&seg, t, &|q, z| [q[0], q[1], z]);
                parts3d.push((format!("Schicht_{}", label.replace('.', "-")), flat));
                sheet_parts.push(Sheet2D { label, polys: seg, engrave: eng });
            }
        }
    }
    out.stat("Schichten", n_layers);
    out.stat("Teile", sheet_parts.len());
    emit_sheets(&mut out, sheet_parts, p, "stack");
    out.preview.push(("Schichten 1, 3, 5 …".into(), preview));
    out.preview.push(("Schichten 2, 4, 6 …".into(), preview_odd));
    if p.dowel_d > 0.0 {
        out.stat("Dübellöcher", holes.iter().map(|h| h.len()).sum::<usize>() / 2);
    }
    emit_parts(&mut out, parts3d, p, "stack_druck");
    note_print_only(&mut out);
    Ok(out)
}

fn emit_sheets(out: &mut Output, parts: Vec<Sheet2D>, p: &Params, prefix: &str) {
    let sheets = export::nest_sheets(parts, p.sheet_w, p.sheet_h, 4.0);
    for (i, s) in sheets.iter().enumerate() {
        out.files.push((format!("laser/{prefix}_bogen_{:02}.svg", i + 1), export::sheet_svg(s, p.sheet_w, p.sheet_h).into_bytes()));
        out.files.push((format!("laser/{prefix}_bogen_{:02}.dxf", i + 1), export::sheet_dxf(s).into_bytes()));
    }
    out.sheets = sheets.len();
    out.stat("Bögen", format!("{} × ({:.0} × {:.0} mm)", sheets.len(), p.sheet_w, p.sheet_h));
}

fn note_print_only(out: &mut Output) {
    for w in out.warnings.iter_mut() {
        if w.contains("größer als die Platte") {
            *w = format!("{} Betrifft nur die Druckversion – die Laser-Bögen passen.", w);
        }
    }
}

// ───────────────────────── Hash ─────────────────────────

/// Abschnitte einer Fläche auf einer Linie (horizontal: v = c, sonst u = c) → Intervalle im anderen Parameter
fn line_intervals(polys: &[Poly], c: f64, horizontal: bool) -> Vec<(f64, f64)> {
    let mut xs: Vec<f64> = Vec::new();
    for p in polys {
        let mut rings = vec![&p.outer];
        rings.extend(p.holes.iter());
        for r in rings {
            for i in 0..r.len() {
                let (a, b) = (r[i], r[(i + 1) % r.len()]);
                let (ac, bc, ao, bo) = if horizontal { (a[1], b[1], a[0], b[0]) } else { (a[0], b[0], a[1], b[1]) };
                if (ac > c) != (bc > c) {
                    xs.push(ao + (c - ac) / (bc - ac) * (bo - ao));
                }
            }
        }
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    xs.chunks(2).filter(|c| c.len() == 2).map(|c| (c[0], c[1])).collect()
}

fn intersect_intervals(a: &[(f64, f64)], b: &[(f64, f64)]) -> Vec<(f64, f64)> {
    let mut out = Vec::new();
    for x in a {
        for y in b {
            let lo = x.0.max(y.0);
            let hi = x.1.min(y.1);
            if hi > lo + 0.5 {
                out.push((lo, hi));
            }
        }
    }
    out
}

pub fn hash(mesh: &Mesh, p: &Params) -> Result<Output> {
    let mut out = Output::default();
    let m = scaled(mesh, p.size);
    let b = m.bbox();
    let t = p.sheet_t.max(0.3);
    let slot = (t - p.tolerance).max(0.1);
    let nx = p.x_layers.max(1);
    let nz = p.z_layers.max(1);
    let xs: Vec<f64> = (0..nx).map(|i| b.min[0] + b.size()[0] * (i as f64 + 0.5) / nx as f64).collect();
    let zs: Vec<f64> = (0..nz).map(|i| b.min[2] + b.size()[2] * (i as f64 + 0.5) / nz as f64).collect();
    // X-Scheiben: Koordinaten (y, z); Z-Scheiben: (x, y)
    let mut xsl: Vec<Vec<Poly>> = xs.iter().map(|&x| section::section(&m, 0, x)).collect();
    let mut zsl: Vec<Vec<Poly>> = zs.iter().map(|&z| section::section(&m, 2, z)).collect();
    if p.ring_w > 0.0 {
        for l in xsl.iter_mut().chain(zsl.iter_mut()) {
            let g = section::polys_to_multi(l);
            *l = section::multi_to_polys(&g.difference(&g.buffer(-p.ring_w)));
        }
    }
    let mut cut_x: Vec<Vec<Poly>> = vec![Vec::new(); nx];
    let mut cut_z: Vec<Vec<Poly>> = vec![Vec::new(); nz];
    let mut n_slots = 0;
    for (i, &x) in xs.iter().enumerate() {
        for (k, &z) in zs.iter().enumerate() {
            let ix = line_intervals(&xsl[i], z, true); // y-Intervalle der X-Scheibe bei z
            let iz = line_intervals(&zsl[k], x, false); // y-Intervalle der Z-Scheibe bei x
            for (lo, hi) in intersect_intervals(&ix, &iz) {
                let mid = (lo + hi) * 0.5;
                cut_x[i].push(rect_poly(lo - 1.0, z - slot * 0.5, mid, z + slot * 0.5));
                cut_z[k].push(rect_poly(x - slot * 0.5, mid, x + slot * 0.5, hi + 1.0));
                n_slots += 1;
            }
        }
    }
    let apply = |polys: &Vec<Poly>, cuts: &Vec<Poly>| -> Vec<Poly> {
        if cuts.is_empty() {
            return polys.clone();
        }
        section::multi_to_polys(&section::polys_to_multi(polys).difference(&section::polys_to_multi(cuts)))
    };
    let mut sheet_parts = Vec::new();
    let mut preview = Mesh::new();
    let mut preview_z = Mesh::new();
    let mut parts3d = Vec::new();
    for (i, &x) in xs.iter().enumerate() {
        let polys = apply(&xsl[i], &cut_x[i]);
        preview.extend(&export::extrude(&polys, t, &place_fn(0, x - t * 0.5)));
        for (j, pl) in polys.into_iter().enumerate() {
            if pl.area() < 1.0 {
                continue;
            }
            let label = format!("X{}.{}", i + 1, j + 1);
            parts3d.push((label.replace('.', "-"), export::extrude(std::slice::from_ref(&pl), t, &|q, h| [q[0], q[1], h])));
            sheet_parts.push(Sheet2D { label, polys: vec![pl], engrave: vec![] });
        }
    }
    for (k, &z) in zs.iter().enumerate() {
        let polys = apply(&zsl[k], &cut_z[k]);
        preview_z.extend(&export::extrude(&polys, t, &place_fn(2, z - t * 0.5)));
        for (j, pl) in polys.into_iter().enumerate() {
            if pl.area() < 1.0 {
                continue;
            }
            let label = format!("Z{}.{}", k + 1, j + 1);
            parts3d.push((label.replace('.', "-"), export::extrude(std::slice::from_ref(&pl), t, &|q, h| [q[0], q[1], h])));
            sheet_parts.push(Sheet2D { label, polys: vec![pl], engrave: vec![] });
        }
    }
    out.stat("Scheiben", format!("{} X + {} Z", nx, nz));
    out.stat("Teile", sheet_parts.len());
    out.stat("Schlitze", n_slots);
    out.stat("Schlitzbreite", format!("{:.2} mm", slot).replace('.', ","));
    emit_sheets(&mut out, sheet_parts, p, "hash");
    out.preview.push(("X-Scheiben".into(), preview));
    out.preview.push(("Z-Scheiben".into(), preview_z));
    emit_parts(&mut out, parts3d, p, "hash_druck");
    note_print_only(&mut out);
    Ok(out)
}

// ───────────────────────── Wireframe ─────────────────────────

fn simplify(r: &[P2], tol: f64) -> Vec<P2> {
    if r.len() < 4 {
        return r.to_vec();
    }
    fn dp(pts: &[P2], tol: f64, out: &mut Vec<P2>) {
        let (a, b) = (pts[0], pts[pts.len() - 1]);
        let mut best = (0.0, 0);
        for (i, p) in pts.iter().enumerate().take(pts.len() - 1).skip(1) {
            let d = section::dist_to_ring(*p, &[a, b]);
            if d > best.0 {
                best = (d, i);
            }
        }
        if best.0 > tol {
            dp(&pts[..=best.1], tol, out);
            out.pop();
            dp(&pts[best.1..], tol, out);
        } else {
            out.push(a);
            out.push(b);
        }
    }
    let mut closed = r.to_vec();
    closed.push(r[0]);
    let mut out = Vec::new();
    dp(&closed, tol, &mut out);
    out.pop();
    out
}

/// Kantiger Draht (Quader) von a nach b, Querschnitt w × w
fn strut(m: &mut Mesh, a: V3, b: V3, w: f64, normal: V3) {
    use crate::mesh::{add, cross, mul, norm, sub};
    let d = sub(b, a);
    let l = crate::mesh::len(d);
    if l < 1e-6 {
        return;
    }
    let dir = mul(d, 1.0 / l);
    let a = sub(a, mul(dir, w * 0.5));
    let b = add(b, mul(dir, w * 0.5));
    let u = norm(normal);
    let v = norm(cross(dir, u));
    let h = w * 0.5;
    let corners = |p: V3| -> [V3; 4] {
        [
            add(add(p, mul(u, h)), mul(v, h)),
            add(sub(p, mul(u, h)), mul(v, h)),
            sub(sub(p, mul(u, h)), mul(v, h)),
            sub(add(p, mul(u, h)), mul(v, h)),
        ]
    };
    let ca = corners(a);
    let cb = corners(b);
    let mut piece = Mesh::new();
    for i in 0..4 {
        let j = (i + 1) % 4;
        piece.quad(ca[i], ca[j], cb[j], cb[i]);
    }
    piece.quad(ca[3], ca[2], ca[1], ca[0]);
    piece.quad(cb[0], cb[1], cb[2], cb[3]);
    piece.fix_orientation_local();
    m.extend(&piece);
}

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

pub fn wireframe(mesh: &Mesh, p: &Params) -> Result<Output> {
    let mut out = Output::default();
    let m = scaled(mesh, p.size);
    let b = m.bbox();
    let w = p.wire_t.max(0.4);
    let counts = [p.x_layers, p.y_layers, p.z_layers];
    let mut wire = Mesh::new();
    let mut n_loops = 0;
    for a in 0..3 {
        let n = counts[a];
        let mut normal = [0.0; 3];
        normal[a] = 1.0;
        for i in 0..n {
            let v = b.min[a] + b.size()[a] * (i as f64 + 0.5) / n as f64;
            for poly in section::section(&m, a, v) {
                let mut rings = vec![poly.outer.clone()];
                rings.extend(poly.holes.clone());
                for r in rings {
                    let r = simplify(&r, w * 0.25);
                    n_loops += 1;
                    for k in 0..r.len() {
                        let p0 = section::to3(r[k], a, v);
                        let p1 = section::to3(r[(k + 1) % r.len()], a, v);
                        strut(&mut wire, p0, p1, w, normal);
                    }
                }
            }
        }
    }
    if wire.is_empty() {
        bail!("Keine Drähte – bitte Schichtanzahl erhöhen.");
    }
    let s = wire.bbox().size();
    out.stat("Drahtschleifen", n_loops);
    out.stat("Größe", format!("{:.0} × {:.0} × {:.0} mm", s[0], s[1], s[2]));
    out.stat("Dreiecke", fmt_tris(wire.tris.len()));
    let pr = main_printer(p);
    if s[0] > pr.x - 2.0 * p.margin || s[1] > pr.y - 2.0 * p.margin || s[2] > pr.z {
        out.warnings.push("Das Drahtmodell ist größer als die Platte. Tipp: das Ergebnis-STL mit „Teilen“ zerlegen.".into());
    }
    out.preview.push(("Wireframe".into(), wire.clone()));
    emit_parts(&mut out, vec![("wireframe".into(), wire)], p, "wireframe");
    Ok(out)
}
