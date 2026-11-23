//! HTTP-Server: Oberfläche, Berechnung, Projekte, Export und MCP unter /mcp.
use crate::mcp::Kontext;
use bauwerk_kern::{berechnen, dokument_lesen, exportieren, Ergebnis};
use serde_json::json;
use std::sync::Arc;
use tiny_http::{Header, Method, Request, Response, Server};

macro_rules! datei { ($p:literal) => { include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/../../web/", $p)) }; }
const STATISCH: &[(&str, &[u8], &str)] = &[
    ("/", datei!("index.html"), "text/html; charset=utf-8"),
    ("/index.html", datei!("index.html"), "text/html; charset=utf-8"),
    ("/app.js", datei!("app.js"), "text/javascript; charset=utf-8"),
    ("/vendor/three.module.js", datei!("vendor/three.module.js"), "text/javascript; charset=utf-8"),
    ("/vendor/OrbitControls.js", datei!("vendor/OrbitControls.js"), "text/javascript; charset=utf-8"),
];

fn kopf(k: &str, v: &str) -> Header { Header::from_bytes(k.as_bytes(), v.as_bytes()).unwrap() }

/// Ergebnis binär: [u32 JSON-Länge][JSON][Auffüllung auf 4][f32 Positionen][u32 Indizes]
pub fn binaer(e: &Ergebnis) -> Vec<u8> {
    let mut info = serde_json::to_value(e).unwrap_or(json!({}));
    info["anzahl_punkte"] = json!(e.netz.pos.len());
    info["anzahl_indizes"] = json!(e.netz.idx.len() * 3);
    let j = info.to_string().into_bytes();
    let mut b = Vec::with_capacity(8 + j.len() + e.netz.pos.len() * 12 + e.netz.idx.len() * 12);
    b.extend_from_slice(&(j.len() as u32).to_le_bytes());
    b.extend_from_slice(&j);
    while b.len() % 4 != 0 { b.push(b' '); }
    for p in &e.netz.pos { for v in p { b.extend_from_slice(&(*v as f32).to_le_bytes()); } }
    for t in &e.netz.idx { for v in t { b.extend_from_slice(&(*v as u32).to_le_bytes()); } }
    b
}

fn antwort(req: Request, code: u16, body: Vec<u8>, typ: &str, extra: &[(&str, String)]) {
    let mut r = Response::from_data(body).with_status_code(code).with_header(kopf("Content-Type", typ)).with_header(kopf("Cache-Control", "no-store"));
    for (k, v) in extra { r = r.with_header(kopf(k, v)); }
    let _ = req.respond(r);
}
fn json_antwort(req: Request, code: u16, v: serde_json::Value) { antwort(req, code, v.to_string().into_bytes(), "application/json; charset=utf-8", &[]) }

fn dateiname(n: &str) -> String {
    let s: String = n.chars().map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
    if s.is_empty() { "teil".into() } else { s }
}
fn mime(f: &str) -> &'static str { match f { "stl" => "model/stl", "3mf" => "model/3mf", _ => "model/step" } }

fn behandeln(k: &Kontext, mut req: Request) {
    let url = req.url().to_string();
    let pfad = url.split('?').next().unwrap_or("/").to_string();
    let meth = req.method().clone();
    let mut body = vec![];
    if matches!(meth, Method::Post | Method::Put) {
        if req.body_length().unwrap_or(0) > 64 * 1024 * 1024 { return json_antwort(req, 413, json!({"ok":false,"text":"zu groß"})); }
        let _ = req.as_reader().read_to_end(&mut body);
    }
    let text = String::from_utf8_lossy(&body).to_string();
    match (&meth, pfad.as_str()) {
        (Method::Get, "/gesund") => json_antwort(req, 200, json!({"ok":true,"version":bauwerk_kern::VERSION})),
        (Method::Get, p) if STATISCH.iter().any(|s| s.0 == p) => {
            let s = STATISCH.iter().find(|s| s.0 == p).unwrap();
            antwort(req, 200, s.1.to_vec(), s.2, &[])
        }
        (Method::Post, "/api/berechnen") => match dokument_lesen(&text) {
            Ok(d) => antwort(req, 200, binaer(&berechnen(&d)), "application/octet-stream", &[]),
            Err(e) => json_antwort(req, 400, json!({"ok":false,"text":e})),
        },
        (Method::Post, p) if p.starts_with("/api/export.") => {
            let f = &p["/api/export.".len()..];
            match dokument_lesen(&text).map(|d| berechnen(&d)).and_then(|e| exportieren(&e, f).map(|b| (b, e.dok.name.clone()))) {
                Ok((b, n)) => antwort(req, 200, b, mime(f), &[("Content-Disposition", format!("attachment; filename=\"{}.{}\"", dateiname(&n), f))]),
                Err(e) => json_antwort(req, 400, json!({"ok":false,"text":e})),
            }
        }
        (Method::Get, "/api/projekte") => json_antwort(req, 200, serde_json::to_value(k.ablage.liste()).unwrap()),
        (_, p) if p.starts_with("/api/projekte/") => {
            let rest = &p["/api/projekte/".len()..];
            let (id, export) = match rest.split_once("/export.") { Some((i, f)) => (i, Some(f.to_string())), None => (rest, None) };
            if crate::projekte::gueltig(id).is_err() { return json_antwort(req, 400, json!({"ok":false,"text":"ungültige ID"})); }
            match (&meth, export) {
                (Method::Get, Some(f)) => match k.ablage.lesen(id).map(|d| berechnen(&d)).and_then(|e| exportieren(&e, &f).map(|b| (b, e.dok.name.clone()))) {
                    Ok((b, n)) => antwort(req, 200, b, mime(&f), &[("Content-Disposition", format!("attachment; filename=\"{}.{}\"", dateiname(&n), f))]),
                    Err(e) => json_antwort(req, 404, json!({"ok":false,"text":e})),
                },
                (Method::Get, None) => match k.ablage.roh(id) {
                    Ok(t) => antwort(req, 200, t.into_bytes(), "application/json; charset=utf-8", &[]),
                    Err(e) => json_antwort(req, 404, json!({"ok":false,"text":e})),
                },
                (Method::Put, None) => match dokument_lesen(&text) {
                    Ok(mut d) => { d.id = id.into(); match k.ablage.schreiben(&d) { Ok(()) => json_antwort(req, 200, json!({"ok":true})), Err(e) => json_antwort(req, 500, json!({"ok":false,"text":e})) } }
                    Err(e) => json_antwort(req, 400, json!({"ok":false,"text":e})),
                },
                (Method::Delete, None) => { let _ = k.ablage.loeschen(id); json_antwort(req, 200, json!({"ok":true})) }
                _ => json_antwort(req, 405, json!({"ok":false})),
            }
        }
        (Method::Post, "/mcp") => match k.nachricht(&text) {
            Some(a) => antwort(req, 200, a.into_bytes(), "application/json", &[]),
            None => antwort(req, 202, vec![], "text/plain", &[]),
        },
        (Method::Get, "/mcp") => antwort(req, 405, vec![], "text/plain", &[("Allow", "POST".into())]),
        _ => json_antwort(req, 404, json!({"ok":false})),
    }
}

pub fn starten(adresse: &str, k: Kontext, bei_start: Option<Box<dyn FnOnce(String) + Send>>) -> Result<(), String> {
    let server = Arc::new(Server::http(adresse).map_err(|e| format!("Server auf {} nicht startbar: {}", adresse, e))?);
    let echt = server.server_addr().to_ip().map(|a| a.to_string()).unwrap_or_else(|| adresse.to_string());
    println!("Bauwerk {} läuft auf http://{}", bauwerk_kern::VERSION, echt);
    if let Some(f) = bei_start { f(echt); }
    let k = Arc::new(k);
    let mut faeden = vec![];
    for _ in 0..4 {
        let (s, k) = (server.clone(), k.clone());
        faeden.push(std::thread::spawn(move || { for req in s.incoming_requests() { behandeln(&k, req); } }));
    }
    for f in faeden { let _ = f.join(); }
    Ok(())
}
