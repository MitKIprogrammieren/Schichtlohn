//! MCP-Schnittstelle (JSON-RPC) – gemeinsam für stdio (`bauwerk mcp`) und HTTP (`/mcp`).
use crate::projekte::{neue_id, Ablage};
use bauwerk_kern::{berechnen, dokument_lesen, exportieren, modell::Wert, Ergebnis};
use serde_json::{json, Value};

pub struct Kontext {
    pub ablage: Ablage,
    /// Basis-URL für Download-Links (Server) – sonst werden Dateien in <ordner>/exporte geschrieben.
    pub basis_url: Option<String>,
}

pub const FORMAT: &str = r#"Bauwerk-Dokument (JSON). Einheiten mm, Z ist oben. Die Zeitleiste wird der Reihe nach berechnet.
{"name":"Halter","parameter":[{"name":"breite","ausdruck":60},{"name":"wand","ausdruck":"breite/20"}],"features":[...]}
Werte (Längen, Maße, Winkel) dürfen Zahlen oder Ausdrücke mit Parametern sein: "breite/2+3", "sqrt(2)*wand".

SKIZZE {"typ":"skizze","id":"s1","name":"Skizze 1","ebene":{"basis":"XY"|"XZ"|"YZ","versatz":0,"umgedreht":false},
  "punkte":[{"id":"a","x":0,"y":0}, ...],            Punkt "0" ist der feste Ursprung (wird automatisch angelegt)
  "elemente":[{"art":"linie","id":"l1","a":"a","b":"b"}, {"art":"kreis","id":"k1","m":"m","r":4},
              {"art":"bogen","id":"g1","m":"m","a":"p","b":"q"}  (gegen den Uhrzeigersinn von a nach b),
              "hilfs":true macht ein Element zur Hilfslinie (zählt nicht zum Profil)],
  "bedingungen":[ koinzident{a,b} horizontal{linie} vertikal{linie} parallel{a,b} senkrecht{a,b} gleich{a,b}
     fix{punkt} punkt_auf_linie{punkt,linie} punkt_auf_kreis{punkt,kreis} mittelpunkt{punkt,linie}
     tangential{linie,kreis} symmetrisch{a,b,linie}
     Bemaßungen mit "wert": abstand{a,b} (Punkt–Punkt oder Punkt–Linie) abstand_x{a,b} abstand_y{a,b}
     laenge{linie} radius{kreis} durchmesser{kreis} winkel{a,b} ]}
  Beispiel: {"art":"laenge","linie":"l1","wert":"breite"}
  Ebenen: XY = Oben (u=X, v=Y, Normale +Z), XZ = Vorne (u=X, v=Z, Normale −Y), YZ = Rechts (u=Y, v=Z, Normale +X).
  versatz verschiebt entlang der Grund-Normale (XY: z=versatz). umgedreht kehrt Normale und u-Achse um.
  Geschlossene Linienzüge, Kreise und Bögen bilden Profile; Formen in Formen werden zu Löchern.
EXTRUSION {"typ":"extrusion","id":"e1","skizze":"s1","laenge":10,"richtung":"normal"|"umgekehrt"|"symmetrisch",
  "modus":"hinzu"|"abziehen"|"schnitt","ecken":{"art":"keine"|"rund"|"fase","r":2}}  (ecken = Außenecken des Profils)
DREHUNG {"typ":"drehung","id":"d1","skizze":"s1","achse":"<Linien-ID>","winkel":360,"modus":"hinzu"}
BOHRUNG {"typ":"bohrung","id":"b1","skizze":"s2","d":3.4,"tiefe":0 (0 = durch),"senkung":"keine"|"kegel"|"zylinder","sd":6.5,"st":3.3}
  Jeder Kreismittelpunkt und jeder freie Punkt der Skizze wird gebohrt, gegen die Skizzen-Normale.
  Für Bohrungen von oben in ein 10 mm hohes Teil: Skizze auf XY mit versatz 10.
Jedes Feature kann "aus":true haben. Der Server rechnet alles selbst; Export als STL, 3MF oder STEP."#;

