//! Ausgabe: Platten-Packen, Bambu-3MF mit mehreren Platten, SVG/DXF für den Laser, ZIP.
use crate::mesh::{Mesh, V3};
use crate::section::{P2, Poly};
use std::fmt::Write as _;
use std::io::Write;

/// Rechteck-Packen in Regalen. Liefert je Teil (Platte, x, y, gedreht).
pub fn shelf_pack(sizes: &[(f64, f64)], w: f64, h: f64, gap: f64) -> Vec<(usize, f64, f64, bool)> {
    let mut order: Vec<usize> = (0..sizes.len()).collect();
    // Teile so drehen, dass sie liegen (breiter als hoch), wenn es passt
    let rot: Vec<bool> = sizes
        .iter()
        .map(|&(a, b)| {
            let fits_normal = a <= w && b <= h;
            let fits_rot = b <= w && a <= h;
            (!fits_normal && fits_rot) || (fits_normal && fits_rot && b > a)
        })
        .collect();
    let dims: Vec<(f64, f64)> = sizes.iter().zip(&rot).map(|(&(a, b), &r)| if r { (b, a) } else { (a, b) }).collect();
    order.sort_by(|&i, &j| dims[j].1.partial_cmp(&dims[i].1).unwrap());
    let mut out = vec![(0, 0.0, 0.0, false); sizes.len()];
    // offene Platten: (Regale: (y, Höhe, belegte Breite)), nächstes freies y
    let mut plates: Vec<(Vec<(f64, f64, f64)>, f64)> = Vec::new();
    for i in order {
        let (pw, ph) = dims[i];
        let mut placed = false;
        'outer: for (pi, (shelves, next_y)) in plates.iter_mut().enumerate() {
            for s in shelves.iter_mut() {
                if ph <= s.1 + 1e-9 && s.2 + pw <= w + 1e-9 {
                    out[i] = (pi, s.2, s.0, rot[i]);
                    s.2 += pw + gap;
                    placed = true;
                    break 'outer;
                }
            }
            if *next_y + ph <= h + 1e-9 {
                shelves.push((*next_y, ph, pw + gap));
                out[i] = (pi, 0.0, *next_y, rot[i]);
                *next_y += ph + gap;
                placed = true;
                break;
            }
        }
        if !placed {
            plates.push((vec![(0.0, ph, pw + gap)], ph + gap));
            out[i] = (plates.len() - 1, 0.0, 0.0, rot[i]);
        }
    }
    out
}

pub struct PlatePart {
    pub name: String,
    pub mesh: Mesh, // schon auf der Platte positioniert (Plattenkoordinaten 0..bed)
    pub plate: usize,
}

