//! Formwerk – große Modelle aufs Druckbett zerlegen, im Bambu-Studio-Look (nach LuBan „Mesh → Cut“)
mod export;
mod farben;
mod werk;
mod mesh;
mod prep;
mod schnitt;
mod section;
mod teilen_api;

use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, Multipart, Path},
    http::{StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use serde_json::json;
use std::path::PathBuf;

fn data_dir() -> PathBuf {
    PathBuf::from(std::env::var("FORMWERK_DATA").unwrap_or_else(|_| "./data".into()))
}

static INDEX: &str = include_str!("../static/index.html");
static TEILEN: &str = include_str!("../static/teilen.html");
static TEILEN_APP: &str = include_str!("../static/teilen_app.js");
static DRUCK: &str = include_str!("../static/druck.html");
static DRUCK_APP: &str = include_str!("../static/druck_app.js");
static DRUCK_GEST: &str = include_str!("../static/druck_gestalten.js");
static OPENTYPE: &[u8] = include_bytes!("../static/vendor/opentype.min.js");
static QRCODE: &[u8] = include_bytes!("../static/vendor/qrcode.js");
static FONT: &[u8] = include_bytes!("../static/vendor/schrift.woff");
static THREE: &[u8] = include_bytes!("../static/vendor/three.module.min.js");
static STL_LOADER: &[u8] = include_bytes!("../static/vendor/STLLoader.js");
static ORBIT: &[u8] = include_bytes!("../static/vendor/OrbitControls.js");

#[tokio::main]
async fn main() {
    let port: u16 = std::env::var("PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8097);
    let _ = std::fs::create_dir_all(data_dir().join("jobs"));
    let app = Router::new()
        .route("/", get(|| async { Html(DRUCK) }))
        .route("/teilen", get(|| async { Html(TEILEN) }))
        .route("/teilen/klassisch", get(|| async { Html(INDEX) }))
        .route("/api/teilen/laden", post(teilen_api::laden))
        .route("/api/teilen/{sid}/stand", get(teilen_api::stand))
        .route("/api/teilen/{sid}/teil/{nr}", get(teilen_api::teil_bin))
        .route("/api/teilen/{sid}/ring", post(teilen_api::ring))
        .route("/api/teilen/{sid}/schneiden", post(teilen_api::schneiden))
        .route("/api/teilen/{sid}/mehrfach", post(teilen_api::mehrfach))
        .route("/api/teilen/{sid}/auto", post(teilen_api::auto))
        .route("/api/teilen/{sid}/umbenennen", post(teilen_api::umbenennen))
        .route("/api/teilen/{sid}/farben", post(teilen_api::farben))
        .route("/api/teilen/{sid}/bemalung/{nr}", get(teilen_api::bemalung_bin))
        .route("/api/teilen/{sid}/zurueck", post(teilen_api::zurueck))
        .route("/api/teilen/{sid}/export", post(teilen_api::export))
        .route("/api/prep/load", post(prep_load))
        .route("/api/prep/{sid}/{id}/bin", get(prep_bin))
        .route("/api/prep/{sid}/export", post(prep_export))
        .route("/api/prep/{sid}/zerlegen", post(prep_zerlegen))
        .route("/vendor/{name}", get(vendor))
        .route("/js/{name}", get(js))
        .route("/api/run", post(run))
        .route("/api/load", post(load_model))
        .route("/api/job/{id}/zip", get(job_zip))
        .route("/api/job/{id}/file/{*path}", get(job_file))
        .route("/health", get(|| async { "ok" }))
        .route("/favicon.svg", get(|| async {
            ([(header::CONTENT_TYPE, "image/svg+xml")], r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="5" fill="#00AE42"/><g fill="none" stroke="#fff" stroke-width="2"><path d="M12 4 5 8v8l7 4 7-4V8z"/><path d="M5 8l7 4 7-4M12 12v8"/></g></svg>"##)
        }))
        .layer(DefaultBodyLimit::max(600 * 1024 * 1024));
    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], port));
    println!("Formwerk läuft auf http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn vendor(Path(name): Path<String>) -> Response {
    let body: &[u8] = match name.as_str() {
        "three.module.min.js" => THREE,
        "STLLoader.js" => STL_LOADER,
        "OrbitControls.js" => ORBIT,
        "opentype.min.js" => OPENTYPE,
        "qrcode.js" => QRCODE,
        "schrift.woff" => return ([(header::CONTENT_TYPE, "font/woff"), (header::CACHE_CONTROL, "public, max-age=604800")], FONT).into_response(),
        _ => return StatusCode::NOT_FOUND.into_response(),
    };
    ([(header::CONTENT_TYPE, "text/javascript"), (header::CACHE_CONTROL, "public, max-age=86400")], body).into_response()
}

async fn js(Path(name): Path<String>) -> Response {
    let body = match name.as_str() {
        "druck_app.js" => DRUCK_APP,
        "druck_gestalten.js" => DRUCK_GEST,
        "teilen_app.js" => TEILEN_APP,
        _ => return StatusCode::NOT_FOUND.into_response(),
    };
    ([(header::CONTENT_TYPE, "text/javascript; charset=utf-8"), (header::CACHE_CONTROL, "no-cache")], body).into_response()
}

fn err(msg: impl ToString) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({ "error": msg.to_string() }))).into_response()
}