fn werkzeuge() -> Value {
    let id = json!({"type":"object","properties":{"id":{"type":"string"}},"required":["id"]});
    json!([
        {"name":"format_hilfe","description":"Beschreibt das Bauwerk-Format: Parameter, Skizzen mit Bedingungen und Bemaßungen, Extrusion, Drehung, Bohrung. Vor dem ersten Modell lesen.","inputSchema":{"type":"object","properties":{}}},
        {"name":"projekte_liste","description":"Alle Bauwerk-Projekte mit ID, Name und Änderungszeit.","inputSchema":{"type":"object","properties":{}}},
        {"name":"projekt_lesen","description":"Ein Projekt als JSON lesen (mit gelösten Skizzen).","inputSchema":id},
        {"name":"projekt_pruefen","description":"Ein Dokument berechnen, ohne es zu speichern: Größe, Volumen, Zustand der Skizzen (voll bestimmt?), Fehler.","inputSchema":{"type":"object","properties":{"dokument":{"type":"object"}},"required":["dokument"]}},
        {"name":"projekt_schreiben","description":"Projekt anlegen oder ersetzen. Wird sofort berechnet; Antwort enthält Größe, Fehler und Links.","inputSchema":{"type":"object","properties":{"id":{"type":"string","description":"weglassen für ein neues Projekt"},"name":{"type":"string"},"parameter":{"type":"array","items":{"type":"object"}},"features":{"type":"array","items":{"type":"object"}}},"required":["name","features"]}},
        {"name":"parameter_setzen","description":"Einen Parameter eines Projekts ändern (oder anlegen) und neu berechnen.","inputSchema":{"type":"object","properties":{"id":{"type":"string"},"name":{"type":"string"},"wert":{"description":"Zahl oder Ausdruck"}},"required":["id","name","wert"]}},
        {"name":"exportieren","description":"Projekt als STL, 3MF oder STEP ausgeben (z. B. als Eingabe für Mesh2STEP oder den Slicer). Gibt einen Download-Link oder Dateipfad zurück.","inputSchema":{"type":"object","properties":{"id":{"type":"string"},"format":{"type":"string","enum":["stl","3mf","step"]}},"required":["id","format"]}}
    ])
}

pub fn zusammenfassung(e: &Ergebnis) -> String {
    let mut s = String::new();
    if e.dreiecke > 0 {
        s.push_str(&format!("Körper: {:.2} × {:.2} × {:.2} mm, Volumen {:.2} cm³, {} Dreiecke\n", e.groesse[0], e.groesse[1], e.groesse[2], e.volumen / 1000.0, e.dreiecke));
    } else { s.push_str("Noch kein Körper.\n"); }
    for (id, st) in &e.skizzen {
        let name = e.dok.features.iter().find(|f| f.id() == id).map(|f| f.name().to_string()).unwrap_or_default();
        let z = match st.zustand.as_str() { "voll_bestimmt" => "voll bestimmt".to_string(), "unterbestimmt" => format!("unterbestimmt ({} Freiheitsgrade)", st.freiheitsgrade), _ => "WIDERSPRÜCHLICH".into() };
        s.push_str(&format!("Skizze {} {}: {}\n", id, name, z));
    }
    for f in &e.features { if let Some(m) = &f.fehler { s.push_str(&format!("FEHLER {}: {}\n", f.id, m)); } }
    for m in &e.meldungen { s.push_str(&format!("Hinweis: {}\n", m)); }
    s
}

impl Kontext {
    fn links(&self, id: &str) -> String {
        match &self.basis_url {
            Some(b) => format!("Öffnen: {b}/?projekt={id}\nSTL: {b}/api/projekte/{id}/export.stl  3MF: {b}/api/projekte/{id}/export.3mf  STEP: {b}/api/projekte/{id}/export.step"),
            None => format!("Projektdatei: {}", self.ablage.ordner.join("projekte").join(format!("{}.json", id)).display()),
        }
    }

