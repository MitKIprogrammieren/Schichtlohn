//! Aus Skizzen-Elementen geschlossene Profile bilden (Gerade-Ungerade-Regel), Ecken runden/fasen.
use crate::modell::{Element, Punkt};
use i_overlay::core::fill_rule::FillRule;
use i_overlay::float::simplify::SimplifyShape;
use i_overlay::mesh::float::outline::offset::OutlineOffset;
use i_overlay::mesh::float::style::{LineJoin, OutlineStyle};
use std::collections::HashMap;

pub type P2 = [f64; 2];
pub type Kontur = Vec<P2>;
/// Eine Fläche: erste Kontur außen (gegen den Uhrzeigersinn), weitere sind Löcher (im Uhrzeigersinn).
pub type Flaeche = Vec<Kontur>;

pub fn segmente_fuer_radius(r: f64, winkel: f64) -> usize {
    let voll = (std::f64::consts::TAU * r / 0.5).ceil().clamp(24.0, 180.0);
    ((voll * winkel / std::f64::consts::TAU).ceil() as usize).max(3)
}

pub fn kreis(m: P2, r: f64) -> Kontur {
    let n = segmente_fuer_radius(r, std::f64::consts::TAU);
    (0..n).map(|i| { let a = i as f64 / n as f64 * std::f64::consts::TAU; [m[0] + r * a.cos(), m[1] + r * a.sin()] }).collect()
}

/// Punkte eines Bogens von a nach b (gegen den Uhrzeigersinn) – ohne Endpunkt.
pub fn bogen(m: P2, a: P2, b: P2) -> Vec<P2> {
    let r = ((a[0] - m[0]).powi(2) + (a[1] - m[1]).powi(2)).sqrt();
    let w0 = (a[1] - m[1]).atan2(a[0] - m[0]);
    let mut w1 = (b[1] - m[1]).atan2(b[0] - m[0]);
    while w1 <= w0 + 1e-12 { w1 += std::f64::consts::TAU; }
    let n = segmente_fuer_radius(r, w1 - w0);
    (0..n).map(|i| { let w = w0 + (w1 - w0) * i as f64 / n as f64; [m[0] + r * w.cos(), m[1] + r * w.sin()] }).collect()
}

/// Geschlossene Konturen aus den (Nicht-Hilfs-)Elementen.
pub fn konturen(punkte: &[Punkt], elemente: &[Element]) -> Vec<Kontur> {
    let pk: HashMap<&str, P2> = punkte.iter().map(|p| (p.id.as_str(), [p.x, p.y])).collect();
    let mut aus = vec![];
    // Kanten: (von, nach, Zwischenpunkte von→nach ohne Endpunkt)
    let mut kanten: Vec<(String, String, Vec<P2>)> = vec![];
    for e in elemente {
        if e.hilfs() { continue; }
        match e {
            Element::Kreis { m, r, .. } => { if let Some(c) = pk.get(m.as_str()) { if *r > 1e-9 { aus.push(kreis(*c, *r)); } } }
            Element::Linie { a, b, .. } => { if let (Some(pa), Some(_)) = (pk.get(a.as_str()), pk.get(b.as_str())) { if a != b { kanten.push((a.clone(), b.clone(), vec![*pa])); } } }
            Element::Bogen { m, a, b, .. } => {
                if let (Some(pm), Some(pa), Some(pb)) = (pk.get(m.as_str()), pk.get(a.as_str()), pk.get(b.as_str())) {
                    kanten.push((a.clone(), b.clone(), bogen(*pm, *pa, *pb)));
                }
            }
        }
    }
    // Kanten zu Ketten verbinden (Punkte gleicher Lage werden zusammengelegt)
    let schluessel = |id: &str| -> String {
        let p = pk[id];
        format!("{:.6},{:.6}", p[0], p[1])
    };
    let mut benutzt = vec![false; kanten.len()];
    let mut nachbarn: HashMap<String, Vec<usize>> = HashMap::new();
    for (i, k) in kanten.iter().enumerate() {
        nachbarn.entry(schluessel(&k.0)).or_default().push(i);
        nachbarn.entry(schluessel(&k.1)).or_default().push(i);
    }
    for start in 0..kanten.len() {
        if benutzt[start] { continue; }
        benutzt[start] = true;
        let anfang = schluessel(&kanten[start].0);
        let mut pts: Vec<P2> = kanten[start].2.clone();
        let mut ende = kanten[start].1.clone();
        let mut ok = false;
        for _ in 0..kanten.len() {
            let ks = schluessel(&ende);
            if ks == anfang { ok = true; break; }
            let Some(nx) = nachbarn.get(&ks).and_then(|v| v.iter().find(|&&j| !benutzt[j]).copied()) else { break };
            benutzt[nx] = true;
            let k = &kanten[nx];
            if schluessel(&k.0) == ks {
                pts.extend(k.2.iter().cloned());
                ende = k.1.clone();
            } else {
                // rückwärts durchlaufen: Punkte von b nach a
                let mut rueck: Vec<P2> = k.2.iter().cloned().collect();
                rueck.push(pk[k.1.as_str()]);
                rueck.reverse();
                rueck.pop(); // Endpunkt a gehört zur nächsten Kante
                pts.extend(rueck);
                ende = k.0.clone();
            }
        }
        if ok && pts.len() >= 3 { aus.push(pts); }
    }
    aus
}

