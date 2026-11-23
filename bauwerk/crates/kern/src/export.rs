//! Export als STL (binär), 3MF und STEP (facettierter Volumenkörper).
use crate::netz::{kreuz, Netz};

pub fn stl(n: &Netz, name: &str) -> Vec<u8> {
    let mut b = Vec::with_capacity(84 + n.idx.len() * 50);
    let mut kopf = format!("Bauwerk {}", name).into_bytes();
    kopf.resize(80, b' ');
    b.extend_from_slice(&kopf[..80]);
    b.extend_from_slice(&(n.idx.len() as u32).to_le_bytes());
    for t in &n.idx {
        let (a, c, d) = (n.pos[t[0]], n.pos[t[1]], n.pos[t[2]]);
        let mut nn = kreuz([c[0] - a[0], c[1] - a[1], c[2] - a[2]], [d[0] - a[0], d[1] - a[1], d[2] - a[2]]);
        let l = (nn[0] * nn[0] + nn[1] * nn[1] + nn[2] * nn[2]).sqrt().max(1e-30);
        for v in nn.iter_mut() { *v /= l; }
        for v in [nn, a, c, d] { for k in v { b.extend_from_slice(&(k as f32).to_le_bytes()); } }
        b.extend_from_slice(&[0, 0]);
    }
    b
}

fn crc32(d: &[u8]) -> u32 {
    let mut c = 0xffff_ffffu32;
    for &x in d {
        c ^= x as u32;
        for _ in 0..8 { c = if c & 1 != 0 { 0xedb8_8320 ^ (c >> 1) } else { c >> 1 }; }
    }
    !c
}

/// Einfaches ZIP (ohne Kompression).
pub fn zip(dateien: &[(&str, Vec<u8>)]) -> Vec<u8> {
    let mut out = vec![];
    let mut zentral = vec![];
    for (name, d) in dateien {
        let crc = crc32(d);
        let off = out.len() as u32;
        let mut h = vec![];
        h.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
        h.extend_from_slice(&20u16.to_le_bytes()); h.extend_from_slice(&[0; 2]); h.extend_from_slice(&[0; 2]);
        h.extend_from_slice(&[0; 4]);
        h.extend_from_slice(&crc.to_le_bytes());
        h.extend_from_slice(&(d.len() as u32).to_le_bytes()); h.extend_from_slice(&(d.len() as u32).to_le_bytes());
        h.extend_from_slice(&(name.len() as u16).to_le_bytes()); h.extend_from_slice(&[0; 2]);
        out.extend(h); out.extend_from_slice(name.as_bytes()); out.extend_from_slice(d);
        let mut z = vec![];
        z.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
        z.extend_from_slice(&20u16.to_le_bytes()); z.extend_from_slice(&20u16.to_le_bytes());
        z.extend_from_slice(&[0; 2]); z.extend_from_slice(&[0; 2]); z.extend_from_slice(&[0; 4]);
        z.extend_from_slice(&crc.to_le_bytes());
        z.extend_from_slice(&(d.len() as u32).to_le_bytes()); z.extend_from_slice(&(d.len() as u32).to_le_bytes());
        z.extend_from_slice(&(name.len() as u16).to_le_bytes());
        z.extend_from_slice(&[0; 2]); z.extend_from_slice(&[0; 2]); z.extend_from_slice(&[0; 2]); z.extend_from_slice(&[0; 2]);
        z.extend_from_slice(&[0; 4]);
        z.extend_from_slice(&off.to_le_bytes());
        z.extend_from_slice(name.as_bytes());
        zentral.extend(z);
    }
    let zoff = out.len() as u32;
    let zl = zentral.len() as u32;
    out.extend(zentral);
    out.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
    out.extend_from_slice(&[0; 4]);
    out.extend_from_slice(&(dateien.len() as u16).to_le_bytes()); out.extend_from_slice(&(dateien.len() as u16).to_le_bytes());
    out.extend_from_slice(&zl.to_le_bytes()); out.extend_from_slice(&zoff.to_le_bytes());
    out.extend_from_slice(&[0; 2]);
    out
}

fn xml(s: &str) -> String { s.replace('&', "&amp;").replace('<', "&lt;").replace('"', "&quot;") }