    pub fn werkzeug(&self, name: &str, a: &Value) -> Result<String, String> {
        let s = |k: &str| a.get(k).and_then(|v| v.as_str()).map(|v| v.to_string()).ok_or(format!("'{}' fehlt", k));
        match name {
            "format_hilfe" => Ok(FORMAT.into()),
            "projekte_liste" => Ok(serde_json::to_string_pretty(&self.ablage.liste()).unwrap()),
            "projekt_lesen" => {
                let d = self.ablage.lesen(&s("id")?)?;
                Ok(serde_json::to_string_pretty(&berechnen(&d).dok).unwrap())
            }
            "projekt_pruefen" => {
                let d = dokument_lesen(&a.get("dokument").ok_or("'dokument' fehlt")?.to_string())?;
                Ok(zusammenfassung(&berechnen(&d)))
            }
            "projekt_schreiben" => {
                let id = a.get("id").and_then(|v| v.as_str()).map(|v| v.to_string()).unwrap_or_else(neue_id);
                let mut roh = a.clone();
                roh["id"] = json!(id);
                let d = dokument_lesen(&roh.to_string())?;
                let e = berechnen(&d);
                self.ablage.schreiben(&e.dok)?;
                Ok(format!("Gespeichert als {}.\n{}{}", id, zusammenfassung(&e), self.links(&id)))
            }
            "parameter_setzen" => {
                let id = s("id")?;
                let mut d = self.ablage.lesen(&id)?;
                let name = s("name")?;
                let w = match a.get("wert") { Some(Value::Number(n)) => Wert::Zahl(n.as_f64().unwrap_or(0.0)), Some(Value::String(t)) => Wert::Text(t.clone()), _ => return Err("'wert' fehlt".into()) };
                match d.parameter.iter_mut().find(|p| p.name == name) {
                    Some(p) => p.ausdruck = w,
                    None => d.parameter.push(bauwerk_kern::modell::Parameter { name: name.clone(), ausdruck: w, kommentar: String::new() }),
                }
                let e = berechnen(&d);
                self.ablage.schreiben(&e.dok)?;
                Ok(format!("{} gesetzt.\n{}", name, zusammenfassung(&e)))
            }
            "exportieren" => {
                let id = s("id")?;
                let f = s("format")?.to_lowercase();
                let e = berechnen(&self.ablage.lesen(&id)?);
                let daten = exportieren(&e, &f)?;
                match &self.basis_url {
                    Some(b) => Ok(format!("{}/api/projekte/{}/export.{}", b, id, f)),
                    None => {
                        let ordner = self.ablage.ordner.join("exporte");
                        std::fs::create_dir_all(&ordner).map_err(|e| e.to_string())?;
                        let name = e.dok.name.chars().map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect::<String>();
                        let p = ordner.join(format!("{}.{}", name, f));
                        std::fs::write(&p, daten).map_err(|e| e.to_string())?;
                        Ok(format!("Geschrieben: {}", p.display()))
                    }
                }
            }
            _ => Err(format!("unbekanntes Werkzeug {}", name)),
        }
    }

    /// Eine JSON-RPC-Nachricht beantworten (None bei Benachrichtigungen).
    pub fn anfrage(&self, a: &Value) -> Option<Value> {
        let id = a.get("id")?.clone();
        let m = a.get("method").and_then(|m| m.as_str()).unwrap_or("");
        let p = a.get("params").cloned().unwrap_or(json!({}));
        let res = match m {
            "initialize" => json!({
                "protocolVersion": p.get("protocolVersion").cloned().unwrap_or(json!("2025-06-18")),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bauwerk", "version": bauwerk_kern::VERSION},
                "instructions": "Bauwerk ist ein schlankes parametrisches CAD. Erst format_hilfe lesen, dann mit projekt_schreiben modellieren. Skizzen möglichst voll bestimmen (Bedingungen + Bemaßungen)."
            }),
            "ping" => json!({}),
            "tools/list" => json!({"tools": werkzeuge()}),
            "tools/call" => {
                let name = p.get("name").and_then(|n| n.as_str()).unwrap_or("");
                let args = p.get("arguments").cloned().unwrap_or(json!({}));
                match self.werkzeug(name, &args) {
                    Ok(t) => json!({"content":[{"type":"text","text":t}]}),
                    Err(e) => json!({"content":[{"type":"text","text":format!("Fehler: {}", e)}],"isError":true}),
                }
            }
            _ => return Some(json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":"unbekannte Methode"}})),
        };
        Some(json!({"jsonrpc":"2.0","id":id,"result":res}))
    }

    pub fn nachricht(&self, text: &str) -> Option<String> {
        let v: Value = match serde_json::from_str(text) {
            Ok(v) => v,
            Err(_) => return Some(json!({"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}).to_string()),
        };
        if let Some(arr) = v.as_array() {
            let r: Vec<Value> = arr.iter().filter_map(|x| self.anfrage(x)).collect();
            if r.is_empty() { None } else { Some(Value::Array(r).to_string()) }
        } else {
            self.anfrage(&v).map(|r| r.to_string())
        }
    }
}
