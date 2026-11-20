//! Konturwerk – Werkzeug-Umrisse aus einem Foto → Gridfinity-Einsatz oder Platte, optional mit TPU-Inlay.
//! Nachbau der Tooltrace-Kernfunktionen in Rust, Oberfläche im Bambu-Studio-Look.
mod behaelter;
mod erkennung;
mod export;
mod ki;
mod netz;

use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, Multipart, Path},
    http::{StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use erkennung::{PX_MM, Umriss};
use serde::Deserialize;
use serde_json::json;
use std::path::PathBuf;

pub fn daten() -> PathBuf {
    PathBuf::from(std::env::var("KONTURWERK_DATA").unwrap_or_else(|_| "./data".into()))
}

static INDEX: &str = include_str!("../static/index.html");
static THREE: &[u8] = include_bytes!("../static/vendor/three.module.min.js");
static STL_LOADER: &[u8] = include_bytes!("../static/vendor/STLLoader.js");
static ORBIT: &[u8] = include_bytes!("../static/vendor/OrbitControls.js");
const ICON: &str = r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="5" fill="#00AE42"/><g fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 9V6a1 1 0 0 1 1-1h3M15 5h3a1 1 0 0 1 1 1v3M19 15v3a1 1 0 0 1-1 1h-3M9 19H6a1 1 0 0 1-1-1v-3"/><path d="M9 14.5 14.5 9a1.8 1.8 0 0 1 2.5 2.5L11.5 17"/></g></svg>"##;

#[tokio::main]
async fn main() {
    let port: u16 = std::env::var("PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8089);
    let _ = std::fs::create_dir_all(daten().join("jobs"));
    let app = Router::new()
        .route("/", get(|| async { Html(INDEX) }))
        .route("/vendor/{name}", get(vendor))
        .route("/favicon.svg", get(|| async { ([(header::CONTENT_TYPE, "image/svg+xml")], ICON) }))
        .route("/health", get(|| async { "ok" }))
        .route("/api/ki", get(|| async { Json(tokio::task::spawn_blocking(ki::status).await.ok()) }))
        .route("/api/ki/laden", post(ki_laden))
        .route("/api/erkennen", post(erkennen))
        .route("/api/nachbessern", post(nachbessern))
        .route("/api/erzeugen", post(erzeugen))
        .route("/api/bibliothek", get(bibliothek_lesen).post(bibliothek_schreiben))
        .route("/api/job/{id}/file/{*path}", get(job_datei))
        .layer(DefaultBodyLimit::max(80 * 1024 * 1024));
    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], port));
    println!("Konturwerk läuft auf http://{addr}");
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

fn fehler(msg: impl ToString) -> Response {
    (StatusCode::BAD_REQUEST, Json(json!({ "error": msg.to_string() }))).into_response()
}

fn neue_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()[..12].to_string()
}

fn job_ordner(id: &str) -> Option<PathBuf> {
    if id.len() != 12 || !id.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    Some(daten().join("jobs").join(id))
}

fn aufraeumen() {
    if let Ok(rd) = std::fs::read_dir(daten().join("jobs")) {
        for e in rd.flatten() {
            let alt = e.metadata().ok().and_then(|m| m.modified().ok()).and_then(|t| t.elapsed().ok()).is_some_and(|d| d.as_secs() > 7 * 24 * 3600);
            if alt {
                let _ = std::fs::remove_dir_all(e.path());
            }
        }
    }
}

async fn job_datei(Path((id, pfad)): Path<(String, String)>) -> Response {
    let Some(dir) = job_ordner(&id) else { return StatusCode::NOT_FOUND.into_response() };
    if pfad.contains("..") {
        return StatusCode::NOT_FOUND.into_response();
    }
    let Ok(data) = std::fs::read(dir.join(&pfad)) else { return StatusCode::NOT_FOUND.into_response() };
    let typ = match pfad.rsplit('.').next().unwrap_or("") {
        "jpg" => "image/jpeg",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "stl" => "model/stl",
        "3mf" => "model/3mf",
        "dxf" => "application/dxf",
        _ => "application/octet-stream",
    };
    let name = pfad.rsplit('/').next().unwrap_or("datei").to_string();
    let mut h = vec![(header::CONTENT_TYPE, typ.to_string())];
    if !matches!(typ, "image/jpeg" | "image/png") {
        h.push((header::CONTENT_DISPOSITION, format!("attachment; filename=\"{name}\"")));
    }
    let mut r = data.into_response();
    for (k, v) in h {
        r.headers_mut().insert(k, v.parse().unwrap());
    }
    r
}

