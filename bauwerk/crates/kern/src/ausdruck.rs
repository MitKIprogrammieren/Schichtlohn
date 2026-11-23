//! Kleine Ausdrucks-Auswertung für Parameter und Maße: + - * / ^ ( ), Zahlen mit Komma oder Punkt,
//! Parameternamen sowie sqrt, sin, cos, tan (Grad), min, max, abs, round, pi.
use crate::modell::{Parameter, Wert};
use std::collections::HashMap;

pub type Umgebung = HashMap<String, f64>;

/// Parameter der Reihe nach auswerten (ein Parameter darf frühere benutzen).
pub fn parameter_auswerten(ps: &[Parameter]) -> (Umgebung, Vec<String>) {
    let mut u = Umgebung::new();
    let mut fehler = vec![];
    for _ in 0..3 {
        for p in ps {
            match wert(&p.ausdruck, &u) {
                Ok(v) => { u.insert(p.name.clone(), v); }
                Err(_) => {}
            }
        }
    }
    for p in ps {
        if let Err(e) = wert(&p.ausdruck, &u) { fehler.push(format!("Parameter {}: {}", p.name, e)); }
    }
    (u, fehler)
}

pub fn wert(w: &Wert, u: &Umgebung) -> Result<f64, String> {
    match w {
        Wert::Zahl(z) => Ok(*z),
        Wert::Text(t) => auswerten(t, u),
    }
}

pub fn auswerten(s: &str, u: &Umgebung) -> Result<f64, String> {
    let t: Vec<char> = s.chars().collect();
    let mut p = Leser { t: &t, i: 0, u };
    let v = p.summe()?;
    p.leer();
    if p.i < t.len() { return Err(format!("unerwartetes Zeichen '{}'", t[p.i])); }
    if !v.is_finite() { return Err("Ergebnis ist keine Zahl".into()); }
    Ok(v)
}

struct Leser<'a> { t: &'a [char], i: usize, u: &'a Umgebung }
impl<'a> Leser<'a> {
    fn leer(&mut self) { while self.i < self.t.len() && self.t[self.i].is_whitespace() { self.i += 1; } }
    fn sieh(&mut self) -> Option<char> { self.leer(); self.t.get(self.i).copied() }
    fn summe(&mut self) -> Result<f64, String> {
        let mut v = self.produkt()?;
        loop {
            match self.sieh() {
                Some('+') => { self.i += 1; v += self.produkt()?; }
                Some('-') => { self.i += 1; v -= self.produkt()?; }
                _ => return Ok(v),
            }
        }
    }
    fn produkt(&mut self) -> Result<f64, String> {
        let mut v = self.potenz()?;
        loop {
            match self.sieh() {
                Some('*') => { self.i += 1; v *= self.potenz()?; }
                Some('/') => { self.i += 1; let d = self.potenz()?; if d == 0.0 { return Err("Division durch 0".into()); } v /= d; }
                _ => return Ok(v),
            }
        }
    }
    fn potenz(&mut self) -> Result<f64, String> {
        let b = self.einheit()?;
        if self.sieh() == Some('^') { self.i += 1; let e = self.potenz()?; return Ok(b.powf(e)); }
        Ok(b)
    }
    fn einheit(&mut self) -> Result<f64, String> {
        match self.sieh() {
            Some('-') => { self.i += 1; Ok(-self.potenz()?) }
            Some('+') => { self.i += 1; self.einheit() }
            Some('(') => {
                self.i += 1;
                let v = self.summe()?;
                if self.sieh() != Some(')') { return Err("')' fehlt".into()); }
                self.i += 1;
                Ok(v)
            }
            Some(c) if c.is_ascii_digit() || c == '.' || c == ',' => {
                let st = self.i;
                while self.i < self.t.len() && (self.t[self.i].is_ascii_digit() || self.t[self.i] == '.' || self.t[self.i] == ',') { self.i += 1; }
                let z: String = self.t[st..self.i].iter().map(|c| if *c == ',' { '.' } else { *c }).collect();
                let mut v: f64 = z.parse().map_err(|_| format!("ungültige Zahl {}", z))?;
                // Einheiten-Endungen
                let rest: String = self.t[self.i..].iter().take(2).collect();
                if rest.starts_with("mm") { self.i += 2; }
                else if rest.starts_with("cm") { self.i += 2; v *= 10.0; }
                else if rest.starts_with('°') { self.i += 1; }
                Ok(v)
            }
            Some(c) if c.is_alphabetic() || c == '_' => {
                let st = self.i;
                while self.i < self.t.len() && (self.t[self.i].is_alphanumeric() || self.t[self.i] == '_') { self.i += 1; }
                let name: String = self.t[st..self.i].iter().collect();
                if self.sieh() == Some('(') {
                    self.i += 1;
                    let mut args = vec![self.summe()?];
                    while self.sieh() == Some(';') || self.sieh() == Some(',') { self.i += 1; args.push(self.summe()?); }
                    if self.sieh() != Some(')') { return Err("')' fehlt".into()); }
                    self.i += 1;
                    let g = |x: f64| x.to_radians();
                    return match (name.as_str(), args.as_slice()) {
                        ("sqrt" | "wurzel", [a]) => Ok(a.sqrt()),
                        ("sin", [a]) => Ok(g(*a).sin()),
                        ("cos", [a]) => Ok(g(*a).cos()),
                        ("tan", [a]) => Ok(g(*a).tan()),
                        ("abs", [a]) => Ok(a.abs()),
                        ("round" | "runden", [a]) => Ok(a.round()),
                        ("floor", [a]) => Ok(a.floor()),
                        ("ceil", [a]) => Ok(a.ceil()),
                        ("min", a) if !a.is_empty() => Ok(a.iter().cloned().fold(f64::INFINITY, f64::min)),
                        ("max", a) if !a.is_empty() => Ok(a.iter().cloned().fold(f64::NEG_INFINITY, f64::max)),
                        _ => Err(format!("unbekannte Funktion {}", name)),
                    };
                }
                if name == "pi" { return Ok(std::f64::consts::PI); }
                self.u.get(&name).copied().ok_or_else(|| format!("unbekannter Parameter '{}'", name))
            }
            Some(c) => Err(format!("unerwartetes Zeichen '{}'", c)),
            None => Err("Ausdruck ist leer".into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rechnet() {
        let mut u = Umgebung::new();
        u.insert("breite".into(), 60.0);
        assert_eq!(auswerten("breite/2 + 3", &u).unwrap(), 33.0);
        assert_eq!(auswerten("2,5*2", &u).unwrap(), 5.0);
        assert_eq!(auswerten("-(1+2)^2", &u).unwrap(), -9.0);
        assert!((auswerten("sin(30)", &u).unwrap() - 0.5).abs() < 1e-12);
        assert_eq!(auswerten("max(1;breite)", &u).unwrap(), 60.0);
        assert!(auswerten("foo+1", &u).is_err());
    }
}
