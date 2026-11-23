//! Skizzen-Löser: Bedingungen und Bemaßungen als Gleichungssystem, gelöst mit
//! Levenberg-Marquardt. Meldet die verbleibenden Freiheitsgrade.
use crate::ausdruck::{wert, Umgebung};
use crate::modell::{Bedingung, Element, Punkt};
use serde::Serialize;
use std::collections::HashMap;

pub const URSPRUNG: &str = "0";

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct LoeserStatus {
    /// voll_bestimmt | unterbestimmt | widerspruechlich
    pub zustand: String,
    pub freiheitsgrade: usize,
    pub restfehler: f64,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub meldungen: Vec<String>,
}

#[derive(Clone, Copy)]
enum Var { Fest(f64), Frei(usize) }

struct System<'a> {
    pkt: HashMap<&'a str, (Var, Var)>,
    rad: HashMap<&'a str, Var>,
    lin: HashMap<&'a str, (&'a str, &'a str)>,
    kreis: HashMap<&'a str, &'a str>, // id -> Mittelpunkt (Kreise und Bögen)
    boegen: Vec<(&'a str, &'a str, &'a str)>,
    gl: Vec<Gl<'a>>,
}

enum Gl<'a> {
    Koinz(&'a str, &'a str),
    Hor(&'a str), Ver(&'a str),
    Par(&'a str, &'a str), Senk(&'a str, &'a str),
    GleichL(&'a str, &'a str), GleichR(&'a str, &'a str),
    PaufL(&'a str, &'a str), PaufK(&'a str, &'a str),
    Mitte(&'a str, &'a str), Tang(&'a str, &'a str),
    Sym(&'a str, &'a str, &'a str),
    Abst(&'a str, &'a str, f64), AbstPL(&'a str, &'a str, f64),
    AbstX(&'a str, &'a str, f64), AbstY(&'a str, &'a str, f64),
    Laenge(&'a str, f64), Rad(&'a str, f64), Winkel(&'a str, &'a str, f64),
    Bogen(&'a str, &'a str, &'a str),
}

impl<'a> System<'a> {
    fn v(&self, var: Var, x: &[f64]) -> f64 { match var { Var::Fest(f) => f, Var::Frei(i) => x[i] } }
    fn p(&self, id: &str, x: &[f64]) -> (f64, f64) {
        let (a, b) = self.pkt[id];
        (self.v(a, x), self.v(b, x))
    }
    fn r(&self, id: &str, x: &[f64]) -> f64 {
        if let Some(v) = self.rad.get(id) { return self.v(*v, x); }
        // Bogen: Radius = Abstand Mittelpunkt–Startpunkt
        if let Some((m, a, _)) = self.boegen.iter().find(|b| b.0 == id).map(|b| (b.1, b.2, 0)) {
            let (mx, my) = self.p(m, x); let (ax, ay) = self.p(a, x);
            return ((ax - mx).powi(2) + (ay - my).powi(2)).sqrt();
        }
        0.0
    }
    fn d(&self, l: &str, x: &[f64]) -> ((f64, f64), (f64, f64)) {
        let (a, b) = self.lin[l];
        let pa = self.p(a, x); let pb = self.p(b, x);
        (pa, (pb.0 - pa.0, pb.1 - pa.1))
    }
    fn res(&self, x: &[f64], out: &mut Vec<f64>) {
        out.clear();
        let n = |d: (f64, f64)| (d.0 * d.0 + d.1 * d.1).sqrt().max(1e-12);
        for g in &self.gl {
            match *g {
                Gl::Koinz(a, b) => { let pa = self.p(a, x); let pb = self.p(b, x); out.push(pa.0 - pb.0); out.push(pa.1 - pb.1); }
                Gl::Hor(l) => { let (_, d) = self.d(l, x); out.push(d.1); }
                Gl::Ver(l) => { let (_, d) = self.d(l, x); out.push(d.0); }
                Gl::Par(a, b) => { let (_, d1) = self.d(a, x); let (_, d2) = self.d(b, x); out.push((d1.0 * d2.1 - d1.1 * d2.0) / (n(d1) * n(d2))); }
                Gl::Senk(a, b) => { let (_, d1) = self.d(a, x); let (_, d2) = self.d(b, x); out.push((d1.0 * d2.0 + d1.1 * d2.1) / (n(d1) * n(d2))); }
                Gl::GleichL(a, b) => { let (_, d1) = self.d(a, x); let (_, d2) = self.d(b, x); out.push(n(d1) - n(d2)); }
                Gl::GleichR(a, b) => out.push(self.r(a, x) - self.r(b, x)),
                Gl::PaufL(p, l) => { let pp = self.p(p, x); let (a, d) = self.d(l, x); out.push((d.0 * (pp.1 - a.1) - d.1 * (pp.0 - a.0)) / n(d)); }
                Gl::PaufK(p, k) => { let pp = self.p(p, x); let m = self.p(self.kreis[k], x); out.push(n((pp.0 - m.0, pp.1 - m.1)) - self.r(k, x)); }
                Gl::Mitte(p, l) => { let pp = self.p(p, x); let (a, d) = self.d(l, x); out.push(pp.0 - (a.0 + d.0 / 2.0)); out.push(pp.1 - (a.1 + d.1 / 2.0)); }
                Gl::Tang(l, k) => { let (a, d) = self.d(l, x); let m = self.p(self.kreis[k], x); out.push(((d.0 * (m.1 - a.1) - d.1 * (m.0 - a.0)) / n(d)).abs() - self.r(k, x)); }
                Gl::Sym(a, b, l) => {
                    let pa = self.p(a, x); let pb = self.p(b, x); let (o, d) = self.d(l, x);
                    let m = ((pa.0 + pb.0) / 2.0, (pa.1 + pb.1) / 2.0);
                    out.push((d.0 * (m.1 - o.1) - d.1 * (m.0 - o.0)) / n(d));
                    out.push(((pb.0 - pa.0) * d.0 + (pb.1 - pa.1) * d.1) / n(d));
                }
                Gl::Abst(a, b, w) => { let pa = self.p(a, x); let pb = self.p(b, x); out.push(n((pb.0 - pa.0, pb.1 - pa.1)) - w); }
                Gl::AbstPL(p, l, w) => { let pp = self.p(p, x); let (a, d) = self.d(l, x); out.push(((d.0 * (pp.1 - a.1) - d.1 * (pp.0 - a.0)) / n(d)).abs() - w); }
                Gl::AbstX(a, b, w) => { let pa = self.p(a, x); let pb = self.p(b, x); out.push((pb.0 - pa.0).abs() - w); }
                Gl::AbstY(a, b, w) => { let pa = self.p(a, x); let pb = self.p(b, x); out.push((pb.1 - pa.1).abs() - w); }
                Gl::Laenge(l, w) => { let (_, d) = self.d(l, x); out.push(n(d) - w); }
                Gl::Rad(k, w) => out.push(self.r(k, x) - w),
                Gl::Winkel(a, b, w) => {
                    let (_, d1) = self.d(a, x); let (_, d2) = self.d(b, x);
                    let c = ((d1.0 * d2.0 + d1.1 * d2.1) / (n(d1) * n(d2))).clamp(-1.0, 1.0);
                    out.push(c.acos() - w.to_radians());
                }
                Gl::Bogen(m, a, b) => { let pm = self.p(m, x); let pa = self.p(a, x); let pb = self.p(b, x); out.push(n((pa.0 - pm.0, pa.1 - pm.1)) - n((pb.0 - pm.0, pb.1 - pm.1))); }
            }
        }
    }
}

/// Löst eine Skizze in-place. Gibt den Status zurück.
pub fn loesen(punkte: &mut Vec<Punkt>, elemente: &mut Vec<Element>, bedingungen: &[Bedingung], u: &Umgebung) -> LoeserStatus {
    let mut meldungen = vec![];
    // Ursprung sicherstellen
    if !punkte.iter().any(|p| p.id == URSPRUNG) {
        punkte.insert(0, Punkt { id: URSPRUNG.into(), x: 0.0, y: 0.0, fest: true });
    }
    let fix: std::collections::HashSet<String> = bedingungen.iter().filter_map(|b| if let Bedingung::Fix { punkt } = b { Some(punkt.clone()) } else { None }).collect();
    let pk_kopie = punkte.clone();
    let el_kopie = elemente.clone();
    let mut wfehler: Vec<String> = vec![];
    let mut x0: Vec<f64> = vec![];
    let mut sys = System { pkt: HashMap::new(), rad: HashMap::new(), lin: HashMap::new(), kreis: HashMap::new(), boegen: vec![], gl: vec![] };
    for p in pk_kopie.iter() {
        let fest = p.fest || p.id == URSPRUNG || fix.contains(&p.id);
        let vx = if fest { Var::Fest(p.x) } else { x0.push(p.x); Var::Frei(x0.len() - 1) };
        let vy = if fest { Var::Fest(p.y) } else { x0.push(p.y); Var::Frei(x0.len() - 1) };
        sys.pkt.insert(p.id.as_str(), (vx, vy));
    }
    // Elemente mit fehlenden Punkten aussortieren
    let hat = |id: &str| sys.pkt.contains_key(id);
    let mut kaputt = vec![];
    for e in el_kopie.iter() {
        match e {
            Element::Linie { id, a, b, .. } => { if hat(a) && hat(b) { sys.lin.insert(id, (a, b)); } else { kaputt.push(id.clone()); } }
            Element::Kreis { id, m, r, .. } => { if hat(m) { x0.push(*r); sys.rad.insert(id, Var::Frei(x0.len() - 1)); sys.kreis.insert(id, m); } else { kaputt.push(id.clone()); } }
            Element::Bogen { id, m, a, b, .. } => { if hat(m) && hat(a) && hat(b) { sys.kreis.insert(id, m); sys.boegen.push((id, m, a)); sys.gl.push(Gl::Bogen(m, a, b)); } else { kaputt.push(id.clone()); } }
        }
    }
    for k in kaputt { meldungen.push(format!("Element {} verweist auf fehlende Punkte", k)); }
    let istp = |s: &str| sys.pkt.contains_key(s);
    let istl = |s: &str| sys.lin.contains_key(s);
    let istk = |s: &str| sys.kreis.contains_key(s);
    let mut gl = vec![];
    for b in bedingungen {
        let mut w = |v: &crate::modell::Wert| match wert(v, u) { Ok(z) => Some(z), Err(e) => { wfehler.push(e); None } };
        let g = match b {
            Bedingung::Koinzident { a, b } if istp(a) && istp(b) => Some(Gl::Koinz(a, b)),
            Bedingung::Horizontal { linie } if istl(linie) => Some(Gl::Hor(linie)),
            Bedingung::Vertikal { linie } if istl(linie) => Some(Gl::Ver(linie)),
            Bedingung::Parallel { a, b } if istl(a) && istl(b) => Some(Gl::Par(a, b)),
            Bedingung::Senkrecht { a, b } if istl(a) && istl(b) => Some(Gl::Senk(a, b)),
            Bedingung::Gleich { a, b } if istl(a) && istl(b) => Some(Gl::GleichL(a, b)),
            Bedingung::Gleich { a, b } if istk(a) && istk(b) => Some(Gl::GleichR(a, b)),
            Bedingung::Fix { .. } => None,
            Bedingung::PunktAufLinie { punkt, linie } if istp(punkt) && istl(linie) => Some(Gl::PaufL(punkt, linie)),
            Bedingung::PunktAufKreis { punkt, kreis } if istp(punkt) && istk(kreis) => Some(Gl::PaufK(punkt, kreis)),
            Bedingung::Mittelpunkt { punkt, linie } if istp(punkt) && istl(linie) => Some(Gl::Mitte(punkt, linie)),
            Bedingung::Tangential { linie, kreis } if istl(linie) && istk(kreis) => Some(Gl::Tang(linie, kreis)),
            Bedingung::Symmetrisch { a, b, linie } if istp(a) && istp(b) && istl(linie) => Some(Gl::Sym(a, b, linie)),
            Bedingung::Abstand { a, b, wert } if istp(a) && istp(b) => w(wert).map(|z| Gl::Abst(a, b, z)),
            Bedingung::Abstand { a, b, wert } if istp(a) && istl(b) => w(wert).map(|z| Gl::AbstPL(a, b, z)),
            Bedingung::AbstandX { a, b, wert } if istp(a) && istp(b) => w(wert).map(|z| Gl::AbstX(a, b, z.abs())),
            Bedingung::AbstandY { a, b, wert } if istp(a) && istp(b) => w(wert).map(|z| Gl::AbstY(a, b, z.abs())),
            Bedingung::Laenge { linie, wert } if istl(linie) => w(wert).map(|z| Gl::Laenge(linie, z)),
            Bedingung::Radius { kreis, wert } if istk(kreis) => w(wert).map(|z| Gl::Rad(kreis, z)),
            Bedingung::Durchmesser { kreis, wert } if istk(kreis) => w(wert).map(|z| Gl::Rad(kreis, z / 2.0)),
            Bedingung::Winkel { a, b, wert } if istl(a) && istl(b) => w(wert).map(|z| Gl::Winkel(a, b, z)),
            andere => { meldungen.push(format!("Bedingung passt nicht zu den Elementen: {:?}", andere)); None }
        };
        if let Some(g) = g { gl.push(g); }
    }
    sys.gl.extend(gl);
    meldungen.extend(wfehler);

    let n = x0.len();
    let mut x = x0.clone();
    let mut f = vec![];
    sys.res(&x, &mut f);
    let m = f.len();
    let norm = |f: &[f64]| f.iter().map(|v| v * v).sum::<f64>();
    let mut fehler = norm(&f);
    let mut lambda = 1e-3;
    let mut jac = vec![0.0; m * n];
    let mut f2 = vec![];
    if n > 0 && m > 0 {
        for _iter in 0..200 {
            if fehler < 1e-20 { break; }
            jacobi(&sys, &x, &f, &mut jac, m, n);
            // (JᵀJ + λ·(diag+1)) Δ = -Jᵀf
            let mut a = vec![0.0; n * n];
            let mut g = vec![0.0; n];
            for r in 0..m {
                let row = &jac[r * n..(r + 1) * n];
                for i in 0..n {
                    if row[i] == 0.0 { continue; }
                    g[i] -= row[i] * f[r];
                    for j in 0..n { a[i * n + j] += row[i] * row[j]; }
                }
            }
            let mut besser = false;
            for _ in 0..12 {
                let mut aa = a.clone();
                for i in 0..n { aa[i * n + i] += lambda * (a[i * n + i] + 1.0); }
                let Some(delta) = gauss(&mut aa, &mut g.clone(), n) else { lambda *= 10.0; continue; };
                let xn: Vec<f64> = x.iter().zip(&delta).map(|(a, b)| a + b).collect();
                sys.res(&xn, &mut f2);
                let fe = norm(&f2);
                if fe < fehler {
                    x = xn; std::mem::swap(&mut f, &mut f2); fehler = fe;
                    lambda = (lambda * 0.3).max(1e-12);
                    besser = true;
                    break;
                }
                lambda *= 8.0;
            }
            if !besser { break; }
        }
    }
    // Freiheitsgrade = Variablen − Rang der Jacobi-Matrix
    let rang = if n > 0 && m > 0 { jacobi(&sys, &x, &f, &mut jac, m, n); rang(&jac, m, n) } else { 0 };
    let frei = n - rang.min(n);
    let rest = fehler.sqrt();
    let zustand = if rest > 1e-5 { "widerspruechlich" } else if frei == 0 { "voll_bestimmt" } else { "unterbestimmt" };
    if rest > 1e-5 { meldungen.push("Bedingungen widersprechen sich oder sind nicht erfüllbar".into()); }
    // Ergebnis zurückschreiben
    for p in punkte.iter_mut() {
        if let Some((vx, vy)) = sys.pkt.get(p.id.as_str()) {
            if let Var::Frei(i) = vx { p.x = runde(x[*i]); }
            if let Var::Frei(i) = vy { p.y = runde(x[*i]); }
        }
    }
    for e in elemente.iter_mut() {
        if let Element::Kreis { id, r, .. } = e {
            if let Some(Var::Frei(i)) = sys.rad.get(id.as_str()) { *r = runde(x[*i].abs()); }
        }
    }
    LoeserStatus { zustand: zustand.into(), freiheitsgrade: frei, restfehler: rest, meldungen }
}

fn runde(v: f64) -> f64 { (v * 1e9).round() / 1e9 }

fn jacobi(sys: &System, x: &[f64], f: &[f64], jac: &mut [f64], m: usize, n: usize) {
    let mut xx = x.to_vec();
    let mut fp = vec![];
    for j in 0..n {
        let h = 1e-7 * x[j].abs().max(1.0);
        let alt = xx[j];
        xx[j] = alt + h;
        sys.res(&xx, &mut fp);
        xx[j] = alt;
        for r in 0..m { jac[r * n + j] = (fp[r] - f[r]) / h; }
    }
}

fn gauss(a: &mut [f64], b: &mut [f64], n: usize) -> Option<Vec<f64>> {
    for c in 0..n {
        let mut p = c;
        for r in c + 1..n { if a[r * n + c].abs() > a[p * n + c].abs() { p = r; } }
        if a[p * n + c].abs() < 1e-14 { return None; }
        if p != c { for k in 0..n { a.swap(c * n + k, p * n + k); } b.swap(c, p); }
        for r in c + 1..n {
            let fak = a[r * n + c] / a[c * n + c];
            if fak == 0.0 { continue; }
            for k in c..n { a[r * n + k] -= fak * a[c * n + k]; }
            b[r] -= fak * b[c];
        }
    }
    let mut x = vec![0.0; n];
    for c in (0..n).rev() {
        let mut s = b[c];
        for k in c + 1..n { s -= a[c * n + k] * x[k]; }
        x[c] = s / a[c * n + c];
    }
    Some(x)
}

fn rang(j: &[f64], m: usize, n: usize) -> usize {
    let mut a = j.to_vec();
    let max = a.iter().fold(0.0f64, |s, v| s.max(v.abs())).max(1e-12);
    let tol = max * 1e-7;
    let mut r = 0;
    for c in 0..n {
        if r >= m { break; }
        let mut p = r;
        for i in r + 1..m { if a[i * n + c].abs() > a[p * n + c].abs() { p = i; } }
        if a[p * n + c].abs() <= tol { continue; }
        for k in 0..n { a.swap(r * n + k, p * n + k); }
        for i in r + 1..m {
            let fak = a[i * n + c] / a[r * n + c];
            if fak == 0.0 { continue; }
            for k in c..n { a[i * n + k] -= fak * a[r * n + k]; }
        }
        r += 1;
    }
    r
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::modell::Wert;
    fn p(id: &str, x: f64, y: f64) -> Punkt { Punkt { id: id.into(), x, y, fest: false } }
    fn l(id: &str, a: &str, b: &str) -> Element { Element::Linie { id: id.into(), a: a.into(), b: b.into(), hilfs: false } }
    #[test]
    fn rechteck_voll_bestimmt() {
        let mut pk = vec![p("a", 0.1, -0.2), p("b", 55.0, 1.0), p("c", 52.0, 38.0), p("d", 2.0, 41.0)];
        let mut el = vec![l("l1", "a", "b"), l("l2", "b", "c"), l("l3", "c", "d"), l("l4", "d", "a")];
        let bd = vec![
            Bedingung::Horizontal { linie: "l1".into() }, Bedingung::Horizontal { linie: "l3".into() },
            Bedingung::Vertikal { linie: "l2".into() }, Bedingung::Vertikal { linie: "l4".into() },
            Bedingung::Koinzident { a: "a".into(), b: URSPRUNG.into() },
            Bedingung::Laenge { linie: "l1".into(), wert: Wert::Text("breite".into()) },
            Bedingung::Laenge { linie: "l2".into(), wert: Wert::Zahl(40.0) },
        ];
        let mut u = Umgebung::new(); u.insert("breite".into(), 60.0);
        let s = loesen(&mut pk, &mut el, &bd, &u);
        assert_eq!(s.zustand, "voll_bestimmt", "{:?}", s);
        let c = pk.iter().find(|p| p.id == "c").unwrap();
        assert!((c.x - 60.0).abs() < 1e-6 && (c.y - 40.0).abs() < 1e-6, "{:?}", c);
    }
    #[test]
    fn widerspruch() {
        let mut pk = vec![p("a", 0.0, 0.0), p("b", 10.0, 0.0)];
        let mut el = vec![l("l1", "a", "b")];
        let bd = vec![Bedingung::Laenge { linie: "l1".into(), wert: Wert::Zahl(10.0) }, Bedingung::Laenge { linie: "l1".into(), wert: Wert::Zahl(20.0) }];
        let s = loesen(&mut pk, &mut el, &bd, &Umgebung::new());
        assert_eq!(s.zustand, "widerspruechlich");
    }
}
