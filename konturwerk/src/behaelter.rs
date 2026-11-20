//! Gridfinity-Behälter bzw. freie Platte mit Werkzeugtaschen, Fingermulden und optionalem TPU-Inlay.
use crate::netz::{self, Netz, P2, Schicht, deckel, kreis, loft, poly, rrect};
use geo::{BooleanOps, Buffer, MultiPolygon, Simplify};
use serde::Deserialize;

pub const RASTER: f64 = 42.0;
pub const HOEHE_U: f64 = 7.0;
const FUSS_Z: f64 = 5.0;
const SEG: usize = 6;

#[derive(Deserialize, Clone, Default)]
#[serde(default)]
pub struct Werkzeug {
    pub name: String,
    /// Umriss in mm, lokal (um den Schwerpunkt), y nach unten wie im Foto
    pub umriss: Vec<P2>,
    pub x: f64,
    pub y: f64,
    /// Grad, im Uhrzeigersinn (Bildschirm)
    pub winkel: f64,
    pub spiegeln: bool,
    pub tiefe: f64,
    /// eigene Toleranz (sonst global)
    pub toleranz: Option<f64>,
}

#[derive(Deserialize, Clone, Default)]
#[serde(default)]
pub struct Form {
    /// "kreis" (Fingermulde), "rechteck", "langloch"
    pub art: String,
    pub x: f64,
    pub y: f64,
    pub b: f64,
    pub h: f64,
    pub winkel: f64,
    pub tiefe: f64,
}

#[derive(Deserialize, Clone)]
#[serde(default)]
pub struct Einstellungen {
    /// "gridfinity" oder "platte"
    pub typ: String,
    pub raster_x: u32,
    pub raster_y: u32,
    pub hoehe_u: u32,
    pub platte_b: f64,
    pub platte_t: f64,
    pub platte_h: f64,
    pub toleranz: f64,
    pub boden: f64,
    pub magnete: bool,
    pub stapelrand: bool,
    /// "aus", "separat", "kombiniert"
    pub inlay: String,
    pub inlay_spiel: f64,
    pub tpu_boden: f64,
    pub name: String,
}

impl Default for Einstellungen {
    fn default() -> Self {
        Self {
            typ: "gridfinity".into(),
            raster_x: 3,
            raster_y: 2,
            hoehe_u: 4,
            platte_b: 200.0,
            platte_t: 120.0,
            platte_h: 20.0,
            toleranz: 1.0,
            boden: 1.2,
            magnete: false,
            stapelrand: true,
            inlay: "aus".into(),
            inlay_spiel: 0.3,
            tpu_boden: 1.0,
            name: "Werkzeugeinsatz".into(),
        }
    }
}

#[derive(Deserialize, Clone, Default)]
#[serde(default)]
pub struct Layout {
    pub werkzeuge: Vec<Werkzeug>,
    pub formen: Vec<Form>,
    pub einstellungen: Einstellungen,
}

pub struct Teil {
    pub name: String,
    pub netz: Netz,
    /// 1 = Behälter (PLA/PETG), 2 = TPU
    pub filament: u32,
    pub platte: usize,
}

pub struct Ergebnis {
    pub teile: Vec<Teil>,
    /// kombiniertes Objekt (Behälter + Inlay an Ort und Stelle)
    pub kombiniert: bool,
    pub aussen: Vec<P2>,
    pub taschen: Vec<Vec<P2>>,
    pub breite: f64,
    pub tiefe_aussen: f64,
    pub hoehe: f64,
    pub hinweise: Vec<String>,
    pub inlay_dicke: Option<f64>,
}

fn mp(r: &[P2]) -> MultiPolygon<f64> {
    MultiPolygon::new(vec![poly(r)])
}

/// Außenmaße des Behälters (mm)
pub fn aussenmass(e: &Einstellungen) -> (f64, f64, f64) {
    if e.typ == "platte" {
        (e.platte_b.max(20.0), e.platte_t.max(20.0), e.platte_h.max(4.0))
    } else {
        (RASTER * e.raster_x.max(1) as f64 - 0.5, RASTER * e.raster_y.max(1) as f64 - 0.5, HOEHE_U * e.hoehe_u.max(1) as f64)
    }
}

/// Lokalen Umriss in Behälterkoordinaten bringen (Ausgabe: y nach oben)
fn platzieren(u: &[P2], x: f64, y: f64, winkel: f64, spiegeln: bool, d: f64) -> Vec<P2> {
    let a = winkel.to_radians();
    let (s, c) = a.sin_cos();
    let mut v: Vec<P2> = u.iter().map(|p| {
        let px = if spiegeln { -p[0] } else { p[0] };
        let (rx, ry) = (px * c - p[1] * s, px * s + p[1] * c);
        [x + rx, d - (y + ry)]
    }).collect();
    if spiegeln {
        v.reverse();
    }
    v
}

