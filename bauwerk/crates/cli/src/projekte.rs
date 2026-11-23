//! Projektablage: <ordner>/projekte/<id>.json
use bauwerk_kern::modell::Dokument;
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone)]
pub struct Ablage { pub ordner: PathBuf }

#[derive(Serialize)]
pub struct Eintrag { pub id: String, pub name: String, pub zeit: u64, pub features: usize }

pub fn gueltig(id: &str) -> Result<&str, String> {
    if id.len() >= 3 && id.len() <= 40 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') { Ok(id) } else { Err("ungültige Projekt-ID".into()) }
}

pub fn neue_id() -> String {
    let t = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    format!("{:x}{:04x}", t.as_secs(), (t.subsec_nanos() >> 12) & 0xffff)
}

impl Ablage {
    pub fn neu(ordner: &Path) -> Self {
        let _ = std::fs::create_dir_all(ordner.join("projekte"));
        Ablage { ordner: ordner.to_path_buf() }
    }
    fn pfad(&self, id: &str) -> PathBuf { self.ordner.join("projekte").join(format!("{}.json", id)) }
    pub fn liste(&self) -> Vec<Eintrag> {
        let mut v = vec![];
        if let Ok(rd) = std::fs::read_dir(self.ordner.join("projekte")) {
            for e in rd.flatten() {
                let p = e.path();
                if p.extension().and_then(|x| x.to_str()) != Some("json") { continue; }
                let id = p.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string();
                let Ok(txt) = std::fs::read_to_string(&p) else { continue };
                let Ok(d) = bauwerk_kern::dokument_lesen(&txt) else { continue };
                let zeit = e.metadata().and_then(|m| m.modified()).ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs()).unwrap_or(0);
                v.push(Eintrag { id, name: d.name, zeit, features: d.features.len() });
            }
        }
        v.sort_by(|a, b| b.zeit.cmp(&a.zeit));
        v
    }
    pub fn lesen(&self, id: &str) -> Result<Dokument, String> {
        let txt = std::fs::read_to_string(self.pfad(gueltig(id)?)).map_err(|_| format!("Projekt {} nicht gefunden", id))?;
        let mut d = bauwerk_kern::dokument_lesen(&txt)?;
        d.id = id.to_string();
        Ok(d)
    }
    pub fn roh(&self, id: &str) -> Result<String, String> {
        std::fs::read_to_string(self.pfad(gueltig(id)?)).map_err(|_| format!("Projekt {} nicht gefunden", id))
    }
    pub fn schreiben(&self, d: &Dokument) -> Result<(), String> {
        gueltig(&d.id)?;
        let p = self.pfad(&d.id);
        let tmp = p.with_extension("tmp");
        std::fs::write(&tmp, serde_json::to_vec_pretty(d).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, &p).map_err(|e| e.to_string())
    }
    pub fn loeschen(&self, id: &str) -> Result<(), String> {
        std::fs::remove_file(self.pfad(gueltig(id)?)).map_err(|e| e.to_string())
    }
}
