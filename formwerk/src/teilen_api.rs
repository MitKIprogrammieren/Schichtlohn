//! Web-Schnittstelle der neuen Teilen-Seite (/teilen)
use crate::mesh::{self, V3};
use crate::schnitt::{self, Drucker, Stand, Verbindung};
use axum::{
    Json,
    extract::{Multipart, Path},
    http::{StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{Value, json};

use super::err;

fn stand_json(sid: &str, name: &str, st: &Stand, zurueck: bool, hinweise: &[String]) -> Value {
    let teile: Vec<Value> = st
        .teile
        .iter()
        .map(|t| {
            let b = t.mesh.bbox();
            json!({
                "nr": t.nr, "name": t.name, "min": b.min, "max": b.max, "groesse": b.size(),
                "dreiecke": t.mesh.tris.len(), "volumen": t.mesh.volume().abs() / 1000.0
            })
        })
        .collect();
    json!({ "sid": sid, "name": name, "teile": teile, "fugen": st.fugen, "lose": st.lose.len(), "zurueck": zurueck, "hinweise": hinweise })
}

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> anyhow::Result<T> + Send + 'static) -> Result<T, Response> {
    match tokio::task::spawn_blocking(f).await {
        Ok(Ok(x)) => Ok(x),
        Ok(Err(e)) => Err(err(e)),
        Err(_) => Err(err("Die Berechnung ist abgestürzt.")),
    }
}

pub async fn laden(mut mp: Multipart) -> Response {
    let mut file: Option<(String, Vec<u8>)> = None;
    while let Ok(Some(field)) = mp.next_field().await {
        if field.name() == Some("file") {
            let fname = field.file_name().unwrap_or("upload.stl").to_string();
            match field.bytes().await {
                Ok(b) => file = Some((fname, b.to_vec())),
                Err(e) => return err(format!("Upload fehlgeschlagen: {e}")),
            }
        }
    }
    let Some((fname, bytes)) = file else { return err("Keine Datei") };
    let name = fname.rsplit(['/', '\\']).next().unwrap_or(&fname).rsplit_once('.').map(|x| x.0.to_string()).unwrap_or(fname.clone());
    let lower = fname.to_lowercase();
    if ![".stl", ".obj", ".3mf"].iter().any(|e| lower.ends_with(e)) {
        return err(if lower.ends_with(".step") || lower.ends_with(".stp") {
            "STEP kann Formwerk noch nicht lesen – bitte als STL oder 3MF speichern (z. B. mit Mesh2STEP oder Fusion)."
        } else {
            "Bitte ein 3D-Modell laden (STL, 3MF oder OBJ)."
        });
    }
    let st = match blocking(move || {
        let objs = mesh::load(&bytes, &fname)?;
        Ok(if lower.ends_with(".3mf") { schnitt::projekt_laden(&bytes, objs) } else { schnitt::stand_aus_objekten(objs) })
    })
    .await
    {
        Ok(s) => s,
        Err(e) => return e,
    };
    let sid = schnitt::neu(name.clone(), st.clone());
    Json(stand_json(&sid, &name, &st, false, &[])).into_response()
}

fn abgelaufen() -> Response {
    err("Die Sitzung ist abgelaufen – bitte das Modell neu laden.")
}

pub async fn stand(Path(sid): Path<String>) -> Response {
    let Some((name, st, z)) = schnitt::aktuell(&sid) else { return abgelaufen() };
    Json(stand_json(&sid, &name, &st, z, &[])).into_response()
}

/// Dreiecke eines Teils als Float32 (9 Werte je Dreieck)
pub async fn teil_bin(Path((sid, nr)): Path<(String, u32)>) -> Response {
    let Some((_, st, _)) = schnitt::aktuell(&sid) else { return (StatusCode::NOT_FOUND, "abgelaufen").into_response() };
    let Some(t) = st.teile.iter().find(|t| t.nr == nr).cloned() else { return (StatusCode::NOT_FOUND, "unbekannt").into_response() };
    let b = tokio::task::spawn_blocking(move || {
        let mut v = Vec::with_capacity(t.mesh.tris.len() * 36);
        for tri in &t.mesh.tris {
            for p in tri {
                for c in p {
                    v.extend_from_slice(&(*c as f32).to_le_bytes());
                }
            }
        }
        v
    })
    .await
    .unwrap_or_default();
    ([(header::CONTENT_TYPE, "application/octet-stream"), (header::CACHE_CONTROL, "private, max-age=3600")], b).into_response()
}

#[derive(Deserialize)]
pub struct RingAnfrage {
    teil: u32,
    #[serde(default)]
    punkt: Option<V3>,
    #[serde(default)]
    normale: Option<V3>,
    /// alle | rand | innen
    ort: String,
    /// Band: Flächennormale am Klickpunkt → Richtung automatisch
    #[serde(default)]
    flaeche_n: Option<V3>,
    #[serde(default)]
    kipp: f64,
    /// Bemalen: Randpunkte der bemalten Fläche
    #[serde(default)]
    rand_punkte: Option<Vec<V3>>,
    /// Linie: Anfang, Ende, Blickrichtung
    #[serde(default)]
    linie: Option<[V3; 3]>,
}

pub async fn ring(Path(sid): Path<String>, Json(a): Json<RingAnfrage>) -> Response {
    let Some((_, st, _)) = schnitt::aktuell(&sid) else { return abgelaufen() };
    let Some(t) = st.teile.iter().find(|t| t.nr == a.teil).cloned() else { return err("Teil nicht gefunden") };
    match blocking(move || {
        let (mut p, mut n) = (a.punkt.unwrap_or([0.0; 3]), a.normale.unwrap_or([0.0, 0.0, 1.0]));
        if let Some(rp) = &a.rand_punkte {
            let Some((c, nn)) = schnitt::ebene_aus_punkten(rp) else { anyhow::bail!("Bitte eine größere Fläche bemalen.") };
            p = c;
            n = nn;
        } else if let Some(sn) = a.flaeche_n {
            let Some(nn) = schnitt::band_richtung(&t.mesh, p, sn, a.kipp) else { anyhow::bail!("Hier lässt sich kein Band legen.") };
            n = nn;
        }
        let r = schnitt::ringe(&t.mesh, p, n, &a.ort, a.linie);
        Ok(json!({ "punkt": p, "normale": n, "ringe": r }))
    })
    .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => e,
    }
}

