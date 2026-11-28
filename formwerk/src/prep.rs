//! Druckvorbereitung: Modelle laden (mit Teilen, Filamenten und Bemalung), beste Drucklage finden,
//! Anordnung aus der Oberfläche als Bambu-3MF oder STL ausgeben.
use crate::mesh::{self, Mesh, V3, add, cross, dot, len, mul, norm, sub};
use anyhow::{Context, Result, bail};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::fmt::Write as _;
use std::io::{Cursor, Read, Write};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Instant;

pub struct Teil {
    pub name: String,
    pub mesh: Mesh,
    /// Bemalung je Dreieck (Bambu „paint_color“ bzw. PrusaSlicer „mmu_segmentation“)
    pub paint: Vec<Option<String>>,
    /// Stützen-Bemalung je Dreieck
    pub sup: Vec<Option<String>>,
    pub extruder: u32,
    /// Objekt war gespiegelt (Eckenreihenfolge vertauscht – wichtig fürs Lesen der Bemalung)
    pub gespiegelt: bool,
}

pub struct Modell {
    pub name: String,
    pub teile: Vec<Teil>,
}

impl Modell {
    pub fn einfach(name: String, mesh: Mesh, extruder: u32) -> Self {
        let n = mesh.tris.len();
        Modell { name: name.clone(), teile: vec![Teil { name, mesh, paint: vec![None; n], sup: vec![None; n], extruder, gespiegelt: false }] }
    }
    pub fn alles(&self) -> Mesh {
        let mut m = Mesh::new();
        for t in &self.teile {
            m.extend(&t.mesh);
        }
        m
    }
}

// ───────────────────────── Sitzungen im Speicher ─────────────────────────

pub struct Sitzung {
    zeit: Instant,
    next: u32,
    pub modelle: HashMap<u32, Arc<Modell>>,
}

fn sitzungen() -> &'static Mutex<HashMap<String, Sitzung>> {
    static S: OnceLock<Mutex<HashMap<String, Sitzung>>> = OnceLock::new();
    S.get_or_init(Default::default)
}

/// Modelle in die Sitzung legen (neue Sitzung, wenn `sid` leer/unbekannt). Liefert Sitzung und neue IDs.
pub fn ablegen(sid: &str, modelle: Vec<Modell>) -> (String, Vec<(u32, Arc<Modell>)>) {
    let mut s = sitzungen().lock().unwrap();
    s.retain(|_, v| v.zeit.elapsed().as_secs() < 6 * 3600);
    // höchstens 40 Sitzungen gleichzeitig: älteste fliegt raus
    while s.len() >= 40 {
        let alt = s.iter().min_by_key(|(_, v)| v.zeit).map(|(k, _)| k.clone()).unwrap();
        s.remove(&alt);
    }
    let sid = if !sid.is_empty() && s.contains_key(sid) { sid.to_string() } else { uuid::Uuid::new_v4().simple().to_string()[..16].to_string() };
    let e = s.entry(sid.clone()).or_insert_with(|| Sitzung { zeit: Instant::now(), next: 1, modelle: HashMap::new() });
    e.zeit = Instant::now();
    let mut neu = Vec::new();
    for m in modelle {
        let id = e.next;
        e.next += 1;
        let a = Arc::new(m);
        e.modelle.insert(id, a.clone());
        neu.push((id, a));
    }
    (sid, neu)
}

pub fn holen(sid: &str, id: u32) -> Option<Arc<Modell>> {
    let mut s = sitzungen().lock().unwrap();
    let e = s.get_mut(sid)?;
    e.zeit = Instant::now();
    e.modelle.get(&id).cloned()
}

pub fn bekannt(sid: &str) -> bool {
    sitzungen().lock().unwrap().contains_key(sid)
}

// ───────────────────────── Laden ─────────────────────────

pub fn laden(bytes: &[u8], fname: &str) -> Result<Vec<Modell>> {
    let lower = fname.to_lowercase();
    if lower.ends_with(".3mf") {
        let m = laden_3mf(bytes)?;
        if m.is_empty() {
            bail!("Die 3MF enthält keine druckbaren Objekte.");
        }
        return Ok(m);
    }
    if ![".stl", ".obj"].iter().any(|e| lower.ends_with(e)) {
        bail!("Bitte eine 3D-Datei laden (STL, 3MF oder OBJ).");
    }
    let objs = mesh::load(bytes, fname)?;
    Ok(objs.into_iter().map(|(n, m)| Modell::einfach(n, m, 1)).collect())
}

type Tf = [f64; 12];
const IDENT: Tf = [1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.];

fn tf_apply(t: &Tf, p: V3) -> V3 {
    [
        p[0] * t[0] + p[1] * t[3] + p[2] * t[6] + t[9],
        p[0] * t[1] + p[1] * t[4] + p[2] * t[7] + t[10],
        p[0] * t[2] + p[1] * t[5] + p[2] * t[8] + t[11],
    ]
}
/// erst a, dann b
fn tf_mul(a: &Tf, b: &Tf) -> Tf {
    let mut r = [0.0; 12];
    for i in 0..3 {
        for j in 0..3 {
            r[i * 3 + j] = (0..3).map(|k| a[i * 3 + k] * b[k * 3 + j]).sum();
        }
    }
    for j in 0..3 {
        r[9 + j] = (0..3).map(|k| a[9 + k] * b[k * 3 + j]).sum::<f64>() + b[9 + j];
    }
    r
}
fn tf_det(t: &Tf) -> f64 {
    t[0] * (t[4] * t[8] - t[5] * t[7]) - t[1] * (t[3] * t[8] - t[5] * t[6]) + t[2] * (t[3] * t[7] - t[4] * t[6])
}

struct ObjD {
    name: String,
    verts: Vec<V3>,
    tris: Vec<[usize; 3]>,
    paint: Vec<Option<String>>,
    sup: Vec<Option<String>>,
    comps: Vec<(String, String, Tf)>,
}

