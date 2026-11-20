//! KI-Erkennung: Freistell-Modelle (U²-Net / IS-Net) lokal über ONNX Runtime.
//! Modelle werden beim ersten Gebrauch nach <daten>/modelle geladen.
use image::RgbImage;
use ort::session::Session;
use ort::value::Tensor;
use serde::Serialize;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

pub struct Modell {
    pub id: &'static str,
    pub name: &'static str,
    pub datei: &'static str,
    pub url: &'static str,
    pub groesse: u32,
    pub mittel: [f32; 3],
    pub streu: [f32; 3],
    pub mb: u32,
}

pub const MODELLE: [Modell; 2] = [
    Modell {
        id: "schnell",
        name: "Schnell (U²-Net klein)",
        datei: "u2netp.onnx",
        url: "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
        groesse: 320,
        mittel: [0.485, 0.456, 0.406],
        streu: [0.229, 0.224, 0.225],
        mb: 5,
    },
    Modell {
        id: "genau",
        name: "Genau (IS-Net)",
        datei: "isnet-general-use.onnx",
        url: "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        groesse: 1024,
        mittel: [0.5, 0.5, 0.5],
        streu: [1.0, 1.0, 1.0],
        mb: 170,
    },
];

pub fn modell(id: &str) -> &'static Modell {
    MODELLE.iter().find(|m| m.id == id).unwrap_or(&MODELLE[0])
}

fn modell_ordner() -> PathBuf {
    crate::daten().join("modelle")
}

fn runtime_pfad() -> String {
    std::env::var("ORT_DYLIB_PATH").unwrap_or_else(|_| "/usr/local/lib/libonnxruntime.so".into())
}

static INIT: OnceLock<Result<(), String>> = OnceLock::new();
static SITZUNGEN: OnceLock<Mutex<std::collections::HashMap<&'static str, Session>>> = OnceLock::new();
static LADEN: Mutex<Option<(String, u64, u64)>> = Mutex::new(None);

fn init() -> Result<(), String> {
    INIT.get_or_init(|| {
        let p = runtime_pfad();
        if !std::path::Path::new(&p).exists() {
            return Err(format!("ONNX Runtime fehlt ({p})."));
        }
        // ort lädt die Bibliothek dynamisch; ein Fehler darf den Server nicht abstürzen lassen
        match std::panic::catch_unwind(|| ort::init_from(p.clone()).with_name("konturwerk").commit()) {
            Ok(Ok(_)) => Ok(()),
            Ok(Err(e)) => Err(format!("ONNX Runtime nicht nutzbar: {e}")),
            Err(_) => Err("ONNX Runtime nicht nutzbar.".into()),
        }
    })
    .clone()
}

#[derive(Serialize)]
pub struct Status {
    pub runtime: bool,
    pub fehler: Option<String>,
    pub modelle: Vec<serde_json::Value>,
    pub laedt: Option<serde_json::Value>,
}

pub fn status() -> Status {
    let r = init();
    let laedt = LADEN.lock().unwrap().clone().map(|(n, a, g)| serde_json::json!({ "modell": n, "bytes": a, "gesamt": g }));
    Status {
        runtime: r.is_ok(),
        fehler: r.err(),
        modelle: MODELLE.iter().map(|m| serde_json::json!({
            "id": m.id, "name": m.name, "mb": m.mb, "vorhanden": modell_ordner().join(m.datei).exists()
        })).collect(),
        laedt,
    }
}