fn cleanup() {
    let dir = data_dir().join("jobs");
    if let Ok(rd) = std::fs::read_dir(&dir) {
        for e in rd.flatten() {
            let old = e.metadata().ok().and_then(|m| m.modified().ok()).and_then(|t| t.elapsed().ok()).is_some_and(|d| d.as_secs() > 24 * 3600);
            if old {
                let _ = std::fs::remove_dir_all(e.path());
            }
        }
    }
}

/// Modell in echter Größe für die Ansicht auf dem Druckbett (vor dem Teilen)
async fn load_model(mut mp: Multipart) -> Response {
    let mut file: Option<(String, Vec<u8>)> = None;
    let mut params = String::from("{}");
    while let Ok(Some(field)) = mp.next_field().await {
        match field.name().unwrap_or("") {
            "file" => {
                let fname = field.file_name().unwrap_or("upload").to_string();
                if let Ok(b) = field.bytes().await {
                    file = Some((fname, b.to_vec()));
                }
            }
            "params" => params = field.text().await.unwrap_or_default(),
            _ => {}
        }
    }
    let Some((fname, bytes)) = file else { return err("Keine Datei") };
    let p: werk::Params = serde_json::from_str(&params).unwrap_or_default();
    let res = tokio::task::spawn_blocking(move || -> anyhow::Result<(Vec<u8>, Vec<serde_json::Value>, [f64; 3])> {
        let lower = fname.to_lowercase();
        if ![".stl", ".obj", ".3mf"].iter().any(|e| lower.ends_with(e)) {
            anyhow::bail!("Bitte ein 3D-Modell laden (STL, 3MF oder OBJ).");
        }
        let objects = mesh::load(&bytes, &fname)?;
        let mut all = mesh::Mesh::new();
        for (_, m) in &objects {
            all.extend(m);
        }
        let k = werk::scale_factor(all.bbox().size(), &p);
        all.scale(k);
        let infos = objects
            .iter()
            .map(|(n, m)| {
                let s = m.bbox().size();
                json!({ "name": n, "size": [s[0] * k, s[1] * k, s[2] * k] })
            })
            .collect();
        let s = all.bbox().size();
        Ok((all.to_stl("Modell"), infos, s))
    })
    .await;
    match res {
        Ok(Ok((stl, infos, size))) => {
            let id = uuid::Uuid::new_v4().simple().to_string()[..12].to_string();
            let dir = data_dir().join("jobs").join(&id).join("_vorschau");
            let _ = std::fs::create_dir_all(&dir);
            let _ = std::fs::write(dir.join("modell.stl"), stl);
            Json(json!({ "url": format!("/api/job/{id}/file/_vorschau/modell.stl"), "objects": infos, "size": size })).into_response()
        }
        Ok(Err(e)) => err(e),
        Err(_) => err("Laden abgestürzt"),
    }
}

