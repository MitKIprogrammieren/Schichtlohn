//! Das Bauwerk-Dokument: Parameter, Skizzen und Features auf einer Zeitleiste.
use serde::{Deserialize, Serialize};

/// Zahl oder Ausdruck („breite/2 + 3“).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
pub enum Wert {
    Zahl(f64),
    Text(String),
}
impl Default for Wert {
    fn default() -> Self { Wert::Zahl(0.0) }
}
impl From<f64> for Wert {
    fn from(v: f64) -> Self { Wert::Zahl(v) }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Dokument {
    #[serde(default)]
    pub id: String,
    #[serde(default = "standard_name")]
    pub name: String,
    #[serde(default)]
    pub parameter: Vec<Parameter>,
    #[serde(default)]
    pub features: Vec<Feature>,
    /// Zeitleisten-Marke: nur Features davor werden berechnet (None = alle).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bis: Option<usize>,
}
fn standard_name() -> String { "Neues Teil".into() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Parameter {
    pub name: String,
    pub ausdruck: Wert,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub kommentar: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ebene {
    #[serde(default = "basis_xy")]
    pub basis: String,
    #[serde(default)]
    pub versatz: Wert,
    #[serde(default)]
    pub umgedreht: bool,
}
fn basis_xy() -> String { "XY".into() }
impl Default for Ebene {
    fn default() -> Self { Ebene { basis: "XY".into(), versatz: Wert::Zahl(0.0), umgedreht: false } }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Punkt {
    pub id: String,
    pub x: f64,
    pub y: f64,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub fest: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "art", rename_all = "snake_case")]
pub enum Element {
    Linie { id: String, a: String, b: String, #[serde(default, skip_serializing_if = "std::ops::Not::not")] hilfs: bool },
    Kreis { id: String, m: String, r: f64, #[serde(default, skip_serializing_if = "std::ops::Not::not")] hilfs: bool },
    /// Bogen gegen den Uhrzeigersinn von a nach b um den Mittelpunkt m.
    Bogen { id: String, m: String, a: String, b: String, #[serde(default, skip_serializing_if = "std::ops::Not::not")] hilfs: bool },
}
impl Element {
    pub fn id(&self) -> &str {
        match self { Element::Linie { id, .. } | Element::Kreis { id, .. } | Element::Bogen { id, .. } => id }
    }
    pub fn hilfs(&self) -> bool {
        match self { Element::Linie { hilfs, .. } | Element::Kreis { hilfs, .. } | Element::Bogen { hilfs, .. } => *hilfs }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "art", rename_all = "snake_case")]
pub enum Bedingung {
    Koinzident { a: String, b: String },
    Horizontal { linie: String },
    Vertikal { linie: String },
    Parallel { a: String, b: String },
    Senkrecht { a: String, b: String },
    /// Gleiche Länge (Linien) oder gleicher Radius (Kreise/Bögen).
    Gleich { a: String, b: String },
    Fix { punkt: String },
    PunktAufLinie { punkt: String, linie: String },
    PunktAufKreis { punkt: String, kreis: String },
    Mittelpunkt { punkt: String, linie: String },
    Tangential { linie: String, kreis: String },
    Symmetrisch { a: String, b: String, linie: String },
    // Bemaßungen
    Abstand { a: String, b: String, wert: Wert },
    AbstandX { a: String, b: String, wert: Wert },
    AbstandY { a: String, b: String, wert: Wert },
    Laenge { linie: String, wert: Wert },
    Radius { kreis: String, wert: Wert },
    Durchmesser { kreis: String, wert: Wert },
    Winkel { a: String, b: String, wert: Wert },
}
impl Bedingung {
    pub fn ist_bemassung(&self) -> bool {
        matches!(self, Bedingung::Abstand { .. } | Bedingung::AbstandX { .. } | Bedingung::AbstandY { .. } | Bedingung::Laenge { .. }
            | Bedingung::Radius { .. } | Bedingung::Durchmesser { .. } | Bedingung::Winkel { .. })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Ecken {
    #[serde(default = "keine")]
    pub art: String,
    #[serde(default)]
    pub r: Wert,
}
fn keine() -> String { "keine".into() }

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "typ", rename_all = "snake_case")]
pub enum Feature {
    Skizze {
        id: String,
        #[serde(default)]
        name: String,
        #[serde(default)]
        ebene: Ebene,
        #[serde(default)]
        punkte: Vec<Punkt>,
        #[serde(default)]
        elemente: Vec<Element>,
        #[serde(default)]
        bedingungen: Vec<Bedingung>,
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        aus: bool,
    },
    Extrusion {
        id: String,
        #[serde(default)]
        name: String,
        skizze: String,
        #[serde(default = "zehn")]
        laenge: Wert,
        /// normal | umgekehrt | symmetrisch
        #[serde(default = "normal")]
        richtung: String,
        /// hinzu | abziehen | schnitt
        #[serde(default = "hinzu")]
        modus: String,
        #[serde(default)]
        ecken: Ecken,
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        aus: bool,
    },
    Drehung {
        id: String,
        #[serde(default)]
        name: String,
        skizze: String,
        /// Linie der Skizze, um die gedreht wird.
        achse: String,
        #[serde(default = "voll")]
        winkel: Wert,
        #[serde(default = "hinzu")]
        modus: String,
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        aus: bool,
    },
    Bohrung {
        id: String,
        #[serde(default)]
        name: String,
        skizze: String,
        #[serde(default = "m3")]
        d: Wert,
        /// 0 = durch alles
        #[serde(default)]
        tiefe: Wert,
        /// keine | kegel | zylinder
        #[serde(default = "keine")]
        senkung: String,
        #[serde(default = "sd")]
        sd: Wert,
        #[serde(default = "st")]
        st: Wert,
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        aus: bool,
    },
}
fn zehn() -> Wert { Wert::Zahl(10.0) }
fn voll() -> Wert { Wert::Zahl(360.0) }
fn m3() -> Wert { Wert::Zahl(3.4) }
fn sd() -> Wert { Wert::Zahl(6.5) }
fn st() -> Wert { Wert::Zahl(3.3) }
fn normal() -> String { "normal".into() }
fn hinzu() -> String { "hinzu".into() }

impl Feature {
    pub fn id(&self) -> &str {
        match self {
            Feature::Skizze { id, .. } | Feature::Extrusion { id, .. } | Feature::Drehung { id, .. } | Feature::Bohrung { id, .. } => id,
        }
    }
    pub fn name(&self) -> &str {
        match self {
            Feature::Skizze { name, .. } | Feature::Extrusion { name, .. } | Feature::Drehung { name, .. } | Feature::Bohrung { name, .. } => name,
        }
    }
    pub fn aus(&self) -> bool {
        match self {
            Feature::Skizze { aus, .. } | Feature::Extrusion { aus, .. } | Feature::Drehung { aus, .. } | Feature::Bohrung { aus, .. } => *aus,
        }
    }
    pub fn skizze_id(&self) -> Option<&str> {
        match self {
            Feature::Skizze { .. } => None,
            Feature::Extrusion { skizze, .. } | Feature::Drehung { skizze, .. } | Feature::Bohrung { skizze, .. } => Some(skizze),
        }
    }
}