fn flaeche_von(k: &Kontur) -> f64 {
    let mut s = 0.0;
    for i in 0..k.len() { let a = k[i]; let b = k[(i + 1) % k.len()]; s += a[0] * b[1] - b[0] * a[1]; }
    s / 2.0
}

/// Konturen nach Gerade-Ungerade-Regel zu Flächen mit Löchern zusammenfassen.
pub fn flaechen(konturen: &[Kontur]) -> Vec<Flaeche> {
    if konturen.is_empty() { return vec![]; }
    let roh: Vec<Vec<P2>> = konturen.to_vec();
    let mut f = roh.simplify_shape(FillRule::EvenOdd);
    ausrichten(&mut f);
    f
}

/// Außen gegen, Löcher im Uhrzeigersinn; Doppelpunkte entfernen.
pub fn ausrichten(f: &mut Vec<Flaeche>) {
    for fl in f.iter_mut() {
        fl.retain(|k| k.len() >= 3);
        for (i, k) in fl.iter_mut().enumerate() {
            k.dedup_by(|a, b| (a[0] - b[0]).abs() < 1e-9 && (a[1] - b[1]).abs() < 1e-9);
            let a = flaeche_von(k);
            if (i == 0 && a < 0.0) || (i > 0 && a > 0.0) { k.reverse(); }
        }
    }
    f.retain(|fl| !fl.is_empty() && flaeche_von(&fl[0]).abs() > 1e-9);
}

/// Alle Ecken (außen wie innen) mit Radius r runden oder fasen.
pub fn ecken(f: Vec<Flaeche>, art: &str, r: f64) -> Vec<Flaeche> {
    if r <= 0.0 || art == "keine" || f.is_empty() { return f; }
    let join = |r: f64| if art == "rund" { LineJoin::Round(0.5 / r.max(0.5)) } else { LineJoin::Bevel };
    let mut aus = vec![];
    for fl in f {
        // Öffnen (erst nach innen, dann nach außen) rundet die Außenecken; Löcher bleiben erhalten.
        let a = vec![fl].outline(&OutlineStyle::new(-r).line_join(join(r)));
        let b: Vec<Flaeche> = a.into_iter().flat_map(|s| vec![s].outline(&OutlineStyle::new(r).line_join(join(r)))).collect();
        aus.extend(b);
    }
    ausrichten(&mut aus);
    aus
}

/// Fläche in Dreiecke zerlegen: Indizes in die aneinandergehängten Konturpunkte.
pub fn dreiecke(fl: &Flaeche) -> Vec<[usize; 3]> {
    let mut daten = vec![];
    let mut loecher = vec![];
    for (i, k) in fl.iter().enumerate() {
        if i > 0 { loecher.push(daten.len() / 2); }
        for p in k { daten.push(p[0]); daten.push(p[1]); }
    }
    let idx = earcutr::earcut(&daten, &loecher, 2).unwrap_or_default();
    let mut aus = vec![];
    for t in idx.chunks(3) {
        let (a, b, c) = (t[0], t[1], t[2]);
        let pa = [daten[2 * a], daten[2 * a + 1]]; let pb = [daten[2 * b], daten[2 * b + 1]]; let pc = [daten[2 * c], daten[2 * c + 1]];
        let s = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]);
        if s.abs() < 1e-14 { continue; }
        aus.push(if s > 0.0 { [a, b, c] } else { [a, c, b] });
    }
    aus
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rechteck_mit_loch_und_rundung() {
        let r = vec![[0.0, 0.0], [60.0, 0.0], [60.0, 40.0], [0.0, 40.0]];
        let k = kreis([20.0, 20.0], 4.0);
        let f = flaechen(&[r, k]);
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].len(), 2);
        let g = ecken(f, "rund", 5.0);
        assert_eq!(g.len(), 1);
        assert!(g[0][0].len() > 8, "Ecken sollten gerundet sein");
        assert!(!dreiecke(&g[0]).is_empty());
    }
}
#[cfg(test)]
mod tests2 {
    use super::*;
    #[test]
    fn rundung_ohne_loch() {
        for r in [2.0, 5.0, 6.0] {
            let f = flaechen(&[vec![[0.0, 0.0], [60.0, 0.0], [60.0, 40.0], [0.0, 40.0]]]);
            let a = vec![f[0].clone()].outline(&OutlineStyle::new(-r).line_join(LineJoin::Round(0.1)));
            eprintln!("r={} innen: {:?}", r, a.iter().map(|s| s.iter().map(|k| k.len()).collect::<Vec<_>>()).collect::<Vec<_>>());
            let g = ecken(f, "rund", r);
            eprintln!("  ergebnis {:?}", g.iter().map(|s| s.iter().map(|k| k.len()).collect::<Vec<_>>()).collect::<Vec<_>>());
        }
    }
}
