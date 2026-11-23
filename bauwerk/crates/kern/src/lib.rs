//! Bauwerk-Kern: parametrisches CAD in reinem Rust.
//! Dokument → Skizzen lösen → Features der Zeitleiste nach berechnen → Netz → Export.
pub mod ausdruck;
pub mod export;
pub mod loeser;
pub mod modell;
pub mod netz;
pub mod profil;

use ausdruck::{parameter_auswerten, wert, Umgebung};
use loeser::LoeserStatus;
use modell::*;
use netz::{boolesch, Netz, Op, Rahmen};
use serde::Serialize;
use std::collections::{BTreeMap, HashMap, HashSet};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Clone, Serialize)]
pub struct FeatureInfo {
    pub id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fehler: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Ergebnis {
    /// Dokument mit gelösten Skizzen
    pub dok: Dokument,
    pub parameter: BTreeMap<String, f64>,
    pub skizzen: BTreeMap<String, LoeserStatus>,
    pub features: Vec<FeatureInfo>,
    pub meldungen: Vec<String>,
    pub volumen: f64,
    pub groesse: [f64; 3],
    pub minimum: [f64; 3],
    pub dreiecke: usize,
    #[serde(skip)]
    pub netz: Netz,
}

pub fn rahmen(e: &Ebene, u: &Umgebung) -> Result<Rahmen, String> {
    let (bu, bv, bn): ([f64; 3], [f64; 3], [f64; 3]) = match e.basis.as_str() {
        "XZ" => ([1., 0., 0.], [0., 0., 1.], [0., -1., 0.]),
        "YZ" => ([0., 1., 0.], [0., 0., 1.], [1., 0., 0.]),
        _ => ([1., 0., 0.], [0., 1., 0.], [0., 0., 1.]),
    };
    let s = if e.umgedreht { -1.0 } else { 1.0 };
    let vs = wert(&e.versatz, u)?;
    Ok(Rahmen { o: bn.map(|x| x * vs), u: bu.map(|x| x * s), v: bv, n: bn.map(|x| x * s) })
}

fn skizzen_geometrie(f: &Feature) -> Option<(&Ebene, &Vec<Punkt>, &Vec<Element>, &Vec<Bedingung>)> {
    if let Feature::Skizze { ebene, punkte, elemente, bedingungen, .. } = f { Some((ebene, punkte, elemente, bedingungen)) } else { None }
}

/// Punkt-IDs, die in Bedingungen vorkommen.
fn punkte_in_bedingungen(b: &[Bedingung]) -> HashSet<String> {
    let v = serde_json::to_value(b).unwrap_or_default();
    let mut s = HashSet::new();
    if let Some(a) = v.as_array() { for x in a { for k in ["a", "b", "punkt"] { if let Some(t) = x.get(k).and_then(|t| t.as_str()) { s.insert(t.to_string()); } } } }
    s
}

/// Komplettes Dokument berechnen.
pub fn berechnen(eingabe: &Dokument) -> Ergebnis {
    let mut dok = eingabe.clone();
    let (u, mut meldungen) = parameter_auswerten(&dok.parameter);
    let mut skizzen = BTreeMap::new();
    let mut infos = vec![];
    // 1. Skizzen lösen
    for f in dok.features.iter_mut() {
        if let Feature::Skizze { id, punkte, elemente, bedingungen, .. } = f {
            let st = loeser::loesen(punkte, elemente, bedingungen, &u);
            skizzen.insert(id.clone(), st);
        }
    }
    // 2. Zeitleiste abarbeiten
    let bis = dok.bis.unwrap_or(usize::MAX);
    let mut koerper = Netz::default();
    let index: HashMap<&str, &Feature> = dok.features.iter().map(|f| (f.id(), f)).collect();
    let mut gesehen: HashSet<&str> = HashSet::new();
    for (i, f) in dok.features.iter().enumerate() {
        gesehen.insert(f.id());
        if i >= bis || f.aus() || matches!(f, Feature::Skizze { .. }) {
            infos.push(FeatureInfo { id: f.id().into(), ok: true, fehler: None });
            continue;
        }
        let r = (|| -> Result<(), String> {
            let sid = f.skizze_id().unwrap_or("");
            let sk = index.get(sid).filter(|_| gesehen.contains(sid)).ok_or("Skizze fehlt oder steht später in der Zeitleiste")?;
            let (ebene, punkte, elemente, bedingungen) = skizzen_geometrie(sk).ok_or("verweist nicht auf eine Skizze")?;
            let rh = rahmen(ebene, &u)?;
            match f {
                Feature::Extrusion { laenge, richtung, modus, ecken, .. } => {
                    let l = wert(laenge, &u)?.abs().max(1e-4);
                    let fl = profil::flaechen(&profil::konturen(punkte, elemente));
                    if fl.is_empty() { return Err("Skizze hat kein geschlossenes Profil".into()); }
                    let rr = wert(&ecken.r, &u).unwrap_or(0.0);
                    let fl = profil::ecken(fl, &ecken.art, rr);
                    if fl.is_empty() { return Err("Rundung ist größer als das Profil".into()); }
                    let (z0, z1) = match richtung.as_str() { "umgekehrt" => (-l, 0.0), "symmetrisch" => (-l / 2.0, l / 2.0), _ => (0.0, l) };
                    let n = netz::extrusion(&fl, z0, z1).transformiert(&rh);
                    koerper = anwenden(&koerper, &n, modus)?;
                }
                Feature::Drehung { achse, winkel, modus, .. } => {
                    let pk: HashMap<&str, [f64; 2]> = punkte.iter().map(|p| (p.id.as_str(), [p.x, p.y])).collect();
                    let (a, b) = elemente.iter().find_map(|e| match e { Element::Linie { id, a, b, .. } if id == achse => Some((a, b)), _ => None }).ok_or("Drehachse (Linie) nicht gefunden")?;
                    let ohne: Vec<Element> = elemente.iter().filter(|e| e.id() != achse).cloned().collect();
                    let fl = profil::flaechen(&profil::konturen(punkte, &ohne));
                    if fl.is_empty() { return Err("Skizze hat kein geschlossenes Profil".into()); }
                    let w = wert(winkel, &u)?;
                    let n = netz::drehung(&fl, pk[a.as_str()], pk[b.as_str()], w)?.transformiert(&rh);
                    koerper = anwenden(&koerper, &n, modus)?;
                }
                Feature::Bohrung { d, tiefe, senkung, sd, st, .. } => {
                    let pk: HashMap<&str, [f64; 2]> = punkte.iter().map(|p| (p.id.as_str(), [p.x, p.y])).collect();
                    let mut mitten: Vec<[f64; 2]> = elemente.iter().filter_map(|e| if let Element::Kreis { m, .. } = e { pk.get(m.as_str()).copied() } else { None }).collect();
                    // einzelne Punkte (nicht Teil eines Elements) zählen auch
                    let benutzt: HashSet<&str> = elemente.iter().flat_map(|e| match e { Element::Linie { a, b, .. } => vec![a.as_str(), b.as_str()], Element::Kreis { m, .. } => vec![m.as_str()], Element::Bogen { m, a, b, .. } => vec![m.as_str(), a.as_str(), b.as_str()] }).collect();
                    let gebunden = punkte_in_bedingungen(bedingungen);
                    mitten.extend(punkte.iter().filter(|p| p.id != loeser::URSPRUNG && !benutzt.contains(p.id.as_str()) && !gebunden.contains(&p.id)).map(|p| [p.x, p.y]));
                    if mitten.is_empty() { return Err("Skizze hat keinen Kreis oder Punkt für die Bohrung".into()); }
                    if koerper.leer() { return Ok(()); }
                    let r = wert(d, &u)?.abs() / 2.0;
                    let t = wert(tiefe, &u)?.abs();
                    let t = if t > 0.0 { t } else { 1e4 };
                    let (sdv, stv) = (wert(sd, &u)?.abs() / 2.0, wert(st, &u)?.abs());
                    let ue = 0.05;
                    let mut werkzeug = Netz::default();
                    for m in mitten {
                        let mut w = netz::kegel(m[0], m[1], -t, ue, r, r);
                        if senkung == "kegel" && sdv > r {
                            let hk = sdv - r;
                            w = boolesch(&w, &netz::kegel(m[0], m[1], -hk, 0.0, r, sdv), Op::Vereinigen)?;
                            w = boolesch(&w, &netz::kegel(m[0], m[1], -0.001, ue, sdv, sdv), Op::Vereinigen)?;
                        } else if senkung == "zylinder" && sdv > r && stv > 0.0 {
                            w = boolesch(&w, &netz::kegel(m[0], m[1], -stv, ue, sdv, sdv), Op::Vereinigen)?;
                        }
                        werkzeug = if werkzeug.leer() { w } else { boolesch(&werkzeug, &w, Op::Vereinigen)? };
                    }
                    koerper = boolesch(&koerper, &werkzeug.transformiert(&rh), Op::Abziehen)?;
                }
                Feature::Skizze { .. } => {}
            }
            Ok(())
        })();
        match r {
            Ok(()) => infos.push(FeatureInfo { id: f.id().into(), ok: true, fehler: None }),
            Err(e) => infos.push(FeatureInfo { id: f.id().into(), ok: false, fehler: Some(e) }),
        }
    }
    for (id, st) in &skizzen { for m in &st.meldungen { meldungen.push(format!("{}: {}", name_von(&dok, id), m)); } }
    let (mi, ma) = if koerper.leer() { ([0.0; 3], [0.0; 3]) } else { koerper.grenzen() };
    let groesse = [ma[0] - mi[0], ma[1] - mi[1], ma[2] - mi[2]];
    Ergebnis {
        parameter: u.into_iter().collect(),
        skizzen,
        features: infos,
        meldungen,
        volumen: koerper.volumen(),
        groesse,
        minimum: mi,
        dreiecke: koerper.idx.len(),
        netz: koerper,
        dok,
    }
}

fn name_von(d: &Dokument, id: &str) -> String {
    d.features.iter().find(|f| f.id() == id).map(|f| if f.name().is_empty() { id.to_string() } else { f.name().to_string() }).unwrap_or_else(|| id.into())
}

fn anwenden(k: &Netz, n: &Netz, modus: &str) -> Result<Netz, String> {
    match modus {
        "abziehen" => boolesch(k, n, Op::Abziehen),
        "schnitt" => boolesch(k, n, Op::Schneiden),
        _ => boolesch(k, n, Op::Vereinigen),
    }
}

/// Export in stl | 3mf | step.
pub fn exportieren(e: &Ergebnis, format: &str) -> Result<Vec<u8>, String> {
    if e.netz.leer() { return Err("Kein Körper zum Exportieren".into()); }
    let name = &e.dok.name;
    match format.to_lowercase().as_str() {
        "stl" => Ok(export::stl(&e.netz, name)),
        "3mf" => Ok(export::dreimf(&e.netz, name)),
        "step" | "stp" => Ok(export::step(&e.netz, name)),
        f => Err(format!("Unbekanntes Format {}", f)),
    }
}

/// Dokument aus JSON lesen (nimmt auch das alte Bauwerk-1-Format mit „formen“ an).
pub fn dokument_lesen(json: &str) -> Result<Dokument, String> {
    let mut v: serde_json::Value = serde_json::from_str(json).map_err(|e| format!("JSON: {}", e))?;
    if let Some(fs) = v.get_mut("features").and_then(|f| f.as_array_mut()) {
        for f in fs.iter_mut() { alt_umwandeln(f); }
    }
    serde_json::from_value(v).map_err(|e| format!("Dokument: {}", e))
}

/// Bauwerk-1-Skizzen (formen: rechteck/kreis/linie) in Punkte + Elemente + Bedingungen umsetzen.
fn alt_umwandeln(f: &mut serde_json::Value) {
    use serde_json::json;
    if f.get("typ").and_then(|t| t.as_str()) != Some("skizze") { return; }
    let Some(formen) = f.get("formen").and_then(|x| x.as_array()).cloned() else { return };
    let (mut pk, mut el, mut bd) = (vec![], vec![], vec![]);
    for (i, fo) in formen.iter().enumerate() {
        let g = |k: &str| fo.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0);
        let p = format!("a{}", i);
        match fo.get("art").and_then(|a| a.as_str()) {
            Some("rechteck") => {
                let (x, y, b, h) = (g("x"), g("y"), g("b"), g("h"));
                let ecken = [(x, y), (x + b, y), (x + b, y + h), (x, y + h)];
                for (k, (px, py)) in ecken.iter().enumerate() { pk.push(json!({"id": format!("{}p{}", p, k), "x": px, "y": py})); }
                for k in 0..4 { el.push(json!({"art": "linie", "id": format!("{}l{}", p, k), "a": format!("{}p{}", p, k), "b": format!("{}p{}", p, (k + 1) % 4)})); }
                bd.push(json!({"art": "horizontal", "linie": format!("{}l0", p)})); bd.push(json!({"art": "horizontal", "linie": format!("{}l2", p)}));
                bd.push(json!({"art": "vertikal", "linie": format!("{}l1", p)})); bd.push(json!({"art": "vertikal", "linie": format!("{}l3", p)}));
            }
            Some("kreis") => {
                pk.push(json!({"id": format!("{}m", p), "x": g("x"), "y": g("y")}));
                el.push(json!({"art": "kreis", "id": format!("{}k", p), "m": format!("{}m", p), "r": g("d") / 2.0}));
            }
            Some("linie") => {
                let pts = fo.get("punkte").and_then(|x| x.as_array()).cloned().unwrap_or_default();
                let n = pts.len();
                for (k, q) in pts.iter().enumerate() { pk.push(json!({"id": format!("{}p{}", p, k), "x": q[0], "y": q[1]})); }
                let zu = fo.get("geschlossen").and_then(|x| x.as_bool()).unwrap_or(false);
                let m = if zu { n } else { n.saturating_sub(1) };
                for k in 0..m { el.push(json!({"art": "linie", "id": format!("{}l{}", p, k), "a": format!("{}p{}", p, k), "b": format!("{}p{}", p, (k + 1) % n)})); }
            }
            _ => {}
        }
    }
    let o = f.as_object_mut().unwrap();
    o.remove("formen");
    o.insert("punkte".into(), json!(pk));
    o.insert("elemente".into(), json!(el));
    o.insert("bedingungen".into(), json!(bd));
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ganzes_teil() {
        let json = r#"{"name":"Halter","parameter":[{"name":"breite","ausdruck":60},{"name":"hoehe","ausdruck":"12"}],
        "features":[
          {"typ":"skizze","id":"s1","name":"Skizze 1","punkte":[{"id":"a","x":0,"y":0},{"id":"b","x":50,"y":0},{"id":"c","x":50,"y":30},{"id":"d","x":0,"y":30}],
           "elemente":[{"art":"linie","id":"l1","a":"a","b":"b"},{"art":"linie","id":"l2","a":"b","b":"c"},{"art":"linie","id":"l3","a":"c","b":"d"},{"art":"linie","id":"l4","a":"d","b":"a"}],
           "bedingungen":[{"art":"horizontal","linie":"l1"},{"art":"horizontal","linie":"l3"},{"art":"vertikal","linie":"l2"},{"art":"vertikal","linie":"l4"},
             {"art":"koinzident","a":"a","b":"0"},{"art":"laenge","linie":"l1","wert":"breite"},{"art":"laenge","linie":"l2","wert":40}]},
          {"typ":"extrusion","id":"e1","skizze":"s1","laenge":"hoehe","ecken":{"art":"rund","r":5}},
          {"typ":"skizze","id":"s2","ebene":{"basis":"XY","versatz":"hoehe"},"punkte":[{"id":"m","x":15,"y":20},{"id":"n","x":45,"y":20}],"elemente":[]},
          {"typ":"bohrung","id":"b1","skizze":"s2","d":3.4,"senkung":"kegel"}
        ]}"#;
        let d = dokument_lesen(json).unwrap();
        let e = berechnen(&d);
        assert!(e.features.iter().all(|f| f.ok), "{:?}", e.features);
        assert_eq!(e.skizzen["s1"].zustand, "voll_bestimmt");
        assert!((e.groesse[0] - 60.0).abs() < 1e-6 && (e.groesse[2] - 12.0).abs() < 1e-6, "{:?}", e.groesse);
        assert!(e.volumen > 60.0 * 40.0 * 12.0 * 0.95 && e.volumen < 60.0 * 40.0 * 12.0, "{}", e.volumen);
        for f in ["stl", "3mf", "step"] { assert!(exportieren(&e, f).unwrap().len() > 1000); }
    }
    #[test]
    fn altes_format() {
        let json = r#"{"name":"alt","features":[{"typ":"skizze","id":"s","ebene":{"basis":"XY","versatz":0,"umgedreht":false},"formen":[{"id":"x","art":"rechteck","x":-30,"y":-20,"b":60,"h":40},{"id":"k","art":"kreis","x":0,"y":0,"d":8}]},{"typ":"extrusion","id":"e","skizze":"s","laenge":10,"richtung":"normal","modus":"hinzu","ecken":{"art":"keine","r":2}}]}"#;
        let e = berechnen(&dokument_lesen(json).unwrap());
        assert!(e.features.iter().all(|f| f.ok), "{:?}", e.features);
        assert!((e.volumen - (2400.0 - std::f64::consts::PI * 16.0) * 10.0).abs() < 20.0, "{}", e.volumen);
    }
}