/// Teile auf Platten des Druckbetts verteilen (Netze werden flach gelegt: min z = 0)
pub fn arrange_on_plates(parts: Vec<(String, Mesh)>, bed: [f64; 2], gap: f64, plate_offset: usize) -> Vec<PlatePart> {
    let mut parts = parts;
    for (_, m) in parts.iter_mut() {
        m.place_on_origin();
    }
    let sizes: Vec<(f64, f64)> = parts.iter().map(|(_, m)| {
        let s = m.bbox().size();
        (s[0], s[1])
    }).collect();
    let usable = [bed[0] - 2.0 * gap, bed[1] - 2.0 * gap];
    let pl = shelf_pack(&sizes, usable[0], usable[1], gap);
    let mut out = Vec::new();
    for ((name, mut m), (plate, x, y, r)) in parts.into_iter().zip(pl) {
        if r {
            m.map(|p| [p[1], -p[0], p[2]]);
            m.place_on_origin();
        }
        m.translate([x + gap, y + gap, 0.0]);
        out.push(PlatePart { name, mesh: m, plate: plate + plate_offset });
    }
    out
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

/// Spaltenzahl der Plattenanordnung wie in Bambu Studio
fn plate_cols(n: usize) -> usize {
    let v = (n as f64).sqrt();
    let r = v.round();
    (if v > r { r + 1.0 } else { r }).max(1.0) as usize
}

/// 3MF mit mehreren Platten (Bambu Studio / OrcaSlicer)
pub fn bambu_3mf(parts: &[PlatePart], bed: [f64; 2], printer_names: &[String]) -> Vec<u8> {
    let n_plates = parts.iter().map(|p| p.plate + 1).max().unwrap_or(1);
    let cols = plate_cols(n_plates);
    let gap = 1.0 / 5.0;
    let mut model = String::new();
    model.push_str(r#"<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
 <metadata name="Application">Formwerk</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
"#);
    for (i, p) in parts.iter().enumerate() {
        let id = i + 1;
        let _ = write!(model, "  <object id=\"{id}\" name=\"{}\" type=\"model\">\n   <mesh>\n    <vertices>\n", xml_escape(&p.name));
        // Eckpunkte zusammenführen
        let mut idx: std::collections::HashMap<(u64, u64, u64), usize> = Default::default();
        let mut verts: Vec<V3> = Vec::new();
        let mut tris: Vec<[usize; 3]> = Vec::new();
        for t in &p.mesh.tris {
            let mut tri = [0; 3];
            for k in 0..3 {
                let v = t[k];
                let key = ((v[0] as f32).to_bits() as u64, (v[1] as f32).to_bits() as u64, (v[2] as f32).to_bits() as u64);
                tri[k] = *idx.entry(key).or_insert_with(|| {
                    verts.push(v);
                    verts.len() - 1
                });
            }
            if tri[0] != tri[1] && tri[1] != tri[2] && tri[0] != tri[2] {
                tris.push(tri);
            }
        }
        for v in &verts {
            let _ = writeln!(model, "     <vertex x=\"{:.4}\" y=\"{:.4}\" z=\"{:.4}\"/>", v[0], v[1], v[2]);
        }
        model.push_str("    </vertices>\n    <triangles>\n");
        for t in &tris {
            let _ = writeln!(model, "     <triangle v1=\"{}\" v2=\"{}\" v3=\"{}\"/>", t[0], t[1], t[2]);
        }
        model.push_str("    </triangles>\n   </mesh>\n  </object>\n");
    }
    model.push_str(" </resources>\n <build>\n");
    for (i, p) in parts.iter().enumerate() {
        let col = p.plate % cols;
        let row = p.plate / cols;
        let ox = col as f64 * bed[0] * (1.0 + gap);
        let oy = -(row as f64) * bed[1] * (1.0 + gap);
        let _ = writeln!(model, "  <item objectid=\"{}\" transform=\"1 0 0 0 1 0 0 0 1 {ox:.3} {oy:.3} 0\" printable=\"1\"/>", i + 1);
    }
    model.push_str(" </build>\n</model>\n");

    let mut cfg = String::from("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<config>\n");
    for (i, p) in parts.iter().enumerate() {
        let _ = write!(cfg, "  <object id=\"{}\">\n    <metadata key=\"name\" value=\"{}\"/>\n    <metadata key=\"extruder\" value=\"1\"/>\n    <part id=\"1\" subtype=\"normal_part\">\n      <metadata key=\"name\" value=\"{}\"/>\n    </part>\n  </object>\n", i + 1, xml_escape(&p.name), xml_escape(&p.name));
    }
    for plate in 0..n_plates {
        let pname = printer_names.get(plate).cloned().unwrap_or_default();
        let _ = write!(cfg, "  <plate>\n    <metadata key=\"plater_id\" value=\"{}\"/>\n    <metadata key=\"plater_name\" value=\"{}\"/>\n    <metadata key=\"locked\" value=\"false\"/>\n", plate + 1, xml_escape(&pname));
        for (i, p) in parts.iter().enumerate().filter(|(_, p)| p.plate == plate) {
            let _ = write!(cfg, "    <model_instance>\n      <metadata key=\"object_id\" value=\"{}\"/>\n      <metadata key=\"instance_id\" value=\"0\"/>\n      <metadata key=\"identify_id\" value=\"{}\"/>\n    </model_instance>\n", i + 1, 100 + i);
            let _ = p;
        }
        cfg.push_str("  </plate>\n");
    }
    cfg.push_str("</config>\n");

    let mut buf = std::io::Cursor::new(Vec::new());
    {
        let mut z = zip::ZipWriter::new(&mut buf);
        let opt = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
        let _ = z.start_file("[Content_Types].xml", opt);
        let _ = z.write_all(br#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>"#);
        let _ = z.start_file("_rels/.rels", opt);
        let _ = z.write_all(br#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"#);
        let _ = z.start_file("3D/3dmodel.model", opt);
        let _ = z.write_all(model.as_bytes());
        let _ = z.start_file("Metadata/model_settings.config", opt);
        let _ = z.write_all(cfg.as_bytes());
        let _ = z.finish();
    }
    buf.into_inner()
}

/// Ein Laser-Teil: Schneidkonturen, Gravurlinien, Beschriftung
#[derive(Clone)]
pub struct Sheet2D {
    pub label: String,
    pub polys: Vec<Poly>,
    pub engrave: Vec<Vec<P2>>, // offene oder geschlossene Linien
}

impl Sheet2D {
    pub fn bbox(&self) -> (P2, P2) {
        let mut mn = [f64::MAX; 2];
        let mut mx = [f64::MIN; 2];
        for p in &self.polys {
            let (a, b) = p.bbox();
            mn = [mn[0].min(a[0]), mn[1].min(a[1])];
            mx = [mx[0].max(b[0]), mx[1].max(b[1])];
        }
        (mn, mx)
    }
    pub fn transform(&mut self, f: &dyn Fn(P2) -> P2) {
        for p in &mut self.polys {
            p.outer.iter_mut().for_each(|q| *q = f(*q));
            for h in &mut p.holes {
                h.iter_mut().for_each(|q| *q = f(*q));
            }
        }
        for l in &mut self.engrave {
            l.iter_mut().for_each(|q| *q = f(*q));
        }
    }
}

/// Laser-Teile auf Bögen verschachteln. Rückgabe: Bögen mit platzierten Teilen.
pub fn nest_sheets(mut parts: Vec<Sheet2D>, w: f64, h: f64, gap: f64) -> Vec<Vec<Sheet2D>> {
    for p in parts.iter_mut() {
        let (mn, _) = p.bbox();
        p.transform(&|q| [q[0] - mn[0], q[1] - mn[1]]);
    }
    let sizes: Vec<(f64, f64)> = parts.iter().map(|p| {
        let (_, mx) = p.bbox();
        (mx[0], mx[1])
    }).collect();
    let pl = shelf_pack(&sizes, w - 2.0 * gap, h - 2.0 * gap, gap);
    let n = pl.iter().map(|x| x.0 + 1).max().unwrap_or(0);
    let mut sheets: Vec<Vec<Sheet2D>> = vec![Vec::new(); n];
    for (mut p, (s, x, y, r)) in parts.into_iter().zip(pl) {
        if r {
            let (_, mx) = p.bbox();
            let hh = mx[1];
            p.transform(&|q| [hh - q[1], q[0]]);
        }
        p.transform(&|q| [q[0] + x + gap, q[1] + y + gap]);
        sheets[s].push(p);
    }
    sheets
}

fn path_d(r: &[P2], h: f64, close: bool) -> String {
    let mut s = String::new();
    for (i, p) in r.iter().enumerate() {
        let _ = write!(s, "{}{:.3},{:.3} ", if i == 0 { "M" } else { "L" }, p[0], h - p[1]);
    }
    if close {
        s.push('Z');
    }
    s
}

/// SVG eines Bogens (mm). Rot = schneiden, Blau = gravieren, Schwarz = Beschriftung
pub fn sheet_svg(parts: &[Sheet2D], w: f64, h: f64) -> String {
    let mut s = format!(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{w}mm\" height=\"{h}mm\" viewBox=\"0 0 {w} {h}\">\n<rect x=\"0\" y=\"0\" width=\"{w}\" height=\"{h}\" fill=\"none\" stroke=\"#cccccc\" stroke-width=\"0.2\"/>\n"
    );
    for p in parts {
        for poly in &p.polys {
            let mut d = path_d(&poly.outer, h, true);
            for hole in &poly.holes {
                d.push(' ');
                d.push_str(&path_d(hole, h, true));
            }
            let _ = writeln!(s, "<path d=\"{d}\" fill=\"none\" stroke=\"#ff0000\" stroke-width=\"0.1\"/>");
        }
        for l in &p.engrave {
            let closed = l.len() > 2 && l.first() == l.last();
            let _ = writeln!(s, "<path d=\"{}\" fill=\"none\" stroke=\"#0000ff\" stroke-width=\"0.1\"/>", path_d(l, h, closed));
        }
        // Beschriftung an einer Stelle innerhalb des Teils
        if let Some(pt) = label_point(&p.polys) {
            let size = label_size(&p.polys);
            let _ = writeln!(s, "<text x=\"{:.2}\" y=\"{:.2}\" font-family=\"Arial\" font-size=\"{:.1}\" text-anchor=\"middle\" fill=\"#000000\">{}</text>", pt[0], h - pt[1] + size * 0.35, size, xml_escape(&p.label));
        }
    }
    s.push_str("</svg>\n");
    s
}

/// Punkt mit größtem Randabstand für die Beschriftung
pub fn label_point(polys: &[Poly]) -> Option<P2> {
    let mut best: Option<(f64, P2)> = None;
    for p in polys {
        let (mn, mx) = p.bbox();
        let step = ((mx[0] - mn[0]).max(mx[1] - mn[1]) / 24.0).max(0.5);
        let mut y = mn[1] + step * 0.5;
        while y < mx[1] {
            let mut x = mn[0] + step * 0.5;
            while x < mx[0] {
                if p.contains([x, y]) {
                    let d = p.boundary_dist([x, y]);
                    if best.is_none_or(|b| d > b.0) {
                        best = Some((d, [x, y]));
                    }
                }
                x += step;
            }
            y += step;
        }
    }
    best.map(|b| b.1)
}

fn label_size(polys: &[Poly]) -> f64 {
    let d = label_point(polys).map(|p| polys.iter().filter(|q| q.contains(p)).map(|q| q.boundary_dist(p)).fold(0.0, f64::max)).unwrap_or(2.0);
    (d * 0.7).clamp(2.0, 8.0)
}

/// DXF (R12, mm). Layer CUT, ENGRAVE, TEXT
pub fn sheet_dxf(parts: &[Sheet2D]) -> String {
    let mut s = String::from("0\nSECTION\n2\nENTITIES\n");
    let poly = |s: &mut String, layer: &str, r: &[P2], closed: bool| {
        let _ = write!(s, "0\nPOLYLINE\n8\n{layer}\n66\n1\n70\n{}\n", if closed { 1 } else { 0 });
        for p in r {
            let _ = write!(s, "0\nVERTEX\n8\n{layer}\n10\n{:.4}\n20\n{:.4}\n", p[0], p[1]);
        }
        s.push_str("0\nSEQEND\n");
    };
    for p in parts {
        for pl in &p.polys {
            poly(&mut s, "CUT", &pl.outer, true);
            for h in &pl.holes {
                poly(&mut s, "CUT", h, true);
            }
        }
        for l in &p.engrave {
            poly(&mut s, "ENGRAVE", l, false);
        }
        if let Some(pt) = label_point(&p.polys) {
            let size = label_size(&p.polys);
            let _ = write!(s, "0\nTEXT\n8\nTEXT\n10\n{:.3}\n20\n{:.3}\n40\n{:.2}\n1\n{}\n72\n1\n11\n{:.3}\n21\n{:.3}\n", pt[0], pt[1], size, p.label, pt[0], pt[1]);
        }
    }
    s.push_str("0\nENDSEC\n0\nEOF\n");
    s
}

/// Fläche (2D) zu Platte mit Dicke `t` extrudieren; `place` bildet 2D+Höhe auf 3D ab.
pub fn extrude(polys: &[Poly], t: f64, place: &dyn Fn(P2, f64) -> V3) -> Mesh {
    let mut m = Mesh::new();
    for p in polys {
        for tri in p.triangulate() {
            let a = tri[0];
            let b = tri[1];
            let c = tri[2];
            let ccw = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0.0;
            let (b, c) = if ccw { (b, c) } else { (c, b) };
            m.push(place(a, t), place(b, t), place(c, t));
            m.push(place(a, 0.0), place(c, 0.0), place(b, 0.0));
        }
        let mut rings: Vec<(Vec<P2>, bool)> = vec![(p.outer.clone(), true)];
        rings.extend(p.holes.iter().map(|h| (h.clone(), false)));
        for (r, outer) in rings {
            let ccw = crate::section::ring_area(&r) > 0.0;
            // außen: CCW, Löcher: CW → Wände zeigen nach außen
            let mut r = r;
            if ccw != outer {
                r.reverse();
            }
            for i in 0..r.len() {
                let a = r[i];
                let b = r[(i + 1) % r.len()];
                m.quad(place(a, 0.0), place(b, 0.0), place(b, t), place(a, t));
            }
        }
    }
    // Falls `place` die Händigkeit spiegelt, Orientierung korrigieren
    m.fix_orientation();
    m
}

pub fn zip_files(files: &[(String, Vec<u8>)]) -> Vec<u8> {
    let mut buf = std::io::Cursor::new(Vec::new());
    {
        let mut z = zip::ZipWriter::new(&mut buf);
        let opt = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated).large_file(true);
        for (n, d) in files {
            let _ = z.start_file(n.as_str(), opt);
            let _ = z.write_all(d);
        }
        let _ = z.finish();
    }
    buf.into_inner()
}