#[derive(Deserialize)]
#[serde(default)]
struct ErkennenParams {
    papier: String,
    modus: String,
    modell: String,
    empfindlichkeit: f64,
    min_flaeche: f64,
}
impl Default for ErkennenParams {
    fn default() -> Self {
        Self { papier: "a4".into(), modus: "klassisch".into(), modell: "schnell".into(), empfindlichkeit: 0.5, min_flaeche: 150.0 }
    }
}

async fn ki_laden(Json(v): Json<serde_json::Value>) -> Response {
    let id = v.get("modell").and_then(|x| x.as_str()).unwrap_or("schnell").to_string();
    tokio::task::spawn_blocking(move || {
        if let Err(e) = ki::herunterladen(ki::modell(&id)) {
            eprintln!("Modell laden: {e}");
        }
    });
    Json(json!({ "ok": true })).into_response()
}

async fn erkennen(mut mp: Multipart) -> Response {
    let mut datei: Option<Vec<u8>> = None;
    let mut params = String::from("{}");
    while let Ok(Some(f)) = mp.next_field().await {
        match f.name().unwrap_or("") {
            "file" => match f.bytes().await {
                Ok(b) => datei = Some(b.to_vec()),
                Err(e) => return fehler(format!("Upload fehlgeschlagen: {e}")),
            },
            "params" => params = f.text().await.unwrap_or_default(),
            _ => {}
        }
    }
    let p: ErkennenParams = serde_json::from_str(&params).unwrap_or_default();
    let Some(bytes) = datei else { return fehler("Bitte zuerst ein Foto wählen.") };
    let id = neue_id();
    let id2 = id.clone();
    let r = tokio::task::spawn_blocking(move || erkennen_rechnen(&id2, &p, &bytes)).await;
    aufraeumen();
    match r {
        Ok(Ok(v)) => Json(v).into_response(),
        Ok(Err(e)) => fehler(e),
        Err(_) => fehler("Die Erkennung ist abgestürzt."),
    }
}

fn erkennen_rechnen(id: &str, p: &ErkennenParams, bytes: &[u8]) -> anyhow::Result<serde_json::Value> {
    let img = erkennung::laden(bytes)?;
    let pap = erkennung::papier(&img, &p.papier)?;
    let dir = job_ordner(id).unwrap();
    std::fs::create_dir_all(&dir)?;
    let (w, h) = (pap.bild.width() as usize, pap.bild.height() as usize);
    pap.bild.save_with_format(dir.join("papier.png"), image::ImageFormat::Png)?;
    let mut jpg = Vec::new();
    image::DynamicImage::ImageRgb8(pap.bild.clone()).write_to(&mut std::io::Cursor::new(&mut jpg), image::ImageFormat::Jpeg)?;
    std::fs::write(dir.join("papier.jpg"), &jpg)?;
    let karte = erkennung::objektkarte(&pap.bild);
    let (maske, schwelle) = erkennung::werkzeuge(&karte, w, h, p.empfindlichkeit.clamp(0.0, 1.0), p.min_flaeche.max(20.0));
    let mut umrisse = erkennung::umrisse(&maske, w, h, [0.0, 0.0], "klassisch");
    let mut hinweise = Vec::new();
    let mut ki_fehler = None;
    if p.modus == "ki" {
        // sicher erkannte Bereiche (deutlich dunkler/farbiger als Papier, keine weichen Schatten)
        let mittel = (schwelle * 0.7).max(0.26);
        let sicher: Vec<bool> = (0..w * h).map(|i| maske[i] && karte[i] > mittel).collect();
        match ki_alles(&pap.bild, &maske, &sicher, &mut umrisse, &p.modell, p.min_flaeche.max(20.0)) {
            Ok(n) => {
                if n > 0 {
                    hinweise.push(format!("KI hat {n} Umriss(e) verfeinert."));
                }
            }
            Err(e) => ki_fehler = Some(format!("KI nicht verfügbar, klassisch erkannt: {e}")),
        }
    }
    umrisse.sort_by(|a, b| b.flaeche.partial_cmp(&a.flaeche).unwrap());
    for (i, u) in umrisse.iter_mut().enumerate() {
        u.id = i + 1;
        u.name = format!("Werkzeug {}", i + 1);
    }
    if umrisse.is_empty() {
        hinweise.push("Keine Werkzeuge gefunden. Empfindlichkeit erhöhen oder KI verwenden.".into());
    }
    if umrisse.iter().any(|u| u.am_rand) {
        hinweise.push("Ein Werkzeug liegt am Blattrand – der Umriss kann dort abgeschnitten sein.".into());
    }
    Ok(json!({
        "id": id,
        "bild": format!("/api/job/{id}/file/papier.jpg"),
        "breite_mm": pap.breite_mm,
        "hoehe_mm": pap.hoehe_mm,
        "ecken": pap.ecken,
        "foto": [img.width(), img.height()],
        "schwelle": schwelle,
        "umrisse": umrisse,
        "hinweise": hinweise,
        "ki_fehler": ki_fehler,
    }))
}

