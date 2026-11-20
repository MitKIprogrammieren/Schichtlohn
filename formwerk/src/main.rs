//! Formwerk – große Modelle aufs Druckbett zerlegen, im Bambu-Studio-Look (nach LuBan „Mesh → Cut“)
mod export;
mod werk;
mod mesh;
mod section;

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
static THREE: &[u8] = include_bytes!("../static/vendor/three.module.min.js");
static STL_LOADER: &[u8] = include_bytes!("../static/vendor/STLLoader.js");
static ORBIT: &[u8] = include_bytes!("../static/vendor/OrbitControls.js");

#[tokio::main]
async fn main() {
    let port: u16 = std::env::var("PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8097);
    let _ = std::fs::create_dir_all(data_dir().join("jobs"));
    let app = Router::new()
        .route("/", get(|| async { Html(INDEX) }))
        .route("/vendor/{name}", get(vendor))
        .route("/api/run", post(run))
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
        _ => return StatusCode::NOT_FOUND.into_response(),
    };
    ([(header::CONTENT_TYPE, "text/javascript"), (header::CACHE_CONTROL, "public, max-age=86400")], body).into_response()
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
    Json(json!({
        "id": id,
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