/// Modell herunterladen (blockierend), falls noch nicht da
pub fn herunterladen(m: &Modell) -> anyhow::Result<PathBuf> {
    let ziel = modell_ordner().join(m.datei);
    if ziel.exists() {
        return Ok(ziel);
    }
    std::fs::create_dir_all(modell_ordner())?;
    let tmp = ziel.with_extension("teil");
    let resp = ureq::get(m.url).call().map_err(|e| anyhow::anyhow!("Modell konnte nicht geladen werden: {e}"))?;
    let gesamt: u64 = resp.header("Content-Length").and_then(|v| v.parse().ok()).unwrap_or(m.mb as u64 * 1_000_000);
    let mut r = resp.into_reader();
    let mut f = std::fs::File::create(&tmp)?;
    let mut buf = vec![0u8; 1 << 16];
    let mut n_ges = 0u64;
    loop {
        let n = std::io::Read::read(&mut r, &mut buf)?;
        if n == 0 {
            break;
        }
        std::io::Write::write_all(&mut f, &buf[..n])?;
        n_ges += n as u64;
        *LADEN.lock().unwrap() = Some((m.name.to_string(), n_ges, gesamt));
    }
    *LADEN.lock().unwrap() = None;
    std::fs::rename(&tmp, &ziel)?;
    Ok(ziel)
}

/// Freistellmaske (0..1) für ein Bild in Originalgröße
pub fn maske(bild: &RgbImage, modell_id: &str) -> anyhow::Result<Vec<f32>> {
    init().map_err(|e| anyhow::anyhow!(e))?;
    let m = modell(modell_id);
    let pfad = herunterladen(m)?;
    let s = m.groesse;
    let klein = image::imageops::resize(bild, s, s, image::imageops::FilterType::Triangle);
    let maxv = klein.pixels().flat_map(|p| p.0).max().unwrap_or(255).max(1) as f32;
    let n = (s * s) as usize;
    let mut daten = vec![0f32; 3 * n];
    for (i, p) in klein.pixels().enumerate() {
        for c in 0..3 {
            daten[c * n + i] = (p.0[c] as f32 / maxv - m.mittel[c]) / m.streu[c];
        }
    }
    let tensor = Tensor::from_array(([1usize, 3, s as usize, s as usize], daten.into_boxed_slice()))?;
    let sitzungen = SITZUNGEN.get_or_init(|| Mutex::new(Default::default()));
    let mut map = sitzungen.lock().unwrap();
    if !map.contains_key(m.id) {
        let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(8);
        let sess = Session::builder()?.with_intra_threads(threads)?.commit_from_file(&pfad)?;
        map.insert(m.id, sess);
    }
    let sess = map.get_mut(m.id).unwrap();
    let out = sess.run(ort::inputs![tensor])?;
    let (shape, werte) = out[0].try_extract_tensor::<f32>()?;
    let (oh, ow) = (shape[shape.len() - 2] as usize, shape[shape.len() - 1] as usize);
    let plane = &werte[..oh * ow];
    let (mn, mx) = plane.iter().fold((f32::MAX, f32::MIN), |(a, b), &v| (a.min(v), b.max(v)));
    let span = (mx - mn).max(1e-6);
    // auf Originalgröße bringen (bilinear)
    let (bw, bh) = (bild.width() as usize, bild.height() as usize);
    let mut res = vec![0f32; bw * bh];
    for y in 0..bh {
        let fy = ((y as f32 + 0.5) / bh as f32 * oh as f32 - 0.5).clamp(0.0, (oh - 1) as f32);
        let (y0, ay) = (fy.floor() as usize, fy - fy.floor());
        let y1 = (y0 + 1).min(oh - 1);
        for x in 0..bw {
            let fx = ((x as f32 + 0.5) / bw as f32 * ow as f32 - 0.5).clamp(0.0, (ow - 1) as f32);
            let (x0, ax) = (fx.floor() as usize, fx - fx.floor());
            let x1 = (x0 + 1).min(ow - 1);
            let v = (plane[y0 * ow + x0] * (1.0 - ax) + plane[y0 * ow + x1] * ax) * (1.0 - ay) + (plane[y1 * ow + x0] * (1.0 - ax) + plane[y1 * ow + x1] * ax) * ay;
            res[y * bw + x] = (v - mn) / span;
        }
    }
    Ok(res)
}