/// KI: ganzes Blatt (neue Kandidaten) + jeden Umriss im Ausschnitt verfeinern
fn ki_alles(bild: &image::RgbImage, maske: &[bool], sicher: &[bool], umrisse: &mut Vec<Umriss>, modell: &str, min_flaeche: f64) -> anyhow::Result<usize> {
    let (w, h) = (bild.width() as usize, bild.height() as usize);
    let ganz = ki::maske(bild, modell)?;
    let rand = (3.0 * PX_MM) as usize;
    let mut km: Vec<bool> = (0..w * h).map(|i| {
        let (x, y) = (i % w, i / w);
        ganz[i] > 0.5 && x >= rand && y >= rand && x + rand < w && y + rand < h
    }).collect();
    erkennung::loecher_fuellen(&mut km, w, h);
    // neue Kandidaten, die klassisch fehlten
    for u in erkennung::umrisse(&km, w, h, [0.0, 0.0], "ki") {
        if u.flaeche < min_flaeche {
            continue;
        }
        let ueberlappt = umrisse.iter().any(|a| {
            let (g, b) = (a.grenzen, u.grenzen);
            let ix = (g[2].min(b[2]) - g[0].max(b[0])).max(0.0);
            let iy = (g[3].min(b[3]) - g[1].max(b[1])).max(0.0);
            ix * iy > 0.3 * ((b[2] - b[0]) * (b[3] - b[1])).min((g[2] - g[0]) * (g[3] - g[1]))
        });
        if !ueberlappt {
            umrisse.push(u);
        }
    }
    let mut n = 0;
    for u in umrisse.iter_mut() {
        let g = u.grenzen;
        if let Some(neu) = ki_ausschnitt(bild, [g[0] - 10.0, g[1] - 10.0, g[2] + 10.0, g[3] + 10.0], None, Some((maske, u)), Some(sicher), modell)? {
            if neu.flaeche > 0.5 * u.flaeche && neu.flaeche < 1.8 * u.flaeche.max(min_flaeche) {
                let am_rand = u.am_rand;
                *u = neu;
                u.am_rand = am_rand;
                n += 1;
            }
        }
    }
    Ok(n)
}

