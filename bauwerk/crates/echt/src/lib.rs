//! Steckt den Mesh2STEP-Kern an Bauwerk an: STEP-Export mit echten Flächen statt Dreiecken.
use bauwerk_kern::netz::Netz;
use mesh2step_core::{io::RawMesh, math::v3, Params};

fn umwandeln(n: &Netz, name: &str) -> Result<Vec<u8>, String> {
    let raw = RawMesh {
        name: name.to_string(),
        verts: n.pos.iter().map(|p| v3(p[0], p[1], p[2])).collect(),
        tris: n.idx.iter().map(|t| [t[0] as u32, t[1] as u32, t[2] as u32]).collect(),
        paint: vec![],
        flipped: vec![],
        extruder: vec![],
        plate: 0,
    };
    let datei = format!("{}.step", name);
    // Bauwerk-Netze liegen exakt auf der Form (Kreise mit ≤ 0,5 mm Sehne). Eine feste Toleranz
    // ist hier viel schneller (0,1 s statt ~50 s) und erkennt die Flächen sauberer als die
    // automatische Schätzung, die für gescannte/grobe STL gedacht ist.
    let prm = Params { tol: Some(0.02), ..Params::default() };
    // Mesh2STEP bricht per Panik ab, wenn etwas schiefgeht – dann facettiert weiter.
    let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| mesh2step_core::convert_meshes(&[raw], name, &datei, &prm)))
        .map_err(|_| "Mesh2STEP-Kern abgestürzt".to_string())?;
    Ok(r?.0.into_bytes())
}

/// Einmal beim Start aufrufen.
pub fn anmelden() { bauwerk_kern::export::step_echt_anmelden(umwandeln); }

#[cfg(test)]
mod tests {
    use bauwerk_kern::netz::*;
    #[test]
    fn platte_mit_bohrung_wird_echt() {
        super::anmelden();
        let fl = bauwerk_kern::profil::flaechen(&[vec![[0.0, 0.0], [60.0, 0.0], [60.0, 40.0], [0.0, 40.0]]]);
        let k = extrusion(&fl, 0.0, 10.0);
        let b = kegel(20.0, 20.0, -5.0, 15.0, 2.5, 2.5);
        let r = boolesch(&k, &b, Op::Abziehen).unwrap();
        let s = String::from_utf8(bauwerk_kern::export::step_beste(&r, "probe")).unwrap();
        assert_eq!(s.matches("CYLINDRICAL_SURFACE").count(), 1);
        assert_eq!(s.matches("ADVANCED_FACE").count(), 7);
        assert!(!s.contains("FACETED_BREP"));
    }

    #[test]
    fn halter_schnell_und_echt() {
        super::anmelden();
        let doc = r#"{"name":"Halter","features":[
 {"typ":"skizze","id":"s1","ebene":{"basis":"XY","versatz":0},
  "punkte":[{"id":"a","x":0,"y":0},{"id":"b","x":60,"y":0},{"id":"c","x":60,"y":40},{"id":"d","x":0,"y":40}],
  "elemente":[{"art":"linie","id":"l1","a":"a","b":"b"},{"art":"linie","id":"l2","a":"b","b":"c"},{"art":"linie","id":"l3","a":"c","b":"d"},{"art":"linie","id":"l4","a":"d","b":"a"}],"bedingungen":[]},
 {"typ":"extrusion","id":"e1","skizze":"s1","laenge":8,"modus":"hinzu","ecken":{"art":"rund","r":5}},
 {"typ":"skizze","id":"s2","ebene":{"basis":"XY","versatz":8},"punkte":[{"id":"m","x":30,"y":20}],"elemente":[{"art":"kreis","id":"k","m":"m","r":8}],"bedingungen":[]},
 {"typ":"extrusion","id":"e2","skizze":"s2","laenge":12,"modus":"hinzu"},
 {"typ":"skizze","id":"s3","ebene":{"basis":"XY","versatz":8},"punkte":[{"id":"p","x":10,"y":10},{"id":"q","x":50,"y":30}],"elemente":[],"bedingungen":[]},
 {"typ":"bohrung","id":"b1","skizze":"s3","d":3.4,"tiefe":0,"senkung":"kegel","sd":6.5,"st":1.8}]}"#;
        let e = bauwerk_kern::berechnen(&bauwerk_kern::dokument_lesen(doc).unwrap());
        let t0 = std::time::Instant::now();
        let s = String::from_utf8(bauwerk_kern::exportieren(&e, "step").unwrap()).unwrap();
        assert!(t0.elapsed().as_secs_f64() < 10.0, "zu langsam: {:?}", t0.elapsed());
        assert!(!s.contains("FACETED_BREP"));
        assert_eq!(s.matches("CONICAL_SURFACE").count(), 2, "Senkungen");
        assert!(s.matches("CYLINDRICAL_SURFACE").count() >= 6, "Ecken, Zapfen, Bohrung");
        assert!(s.matches("ADVANCED_FACE").count() <= 25);
    }
}
