//! bauwerk – Kommandozeile
//!   bauwerk app                       Bauwerk lokal starten und im Browser öffnen
//!   bauwerk server [--port N] [--daten ORDNER] [--basis-url URL]
//!   bauwerk mcp [--daten ORDNER]      MCP über stdio (z. B. `claude mcp add bauwerk -- bauwerk mcp`)
//!   bauwerk run teil.json --out teil.step|stl|3mf
//!   bauwerk pruefen teil.json
use bauwerk::{mcp, projekte, server};

use std::io::{BufRead, Write};
use std::path::PathBuf;

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
}

fn standard_ordner() -> PathBuf {
    if let Ok(d) = std::env::var("BAUWERK_DATEN") { return PathBuf::from(d); }
    let home = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE")).unwrap_or_else(|_| ".".into());
    PathBuf::from(home).join("Bauwerk")
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let befehl = args.get(1).map(|s| s.as_str()).unwrap_or("app");
    let daten = arg(&args, "--daten").map(PathBuf::from).unwrap_or_else(standard_ordner);
    let ergebnis: Result<(), String> = match befehl {
        "server" => {
            let port = arg(&args, "--port").or_else(|| std::env::var("PORT").ok()).unwrap_or_else(|| "8088".into());
            let basis = arg(&args, "--basis-url").or_else(|| std::env::var("BASIS_URL").ok()).unwrap_or_else(|| format!("http://localhost:{}", port));
            let k = mcp::Kontext { ablage: projekte::Ablage::neu(&daten), basis_url: Some(basis.trim_end_matches('/').to_string()) };
            server::starten(&format!("0.0.0.0:{}", port), k, None)
        }
        "app" => {
            let port = arg(&args, "--port").unwrap_or_else(|| "0".into());
            let k = mcp::Kontext { ablage: projekte::Ablage::neu(&daten), basis_url: None };
            server::starten(&format!("127.0.0.1:{}", port), k, Some(Box::new(|adr: String| {
                let url = format!("http://{}", adr);
                let _ = if cfg!(target_os = "macos") { std::process::Command::new("open").arg(&url).spawn() }
                    else if cfg!(windows) { std::process::Command::new("cmd").args(["/C", "start", &url]).spawn() }
                    else { std::process::Command::new("xdg-open").arg(&url).spawn() };
            })))
        }
        "mcp" => {
            let k = mcp::Kontext { ablage: projekte::Ablage::neu(&daten), basis_url: None };
            let stdin = std::io::stdin();
            let mut out = std::io::stdout();
            for zeile in stdin.lock().lines() {
                let Ok(z) = zeile else { break };
                if z.trim().is_empty() { continue; }
                if let Some(a) = k.nachricht(&z) { let _ = writeln!(out, "{}", a); let _ = out.flush(); }
            }
            Ok(())
        }
        "run" | "pruefen" => (|| {
            let datei = args.get(2).ok_or("Datei fehlt")?;
            let txt = std::fs::read_to_string(datei).map_err(|e| format!("{}: {}", datei, e))?;
            let e = bauwerk_kern::berechnen(&bauwerk_kern::dokument_lesen(&txt)?);
            print!("{}", mcp::zusammenfassung(&e));
            if befehl == "run" {
                let ziel = arg(&args, "--out").ok_or("--out fehlt (z. B. teil.step)")?;
                let f = ziel.rsplit('.').next().unwrap_or("stl");
                std::fs::write(&ziel, bauwerk_kern::exportieren(&e, f)?).map_err(|e| e.to_string())?;
                println!("Geschrieben: {}", ziel);
            }
            if e.features.iter().any(|f| !f.ok) { return Err("Das Modell hat Fehler".into()); }
            Ok(())
        })(),
        "--version" | "version" => { println!("bauwerk {}", bauwerk_kern::VERSION); Ok(()) }
        _ => {
            eprintln!("Befehle: app | server [--port N] [--daten ORDNER] [--basis-url URL] | mcp [--daten ORDNER] | run teil.json --out teil.step | pruefen teil.json");
            Ok(())
        }
    };
    if let Err(e) = ergebnis { eprintln!("Fehler: {}", e); std::process::exit(1); }
}