/// KI auf einem Ausschnitt (mm-Rahmen). Wahl der Komponente: Punkt, sonst größte Überlappung mit dem klassischen Umriss, sonst größte.
fn ki_ausschnitt(bild: &image::RgbImage, rahmen: [f64; 4], punkt: Option<[f64; 2]>, klassisch: Option<(&[bool], &Umriss)>, sicher: Option<&[bool]>, modell: &str) -> anyhow::Result<Option<Umriss>> {
    let (w, h) = (bild.width() as i64, bild.height() as i64);
    let x0 = ((rahmen[0] * PX_MM) as i64).clamp(0, w - 1);
    let y0 = ((rahmen[1] * PX_MM) as i64).clamp(0, h - 1);
    let x1 = ((rahmen[2] * PX_MM).ceil() as i64).clamp(x0 + 8, w);
    let y1 = ((rahmen[3] * PX_MM).ceil() as i64).clamp(y0 + 8, h);
    let (cw, ch) = ((x1 - x0) as usize, (y1 - y0) as usize);
    if cw < 8 || ch < 8 {
        return Ok(None);
    }
    let crop = image::imageops::crop_imm(bild, x0 as u32, y0 as u32, cw as u32, ch as u32).to_image();
    let m = ki::maske(&crop, modell)?;
    let mut b: Vec<bool> = m.iter().map(|&v| v > 0.5).collect();
    if let Some(si) = sicher {
        for y in 0..ch {
            for x in 0..cw {
                if si[(y + y0 as usize) * w as usize + x + x0 as usize] {
                    b[y * cw + x] = true;
                }
            }
        }
    }
    erkennung::loecher_fuellen(&mut b, cw, ch);
    let (lab, gr) = erkennung::komponenten(&b, cw, ch);
    if gr.len() < 2 {
        return Ok(None);
    }
    let wahl = if let Some(pt) = punkt {
        let (px, py) = ((pt[0] * PX_MM) as i64 - x0, (pt[1] * PX_MM) as i64 - y0);
        let mut best = (f64::MAX, 0u32);
        for i in 0..cw * ch {
            if lab[i] != 0 {
                let d = ((i % cw) as i64 - px).pow(2) + ((i / cw) as i64 - py).pow(2);
                if (d as f64) < best.0 {
                    best = (d as f64, lab[i]);
                }
            }
        }
        best.1
    } else if let Some((km, _)) = klassisch {
        let mut zaehl = vec![0usize; gr.len()];
        for y in 0..ch {
            for x in 0..cw {
                let gi = (y + y0 as usize) * w as usize + x + x0 as usize;
                if km[gi] {
                    zaehl[lab[y * cw + x] as usize] += 1;
                }
            }
        }
        zaehl[0] = 0;
        (0..gr.len()).max_by_key(|&i| zaehl[i]).unwrap_or(0) as u32
    } else {
        (1..gr.len()).max_by_key(|&i| gr[i]).unwrap_or(0) as u32
    };
    if wahl == 0 {
        return Ok(None);
    }
    let sel: Vec<bool> = lab.iter().map(|&v| v == wahl).collect();
    let (mut a, mut bb, mut c, mut d) = (cw, ch, 0, 0);
    for i in 0..cw * ch {
        if sel[i] {
            a = a.min(i % cw); bb = bb.min(i / cw); c = c.max(i % cw); d = d.max(i / cw);
        }
    }
    let Some(k) = erkennung::kontur(&sel, cw, ch, a, bb, c, d) else { return Ok(None) };
    let pts = k.iter().map(|q| [(q[0] + x0 as f64) / PX_MM, (q[1] + y0 as f64) / PX_MM]).collect();
    Ok(Some(erkennung::umriss_aus(pts, "ki", false)))
}

#[derive(Deserialize)]
struct NachbessernParams {
    id: String,
    rahmen: [f64; 4],
    punkt: Option<[f64; 2]>,
    #[serde(default)]
    art: String,
    #[serde(default)]
    modell: String,
    #[serde(default)]
    empfindlichkeit: Option<f64>,
}

async fn nachbessern(Json(p): Json<NachbessernParams>) -> Response {
    let r = tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let dir = job_ordner(&p.id).ok_or_else(|| anyhow::anyhow!("Unbekannte Erkennung."))?;
        let bild = image::open(dir.join("papier.png")).map_err(|_| anyhow::anyhow!("Foto nicht mehr vorhanden – bitte neu erkennen."))?.to_rgb8();
        let u = if p.art == "klassisch" {
            let (w, h) = (bild.width() as usize, bild.height() as usize);
            let karte = erkennung::objektkarte(&bild);
            let (m, _) = erkennung::werkzeuge(&karte, w, h, p.empfindlichkeit.unwrap_or(0.5), 20.0);
            let r = p.rahmen;
            let (x0, y0, x1, y1) = ((r[0] * PX_MM) as usize, (r[1] * PX_MM) as usize, (r[2] * PX_MM) as usize, (r[3] * PX_MM) as usize);
            let teil: Vec<bool> = (0..w * h).map(|i| m[i] && (x0..=x1).contains(&(i % w)) && (y0..=y1).contains(&(i / w))).collect();
            let mut l = erkennung::umrisse(&teil, w, h, [0.0, 0.0], "klassisch");
            l.sort_by(|a, b| b.flaeche.partial_cmp(&a.flaeche).unwrap());
            l.into_iter().next()
        } else {
            ki_ausschnitt(&bild, p.rahmen, p.punkt, None, None, if p.modell.is_empty() { "schnell" } else { &p.modell })?
        };
        Ok(json!({ "umriss": u }))
    }).await;
    match r {
        Ok(Ok(v)) => Json(v).into_response(),
        Ok(Err(e)) => fehler(e),
        Err(_) => fehler("Nachbessern abgestürzt."),
    }
}