#[derive(Deserialize)]
pub struct SchnittAnfrage {
    teil: u32,
    punkt: V3,
    normale: V3,
    ort: String,
    #[serde(default)]
    linie: Option<[V3; 3]>,
    #[serde(default)]
    verbindung: Verbindung,
}

async fn aendern(sid: String, f: impl FnOnce(&mut Stand, &mut Vec<String>) -> anyhow::Result<()> + Send + 'static) -> Response {
    let Some((name, mut st, _)) = schnitt::aktuell(&sid) else { return abgelaufen() };
    let r = blocking(move || {
        let mut h = Vec::new();
        f(&mut st, &mut h)?;
        Ok((st, h))
    })
    .await;
    match r {
        Ok((st, h)) => {
            schnitt::setzen(&sid, st.clone());
            Json(stand_json(&sid, &name, &st, true, &h)).into_response()
        }
        Err(e) => e,
    }
}

pub async fn schneiden(Path(sid): Path<String>, Json(a): Json<SchnittAnfrage>) -> Response {
    aendern(sid, move |st, h| {
        schnitt::teil_schneiden(st, a.teil, a.punkt, a.normale, &a.ort, a.linie, &a.verbindung, h)?;
        Ok(())
    })
    .await
}

#[derive(Deserialize)]
pub struct MehrfachAnfrage {
    teil: u32,
    anzahl: [usize; 3],
    #[serde(default)]
    verbindung: Verbindung,
}

pub async fn mehrfach(Path(sid): Path<String>, Json(a): Json<MehrfachAnfrage>) -> Response {
    aendern(sid, move |st, h| schnitt::mehrfach(st, a.teil, a.anzahl, &a.verbindung, h)).await
}

#[derive(Deserialize)]
pub struct AutoAnfrage {
    teil: u32,
    drucker: Drucker,
    #[serde(default)]
    rand: f64,
    #[serde(default)]
    verbindung: Verbindung,
}

pub async fn auto(Path(sid): Path<String>, Json(a): Json<AutoAnfrage>) -> Response {
    aendern(sid, move |st, h| {
        let n = schnitt::auto(st, a.teil, [a.drucker.x, a.drucker.y, a.drucker.z], a.rand, &a.verbindung, h)?;
        if n == 0 {
            h.push("Das Teil passt schon aufs Druckbett – nichts zu schneiden.".into());
        }
        Ok(())
    })
    .await
}

#[derive(Deserialize)]
pub struct NameAnfrage {
    teil: u32,
    name: String,
}

pub async fn umbenennen(Path(sid): Path<String>, Json(a): Json<NameAnfrage>) -> Response {
    aendern(sid, move |st, _| {
        if let Some(t) = st.teile.iter_mut().find(|t| t.nr == a.teil) {
            t.name = a.name.trim().chars().take(60).collect();
        }
        Ok(())
    })
    .await
}

pub async fn zurueck(Path(sid): Path<String>) -> Response {
    schnitt::zurueck(&sid);
    stand(Path(sid)).await
}

#[derive(Deserialize)]
pub struct ExportAnfrage {
    /// 3mf | stl | projekt
    art: String,
    drucker: Drucker,
    #[serde(default)]
    rand: f64,
}

pub async fn export(Path(sid): Path<String>, Json(a): Json<ExportAnfrage>) -> Response {
    let Some((name, st, _)) = schnitt::aktuell(&sid) else { return abgelaufen() };
    let art = a.art.clone();
    let r = blocking(move || {
        Ok(match a.art.as_str() {
            "stl" => schnitt::stl_zip(&st, &a.drucker),
            "projekt" => schnitt::projekt(&st),
            _ => schnitt::bambu(&st, &a.drucker, a.rand),
        })
    })
    .await;
    let bytes = match r {
        Ok(b) => b,
        Err(e) => return e,
    };
    let safe: String = name.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
    let (fname, ct) = match art.as_str() {
        "stl" => (format!("{safe}_teile.zip"), "application/zip"),
        "projekt" => (format!("{safe}_projekt.3mf"), "model/3mf"),
        _ => (format!("{safe}_geteilt.3mf"), "model/3mf"),
    };
    ([(header::CONTENT_TYPE, ct.to_string()), (header::CONTENT_DISPOSITION, format!("attachment; filename=\"{fname}\""))], bytes).into_response()
}