async fn run(mut mp: Multipart) -> Response {
    let mut file: Option<(String, Vec<u8>)> = None;
    let mut params = String::from("{}");
    while let Ok(Some(field)) = mp.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        if name == "file" {
            let fname = field.file_name().unwrap_or("upload").to_string();
            match field.bytes().await {
                Ok(b) => file = Some((fname, b.to_vec())),
                Err(e) => return err(format!("Upload fehlgeschlagen: {e}")),
            }
        } else if name == "params" {
            params = field.text().await.unwrap_or_default();
        }
    }
    let p: werk::Params = match serde_json::from_str(&params) {
        Ok(p) => p,
        Err(e) => return err(format!("Einstellungen fehlerhaft: {e}")),
    };
    let Some((fname, bytes)) = file else { return err("Bitte zuerst ein Foto oder 3D-Modell laden.") };
    let started = std::time::Instant::now();
    let result = tokio::task::spawn_blocking(move || compute(&p, &fname, &bytes)).await;
    let out = match result {
        Ok(Ok(o)) => o,
        Ok(Err(e)) => return err(e),
        Err(_) => return err("Die Berechnung ist abgestürzt."),
    };
    cleanup();
    let id = uuid::Uuid::new_v4().simple().to_string()[..12].to_string();
    let dir = data_dir().join("jobs").join(&id);
    let mut files = Vec::new();
    for (name, data) in &out.files {
        let path = dir.join(name);
        let _ = std::fs::create_dir_all(path.parent().unwrap());
        if std::fs::write(&path, data).is_ok() {
            files.push(json!({ "name": name, "size": data.len() }));
        }
    }
    let mut preview = Vec::new();
    for (i, (name, m)) in out.preview.iter().enumerate() {
        let fname = format!("_vorschau/{i:03}.stl");
        let path = dir.join(&fname);
        let _ = std::fs::create_dir_all(path.parent().unwrap());
        if std::fs::write(&path, m.to_stl(name)).is_ok() {
            preview.push(json!({ "name": name, "url": format!("/api/job/{id}/file/{fname}") }));
        }
    }
    let mut plates = Vec::new();
    for (pi, (printer, bed, plate, parts)) in out.plate_view.iter().enumerate() {
        let mut list = Vec::new();
        for (k, (num, name, mesh)) in parts.iter().enumerate() {
            let fname = format!("_vorschau/platte_{pi:02}_{k:02}.stl");
            let path = dir.join(&fname);
            let _ = std::fs::create_dir_all(path.parent().unwrap());
            if std::fs::write(&path, mesh.to_stl(name)).is_ok() {
                list.push(json!({ "num": num, "name": name, "url": format!("/api/job/{id}/file/{fname}") }));
            }
        }
        plates.push(json!({ "printer": printer, "bed": bed, "plate": plate, "parts": list }));
    }
    Json(json!({
        "id": id,
        "plate_view": plates,
        "summary": out.summary,
        "warnings": out.warnings,
        "files": files,
        "preview": preview,
        "plates": out.plates,
        "seconds": started.elapsed().as_secs_f64(),
    }))
    .into_response()
}

fn compute(p: &werk::Params, fname: &str, bytes: &[u8]) -> anyhow::Result<werk::Output> {
    let lower = fname.to_lowercase();
    if ![".stl", ".obj", ".3mf"].iter().any(|e| lower.ends_with(e)) {
        anyhow::bail!("Bitte ein 3D-Modell laden (STL, 3MF oder OBJ).");
    }
    let objects = mesh::load(bytes, fname)?;
    werk::split(&objects, p)
}

fn safe_id(id: &str) -> bool {
    !id.is_empty() && id.chars().all(|c| c.is_ascii_alphanumeric())
}