fn form_umriss(f: &Form) -> Vec<P2> {
    let b = f.b.max(1.0);
    let h = f.h.max(1.0);
    match f.art.as_str() {
        "rechteck" => rrect(-b / 2.0, -h / 2.0, b, h, 1.0, 3),
        "langloch" => rrect(-b / 2.0, -h / 2.0, b, h, h.min(b) / 2.0 - 0.01, 10),
        _ => kreis(0.0, 0.0, b / 2.0, 48),
    }
}

pub fn bauen(l: &Layout) -> anyhow::Result<Ergebnis> {
    let e = &l.einstellungen;
    let grid = e.typ != "platte";
    let (w, d, top) = aussenmass(e);
    let base_z = if grid { FUSS_Z } else { 0.0 };
    let rand = grid && e.stapelrand;
    let r_aussen = if grid { 3.75 } else { 4.0 };
    let mut hinweise = Vec::new();
    if top - base_z < 4.0 {
        anyhow::bail!("Der Behälter ist zu niedrig.");
    }
    let o_ring = rrect(0.0, 0.0, w, d, r_aussen, SEG);
    let o = mp(&o_ring);
    let inlay = e.inlay != "aus";
    let wand = if rand { 2.6 } else if grid { 1.6 } else { 2.0 };
    let boden = e.boden.clamp(0.6, 10.0);
    let zf = base_z + boden;
    let innen_ring = rrect(wand, wand, w - 2.0 * wand, d - 2.0 * wand, (r_aussen - wand).max(0.5), SEG);
    let erlaubt = mp(&innen_ring).buffer(-if inlay { 1.2 } else { 0.0 });

    // Taschen sammeln: (Fläche, Tiefe)
    let mut taschen: Vec<(MultiPolygon<f64>, f64, String)> = Vec::new();
    for t in &l.werkzeuge {
        if t.umriss.len() < 3 {
            continue;
        }
        let tol = t.toleranz.unwrap_or(e.toleranz).clamp(0.0, 5.0);
        let p = mp(&platzieren(&t.umriss, t.x, t.y, t.winkel, t.spiegeln, d));
        let p = if tol > 0.0 { p.buffer(tol) } else { p };
        taschen.push((p.simplify(0.03), t.tiefe.max(1.0), t.name.clone()));
    }
    for f in &l.formen {
        let u = form_umriss(f);
        let p = mp(&platzieren(&u, f.x, f.y, f.winkel, false, d));
        let name = if f.art == "kreis" { "Fingermulde" } else { "Form" };
        taschen.push((p, f.tiefe.max(1.0), name.into()));
    }
    // auf den Innenraum begrenzen
    for (p, _, name) in taschen.iter_mut() {
        let ueber = p.difference(&erlaubt);
        if geo::Area::unsigned_area(&ueber) > 1.0 {
            hinweise.push(format!("„{name}“ ragt über den Rand und wurde abgeschnitten."));
            *p = p.intersection(&erlaubt);
        }
    }

    let mut teile = Vec::new();
    let mut inlay_dicke = None;

    // Taschen nach Unterkante in Schichten umsetzen
    let schichten = |region: &MultiPolygon<f64>, z_unten: f64, z_oben: f64, unten_min: f64, durch_ab: Option<f64>, hinw: &mut Vec<String>| -> Vec<Schicht> {
        let mut liste: Vec<(f64, &MultiPolygon<f64>)> = Vec::new();
        for (p, t, name) in &taschen {
            let mut b = z_oben - t;
            if let Some(grenze) = durch_ab {
                if b < grenze {
                    b = z_unten; // Durchbruch im Inlay
                }
            }
            if b < unten_min {
                hinw.push(format!("„{name}“ ist tiefer als möglich und wurde auf {:.1} mm begrenzt.", z_oben - unten_min));
                b = unten_min;
            }
            liste.push((b, p));
        }
        let mut stufen: Vec<f64> = liste.iter().map(|x| x.0).filter(|&z| z > z_unten + 1e-6 && z < z_oben - 1e-6).collect();
        stufen.push(z_unten);
        stufen.push(z_oben);
        stufen.sort_by(|a, b| a.partial_cmp(b).unwrap());
        stufen.dedup_by(|a, b| (*a - *b).abs() < 0.01);
        let mut out = Vec::new();
        for s in stufen.windows(2) {
            let mut reg = region.clone();
            for (b, p) in &liste {
                if *b <= s[0] + 1e-6 {
                    reg = reg.difference(*p);
                }
            }
            out.push(Schicht { z0: s[0], z1: s[1], region: reg });
        }
        out
    };

    let mut koerper = Netz::default();
    if inlay {
        // Schale: Boden + Wand, Inlay füllt den Innenraum
        let schale = vec![
            Schicht { z0: base_z, z1: zf, region: o.clone() },
            Schicht { z0: zf, z1: top, region: o.difference(&mp(&innen_ring)) },
        ];
        koerper.anhaengen(&netz::stufenkoerper(&schale));
        let spiel = e.inlay_spiel.clamp(0.0, 2.0);
        let i_ring = rrect(wand + spiel, wand + spiel, w - 2.0 * (wand + spiel), d - 2.0 * (wand + spiel), (r_aussen - wand - spiel).max(0.4), SEG);
        let dicke = top - zf;
        inlay_dicke = Some(dicke);
        let tpu_min = e.tpu_boden.clamp(0.4, 5.0);
        let mut h = Vec::new();
        let sch = schichten(&mp(&i_ring), zf, top, zf, Some(zf + tpu_min), &mut h);
        hinweise.extend(h);
        let mut inl = netz::stufenkoerper(&sch);
        if e.inlay == "separat" {
            inl.verschieben([0.0, 0.0, -zf]);
        }
        teile.push(Teil { name: "TPU-Inlay".into(), netz: inl, filament: 2, platte: if e.inlay == "separat" { 1 } else { 0 } });
    } else {
        let mut h = Vec::new();
        let sch = schichten(&o, base_z, top, zf, None, &mut h);
        hinweise.extend(h);
        koerper.anhaengen(&netz::stufenkoerper(&sch));
    }
    if grid {
        for ix in 0..e.raster_x.max(1) {
            for iy in 0..e.raster_y.max(1) {
                let cx = 20.75 + ix as f64 * RASTER;
                let cy = 20.75 + iy as f64 * RASTER;
                koerper.anhaengen(&fuss(cx, cy, e.magnete));
            }
        }
        if rand {
            koerper.anhaengen(&stapelrand(w, d, top));
        }
    }
    teile.insert(0, Teil { name: if grid { "Gridfinity-Behälter".into() } else { "Platte".into() }, netz: koerper, filament: 1, platte: 0 });

    let taschen_2d: Vec<Vec<P2>> = taschen.iter()
        .flat_map(|(p, _, _)| netz::ringe_von(p).into_iter().flatten())
        .map(|r| r.into_iter().map(|q| [q[0], d - q[1]]).collect())
        .collect();
    Ok(Ergebnis {
        teile,
        kombiniert: e.inlay == "kombiniert",
        aussen: o_ring.iter().map(|q| [q[0], d - q[1]]).collect(),
        taschen: taschen_2d,
        breite: w,
        tiefe_aussen: d,
        hoehe: top + if rand { 4.4 } else { 0.0 },
        hinweise: dedup(hinweise),
        inlay_dicke,
    })
}

