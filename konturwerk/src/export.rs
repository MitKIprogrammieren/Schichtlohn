//! Ausgabe: Bambu-3MF (Behälter Filament 1, TPU-Inlay Filament 2), SVG und DXF der Taschen.
use crate::behaelter::{Ergebnis, Teil};
use crate::netz::P2;
use std::fmt::Write as _;
use std::io::Write;

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn mesh_xml(out: &mut String, id: usize, name: &str, t: &Teil, dx: f64, dy: f64) {
    let (v, tris) = t.netz.indiziert();
    let _ = write!(out, "  <object id=\"{id}\" name=\"{}\" type=\"model\">\n   <mesh>\n    <vertices>\n", esc(name));
    for p in &v {
        let _ = writeln!(out, "     <vertex x=\"{:.4}\" y=\"{:.4}\" z=\"{:.4}\"/>", p[0] + dx, p[1] + dy, p[2]);
    }
    out.push_str("    </vertices>\n    <triangles>\n");
    for t in &tris {
        let _ = writeln!(out, "     <triangle v1=\"{}\" v2=\"{}\" v3=\"{}\"/>", t[0], t[1], t[2]);
    }
    out.push_str("    </triangles>\n   </mesh>\n  </object>\n");
}

/// 3MF für Bambu Studio / OrcaSlicer.
/// kombiniert: ein Objekt mit zwei Teilen (Filament 1 und 2). Sonst je Teil ein Objekt auf eigener Platte.
pub fn bambu_3mf(e: &Ergebnis, name: &str) -> Vec<u8> {
    let bett = 256.0;
    let mut model = String::from(r#"<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
 <metadata name="Application">Konturwerk</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
"#);
    let mut cfg = String::from("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<config>\n");
    let mut build = String::new();
    let mut platten: Vec<Vec<usize>> = Vec::new();
    // in die Bettmitte setzen
    let mitte = |t: &Teil| {
        let (mn, mx) = t.netz.grenzen();
        (bett / 2.0 - (mn[0] + mx[0]) / 2.0, bett / 2.0 - (mn[1] + mx[1]) / 2.0)
    };
    if e.kombiniert {
        let (dx, dy) = mitte(&e.teile[0]);
        let mut comps = String::new();
        for (i, t) in e.teile.iter().enumerate() {
            mesh_xml(&mut model, i + 1, &t.name, t, dx, dy);
            let _ = writeln!(comps, "    <component objectid=\"{}\"/>", i + 1);
        }
        let pid = e.teile.len() + 1;
        let _ = write!(model, "  <object id=\"{pid}\" name=\"{}\" type=\"model\">\n   <components>\n{comps}   </components>\n  </object>\n", esc(name));
        let _ = write!(cfg, "  <object id=\"{pid}\">\n    <metadata key=\"name\" value=\"{}\"/>\n    <metadata key=\"extruder\" value=\"1\"/>\n", esc(name));
        for (i, t) in e.teile.iter().enumerate() {
            let _ = write!(cfg, "    <part id=\"{}\" subtype=\"normal_part\">\n      <metadata key=\"name\" value=\"{}\"/>\n      <metadata key=\"extruder\" value=\"{}\"/>\n    </part>\n", i + 1, esc(&t.name), t.filament);
        }
        cfg.push_str("  </object>\n");
        let _ = writeln!(build, "  <item objectid=\"{pid}\" transform=\"1 0 0 0 1 0 0 0 1 0 0 0\" printable=\"1\"/>");
        platten.push(vec![pid]);
    } else {
        for (i, t) in e.teile.iter().enumerate() {
            let id = i + 1;
            let (dx, dy) = mitte(t);
            mesh_xml(&mut model, id, &t.name, t, dx, dy);
            let _ = write!(cfg, "  <object id=\"{id}\">\n    <metadata key=\"name\" value=\"{}\"/>\n    <metadata key=\"extruder\" value=\"{}\"/>\n    <part id=\"1\" subtype=\"normal_part\">\n      <metadata key=\"name\" value=\"{}\"/>\n    </part>\n  </object>\n", esc(&t.name), t.filament, esc(&t.name));
            while platten.len() <= t.platte {
                platten.push(vec![]);
            }
            platten[t.platte].push(id);
            let ox = t.platte as f64 * bett * 1.2;
            let _ = writeln!(build, "  <item objectid=\"{id}\" transform=\"1 0 0 0 1 0 0 0 1 {ox:.3} 0 0\" printable=\"1\"/>");
        }
    }
    model.push_str(" </resources>\n <build>\n");
    model.push_str(&build);
    model.push_str(" </build>\n</model>\n");
    for (pi, ids) in platten.iter().enumerate() {
        let pname = if e.kombiniert { "Behälter + TPU" } else if pi == 0 { "Behälter" } else { "TPU-Inlay" };
        let _ = write!(cfg, "  <plate>\n    <metadata key=\"plater_id\" value=\"{}\"/>\n    <metadata key=\"plater_name\" value=\"{pname}\"/>\n    <metadata key=\"locked\" value=\"false\"/>\n", pi + 1);
        for (k, id) in ids.iter().enumerate() {
            let _ = write!(cfg, "    <model_instance>\n      <metadata key=\"object_id\" value=\"{id}\"/>\n      <metadata key=\"instance_id\" value=\"0\"/>\n      <metadata key=\"identify_id\" value=\"{}\"/>\n    </model_instance>\n", 100 + pi * 10 + k);
        }
        cfg.push_str("  </plate>\n");
    }
    cfg.push_str("</config>\n");

    let mut buf = std::io::Cursor::new(Vec::new());
    {
        let mut z = zip::ZipWriter::new(&mut buf);
        let opt = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
        let dateien: [(&str, &[u8]); 4] = [
            ("[Content_Types].xml", br#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>"#),
            ("_rels/.rels", br#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"#),
            ("3D/3dmodel.model", model.as_bytes()),
            ("Metadata/model_settings.config", cfg.as_bytes()),
        ];
        for (n, d) in dateien {
            let _ = z.start_file(n, opt);
            let _ = z.write_all(d);
        }
        let _ = z.finish();
    }
    buf.into_inner()
}

/// SVG 1:1 in mm: Außenkontur (rot = schneiden) und Taschen
pub fn svg(e: &Ergebnis) -> String {
    let mut s = format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{w:.2}mm\" height=\"{h:.2}mm\" viewBox=\"0 0 {w:.3} {h:.3}\">\n",
        w = e.breite,
        h = e.tiefe_aussen
    );
    let pfad = |r: &[P2]| {
        let mut d = String::new();
        for (i, p) in r.iter().enumerate() {
            let _ = write!(d, "{}{:.3},{:.3} ", if i == 0 { "M" } else { "L" }, p[0], p[1]);
        }
        d.push('Z');
        d
    };
    let _ = writeln!(s, " <path d=\"{}\" fill=\"none\" stroke=\"#ff0000\" stroke-width=\"0.1\"/>", pfad(&e.aussen));
    for t in &e.taschen {
        let _ = writeln!(s, " <path d=\"{}\" fill=\"none\" stroke=\"#0000ff\" stroke-width=\"0.1\"/>", pfad(t));
    }
    s.push_str("</svg>\n");
    s
}

/// DXF (R12, LWPOLYLINE wäre neuer – POLYLINE geht überall), y nach oben
pub fn dxf(e: &Ergebnis) -> String {
    let mut s = String::from("0\nSECTION\n2\nENTITIES\n");
    let mut ring = |r: &[P2], layer: &str, farbe: i32| {
        let _ = write!(s, "0\nPOLYLINE\n8\n{layer}\n62\n{farbe}\n66\n1\n70\n1\n");
        for p in r {
            let _ = write!(s, "0\nVERTEX\n8\n{layer}\n10\n{:.4}\n20\n{:.4}\n", p[0], e.tiefe_aussen - p[1]);
        }
        s.push_str("0\nSEQEND\n");
    };
    ring(&e.aussen, "AUSSEN", 1);
    for t in &e.taschen {
        ring(t, "TASCHEN", 5);
    }
    s.push_str("0\nENDSEC\n0\nEOF\n");
    s
}