pub fn dreimf(n: &Netz, name: &str) -> Vec<u8> {
    let mut m = String::with_capacity(n.pos.len() * 60 + n.idx.len() * 50);
    m.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"millimeter\" xml:lang=\"de-DE\" xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\"><metadata name=\"Application\">Bauwerk</metadata><resources><object id=\"1\" name=\"");
    m.push_str(&xml(name));
    m.push_str("\" type=\"model\"><mesh><vertices>");
    for p in &n.pos { m.push_str(&format!("<vertex x=\"{:.5}\" y=\"{:.5}\" z=\"{:.5}\"/>", p[0], p[1], p[2])); }
    m.push_str("</vertices><triangles>");
    for t in &n.idx { m.push_str(&format!("<triangle v1=\"{}\" v2=\"{}\" v3=\"{}\"/>", t[0], t[1], t[2])); }
    m.push_str("</triangles></mesh></object></resources><build><item objectid=\"1\"/></build></model>");
    zip(&[
        ("[Content_Types].xml", br#"<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>"#.to_vec()),
        ("_rels/.rels", br#"<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>"#.to_vec()),
        ("3D/3dmodel.model", m.into_bytes()),
    ])
}

/// STEP AP214 mit facettiertem Volumenkörper (FACETED_BREP). Für echte Flächen: Mesh2STEP.
pub fn step(n: &Netz, name: &str) -> Vec<u8> {
    let mut s = String::new();
    let mut id = 0usize;
    let mut e = |s: &mut String, t: String| -> usize { id += 1; s.push_str(&format!("#{}={};\n", id, t)); id };
    let mut kopf = String::new();
    kopf.push_str("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Bauwerk'),'2;1');\n");
    kopf.push_str(&format!("FILE_NAME('{}','',(''),(''),'Bauwerk','Bauwerk','');\n", name.replace('\'', "")));
    kopf.push_str("FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n");
    let app = e(&mut s, "APPLICATION_CONTEXT('core data for automotive mechanical design processes')".into());
    e(&mut s, format!("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{})", app));
    let pc = e(&mut s, format!("PRODUCT_CONTEXT('',#{},'mechanical')", app));
    let pr = e(&mut s, format!("PRODUCT('{0}','{0}','',(#{1}))", name.replace('\'', ""), pc));
    let pdf = e(&mut s, format!("PRODUCT_DEFINITION_FORMATION('','',#{})", pr));
    let pdc = e(&mut s, format!("PRODUCT_DEFINITION_CONTEXT('part definition',#{},'design')", app));
    let pd = e(&mut s, format!("PRODUCT_DEFINITION('design','',#{},#{})", pdf, pdc));
    let pds = e(&mut s, format!("PRODUCT_DEFINITION_SHAPE('','',#{})", pd));
    let lu = e(&mut s, "(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))".into());
    let au = e(&mut s, "(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))".into());
    let su = e(&mut s, "(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())".into());
    let unc = e(&mut s, format!("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),#{},'distance_accuracy_value','')", lu));
    let ctx = e(&mut s, format!("(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{}))GLOBAL_UNIT_ASSIGNED_CONTEXT((#{},#{},#{}))REPRESENTATION_CONTEXT('',''))", unc, lu, au, su));
    let pts: Vec<usize> = n.pos.iter().map(|p| e(&mut s, format!("CARTESIAN_POINT('',({:.6},{:.6},{:.6}))", p[0], p[1], p[2]))).collect();
    let mut flaechen = vec![];
    for t in &n.idx {
        let pl = e(&mut s, format!("POLY_LOOP('',(#{},#{},#{}))", pts[t[0]], pts[t[1]], pts[t[2]]));
        let fb = e(&mut s, format!("FACE_OUTER_BOUND('',#{},.T.)", pl));
        flaechen.push(e(&mut s, format!("FACE('',(#{}))", fb)));
    }
    let liste = flaechen.iter().map(|f| format!("#{}", f)).collect::<Vec<_>>().join(",");
    let sh = e(&mut s, format!("CLOSED_SHELL('',({}))", liste));
    let br = e(&mut s, format!("FACETED_BREP('{}',#{})", name.replace('\'', ""), sh));
    let ax_o = e(&mut s, "CARTESIAN_POINT('',(0.,0.,0.))".into());
    let ax = e(&mut s, format!("AXIS2_PLACEMENT_3D('',#{},$,$)", ax_o));
    let sr = e(&mut s, format!("FACETED_BREP_SHAPE_REPRESENTATION('',(#{},#{}),#{})", br, ax, ctx));
    e(&mut s, format!("SHAPE_DEFINITION_REPRESENTATION(#{},#{})", pds, sr));
    kopf.push_str(&s);
    kopf.push_str("ENDSEC;\nEND-ISO-10303-21;\n");
    kopf.into_bytes()
}