fn dedup(v: Vec<String>) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for s in v {
        if !out.contains(&s) {
            out.push(s);
        }
    }
    out
}

/// Gridfinity-Fuß einer Rasterzelle (Profil 0,8 / 1,8 / 2,15 mm), optional mit Magnetlöchern 6,5 × 2,4
fn fuss(cx: f64, cy: f64, magnete: bool) -> Netz {
    let ring = |s: f64, r: f64| rrect(cx - s / 2.0, cy - s / 2.0, s, s, r, SEG);
    let profil = vec![
        (0.0, ring(35.6, 0.8)),
        (0.8, ring(37.2, 1.6)),
        (2.6, ring(37.2, 1.6)),
        (4.75, ring(41.5, 3.75)),
        (FUSS_Z + 0.3, ring(41.5, 3.75)),
    ];
    if !magnete {
        return loft(&profil);
    }
    // Loft ohne Boden, Boden mit Löchern selbst bauen
    let mut n = loft(&profil);
    n.tris.retain(|t| !(t[0][2].abs() < 1e-9 && t[1][2].abs() < 1e-9 && t[2][2].abs() < 1e-9));
    let mut ringe = vec![profil[0].1.clone()];
    for (dx, dy) in [(-13.0, -13.0), (13.0, -13.0), (13.0, 13.0), (-13.0, 13.0)] {
        let k = kreis(cx + dx, cy + dy, 3.25, 32);
        let mut cw = k.clone();
        cw.reverse();
        // Lochwand (Material außen)
        for i in 0..cw.len() {
            let a = cw[i];
            let b = cw[(i + 1) % cw.len()];
            n.quad([a[0], a[1], 0.0], [b[0], b[1], 0.0], [b[0], b[1], 2.4], [a[0], a[1], 2.4]);
        }
        deckel(&mut n, &[k], 2.4, false);
        ringe.push(cw);
    }
    deckel(&mut n, &ringe, 0.0, false);
    n
}