#[derive(Default)]
struct PartCfg {
    name: String,
    extruder: u32,
    subtype: String,
}
#[derive(Default)]
struct ObjCfg {
    name: String,
    extruder: u32,
    parts: HashMap<String, PartCfg>,
}

fn attrs_of(e: &quick_xml::events::BytesStart) -> HashMap<String, String> {
    let mut a = HashMap::new();
    for x in e.attributes().flatten() {
        let k = String::from_utf8_lossy(x.key.local_name().as_ref()).to_string();
        a.insert(k, x.unescape_value().map(|v| v.to_string()).unwrap_or_default());
    }
    a
}

fn laden_3mf(b: &[u8]) -> Result<Vec<Modell>> {
    use quick_xml::events::Event;
    let mut zip = zip::ZipArchive::new(Cursor::new(b)).context("Die 3MF ist beschädigt (kein gültiges ZIP).")?;
    let names: Vec<String> = (0..zip.len()).filter_map(|i| zip.by_index(i).ok().map(|f| f.name().to_string())).collect();
    let parse_tf = |s: &str| -> Tf {
        let v: Vec<f64> = s.split_whitespace().filter_map(|x| x.parse().ok()).collect();
        if v.len() == 12 { v.try_into().unwrap() } else { IDENT }
    };
    let mut objs: HashMap<(String, String), ObjD> = HashMap::new();
    let mut builds: Vec<(String, String, Tf)> = Vec::new();
    let mut total_tris = 0usize;
    let haupt = names.iter().find(|n| n.trim_start_matches('/').eq_ignore_ascii_case("3D/3dmodel.model")).cloned();
    for name in names.iter().filter(|n| n.to_lowercase().ends_with(".model")) {
        let mut xml = String::new();
        zip.by_name(name)?.read_to_string(&mut xml)?;
        let path = format!("/{}", name.trim_start_matches('/'));
        let ist_haupt = haupt.as_deref() == Some(name.as_str()) || haupt.is_none();
        let mut r = quick_xml::Reader::from_str(&xml);
        let mut cur: Option<(String, String)> = None;
        let mut in_build = false;
        loop {
            match r.read_event() {
                Ok(Event::Start(e)) | Ok(Event::Empty(e)) => {
                    let tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                    match tag.as_str() {
                        "object" => {
                            let a = attrs_of(&e);
                            let key = (path.clone(), a.get("id").cloned().unwrap_or_default());
                            objs.insert(key.clone(), ObjD { name: a.get("name").cloned().unwrap_or_default(), verts: vec![], tris: vec![], paint: vec![], sup: vec![], comps: vec![] });
                            cur = Some(key);
                        }
                        "vertex" => {
                            if let Some(k) = &cur {
                                let a = attrs_of(&e);
                                let g = |k: &str| a.get(k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                                objs.get_mut(k).unwrap().verts.push([g("x"), g("y"), g("z")]);
                            }
                        }
                        "triangle" => {
                            if let Some(k) = &cur {
                                let a = attrs_of(&e);
                                let g = |k: &str| a.get(k).and_then(|v| v.parse::<usize>().ok()).unwrap_or(0);
                                let o = objs.get_mut(k).unwrap();
                                o.tris.push([g("v1"), g("v2"), g("v3")]);
                                o.paint.push(a.get("paint_color").or_else(|| a.get("mmu_segmentation")).filter(|s| !s.is_empty()).cloned());
                                o.sup.push(a.get("paint_supports").filter(|s| !s.is_empty()).cloned());
                                total_tris += 1;
                                if total_tris > 6_000_000 {
                                    bail!("Das Modell ist zu fein (über 6 Mio. Dreiecke).");
                                }
                            }
                        }
                        "component" => {
                            if let Some(k) = &cur {
                                let a = attrs_of(&e);
                                let p = a.get("path").cloned().unwrap_or(path.clone());
                                let oid = a.get("objectid").cloned().unwrap_or_default();
                                let tf = a.get("transform").map(|s| parse_tf(s)).unwrap_or(IDENT);
                                objs.get_mut(k).unwrap().comps.push((p, oid, tf));
                            }
                        }
                        "build" => in_build = true,
                        "item" if in_build && ist_haupt => {
                            let a = attrs_of(&e);
                            if a.get("printable").map(|v| v == "0").unwrap_or(false) {
                                continue;
                            }
                            let oid = a.get("objectid").cloned().unwrap_or_default();
                            let p = a.get("path").cloned().unwrap_or(path.clone());
                            builds.push((p, oid, a.get("transform").map(|s| parse_tf(s)).unwrap_or(IDENT)));
                        }
                        _ => {}
                    }
                }
                Ok(Event::End(e)) => match e.local_name().as_ref() {
                    b"object" => cur = None,
                    b"build" => in_build = false,
                    _ => {}
                },
                Ok(Event::Eof) => break,
                Err(e) => bail!("3MF nicht lesbar: {e}"),
                _ => {}
            }
        }
    }
    // Bambu/Orca-Einstellungen: Filament je Objekt und Teil
    let mut cfg: HashMap<String, ObjCfg> = HashMap::new();
    if let Some(cn) = names.iter().find(|n| n.to_lowercase().ends_with("model_settings.config")) {
        let mut xml = String::new();
        zip.by_name(cn)?.read_to_string(&mut xml)?;
        let mut r = quick_xml::Reader::from_str(&xml);
        let mut obj: Option<String> = None;
        let mut part: Option<String> = None;
        loop {
            match r.read_event() {
                Ok(Event::Start(e)) | Ok(Event::Empty(e)) => {
                    let a = attrs_of(&e);
                    match e.local_name().as_ref() {
                        b"object" => {
                            let id = a.get("id").cloned().unwrap_or_default();
                            cfg.entry(id.clone()).or_default();
                            obj = Some(id);
                            part = None;
                        }
                        b"part" => {
                            if let Some(o) = &obj {
                                let id = a.get("id").cloned().unwrap_or_default();
                                cfg.get_mut(o).unwrap().parts.insert(id.clone(), PartCfg { subtype: a.get("subtype").cloned().unwrap_or("normal_part".into()), ..Default::default() });
                                part = Some(id);
                            }
                        }
                        b"metadata" => {
                            if let Some(o) = &obj {
                                let k = a.get("key").cloned().unwrap_or_default();
                                let v = a.get("value").cloned().unwrap_or_default();
                                let oc = cfg.get_mut(o).unwrap();
                                match (&part, k.as_str()) {
                                    (Some(p), "name") => oc.parts.get_mut(p).unwrap().name = v,
                                    (Some(p), "extruder") => oc.parts.get_mut(p).unwrap().extruder = v.parse().unwrap_or(0),
                                    (None, "name") => oc.name = v,
                                    (None, "extruder") => oc.extruder = v.parse().unwrap_or(0),
                                    _ => {}
                                }
                            }
                        }
                        _ => {}
                    }
                }
                Ok(Event::End(e)) => match e.local_name().as_ref() {
                    b"part" => part = None,
                    b"object" => {
                        obj = None;
                        part = None;
                    }
                    _ => {}
                },
                Ok(Event::Eof) | Err(_) => break,
                _ => {}
            }
        }
    }
    if builds.is_empty() {
        // ohne Build-Liste: alle Objekte mit Netz
        for (k, o) in &objs {
            if !o.tris.is_empty() || !o.comps.is_empty() {
                builds.push((k.0.clone(), k.1.clone(), IDENT));
            }
        }
    }
    let mut out = Vec::new();
    for (bi, (p, oid, tf)) in builds.iter().enumerate() {
        let Some(top) = objs.get(&(p.clone(), oid.clone())) else { continue };
        let oc = cfg.get(oid);
        let obj_ext = oc.map(|c| c.extruder).filter(|&e| e > 0).unwrap_or(1);
        let name = oc.map(|c| c.name.clone()).filter(|n| !n.is_empty()).or_else(|| Some(top.name.clone()).filter(|n| !n.is_empty())).unwrap_or(format!("Objekt {}", bi + 1));
        let mut teile = Vec::new();
        // (Objekt, Transformation, Teil-ID für die Einstellungen)
        let mut stack: Vec<((String, String), Tf, Option<String>, usize)> = vec![((p.clone(), oid.clone()), *tf, None, 0)];
        while let Some((key, t, part_id, tiefe)) = stack.pop() {
            let Some(o) = objs.get(&key) else { continue };
            if tiefe > 8 {
                continue;
            }
            if !o.tris.is_empty() {
                let pc = part_id.as_ref().and_then(|pid| oc.and_then(|c| c.parts.get(pid)));
                if pc.map(|c| c.subtype != "normal_part" && !c.subtype.is_empty()).unwrap_or(false) {
                    continue; // Modifier, negative Teile, Stützenblocker
                }
                let ext = pc.map(|c| c.extruder).filter(|&e| e > 0).unwrap_or(obj_ext);
                let tname = pc.map(|c| c.name.clone()).filter(|n| !n.is_empty()).unwrap_or_else(|| if o.name.is_empty() { name.clone() } else { o.name.clone() });
                let spiegel = tf_det(&t) < 0.0;
                let mut m = Mesh::new();
                let mut paint = Vec::new();
                let mut sup = Vec::new();
                for (i, tri) in o.tris.iter().enumerate() {
                    let (Some(a), Some(b), Some(c)) = (o.verts.get(tri[0]), o.verts.get(tri[1]), o.verts.get(tri[2])) else { continue };
                    let (a, b, c) = (tf_apply(&t, *a), tf_apply(&t, *b), tf_apply(&t, *c));
                    if !(a.iter().chain(&b).chain(&c).all(|v| v.is_finite())) {
                        continue;
                    }
                    if spiegel { m.push(a, c, b) } else { m.push(a, b, c) }
                    paint.push(o.paint[i].clone());
                    sup.push(o.sup[i].clone());
                }
                if !m.tris.is_empty() {
                    teile.push(Teil { name: tname, mesh: m, paint, sup, extruder: ext, gespiegelt: spiegel });
                }
            }
            for (cp, cid, ct) in &o.comps {
                // Teil-ID: auf oberster Ebene die Komponenten-ID
                let pid = if tiefe == 0 { Some(cid.clone()) } else { part_id.clone() };
                stack.push(((cp.clone(), cid.clone()), tf_mul(ct, &t), pid, tiefe + 1));
            }
        }
        if !teile.is_empty() {
            teile.reverse();
            out.push(Modell { name, teile });
        }
    }
    Ok(out)
}

/// Häufigster Zustand einer Bambu/Prusa-Bemalung (für die Vorschau). 0 = Grundfarbe des Teils.
pub fn mal_zustand(s: &str) -> u8 {
    let nib: Vec<u8> = s.bytes().rev().filter_map(|c| (c as char).to_digit(16).map(|d| d as u8)).collect();
    let mut zahl = [0usize; 32];
    let mut i = 0;
    while i < nib.len() {
        let code = nib[i];
        i += 1;
        if code & 3 != 0 {
            continue; // geteilt – Kinder folgen
        }
        let mut st = (code >> 2) as usize;
        if st == 3 && i < nib.len() {
            st = nib[i] as usize + 3;
            i += 1;
        }
        if st < zahl.len() {
            zahl[st] += 1;
        }
    }
    // bemalte Zustände vor „nicht bemalt“ bevorzugen
    let best = (1..zahl.len()).max_by_key(|&k| zahl[k]).unwrap_or(0);
    if zahl[best] > 0 && zahl[best] * 3 >= zahl[0] { best as u8 } else if zahl[0] > 0 { 0 } else { best as u8 }
}

// ───────────────────────── Vorschau & Kennzahlen ─────────────────────────

/// Binärdaten für die Vorschau: u32 Teile; je Teil: u32 Filament, u32 Dreiecke, f32 Punkte, u8 Bemalung
pub fn vorschau(m: &Modell) -> Vec<u8> {
    let n: usize = m.teile.iter().map(|t| t.mesh.tris.len()).sum();
    let mut o = Vec::with_capacity(4 + m.teile.len() * 8 + n * 37);
    o.extend_from_slice(&(m.teile.len() as u32).to_le_bytes());
    for t in &m.teile {
        o.extend_from_slice(&t.extruder.to_le_bytes());
        o.extend_from_slice(&(t.mesh.tris.len() as u32).to_le_bytes());
        for tri in &t.mesh.tris {
            for p in tri {
                for c in p {
                    o.extend_from_slice(&(*c as f32).to_le_bytes());
                }
            }
        }
        for p in &t.paint {
            o.push(p.as_deref().map(mal_zustand).unwrap_or(0));
        }
    }
    o
}

fn tri_area_n(t: &[V3; 3]) -> (f64, V3) {
    let c = cross(sub(t[1], t[0]), sub(t[2], t[0]));
    let l = len(c);
    (l / 2.0, if l > 0.0 { mul(c, 1.0 / l) } else { [0.0, 0.0, 0.0] })
}

/// Drehung, die `d` auf (0,0,-1) bringt (Zeilen-Matrix, v' = R·v)
fn nach_unten(d: V3) -> [f64; 9] {
    let a = norm(d);
    let b = [0.0, 0.0, -1.0];
    let v = cross(a, b);
    let c = dot(a, b);
    if c < -0.999999 {
        return [1., 0., 0., 0., -1., 0., 0., 0., -1.]; // 180° um X
    }
    let k = 1.0 / (1.0 + c);
    [
        v[0] * v[0] * k + c, v[0] * v[1] * k - v[2], v[0] * v[2] * k + v[1],
        v[1] * v[0] * k + v[2], v[1] * v[1] * k + c, v[1] * v[2] * k - v[0],
        v[2] * v[0] * k - v[1], v[2] * v[1] * k + v[0], v[2] * v[2] * k + c,
    ]
}

struct Lage {
    rot: [f64; 9],
    hoehe: f64,
    stuetz: f64,
    stuetz_vol: f64,
    kontakt: f64,
    kosten: f64,
}

fn bewerten(tris: &[[V3; 3]], verts_d: impl Fn(V3) -> f64, d: V3) -> (f64, f64, f64, f64) {
    let mut lo = f64::MAX;
    let mut hi = f64::MIN;
    for t in tris {
        for p in t {
            let v = verts_d(*p);
            lo = lo.min(v);
            hi = hi.max(v);
        }
    }
    let (mut stuetz, mut svol, mut kontakt) = (0.0, 0.0, 0.0);
    let cos45 = 0.7071;
    // Höhen von Oberseiten: was dort flach aufliegt, ist kein Überhang
    let mut oben = std::collections::HashSet::new();
    for t in tris {
        let (_, n) = tri_area_n(t);
        if dot(n, d) < -0.995 {
            let cz = (verts_d(t[0]) + verts_d(t[1]) + verts_d(t[2])) / 3.0;
            oben.insert(((hi - cz) * 20.0).round() as i64);
        }
    }
    for t in tris {
        let (a, n) = tri_area_n(t);
        let s = dot(n, d);
        let cz = (verts_d(t[0]) + verts_d(t[1]) + verts_d(t[2])) / 3.0;
        let ueber_bett = hi - cz; // Abstand zum Druckbett
        if s > 0.995 && ueber_bett > 0.15 && oben.contains(&((ueber_bett * 20.0).round() as i64)) {
            continue;
        }
        if s > 0.995 && ueber_bett < 0.15 {
            kontakt += a;
        } else if s > cos45 && ueber_bett > 0.6 {
            stuetz += a * s;
            svol += a * s * ueber_bett;
        }
    }
    (hi - lo, stuetz, svol, kontakt)
}

fn kosten(h: f64, st: f64, k: f64) -> f64 {
    st / 100.0 * 1.2 + h * 0.15 - k.sqrt() * 0.03
}

/// Kennzahlen und Lagen-Vorschläge eines Modells
pub fn kennzahlen(m: &Modell) -> Value {
    let all = m.alles();
    let bb = all.bbox();
    let size = bb.size();
    let vol = all.volume().abs();
    let flaeche: f64 = all.tris.iter().map(|t| tri_area_n(t).0).sum();
    // Original: Unterseite = -Z
    let down = [0.0, 0.0, -1.0];
    let (h0, s0, sv0, k0) = bewerten(&all.tris, |p| dot(p, down), down);
    let orig = Lage { rot: [1., 0., 0., 0., 1., 0., 0., 0., 1.], hoehe: h0, stuetz: s0, stuetz_vol: sv0, kontakt: k0, kosten: kosten(h0, s0, k0) };
    // Kandidaten: große Flächen gleicher Richtung + Achsen
    let mut fl: HashMap<(i32, i32, i32), (f64, V3)> = HashMap::new();
    for t in &all.tris {
        let (a, n) = tri_area_n(t);
        if a <= 0.0 {
            continue;
        }
        let k = ((n[0] * 40.0).round() as i32, (n[1] * 40.0).round() as i32, (n[2] * 40.0).round() as i32);
        let e = fl.entry(k).or_insert((0.0, [0.0; 3]));
        e.0 += a;
        e.1 = add(e.1, mul(n, a));
    }
    let mut kand: Vec<(f64, V3)> = fl.into_values().map(|(a, n)| (a, norm(n))).collect();
    kand.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    kand.truncate(30);
    for ax in [[1., 0., 0.], [-1., 0., 0.], [0., 1., 0.], [0., -1., 0.], [0., 0., 1.], [0., 0., -1.]] {
        kand.push((0.0, ax));
    }
    // für sehr feine Modelle nur eine Stichprobe bewerten
    let probe: Vec<[V3; 3]> = if all.tris.len() > 300_000 {
        let step = all.tris.len() / 300_000 + 1;
        all.tris.iter().step_by(step).cloned().collect()
    } else {
        all.tris.clone()
    };
    let faktor = all.tris.len() as f64 / probe.len().max(1) as f64;
    let mut lagen: Vec<Lage> = Vec::new();
    for (_, d) in kand {
        if lagen.iter().any(|l| {
            let r = l.rot;
            // gleiche Richtung schon bewertet? (R·d = -z)
            let z = r[6] * d[0] + r[7] * d[1] + r[8] * d[2];
            z < -0.999
        }) {
            continue;
        }
        let (h, st, sv, k) = bewerten(&probe, |p| dot(p, d), d);
        let (st, sv, k) = (st * faktor, sv * faktor, k * faktor);
        if k < 1.0 {
            continue; // liegt nicht auf
        }
        lagen.push(Lage { rot: nach_unten(d), hoehe: h, stuetz: st, stuetz_vol: sv, kontakt: k, kosten: kosten(h, st, k) });
    }
    lagen.sort_by(|a, b| a.kosten.partial_cmp(&b.kosten).unwrap());
    lagen.truncate(6);
    let lj = |l: &Lage| json!({ "rot": l.rot, "hoehe": l.hoehe, "stuetz": l.stuetz, "stuetz_vol": l.stuetz_vol, "kontakt": l.kontakt, "kosten": l.kosten });
    let bemalt: Vec<u8> = {
        let mut s: Vec<u8> = m.teile.iter().flat_map(|t| t.paint.iter().flatten().map(|p| mal_zustand(p))).filter(|&z| z > 0).collect();
        s.sort();
        s.dedup();
        s
    };
    json!({
        "name": m.name,
        "groesse": size,
        "volumen": vol,
        "flaeche": flaeche,
        "dreiecke": all.tris.len(),
        "teile": m.teile.iter().map(|t| json!({ "name": t.name, "ext": t.extruder, "dreiecke": t.mesh.tris.len() })).collect::<Vec<_>>(),
        "bemalt": bemalt,
        "orig": lj(&orig),
        "lagen": lagen.iter().map(lj).collect::<Vec<_>>(),
    })
}

// ───────────────────────── Ausgabe ─────────────────────────

#[derive(Deserialize)]
pub struct Instanz {
    pub m: u32,
    /// Drehung (Zeilen-Matrix 3×3), v' = R·v
    pub r: [f64; 9],
    #[serde(default = "eins")]
    pub s: f64,
    /// Mitte auf der Platte (mm, Druckbett-Koordinaten)
    pub x: f64,
    pub y: f64,
    /// 0 = Filamente aus der Datei, sonst alles in diesem Filament
    #[serde(default)]
    pub ext: u32,
    #[serde(default)]
    pub name: String,
    /// Stützen / Rand nur für dieses Teil (sonst aus den Einstellungen)
    #[serde(default)]
    pub stuetzen: Option<bool>,
    #[serde(default)]
    pub rand: Option<bool>,
}
fn eins() -> f64 {
    1.0
}

#[derive(Deserialize, Default)]
#[serde(default)]
pub struct Einst {
    pub schicht: f64,
    pub fuellung: f64,
    pub stuetzen: bool,
    pub rand: bool,
    pub material: String,
}

#[derive(Deserialize)]
pub struct Farbwechsel {
    pub z: f64,
    pub ext: u32,
    #[serde(default)]
    pub farbe: String,
}

#[derive(Deserialize)]
pub struct Auftrag {
    pub format: String,
    pub drucker: String,
    pub bett: [f64; 2],
    pub platten: Vec<Vec<Instanz>>,
    #[serde(default)]
    pub einst: Einst,
    #[serde(default)]
    pub farbwechsel: Vec<Farbwechsel>,
    #[serde(default)]
    pub mehrfarbig: bool,
    #[serde(default)]
    pub titel: String,
    /// In der App eingefärbte Bereiche: Modell-ID → je Teil Liste aus [Dreieck, Filament] (0 = Bemalung entfernen)
    #[serde(default)]
    pub bemalung: HashMap<String, Vec<Vec<[u32; 2]>>>,
}

/// Bemalung eines ganzen Dreiecks im Bambu-Format
pub fn mal_code(state: u32) -> Option<String> {
    match state {
        0 => None,
        1 | 2 => Some(format!("{:X}", state << 2)),
        s => Some(format!("{:X}C", (s - 3).min(15))),
    }
}

pub(crate) struct Obj {
    pub name: String,
    pub plate: usize,
    pub x: f64,
    pub y: f64,
    pub stuetzen: Option<bool>,
    pub rand: Option<bool>,
    pub teile: Vec<(String, u32, Vec<[V3; 3]>, Vec<Option<String>>, Vec<Option<String>>)>,
}

/// Bambu-3MF aus fertig platzierten Objekten (Netze in Plattenkoordinaten), Teile mit eigenem Filament
pub(crate) fn bambu_objekte(objs: &[Obj], bett: [f64; 2], drucker: &str, titel: &str) -> Result<Vec<u8>> {
    let a: Auftrag = serde_json::from_value(json!({ "format": "3mf", "drucker": drucker, "bett": bett, "platten": [], "titel": titel }))?;
    bambu_3mf(objs, &a)
}

/// Filamentfarben aus einer Bambu/Orca-3MF (project_settings.config), z. B. ["#FFFFFF", "#E53935"]
pub fn filamentfarben(b: &[u8]) -> Vec<String> {
    let Ok(mut zip) = zip::ZipArchive::new(Cursor::new(b)) else { return vec![] };
    let Some(n) = (0..zip.len()).filter_map(|i| zip.by_index(i).ok().map(|f| f.name().to_string())).find(|n| n.to_lowercase().ends_with("project_settings.config")) else { return vec![] };
    let mut s = String::new();
    if zip.by_name(&n).ok().and_then(|mut f| f.read_to_string(&mut s).ok()).is_none() {
        return vec![];
    }
    let v: Value = serde_json::from_str(&s).unwrap_or_default();
    v["filament_colour"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.chars().take(7).collect())).collect()).unwrap_or_default()
}

