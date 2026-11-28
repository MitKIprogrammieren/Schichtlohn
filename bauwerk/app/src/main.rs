//! Bauwerk – Mac-App. Startet den Bauwerk-Server im eigenen Prozess (127.0.0.1:8765, sonst freier Port)
//! und zeigt die Oberfläche in einem nativen Fenster. Projekte liegen in ~/Bauwerk.
//! MCP: Solange die App läuft, ist sie unter http://127.0.0.1:8765/mcp erreichbar.
use bauwerk::{mcp::Kontext, projekte::Ablage, server};
use std::path::PathBuf;
use std::sync::mpsc;
use tao::{event::{Event, WindowEvent}, event_loop::{ControlFlow, EventLoop}, window::WindowBuilder};
use wry::WebViewBuilder;

fn home() -> PathBuf { PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| ".".into())) }

fn main() {
    // STEP-Export mit echten Flächen (Mesh2STEP-Kern)
    bauwerk_echt::anmelden();
    let daten = std::env::var("BAUWERK_DATEN").map(PathBuf::from).unwrap_or_else(|_| home().join("Bauwerk"));
    let ablage = Ablage::neu(&daten);
    // Server starten
    let (tx, rx) = mpsc::channel::<String>();
    for port in ["8765", "0"] {
        let tx = tx.clone();
        let (k, adr) = (Kontext { ablage: ablage.clone(), basis_url: Some(format!("http://127.0.0.1:{}", port)) }, format!("127.0.0.1:{}", port));
        let (ok_tx, ok_rx) = mpsc::channel::<bool>();
        std::thread::spawn(move || {
            let tx2 = tx.clone();
            let r = server::starten(&adr, k, Some(Box::new(move |a: String| { let _ = tx2.send(a); })));
            if r.is_err() { let _ = ok_tx.send(false); }
        });
        if ok_rx.recv_timeout(std::time::Duration::from_millis(400)).is_err() { break; }
    }
    let adresse = rx.recv().expect("Server startet nicht");
    let url = format!("http://{}/", adresse);

    let event_loop = EventLoop::new();
    // Menü (nötig, damit Kopieren/Einfügen/Rückgängig in Textfeldern funktionieren)
    #[cfg(target_os = "macos")]
    let _menue = {
        use muda::{Menu, PredefinedMenuItem as P, Submenu};
        let app = Submenu::with_items("Bauwerk", true, &[&P::about(Some("Über Bauwerk"), None), &P::separator(), &P::hide(Some("Bauwerk ausblenden")), &P::hide_others(Some("Andere ausblenden")), &P::separator(), &P::quit(Some("Bauwerk beenden"))]).unwrap();
        let bearbeiten = Submenu::with_items("Bearbeiten", true, &[&P::undo(Some("Widerrufen")), &P::redo(Some("Wiederholen")), &P::separator(), &P::cut(Some("Ausschneiden")), &P::copy(Some("Kopieren")), &P::paste(Some("Einsetzen")), &P::select_all(Some("Alles auswählen"))]).unwrap();
        let fenster = Submenu::with_items("Fenster", true, &[&P::minimize(Some("Im Dock ablegen")), &P::fullscreen(Some("Vollbild"))]).unwrap();
        let m = Menu::with_items(&[&app, &bearbeiten, &fenster]).unwrap();
        m.init_for_nsapp();
        m
    };
    let window = WindowBuilder::new()
        .with_title("Bauwerk")
        .with_inner_size(tao::dpi::LogicalSize::new(1440.0, 900.0))
        .with_min_inner_size(tao::dpi::LogicalSize::new(760.0, 520.0))
        .build(&event_loop)
        .expect("Fenster");
    let abl = ablage.clone();
    let builder = WebViewBuilder::new()
        .with_url(url)
        .with_devtools(cfg!(debug_assertions))
        .with_download_started_handler(move |quelle, ziel| {
            // Exporte landen in ~/Downloads mit dem Projektnamen
            let teile: Vec<&str> = quelle.split('/').collect();
            let datei = teile.last().copied().unwrap_or("export.stl");
            let endung = datei.rsplit('.').next().unwrap_or("stl").to_string();
            let id = teile.iter().position(|t| *t == "projekte").and_then(|i| teile.get(i + 1)).copied().unwrap_or("");
            let name = abl.lesen(id).map(|d| d.name).unwrap_or_else(|_| "Bauwerk".into());
            let name: String = name.chars().map(|c| if c.is_alphanumeric() || c == '-' || c == '_' || c == ' ' { c } else { '_' }).collect();
            let ordner = home().join("Downloads");
            let mut p = ordner.join(format!("{}.{}", name, endung));
            let mut n = 2;
            while p.exists() { p = ordner.join(format!("{} {}.{}", name, n, endung)); n += 1; }
            *ziel = p;
            true
        })
        .with_download_completed_handler(|_, pfad, ok| {
            let _ = (&pfad, ok);
            #[cfg(target_os = "macos")]
            if let (Some(p), true) = (pfad, ok) { let _ = std::process::Command::new("open").arg("-R").arg(p).spawn(); }
        });
    #[cfg(not(target_os = "linux"))]
    let _webview = builder.build(&window).expect("WebView");
    #[cfg(target_os = "linux")]
    let _webview = {
        use tao::platform::unix::WindowExtUnix;
        use wry::WebViewBuilderExtUnix;
        builder.build_gtk(window.default_vbox().unwrap()).expect("WebView")
    };
    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        if let Event::WindowEvent { event: WindowEvent::CloseRequested, .. } = event { *control_flow = ControlFlow::Exit; }
    });
}
