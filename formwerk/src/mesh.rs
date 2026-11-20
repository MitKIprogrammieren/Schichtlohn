//! Dreiecksnetz als Dreieckssuppe, Laden (STL/OBJ/3MF) und Schreiben (STL).
use anyhow::{Context, Result, bail};
use std::io::{Cursor, Read};

pub type V3 = [f64; 3];

#[derive(Clone, Default)]
pub struct Mesh {
    pub tris: Vec<[V3; 3]>,
}

pub fn sub(a: V3, b: V3) -> V3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
pub fn add(a: V3, b: V3) -> V3 {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}
pub fn mul(a: V3, s: f64) -> V3 {
    [a[0] * s, a[1] * s, a[2] * s]
}
pub fn cross(a: V3, b: V3) -> V3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
pub fn dot(a: V3, b: V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
pub fn len(a: V3) -> f64 {
    dot(a, a).sqrt()
}
pub fn norm(a: V3) -> V3 {
    let l = len(a);
    if l < 1e-30 { [0.0, 0.0, 1.0] } else { mul(a, 1.0 / l) }
}

#[derive(Clone, Copy, Debug)]
pub struct BBox {
    pub min: V3,
    pub max: V3,
}
impl BBox {
    pub fn size(&self) -> V3 {
        sub(self.max, self.min)
    }
}

impl Mesh {
    pub fn new() -> Self {
        Mesh { tris: Vec::new() }
    }
    pub fn push(&mut self, a: V3, b: V3, c: V3) {
        self.tris.push([a, b, c]);
    }
    /// Viereck a-b-c-d (gegen den Uhrzeigersinn von außen gesehen)
    pub fn quad(&mut self, a: V3, b: V3, c: V3, d: V3) {
        self.tris.push([a, b, c]);
        self.tris.push([a, c, d]);
    }
    pub fn extend(&mut self, o: &Mesh) {
        self.tris.extend_from_slice(&o.tris);
    }
    pub fn is_empty(&self) -> bool {
        self.tris.is_empty()
    }
    pub fn bbox(&self) -> BBox {
        let mut min = [f64::MAX; 3];
        let mut max = [f64::MIN; 3];
        for t in &self.tris {
            for p in t {
                for i in 0..3 {
                    min[i] = min[i].min(p[i]);
                    max[i] = max[i].max(p[i]);
                }
            }
        }
        if self.tris.is_empty() {
            min = [0.0; 3];
            max = [0.0; 3];
        }
        BBox { min, max }
    }
    pub fn translate(&mut self, d: V3) {
        for t in &mut self.tris {
            for p in t.iter_mut() {
                *p = add(*p, d);
            }
        }
    }
    pub fn scale(&mut self, s: f64) {
        for t in &mut self.tris {
            for p in t.iter_mut() {
                *p = mul(*p, s);
            }
        }
    }
    pub fn map(&mut self, f: impl Fn(V3) -> V3) {
        for t in &mut self.tris {
            for p in t.iter_mut() {
                *p = f(*p);
            }
        }
    }
    /// Spiegelt die Dreiecksorientierung (Normalen umdrehen)
    pub fn flip(&mut self) {
        for t in &mut self.tris {
            t.swap(1, 2);
        }
    }
    /// auf den Ursprung setzen: min x/y = 0, min z = 0
    pub fn place_on_origin(&mut self) {
        let b = self.bbox();
        self.translate([-b.min[0], -b.min[1], -b.min[2]]);
    }
    pub fn volume(&self) -> f64 {
        self.tris.iter().map(|t| dot(t[0], cross(t[1], t[2]))).sum::<f64>() / 6.0
    }
    /// Normalen nach außen drehen, falls das Netz "innen nach außen" ist
    pub fn fix_orientation(&mut self) {
        if self.volume() < 0.0 {
            self.flip();
        }
    }

    pub fn to_stl(&self, name: &str) -> Vec<u8> {
        let mut out = Vec::with_capacity(84 + self.tris.len() * 50);
        let mut header = [0u8; 80];
        let h = format!("Formwerk {name}");
        let hb = h.as_bytes();
        header[..hb.len().min(80)].copy_from_slice(&hb[..hb.len().min(80)]);
        out.extend_from_slice(&header);
        out.extend_from_slice(&(self.tris.len() as u32).to_le_bytes());
        for t in &self.tris {
            let n = norm(cross(sub(t[1], t[0]), sub(t[2], t[0])));
            for v in [n, t[0], t[1], t[2]] {
                for c in v {
                    out.extend_from_slice(&(c as f32).to_le_bytes());
                }
            }
            out.extend_from_slice(&[0, 0]);
        }
        out
    }
}

/// Datei laden. Liefert die einzelnen Objekte (3MF: je Build-Objekt, sonst ein Objekt) mit Namen.
pub fn load(bytes: &[u8], filename: &str) -> Result<Vec<(String, Mesh)>> {
    let lower = filename.to_lowercase();
    let stem = filename.rsplit(['/', '\\']).next().unwrap_or(filename);
    let stem = stem.rsplit_once('.').map(|x| x.0).unwrap_or(stem).to_string();
    let objs: Vec<(String, Mesh)> = if lower.ends_with(".obj") {
        vec![(stem, load_obj(bytes)?)]
    } else if lower.ends_with(".3mf") {
        load_3mf(bytes)?
    } else {
        vec![(stem, load_stl(bytes)?)]
    };
    let mut out = Vec::new();
    for (name, mut m) in objs {
        m.tris.retain(|t| t.iter().all(|p| p.iter().all(|c| c.is_finite())));
        if m.tris.is_empty() {
            continue;
        }
        // jeden Teilkörper einzeln nach außen orientieren
        let comps = crate::section::split_components(&m);
        if comps.len() > 1 && comps.len() < 5000 {
            let mut o = Mesh::new();
            for mut c in comps {
                c.fix_orientation_local();
                o.extend(&c);
            }
            m = o;
        } else {
            m.fix_orientation();
        }
        out.push((name, m));
    }
    if out.is_empty() {
        bail!("Die Datei enthält keine Dreiecke.");
    }
    Ok(out)
}

fn load_stl(b: &[u8]) -> Result<Mesh> {
    if b.len() >= 84 {
        let n = u32::from_le_bytes([b[80], b[81], b[82], b[83]]) as usize;
        if 84 + n * 50 == b.len() {
            let mut m = Mesh::new();
            m.tris.reserve(n);
            for i in 0..n {
                let o = 84 + i * 50 + 12;
                let f = |k: usize| f32::from_le_bytes(b[o + k * 4..o + k * 4 + 4].try_into().unwrap()) as f64;
                m.push([f(0), f(1), f(2)], [f(3), f(4), f(5)], [f(6), f(7), f(8)]);
            }
            return Ok(m);
        }
    }
    // ASCII
    let s = String::from_utf8_lossy(b);
    let mut m = Mesh::new();
    let mut cur: Vec<V3> = Vec::new();
    for line in s.lines() {
        let l = line.trim();
        if let Some(r) = l.strip_prefix("vertex") {
            let v: Vec<f64> = r.split_whitespace().filter_map(|x| x.parse().ok()).collect();
            if v.len() == 3 {
                cur.push([v[0], v[1], v[2]]);
            }
            if cur.len() == 3 {
                m.push(cur[0], cur[1], cur[2]);
                cur.clear();
            }
        } else if l.starts_with("endloop") {
            cur.clear();
        }
    }
    if m.is_empty() {
        bail!("STL konnte nicht gelesen werden.");
    }
    Ok(m)
}

fn load_obj(b: &[u8]) -> Result<Mesh> {
    let s = String::from_utf8_lossy(b);
    let mut vs: Vec<V3> = Vec::new();
    let mut m = Mesh::new();
    for line in s.lines() {
        let mut it = line.split_whitespace();
        match it.next() {
            Some("v") => {
                let v: Vec<f64> = it.take(3).filter_map(|x| x.parse().ok()).collect();
                if v.len() == 3 {
                    vs.push([v[0], v[1], v[2]]);
                }
            }
            Some("f") => {
                let idx: Vec<usize> = it
                    .filter_map(|x| x.split('/').next()?.parse::<i64>().ok())
                    .map(|i| if i < 0 { (vs.len() as i64 + i) as usize } else { (i - 1) as usize })
                    .collect();
                for k in 1..idx.len().saturating_sub(1) {
                    if let (Some(a), Some(b), Some(c)) = (vs.get(idx[0]), vs.get(idx[k]), vs.get(idx[k + 1])) {
                        m.push(*a, *b, *c);
                    }
                }
            }
            _ => {}
        }
    }
    Ok(m)
}

/// 3MF: liest alle Netze aller .model-Dateien und wendet Komponenten- und Build-Transformationen an.
fn load_3mf(b: &[u8]) -> Result<Vec<(String, Mesh)>> {
    use quick_xml::events::Event;
    use std::collections::HashMap;
    let mut zip = zip::ZipArchive::new(Cursor::new(b)).context("3MF ist kein gültiges ZIP")?;
    struct Obj {
        verts: Vec<V3>,
        tris: Vec<[usize; 3]>,
        comps: Vec<(String, String, [f64; 12])>, // (path, objectid, transform)
        name: String,
    }
    let mut objects: HashMap<(String, String), Obj> = HashMap::new();
    let mut builds: Vec<(String, String, [f64; 12])> = Vec::new();
    let names: Vec<String> = (0..zip.len()).filter_map(|i| zip.by_index(i).ok().map(|f| f.name().to_string())).collect();
    let ident = [1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.];
    let parse_tf = |s: &str| -> [f64; 12] {
        let v: Vec<f64> = s.split_whitespace().filter_map(|x| x.parse().ok()).collect();
        if v.len() == 12 { v.try_into().unwrap() } else { ident }
    };
    for name in names.iter().filter(|n| n.to_lowercase().ends_with(".model")) {
        let mut xml = String::new();
        zip.by_name(name)?.read_to_string(&mut xml)?;
        let path = format!("/{}", name.trim_start_matches('/'));
        let mut reader = quick_xml::Reader::from_str(&xml);
        let mut cur_id: Option<String> = None;
        let mut in_build = false;
        loop {
            match reader.read_event() {
                Ok(Event::Start(e)) | Ok(Event::Empty(e)) => {
                    let tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                    let mut attrs: HashMap<String, String> = HashMap::new();
                    for a in e.attributes().flatten() {
                        let k = String::from_utf8_lossy(a.key.local_name().as_ref()).to_string();
                        attrs.insert(k, a.unescape_value().map(|v| v.to_string()).unwrap_or_default());
                    }
                    match tag.as_str() {
                        "object" => {
                            let id = attrs.get("id").cloned().unwrap_or_default();
                            objects.insert((path.clone(), id.clone()), Obj { verts: vec![], tris: vec![], comps: vec![], name: attrs.get("name").cloned().unwrap_or_default() });
                            cur_id = Some(id);
                        }
                        "vertex" => {
                            if let Some(id) = &cur_id {
                                let g = |k: &str| attrs.get(k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                                objects.get_mut(&(path.clone(), id.clone())).unwrap().verts.push([g("x"), g("y"), g("z")]);
                            }
                        }
                        "triangle" => {
                            if let Some(id) = &cur_id {
                                let g = |k: &str| attrs.get(k).and_then(|v| v.parse::<usize>().ok()).unwrap_or(0);
                                objects.get_mut(&(path.clone(), id.clone())).unwrap().tris.push([g("v1"), g("v2"), g("v3")]);
                            }
                        }
                        "component" => {
                            if let Some(id) = &cur_id {
                                let p = attrs.get("path").cloned().unwrap_or(path.clone());
                                let oid = attrs.get("objectid").cloned().unwrap_or_default();
                                let tf = attrs.get("transform").map(|s| parse_tf(s)).unwrap_or(ident);
                                objects.get_mut(&(path.clone(), id.clone())).unwrap().comps.push((p, oid, tf));
                            }
                        }
                        "build" => in_build = true,
                        "item" if in_build => {
                            let oid = attrs.get("objectid").cloned().unwrap_or_default();
                            let p = attrs.get("path").cloned().unwrap_or(path.clone());
                            let tf = attrs.get("transform").map(|s| parse_tf(s)).unwrap_or(ident);
                            builds.push((p, oid, tf));
                        }
                        _ => {}
                    }
                }
                Ok(Event::End(e)) => {
                    let tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                    if tag == "object" {
                        cur_id = None;
                    } else if tag == "build" {
                        in_build = false;
                    }
                }
                Ok(Event::Eof) => break,
                Err(e) => bail!("3MF-XML fehlerhaft: {e}"),
                _ => {}
            }
        }
    }
    fn compose(a: &[f64; 12], b: &[f64; 12]) -> [f64; 12] {
        // 3MF: Zeilenvektor p' = p * M ; M = [m00 m01 m02; m10 m11 m12; m20 m21 m22; m30 m31 m32]
        // Ergebnis = erst a, dann b
        let ma = |r: usize, c: usize| a[r * 3 + c];
        let mb = |r: usize, c: usize| b[r * 3 + c];
        let mut o = [0.0; 12];
        for r in 0..4 {
            for c in 0..3 {
                let mut s = 0.0;
                for k in 0..3 {
                    s += ma(r, k) * mb(k, c);
                }
                if r == 3 {
                    s += mb(3, c);
                }
                o[r * 3 + c] = s;
            }
        }
        o
    }
    fn apply(m: &[f64; 12], p: V3) -> V3 {
        [
            p[0] * m[0] + p[1] * m[3] + p[2] * m[6] + m[9],
            p[0] * m[1] + p[1] * m[4] + p[2] * m[7] + m[10],
            p[0] * m[2] + p[1] * m[5] + p[2] * m[8] + m[11],
        ]
    }
    fn emit(objects: &HashMap<(String, String), Obj>, key: &(String, String), tf: &[f64; 12], out: &mut Mesh, depth: u32) {
        if depth > 16 {
            return;
        }
        let Some(o) = objects.get(key) else { return };
        for t in &o.tris {
            if let (Some(a), Some(b), Some(c)) = (o.verts.get(t[0]), o.verts.get(t[1]), o.verts.get(t[2])) {
                out.push(apply(tf, *a), apply(tf, *b), apply(tf, *c));
            }
        }
        for (p, oid, ctf) in &o.comps {
            emit(objects, &(p.clone(), oid.clone()), &compose(ctf, tf), out, depth + 1);
        }
    }
    // Bambu Studio speichert die Objektnamen in Metadata/model_settings.config
    let mut bambu_names: HashMap<String, String> = HashMap::new();
    if let Ok(mut f) = zip.by_name("Metadata/model_settings.config") {
        let mut xml = String::new();
        if f.read_to_string(&mut xml).is_ok() {
            let mut reader = quick_xml::Reader::from_str(&xml);
            let mut depth_obj: Option<String> = None;
            let mut level = 0;
            loop {
                match reader.read_event() {
                    Ok(Event::Start(e)) => {
                        level += 1;
                        if e.local_name().as_ref() == b"object" {
                            depth_obj = e.attributes().flatten().find(|a| a.key.as_ref() == b"id").map(|a| String::from_utf8_lossy(&a.value).to_string());
                            level = 1;
                        }
                    }
                    Ok(Event::Empty(e)) => {
                        if level == 1 && e.local_name().as_ref() == b"metadata" {
                            if let Some(id) = &depth_obj {
                                let at: HashMap<String, String> = e.attributes().flatten().map(|a| (String::from_utf8_lossy(a.key.as_ref()).to_string(), a.unescape_value().map(|v| v.to_string()).unwrap_or_default())).collect();
                                if at.get("key").map(|k| k == "name").unwrap_or(false) {
                                    bambu_names.entry(id.clone()).or_insert(at.get("value").cloned().unwrap_or_default());
                                }
                            }
                        }
                    }
                    Ok(Event::End(_)) => level -= 1,
                    Ok(Event::Eof) | Err(_) => break,
                    _ => {}
                }
            }
        }
    }
    let mut out: Vec<(String, Mesh)> = Vec::new();
    let mut list: Vec<(String, String, [f64; 12])> = builds.clone();
    if list.is_empty() {
        let mut keys: Vec<_> = objects.keys().cloned().collect();
        keys.sort();
        list = keys.into_iter().map(|(p, id)| (p, id, ident)).collect();
    }
    for (i, (p, oid, tf)) in list.iter().enumerate() {
        let mut m = Mesh::new();
        emit(&objects, &(p.clone(), oid.clone()), tf, &mut m, 0);
        if m.is_empty() {
            continue;
        }
        let name = bambu_names
            .get(oid)
            .cloned()
            .filter(|n| !n.is_empty())
            .or_else(|| objects.get(&(p.clone(), oid.clone())).map(|o| o.name.clone()).filter(|n| !n.is_empty()))
            .unwrap_or_else(|| format!("Objekt {}", i + 1));
        out.push((name, m));
    }
    Ok(out)
}