fn rot_apply(r: &[f64; 9], p: V3) -> V3 {
    [r[0] * p[0] + r[1] * p[1] + r[2] * p[2], r[3] * p[0] + r[4] * p[1] + r[5] * p[2], r[6] * p[0] + r[7] * p[1] + r[8] * p[2]]
}

fn objekte(sid: &str, a: &Auftrag) -> Result<Vec<Obj>> {
    let mut out = Vec::new();
    for (pi, pl) in a.platten.iter().enumerate() {
        for inst in pl {
            let m = holen(sid, inst.m).context("Die Sitzung ist abgelaufen – bitte das Modell neu laden.")?;
            let s = if inst.s > 0.0 && inst.s.is_finite() { inst.s } else { 1.0 };
            let det = {
                let r = &inst.r;
                r[0] * (r[4] * r[8] - r[5] * r[7]) - r[1] * (r[3] * r[8] - r[5] * r[6]) + r[2] * (r[3] * r[7] - r[4] * r[6])
            };
            let mut teile = Vec::new();
            let mut lo = [f64::MAX; 3];
            let mut hi = [f64::MIN; 3];
            for t in &m.teile {
                let mut tris = Vec::with_capacity(t.mesh.tris.len());
                for tri in &t.mesh.tris {
                    let mut q = tri.map(|p| rot_apply(&inst.r, mul(p, s)));
                    if det < 0.0 {
                        q.swap(1, 2);
                    }
                    for p in &q {
                        for k in 0..3 {
                            lo[k] = lo[k].min(p[k]);
                            hi[k] = hi[k].max(p[k]);
                        }
                    }
                    tris.push(q);
                }
                let ti_nr = teile.len();
                let (ext, paint) = if inst.ext > 0 {
                    (inst.ext, vec![None; t.paint.len()])
                } else {
                    let mut p = t.paint.clone();
                    if let Some(b) = a.bemalung.get(&inst.m.to_string()).and_then(|v| v.get(ti_nr)) {
                        for [tri, st] in b {
                            if let Some(x) = p.get_mut(*tri as usize) {
                                *x = mal_code(*st);
                            }
                        }
                    }
                    (t.extruder.max(1), p)
                };
                teile.push((t.name.clone(), ext, tris, paint, t.sup.clone()));
            }
            // Objekt-Ursprung: Mitte unten
            let c = [(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, lo[2]];
            for t in teile.iter_mut() {
                for tri in t.2.iter_mut() {
                    for p in tri.iter_mut() {
                        *p = sub(*p, c);
                    }
                }
            }
            out.push(Obj { name: if inst.name.is_empty() { m.name.clone() } else { inst.name.clone() }, plate: pi, x: inst.x, y: inst.y, stuetzen: inst.stuetzen, rand: inst.rand, teile });
        }
    }
    if out.is_empty() {
        bail!("Auf dem Druckbett liegt nichts.");
    }
    Ok(out)
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn plate_cols(n: usize) -> usize {
    let v = (n as f64).sqrt();
    let r = v.round();
    (if v > r { r + 1.0 } else { r }).max(1.0) as usize
}

fn uuid(a: usize, b: usize) -> String {
    format!("{a:08x}-61cb-4c03-9d28-{b:012x}")
}

pub fn ausgeben(sid: &str, a: &Auftrag) -> Result<(String, &'static str, Vec<u8>)> {
    let objs = objekte(sid, a)?;
    let titel = {
        let t: String = a.titel.chars().filter(|c| c.is_alphanumeric() || "-_ ".contains(*c)).collect();
        if t.trim().is_empty() { "druck".to_string() } else { t.trim().replace(' ', "_") }
    };
    if a.format == "stl" {
        let n_pl = objs.iter().map(|o| o.plate + 1).max().unwrap_or(1);
        let mut dateien = Vec::new();
        for p in 0..n_pl {
            let mut m = Mesh::new();
            for o in objs.iter().filter(|o| o.plate == p) {
                for t in &o.teile {
                    for tri in &t.2 {
                        let q = tri.map(|v| add(v, [o.x, o.y, 0.0]));
                        m.push(q[0], q[1], q[2]);
                    }
                }
            }
            if !m.tris.is_empty() {
                let name = if n_pl > 1 { format!("{titel}_platte{}.stl", p + 1) } else { format!("{titel}.stl") };
                dateien.push((name, m.to_stl(&titel)));
            }
        }
        if dateien.len() == 1 {
            let (n, d) = dateien.pop().unwrap();
            return Ok((n, "model/stl", d));
        }
        return Ok((format!("{titel}_stl.zip"), "application/zip", crate::export::zip_files(&dateien)));
    }
    Ok((format!("{titel}.3mf"), "application/vnd.ms-package.3dmanufacturing-3dmodel+xml", bambu_3mf(&objs, a)?))
}

/// Bambu-Studio-3MF wie in den MakerWorld-Dateien (Objekte aus Teilen, Filament je Teil, Bemalung, mehrere Platten)
fn bambu_3mf(objs: &[Obj], a: &Auftrag) -> Result<Vec<u8>> {
    let f = |v: f64| {
        let s = format!("{v:.5}");
        let s = s.trim_end_matches('0').trim_end_matches('.').to_string();
        if s == "-0" { "0".to_string() } else { s }
    };
    let n_pl = objs.iter().map(|o| o.plate + 1).max().unwrap_or(1);
    let cols = plate_cols(n_pl);
    let datum = "2026-01-01";
    let mut dateien: Vec<(String, Vec<u8>)> = Vec::new();
    let (mut top, mut build, mut cfg, mut rels) = (String::new(), String::new(), String::new(), String::new());
    let mut plate_xml: Vec<String> = vec![String::new(); n_pl];
    let mut sub_id = 1usize;
    let e = &a.einst;
    let schicht = if e.schicht > 0.03 && e.schicht < 1.0 { e.schicht } else { 0.2 };
    for (n, o) in objs.iter().enumerate() {
        let pfad = format!("/3D/Objects/object_{}.model", n + 1);
        let (mut res, mut comps, mut parts) = (String::new(), String::new(), String::new());
        for (tname, ext, tris, paint, sup) in &o.teile {
            let mut idx: HashMap<(u32, u32, u32), usize> = HashMap::new();
            let mut verts: Vec<V3> = Vec::new();
            let mut tri_s = String::with_capacity(tris.len() * 48);
            let mut face = 0usize;
            for (ti, t) in tris.iter().enumerate() {
                let mut k = [0usize; 3];
                for j in 0..3 {
                    let v = t[j];
                    let key = ((v[0] as f32).to_bits(), (v[1] as f32).to_bits(), (v[2] as f32).to_bits());
                    k[j] = *idx.entry(key).or_insert_with(|| {
                        verts.push(v);
                        verts.len() - 1
                    });
                }
                if k[0] == k[1] || k[1] == k[2] || k[0] == k[2] {
                    continue;
                }
                face += 1;
                let _ = write!(tri_s, "     <triangle v1=\"{}\" v2=\"{}\" v3=\"{}\"", k[0], k[1], k[2]);
                if let Some(p) = paint.get(ti).and_then(|p| p.as_ref()) {
                    let _ = write!(tri_s, " paint_color=\"{}\"", esc(p));
                }
                if let Some(p) = sup.get(ti).and_then(|p| p.as_ref()) {
                    let _ = write!(tri_s, " paint_supports=\"{}\"", esc(p));
                }
                tri_s.push_str("/>\n");
            }
            let mut vs = String::with_capacity(verts.len() * 48);
            for v in &verts {
                let _ = writeln!(vs, "     <vertex x=\"{}\" y=\"{}\" z=\"{}\"/>", f(v[0]), f(v[1]), f(v[2]));
            }
            let _ = write!(res, "  <object id=\"{sub_id}\" p:UUID=\"{}\" type=\"model\">\n   <mesh>\n    <vertices>\n{vs}    </vertices>\n    <triangles>\n{tri_s}    </triangles>\n   </mesh>\n  </object>\n", uuid(0x10000 + sub_id, sub_id));
            let _ = writeln!(comps, "    <component p:path=\"{pfad}\" objectid=\"{sub_id}\" p:UUID=\"{}\" transform=\"1 0 0 0 1 0 0 0 1 0 0 0\"/>", uuid(0x20000 + sub_id, sub_id));
            let _ = write!(parts, "    <part id=\"{sub_id}\" subtype=\"normal_part\">\n      <metadata key=\"name\" value=\"{}\"/>\n      <metadata key=\"matrix\" value=\"1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1\"/>\n      <metadata key=\"extruder\" value=\"{ext}\"/>\n      <mesh_stat face_count=\"{face}\" edges_fixed=\"0\" degenerate_facets=\"0\" facets_removed=\"0\" facets_reversed=\"0\" backwards_edges=\"0\"/>\n    </part>\n", esc(tname));
            sub_id += 1;
        }
        dateien.push((pfad[1..].to_string(), format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"millimeter\" xml:lang=\"en-US\" xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\" xmlns:BambuStudio=\"http://schemas.bambulab.com/package/2021\" xmlns:p=\"http://schemas.microsoft.com/3dmanufacturing/production/2015/06\" requiredextensions=\"p\">\n <metadata name=\"BambuStudio:3mfVersion\">1</metadata>\n <resources>\n{res} </resources>\n <build/>\n</model>\n").into_bytes()));
        let _ = writeln!(rels, " <Relationship Target=\"{pfad}\" Id=\"rel-{}\" Type=\"http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel\"/>", n + 1);
        let oid = 10000 + n;
        let _ = write!(top, "  <object id=\"{oid}\" p:UUID=\"{}\" type=\"model\">\n   <components>\n{comps}   </components>\n  </object>\n", uuid(n + 1, oid));
        let col = o.plate % cols;
        let row = o.plate / cols;
        let ox = col as f64 * a.bett[0] * 1.2 + o.x;
        let oy = -(row as f64) * a.bett[1] * 1.2 + o.y;
        let _ = writeln!(build, "  <item objectid=\"{oid}\" p:UUID=\"{}\" transform=\"1 0 0 0 1 0 0 0 1 {} {} 0\" printable=\"1\"/>", uuid(0x30000 + n, oid), f(ox), f(oy));
        let erst = o.teile.first().map(|t| t.1).unwrap_or(1);
        let _ = write!(cfg, "  <object id=\"{oid}\">\n    <metadata key=\"name\" value=\"{}\"/>\n    <metadata key=\"extruder\" value=\"{erst}\"/>\n", esc(&o.name));
        // Einstellungen je Objekt (Bambu Studio / OrcaSlicer übernehmen sie als Objekt-Einstellungen)
        let _ = writeln!(cfg, "    <metadata key=\"layer_height\" value=\"{}\"/>", f(schicht));
        if e.fuellung > 0.0 {
            let _ = writeln!(cfg, "    <metadata key=\"sparse_infill_density\" value=\"{}%\"/>", f(e.fuellung.clamp(0.0, 100.0)));
        }
        let stuetzen = o.stuetzen.unwrap_or(e.stuetzen);
        let rand = o.rand.unwrap_or(false);
        let _ = writeln!(cfg, "    <metadata key=\"enable_support\" value=\"{}\"/>", if stuetzen { 1 } else { 0 });
        if stuetzen {
            cfg.push_str("    <metadata key=\"support_type\" value=\"tree(auto)\"/>\n");
        }
        let _ = writeln!(cfg, "    <metadata key=\"brim_type\" value=\"{}\"/>", if rand { "outer_only" } else if e.rand { "auto_brim" } else { "no_brim" });
        cfg.push_str(&parts);
        cfg.push_str("  </object>\n");
        let _ = write!(plate_xml[o.plate], "    <model_instance>\n      <metadata key=\"object_id\" value=\"{oid}\"/>\n      <metadata key=\"instance_id\" value=\"0\"/>\n      <metadata key=\"identify_id\" value=\"{}\"/>\n    </model_instance>\n", 100 + n);
    }
    let titel = if a.titel.is_empty() { "Druck".to_string() } else { a.titel.clone() };
    dateien.push((
        "3D/3dmodel.model".into(),
        format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"millimeter\" xml:lang=\"de-DE\" xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\" xmlns:BambuStudio=\"http://schemas.bambulab.com/package/2021\" xmlns:p=\"http://schemas.microsoft.com/3dmanufacturing/production/2015/06\" requiredextensions=\"p\">\n <metadata name=\"Application\">BambuStudio-02.04.00.70</metadata>\n <metadata name=\"BambuStudio:3mfVersion\">1</metadata>\n <metadata name=\"CreationDate\">{datum}</metadata>\n <metadata name=\"ModificationDate\">{datum}</metadata>\n <metadata name=\"Title\">{}</metadata>\n <metadata name=\"Description\">Formwerk · {}</metadata>\n <resources>\n{top} </resources>\n <build p:UUID=\"2c7c17d8-22b5-4d84-8835-1976022ea369\">\n{build} </build>\n</model>\n",
            esc(&titel),
            esc(&a.drucker)
        )
        .into_bytes(),
    ));
    dateien.push(("3D/_rels/3dmodel.model.rels".into(), format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n{rels}</Relationships>\n").into_bytes()));
    let mut c = format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<config>\n{cfg}");
    for (i, px) in plate_xml.iter().enumerate() {
        let _ = write!(c, "  <plate>\n    <metadata key=\"plater_id\" value=\"{}\"/>\n    <metadata key=\"plater_name\" value=\"\"/>\n    <metadata key=\"locked\" value=\"false\"/>\n{px}  </plate>\n", i + 1);
    }
    c.push_str("  <assemble>\n  </assemble>\n</config>\n");
    dateien.push(("Metadata/model_settings.config".into(), c.into_bytes()));
    // Farbwechsel ab Höhe
    if !a.farbwechsel.is_empty() {
        let mut g = String::from("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<custom_gcodes_per_layer>\n");
        let typ = if a.mehrfarbig { 2 } else { 0 }; // 2 = Filament wechseln (AMS), 0 = Farbwechsel mit Pause
        for i in 0..n_pl {
            let _ = writeln!(g, "<plate>\n<plate_info id=\"{}\"/>", i + 1);
            for w in &a.farbwechsel {
                let z = ((w.z / schicht).round().max(1.0)) * schicht;
                let farbe = if w.farbe.starts_with('#') { w.farbe.clone() } else { "#FFFFFF".into() };
                let _ = writeln!(g, "<layer top_z=\"{}\" type=\"{typ}\" extruder=\"{}\" color=\"{}\" extra=\"\" gcode=\"{}\"/>", f(z), w.ext.max(1), esc(&farbe), if typ == 0 { "M600" } else { "tool_change" });
            }
            let _ = writeln!(g, "<mode value=\"{}\"/>\n</plate>", if a.mehrfarbig { "MultiAsSingle" } else { "SingleExtruder" });
        }
        g.push_str("</custom_gcodes_per_layer>\n");
        dateien.push(("Metadata/custom_gcode_per_layer.xml".into(), g.into_bytes()));
    }
    dateien.push(("[Content_Types].xml".into(), br#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="config" ContentType="text/xml"/>
 <Default Extension="xml" ContentType="text/xml"/>
</Types>"#.to_vec()));
    dateien.push(("_rels/.rels".into(), br#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"#.to_vec()));
    let mut buf = Cursor::new(Vec::new());
    {
        let mut z = zip::ZipWriter::new(&mut buf);
        let opt = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated).large_file(false);
        for (n, d) in &dateien {
            z.start_file(n.as_str(), opt)?;
            z.write_all(d)?;
        }
        z.finish()?;
    }
    Ok(buf.into_inner())
}

/// Zu großes Modell mit Formwerk zerlegen; liefert die Teile als neue Modelle
pub fn zerlegen(m: &Modell, r: &[f64; 9], s: f64, drucker: crate::werk::Printer) -> Result<(Vec<Modell>, crate::werk::Output)> {
    let mut all = Mesh::new();
    for t in &m.teile {
        for tri in &t.mesh.tris {
            let q = tri.map(|p| rot_apply(r, mul(p, s)));
            all.push(q[0], q[1], q[2]);
        }
    }
    let ext = m.teile.first().map(|t| t.extruder).unwrap_or(1);
    let p = crate::werk::Params { printers: vec![drucker], ..Default::default() };
    let out = crate::werk::split(&[(m.name.clone(), all)], &p)?;
    let mut neu = Vec::new();
    for (_, _, _, parts) in &out.plate_view {
        for (num, name, mesh) in parts {
            let nm = if name.is_empty() { format!("{} Teil {num}", m.name) } else { name.clone() };
            neu.push(Modell::einfach(nm, mesh.clone(), ext));
        }
    }
    if neu.is_empty() {
        bail!("Zerlegen hat keine Teile ergeben.");
    }
    Ok((neu, out))
}