/// Stapelrand (vereinfachtes Gridfinity-Profil) als eigene, leicht überlappende Hülle
fn stapelrand(w: f64, d: f64, top: f64) -> Netz {
    let r = 3.75;
    let ring = |inset: f64| rrect(inset, inset, w - 2.0 * inset, d - 2.0 * inset, (r - inset).max(0.3), SEG);
    let aussen = ring(0.0);
    let z0 = top - 0.2;
    let innen = [(z0, ring(2.0)), (top, ring(2.55)), (top + 0.7, ring(1.9)), (top + 2.5, ring(1.9)), (top + 4.4, ring(0.25))];
    let zt = top + 4.4;
    let mut n = Netz::default();
    let m = aussen.len();
    for i in 0..m {
        let j = (i + 1) % m;
        let (a, b) = (aussen[i], aussen[j]);
        // Außenwand
        n.quad([a[0], a[1], z0], [b[0], b[1], z0], [b[0], b[1], zt], [a[0], a[1], zt]);
        // Innenwand (Material außen → umgekehrt)
        for k in innen.windows(2) {
            let (za, ra) = (&k[0].0, &k[0].1);
            let (zb, rb) = (&k[1].0, &k[1].1);
            n.quad([ra[j][0], ra[j][1], *za], [ra[i][0], ra[i][1], *za], [rb[i][0], rb[i][1], *zb], [rb[j][0], rb[j][1], *zb]);
        }
        // Boden- und Deckring
        let (ia, ib) = (innen[0].1[i], innen[0].1[j]);
        n.quad([a[0], a[1], z0], [ia[0], ia[1], z0], [ib[0], ib[1], z0], [b[0], b[1], z0]);
        let (ta, tb) = (innen[4].1[i], innen[4].1[j]);
        n.quad([a[0], a[1], zt], [b[0], b[1], zt], [tb[0], tb[1], zt], [ta[0], ta[1], zt]);
    }
    n
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn behaelter_dicht() {
        let mut l = Layout::default();
        l.werkzeuge.push(Werkzeug { name: "Schlüssel".into(), umriss: rrect(-40.0, -8.0, 80.0, 16.0, 7.0, 8), x: 60.0, y: 40.0, winkel: 15.0, tiefe: 12.0, ..Default::default() });
        l.formen.push(Form { art: "kreis".into(), x: 60.0, y: 40.0, b: 20.0, h: 20.0, tiefe: 16.0, winkel: 0.0 });
        for inlay in ["aus", "separat", "kombiniert"] {
            l.einstellungen.inlay = inlay.into();
            l.einstellungen.magnete = true;
            let e = bauen(&l).unwrap();
            for t in &e.teile {
                assert!(!t.netz.tris.is_empty());
            }
            // Körper ohne Fuß/Rand separat prüfen geht nicht – Inlay ist eine einzelne Hülle
            if inlay != "aus" {
                crate::netz::debug_offen(&e.teile[1].netz); assert_eq!(e.teile[1].netz.offene_kanten(), 0, "Inlay {inlay}");
            }
        }
        assert_eq!(fuss(20.0, 20.0, true).offene_kanten(), 0);
        assert_eq!(stapelrand(125.5, 83.5, 28.0).offene_kanten(), 0);
    }
}
#[cfg(test)]
mod schale_test {
    use super::*;
    #[test]
    fn schale() {
        let (w, d) = (209.5, 125.5);
        let o_ring = rrect(0.0, 0.0, w, d, 3.75, SEG);
        let o = mp(&o_ring);
        let innen_ring = rrect(2.6, 2.6, w - 5.2, d - 5.2, 1.15, SEG);
        let s = vec![Schicht { z0: 5.0, z1: 6.2, region: o.clone() }, Schicht { z0: 6.2, z1: 28.0, region: o.difference(&mp(&innen_ring)) }];
        for (i, x) in s.iter().enumerate() { for r in netz::ringe_von(&x.region) { eprintln!("schicht {i}: {} ringe, längen {:?}", r.len(), r.iter().map(|q| q.len()).collect::<Vec<_>>()); } }
        let n = netz::stufenkoerper(&s);
        crate::netz::debug_offen(&n);
        assert_eq!(n.offene_kanten(), 0);
    }
}