async fn job_file(Path((id, path)): Path<(String, String)>) -> Response {
    if !safe_id(&id) || path.contains("..") {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let full = data_dir().join("jobs").join(&id).join(&path);
    match tokio::fs::read(&full).await {
        Ok(b) => {
            let ct = if path.ends_with(".svg") {
                "image/svg+xml"
            } else if path.ends_with(".txt") {
                "text/plain; charset=utf-8"
            } else {
                "application/octet-stream"
            };
            let fname = path.rsplit('/').next().unwrap_or("datei").to_string();
            let disp = if path.ends_with(".svg") || path.starts_with("_vorschau") { "inline".to_string() } else { format!("attachment; filename=\"{fname}\"") };
            ([(header::CONTENT_TYPE, ct.to_string()), (header::CONTENT_DISPOSITION, disp)], b).into_response()
        }
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

async fn job_zip(Path(id): Path<String>) -> Response {
    if !safe_id(&id) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let dir = data_dir().join("jobs").join(&id);
    let res = tokio::task::spawn_blocking(move || {
        let mut files = Vec::new();
        fn walk(base: &std::path::Path, d: &std::path::Path, out: &mut Vec<(String, Vec<u8>)>) {
            if let Ok(rd) = std::fs::read_dir(d) {
                for e in rd.flatten() {
                    let p = e.path();
                    let rel = p.strip_prefix(base).unwrap().to_string_lossy().to_string();
                    if rel.starts_with("_vorschau") {
                        continue;
                    }
                    if p.is_dir() {
                        walk(base, &p, out);
                    } else if let Ok(b) = std::fs::read(&p) {
                        out.push((rel, b));
                    }
                }
            }
        }
        walk(&dir, &dir, &mut files);
        files.sort_by(|a, b| a.0.cmp(&b.0));
        export::zip_files(&files)
    })
    .await
    .unwrap_or_default();
    (
        [(header::CONTENT_TYPE, "application/zip".to_string()), (header::CONTENT_DISPOSITION, format!("attachment; filename=\"formwerk_{id}.zip\""))],
        res,
    )
        .into_response()
}

// ───────────────────────── Druckvorbereitung ─────────────────────────

fn modell_json(id: u32, m: &prep::Modell) -> serde_json::Value {
    let mut k = prep::kennzahlen(m);
    k["id"] = json!(id);
    k
}

/// Dateien laden. Mehrere Dateien mit `zusammen=1` werden ein Modell aus Teilen (Filament je Datei in `ext`).
async fn prep_load(mut mp: Multipart) -> Response {
    let mut files: Vec<(String, Vec<u8>)> = Vec::new();
    let mut exts: Vec<u32> = Vec::new();
    let mut namen: Vec<String> = Vec::new();
    let (mut sid, mut zusammen, mut titel) = (String::new(), false, String::new());
    while let Ok(Some(field)) = mp.next_field().await {
        match field.name().unwrap_or("") {
            "file" => {
                let fname = field.file_name().unwrap_or("upload.stl").to_string();
                match field.bytes().await {
                    Ok(b) => files.push((fname, b.to_vec())),
                    Err(e) => return err(format!("Upload fehlgeschlagen: {e}")),
                }
            }
            "ext" => exts.push(field.text().await.unwrap_or_default().parse().unwrap_or(1)),
            "teilname" => namen.push(field.text().await.unwrap_or_default()),
            "sid" => sid = field.text().await.unwrap_or_default(),
            "zusammen" => zusammen = field.text().await.unwrap_or_default() == "1",
            "titel" => titel = field.text().await.unwrap_or_default(),
            _ => {}
        }
    }
    if files.is_empty() {
        return err("Keine Datei");
    }
    let res = tokio::task::spawn_blocking(move || -> anyhow::Result<Vec<prep::Modell>> {
        let mut alle = Vec::new();
        for (fname, b) in &files {
            alle.extend(prep::laden(b, fname)?);
        }
        if zusammen {
            let mut teile = Vec::new();
            for (i, m) in alle.into_iter().enumerate() {
                for mut t in m.teile {
                    t.extruder = exts.get(i).copied().unwrap_or(t.extruder).max(1);
                    if let Some(n) = namen.get(i).filter(|n| !n.is_empty()) {
                        t.name = n.clone();
                    }
                    teile.push(t);
                }
            }
            return Ok(vec![prep::Modell { name: if titel.is_empty() { "Eigenes Teil".into() } else { titel.clone() }, teile }]);
        }
        Ok(alle)
    })
    .await;
    let modelle = match res {
        Ok(Ok(m)) => m,
        Ok(Err(e)) => return err(e),
        Err(_) => return err("Laden abgestürzt"),
    };
    let (sid, neu) = prep::ablegen(&sid, modelle);
    let infos = tokio::task::spawn_blocking(move || neu.iter().map(|(id, m)| modell_json(*id, m)).collect::<Vec<_>>()).await.unwrap_or_default();
    Json(json!({ "sid": sid, "modelle": infos })).into_response()
}

async fn prep_bin(Path((sid, id)): Path<(String, u32)>) -> Response {
    let Some(m) = prep::holen(&sid, id) else { return (StatusCode::NOT_FOUND, "abgelaufen").into_response() };
    let b = tokio::task::spawn_blocking(move || prep::vorschau(&m)).await.unwrap_or_default();
    ([(header::CONTENT_TYPE, "application/octet-stream")], b).into_response()
}

async fn prep_export(Path(sid): Path<String>, Json(a): Json<prep::Auftrag>) -> Response {
    if !prep::bekannt(&sid) {
        return err("Die Sitzung ist abgelaufen – bitte das Modell neu laden.");
    }
    match tokio::task::spawn_blocking(move || prep::ausgeben(&sid, &a)).await {
        Ok(Ok((name, ct, data))) => (
            [(header::CONTENT_TYPE, ct.to_string()), (header::CONTENT_DISPOSITION, format!("attachment; filename=\"{name}\""))],
            data,
        )
            .into_response(),
        Ok(Err(e)) => err(e),
        Err(_) => err("Die Ausgabe ist abgestürzt."),
    }
}

#[derive(serde::Deserialize)]
struct ZerlegenAuftrag {
    m: u32,
    r: [f64; 9],
    s: f64,
    drucker: werk::Printer,
}

async fn prep_zerlegen(Path(sid): Path<String>, Json(z): Json<ZerlegenAuftrag>) -> Response {
    let Some(m) = prep::holen(&sid, z.m) else { return err("Die Sitzung ist abgelaufen – bitte das Modell neu laden.") };
    let res = tokio::task::spawn_blocking(move || prep::zerlegen(&m, &z.r, z.s, z.drucker)).await;
    let (neu, out) = match res {
        Ok(Ok(x)) => x,
        Ok(Err(e)) => return err(e),
        Err(_) => return err("Das Zerlegen ist abgestürzt."),
    };
    cleanup();
    // Montageanleitung und Dübel ablegen
    let id = uuid::Uuid::new_v4().simple().to_string()[..12].to_string();
    let dir = data_dir().join("jobs").join(&id);
    let mut extra = Vec::new();
    for (name, data) in &out.files {
        if name.ends_with(".txt") || name.contains("duebel") {
            let path = dir.join(name);
            let _ = std::fs::create_dir_all(path.parent().unwrap());
            if std::fs::write(&path, data).is_ok() {
                extra.push(json!({ "name": name, "url": format!("/api/job/{id}/file/{name}") }));
            }
        }
    }
    let (sid, neu) = prep::ablegen(&sid, neu);
    let infos = tokio::task::spawn_blocking(move || neu.iter().map(|(id, m)| modell_json(*id, m)).collect::<Vec<_>>()).await.unwrap_or_default();
    Json(json!({ "sid": sid, "modelle": infos, "dateien": extra, "hinweise": out.warnings })).into_response()
}