async fn erzeugen(Json(l): Json<behaelter::Layout>) -> Response {
    let r = tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let t0 = std::time::Instant::now();
        let e = behaelter::bauen(&l)?;
        let id = neue_id();
        let dir = job_ordner(&id).unwrap();
        std::fs::create_dir_all(&dir)?;
        let basis: String = l.einstellungen.name.chars().map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
        let basis = if basis.trim_matches('_').is_empty() { "konturwerk".to_string() } else { basis };
        let mut dateien = Vec::new();
        let mut schreib = |name: String, data: Vec<u8>, art: &str| -> anyhow::Result<()> {
            std::fs::write(dir.join(&name), &data)?;
            dateien.push(json!({ "name": name, "groesse": data.len(), "art": art, "url": format!("/api/job/{id}/file/{name}") }));
            Ok(())
        };
        schreib(format!("{basis}.3mf"), export::bambu_3mf(&e, &l.einstellungen.name), "3mf")?;
        let mut vorschau = Vec::new();
        for (i, t) in e.teile.iter().enumerate() {
            let datei = if t.filament == 2 && t.name == "TPU-Kontur" { format!("{basis}_tpu-kontur.stl") } else if t.filament == 2 { format!("{basis}_tpu-inlay.stl") } else { format!("{basis}_behaelter.stl") };
            let stl = t.netz.stl(&t.name);
            std::fs::write(dir.join(format!("v{i}.stl")), t.vorschau.as_ref().unwrap_or(&t.netz).stl(&t.name))?;
            vorschau.push(json!({ "name": t.name, "filament": t.filament, "url": format!("/api/job/{id}/file/v{i}.stl"), "dreiecke": t.netz.tris.len() }));
            schreib(datei, stl, "stl")?;
        }
        schreib(format!("{basis}_umrisse.svg"), export::svg(&e).into_bytes(), "svg")?;
        schreib(format!("{basis}_umrisse.dxf"), export::dxf(&e).into_bytes(), "dxf")?;
        Ok(json!({
            "id": id,
            "dateien": dateien,
            "vorschau": vorschau,
            "hinweise": e.hinweise,
            "mass": [e.breite, e.tiefe_aussen, e.hoehe],
            "inlay_dicke": e.inlay_dicke,
            "kombiniert": e.kombiniert,
            "sekunden": t0.elapsed().as_secs_f64(),
        }))
    }).await;
    match r {
        Ok(Ok(v)) => Json(v).into_response(),
        Ok(Err(e)) => fehler(e),
        Err(_) => fehler("Die Berechnung ist abgestürzt."),
    }
}

async fn bibliothek_lesen() -> Response {
    let s = std::fs::read_to_string(daten().join("bibliothek.json")).unwrap_or_else(|_| "[]".into());
    ([(header::CONTENT_TYPE, "application/json")], s).into_response()
}

async fn bibliothek_schreiben(Json(v): Json<serde_json::Value>) -> Response {
    if !v.is_array() {
        return fehler("Erwartet eine Liste.");
    }
    let pfad = daten().join("bibliothek.json");
    let tmp = pfad.with_extension("tmp");
    match std::fs::write(&tmp, v.to_string()).and_then(|_| std::fs::rename(&tmp, &pfad)) {
        Ok(_) => Json(json!({ "ok": true })).into_response(),
        Err(e) => fehler(format!("Speichern fehlgeschlagen: {e}")),
    }
}
