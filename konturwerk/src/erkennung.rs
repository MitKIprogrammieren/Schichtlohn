//! Klassische Erkennung: Papierblatt finden, entzerren, Werkzeuge als Umrisse in mm herauslösen.
use crate::netz::P2;
use image::{DynamicImage, RgbImage};
use serde::Serialize;

/// Bildpunkte je mm im entzerrten Bild
pub const PX_MM: f64 = 4.0;
/// Randstreifen des Blatts, der ignoriert wird (mm)
const RAND_MM: f64 = 3.0;

pub struct Papier {
    pub bild: RgbImage,
    pub breite_mm: f64,
    pub hoehe_mm: f64,
    pub ecken: [P2; 4],
}

#[derive(Serialize, Clone)]
pub struct Umriss {
    pub id: usize,
    pub name: String,
    /// Punkte in mm (Blattkoordinaten, y nach unten)
    pub punkte: Vec<P2>,
    pub flaeche: f64,
    pub grenzen: [f64; 4],
    pub quelle: String,
    pub am_rand: bool,
}

pub fn papiermass(name: &str) -> (f64, f64) {
    match name {
        "a3" => (297.0, 420.0),
        "a5" => (148.0, 210.0),
        "letter" => (215.9, 279.4),
        "legal" => (215.9, 355.6),
        _ => (210.0, 297.0),
    }
}

/// HEIC/HEIF/AVIF (iPhone, Mac) erkennen: ISO-BMFF mit passender ftyp-Marke
fn ist_heif(b: &[u8]) -> bool {
    b.len() > 12 && &b[4..8] == b"ftyp" && {
        let marke = &b[8..12];
        [&b"heic"[..], b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"].contains(&marke)
    }
}

/// HEIC über heif-convert (libheif) in JPEG umwandeln – Drehung wird dabei angewendet
fn heif_zu_jpeg(bytes: &[u8]) -> anyhow::Result<Vec<u8>> {
    let dir = std::env::temp_dir().join(format!("kw-heif-{}", uuid::Uuid::new_v4().simple()));
    std::fs::create_dir_all(&dir)?;
    let (ein, aus) = (dir.join("foto.heic"), dir.join("foto.jpg"));
    std::fs::write(&ein, bytes)?;
    let r = std::process::Command::new("heif-convert").arg("-q").arg("95").arg(&ein).arg(&aus).output();
    let ergebnis = match r {
        Ok(o) if o.status.success() => std::fs::read(&aus).map_err(|e| anyhow::anyhow!("HEIC-Umwandlung ohne Ergebnis: {e}")),
        Ok(o) => Err(anyhow::anyhow!("HEIC-Foto nicht lesbar: {}", String::from_utf8_lossy(&o.stderr).trim())),
        Err(_) => Err(anyhow::anyhow!("HEIC wird auf diesem Server nicht unterstützt – bitte als JPEG exportieren.")),
    };
    let _ = std::fs::remove_dir_all(&dir);
    ergebnis
}

pub fn laden(bytes: &[u8]) -> anyhow::Result<DynamicImage> {
    use image::ImageDecoder;
    let umgewandelt;
    let bytes = if ist_heif(bytes) {
        umgewandelt = heif_zu_jpeg(bytes)?;
        &umgewandelt[..]
    } else {
        bytes
    };
    let r = image::ImageReader::new(std::io::Cursor::new(bytes)).with_guessed_format()?;
    let mut dec = r.into_decoder().map_err(|e| anyhow::anyhow!("Foto nicht lesbar ({e}). Bitte JPEG, PNG, WebP oder HEIC verwenden."))?;
    let orient = dec.orientation().unwrap_or(image::metadata::Orientation::NoTransforms);
    let mut img = DynamicImage::from_decoder(dec).map_err(|e| anyhow::anyhow!("Foto nicht lesbar: {e}"))?;
    img.apply_orientation(orient);
    Ok(img)
}

fn lum(p: &[u8]) -> f32 {
    0.299 * p[0] as f32 + 0.587 * p[1] as f32 + 0.114 * p[2] as f32
}
fn sat(p: &[u8]) -> f32 {
    let mx = p[0].max(p[1]).max(p[2]) as f32;
    let mn = p[0].min(p[1]).min(p[2]) as f32;
    if mx < 1.0 { 0.0 } else { (mx - mn) / mx }
}

fn otsu(werte: &[f32], lo: f32, hi: f32) -> f32 {
    let mut hist = [0f64; 256];
    for &v in werte {
        let b = (((v - lo) / (hi - lo)) * 255.0).clamp(0.0, 255.0) as usize;
        hist[b] += 1.0;
    }
    let total: f64 = hist.iter().sum();
    let sum: f64 = hist.iter().enumerate().map(|(i, h)| i as f64 * h).sum();
    let (mut wb, mut sb, mut best, mut thr) = (0.0, 0.0, -1.0, 128usize);
    for (i, h) in hist.iter().enumerate() {
        wb += h;
        if wb == 0.0 {
            continue;
        }
        let wf = total - wb;
        if wf == 0.0 {
            break;
        }
        sb += i as f64 * h;
        let mb = sb / wb;
        let mf = (sum - sb) / wf;
        let v = wb * wf * (mb - mf) * (mb - mf);
        if v > best {
            best = v;
            thr = i;
        }
    }
    lo + (thr as f32 + 0.5) / 255.0 * (hi - lo)
}

/// Zusammenhangskomponenten (8er-Nachbarschaft). Rückgabe: Beschriftung (0 = leer) und Größen
pub fn komponenten(maske: &[bool], w: usize, h: usize) -> (Vec<u32>, Vec<usize>) {
    let mut lab = vec![0u32; w * h];
    let mut groessen = vec![0usize];
    let mut stapel = Vec::new();
    for start in 0..w * h {
        if !maske[start] || lab[start] != 0 {
            continue;
        }
        let id = groessen.len() as u32;
        let mut n = 0;
        lab[start] = id;
        stapel.push(start);
        while let Some(i) = stapel.pop() {
            n += 1;
            let (x, y) = ((i % w) as i64, (i / w) as i64);
            for dy in -1..=1 {
                for dx in -1..=1 {
                    let (nx, ny) = (x + dx, y + dy);
                    if nx < 0 || ny < 0 || nx >= w as i64 || ny >= h as i64 {
                        continue;
                    }
                    let j = ny as usize * w + nx as usize;
                    if maske[j] && lab[j] == 0 {
                        lab[j] = id;
                        stapel.push(j);
                    }
                }
            }
        }
        groessen.push(n);
    }
    (lab, groessen)
}

/// Löcher füllen: alles, was nicht vom Rand aus erreichbar ist, wird Objekt
pub fn loecher_fuellen(m: &mut [bool], w: usize, h: usize) {
    let mut aussen = vec![false; w * h];
    let mut st = Vec::new();
    for x in 0..w {
        for y in [0, h - 1] {
            let i = y * w + x;
            if !m[i] && !aussen[i] { aussen[i] = true; st.push(i); }
        }
    }
    for y in 0..h {
        for x in [0, w - 1] {
            let i = y * w + x;
            if !m[i] && !aussen[i] { aussen[i] = true; st.push(i); }
        }
    }
    while let Some(i) = st.pop() {
        let (x, y) = (i % w, i / w);
        let nb = [(x.wrapping_sub(1), y), (x + 1, y), (x, y.wrapping_sub(1)), (x, y + 1)];
        for (nx, ny) in nb {
            if nx < w && ny < h {
                let j = ny * w + nx;
                if !m[j] && !aussen[j] {
                    aussen[j] = true;
                    st.push(j);
                }
            }
        }
    }
    for i in 0..w * h {
        if !aussen[i] {
            m[i] = true;
        }
    }
}

/// Quadratischer Max- bzw. Min-Filter (Dilatation/Erosion), getrennt nach Zeilen/Spalten
pub fn morph(m: &[bool], w: usize, h: usize, r: usize, dilat: bool) -> Vec<bool> {
    if r == 0 {
        return m.to_vec();
    }
    let ziel = dilat;
    let mut tmp = vec![!ziel; w * h];
    for y in 0..h {
        let mut letzte: i64 = -1_000_000;
        // Vorwärts: Abstand zum letzten Treffer
        let mut abst = vec![usize::MAX; w];
        for x in 0..w {
            if m[y * w + x] == ziel { letzte = x as i64; }
            abst[x] = (x as i64 - letzte) as usize;
        }
        letzte = 1_000_000;
        for x in (0..w).rev() {
            if m[y * w + x] == ziel { letzte = x as i64; }
            let d = abst[x].min((letzte - x as i64) as usize);
            tmp[y * w + x] = if d <= r { ziel } else { !ziel };
        }
    }
    let mut out = vec![!ziel; w * h];
    for x in 0..w {
        let mut letzte: i64 = -1_000_000;
        let mut abst = vec![usize::MAX; h];
        for y in 0..h {
            if tmp[y * w + x] == ziel { letzte = y as i64; }
            abst[y] = (y as i64 - letzte) as usize;
        }
        letzte = 1_000_000;
        for y in (0..h).rev() {
            if tmp[y * w + x] == ziel { letzte = y as i64; }
            let d = abst[y].min((letzte - y as i64) as usize);
            out[y * w + x] = if d <= r { ziel } else { !ziel };
        }
    }
    out
}

fn huelle(mut p: Vec<P2>) -> Vec<P2> {
    p.sort_by(|a, b| a.partial_cmp(b).unwrap());
    p.dedup();
    if p.len() < 3 {
        return p;
    }
    let cross = |o: P2, a: P2, b: P2| (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    let mut lo: Vec<P2> = Vec::new();
    for &q in &p {
        while lo.len() >= 2 && cross(lo[lo.len() - 2], lo[lo.len() - 1], q) <= 0.0 { lo.pop(); }
        lo.push(q);
    }
    let mut hi: Vec<P2> = Vec::new();
    for &q in p.iter().rev() {
        while hi.len() >= 2 && cross(hi[hi.len() - 2], hi[hi.len() - 1], q) <= 0.0 { hi.pop(); }
        hi.push(q);
    }
    lo.pop();
    hi.pop();
    lo.extend(hi);
    lo
}

fn viereck_flaeche(q: &[P2; 4]) -> f64 {
    let mut a = 0.0;
    for i in 0..4 {
        let (p, n) = (q[i], q[(i + 1) % 4]);
        a += p[0] * n[1] - n[0] * p[1];
    }
    a.abs() / 2.0
}

/// Größtes Viereck mit Ecken auf der konvexen Hülle (iterativ verbessert)
fn viereck(h: &[P2]) -> [P2; 4] {
    let ext = |f: &dyn Fn(P2) -> f64| *h.iter().max_by(|a, b| f(**a).partial_cmp(&f(**b)).unwrap()).unwrap();
    let mut q = [ext(&|p| -p[0] - p[1]), ext(&|p| p[0] - p[1]), ext(&|p| p[0] + p[1]), ext(&|p| -p[0] + p[1])];
    for _ in 0..6 {
        let mut besser = false;
        for k in 0..4 {
            let mut best = viereck_flaeche(&q);
            for &p in h {
                let mut t = q;
                t[k] = p;
                let a = viereck_flaeche(&t);
                if a > best + 1e-6 {
                    best = a;
                    q = t;
                    besser = true;
                }
            }
        }
        if !besser {
            break;
        }
    }
    q
}

/// Gerade durch Punkte (Hauptachse) → (Punkt, Richtung)
fn gerade(p: &[P2]) -> Option<(P2, P2)> {
    if p.len() < 5 {
        return None;
    }
    let n = p.len() as f64;
    let (mx, my) = (p.iter().map(|q| q[0]).sum::<f64>() / n, p.iter().map(|q| q[1]).sum::<f64>() / n);
    let (mut sxx, mut sxy, mut syy) = (0.0, 0.0, 0.0);
    for q in p {
        let (dx, dy) = (q[0] - mx, q[1] - my);
        sxx += dx * dx;
        sxy += dx * dy;
        syy += dy * dy;
    }
    let a = 0.5 * (2.0 * sxy).atan2(sxx - syy);
    Some(([mx, my], [a.cos(), a.sin()]))
}

fn schnitt(g1: (P2, P2), g2: (P2, P2)) -> Option<P2> {
    let (p, r) = g1;
    let (q, s) = g2;
    let den = r[0] * s[1] - r[1] * s[0];
    if den.abs() < 1e-9 {
        return None;
    }
    let t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den;
    Some([p[0] + r[0] * t, p[1] + r[1] * t])
}

/// Papier im Foto finden und entzerren
pub fn papier(img: &DynamicImage, format: &str) -> anyhow::Result<Papier> {
    let voll = img.to_rgb8();
    let (fw, fh) = voll.dimensions();
    let s = (1200.0 / fw.max(fh) as f64).min(1.0);
    let (w, h) = (((fw as f64) * s).round().max(1.0) as u32, ((fh as f64) * s).round().max(1.0) as u32);
    let klein = image::imageops::resize(&voll, w, h, image::imageops::FilterType::Triangle);
    let (w, h) = (w as usize, h as usize);
    let l: Vec<f32> = klein.pixels().map(|p| lum(&p.0)).collect();
    let t = otsu(&l, 0.0, 255.0);
    let mut m: Vec<bool> = klein.pixels().zip(&l).map(|(p, &v)| v > t && sat(&p.0) < 0.35).collect();
    m = morph(&morph(&m, w, h, 2, false), w, h, 2, true);
    let (lab, gr) = komponenten(&m, w, h);
    let (id, &groesse) = gr.iter().enumerate().skip(1).max_by_key(|x| x.1).ok_or_else(|| anyhow::anyhow!("Kein Blatt Papier gefunden."))?;
    if (groesse as f64) < 0.08 * (w * h) as f64 {
        anyhow::bail!("Kein Blatt Papier gefunden. Leg die Werkzeuge auf ein weißes Blatt vor einen dunkleren Untergrund und fotografiere es ganz.");
    }
    // Randpunkte des Blatts (je Zeile und Spalte die äußersten)
    let mut rand: Vec<P2> = Vec::new();
    for y in 0..h {
        let row = &lab[y * w..(y + 1) * w];
        if let (Some(a), Some(b)) = (row.iter().position(|&v| v == id as u32), row.iter().rposition(|&v| v == id as u32)) {
            rand.push([a as f64, y as f64]);
            rand.push([b as f64 + 1.0, y as f64]);
        }
    }
    for x in 0..w {
        let col = |y: usize| lab[y * w + x] == id as u32;
        if let (Some(a), Some(b)) = ((0..h).position(col), (0..h).rposition(col)) {
            rand.push([x as f64, a as f64]);
            rand.push([x as f64, b as f64 + 1.0]);
        }
    }
    let hl = huelle(rand.clone());
    if hl.len() < 4 {
        anyhow::bail!("Blattkanten nicht erkennbar.");
    }
    let q = viereck(&hl);
    // Kanten mit Ausgleichsgeraden verfeinern
    let mut gs = Vec::new();
    for k in 0..4 {
        let (a, b) = (q[k], q[(k + 1) % 4]);
        let d = [b[0] - a[0], b[1] - a[1]];
        let len = (d[0] * d[0] + d[1] * d[1]).sqrt();
        let tol = (len * 0.012).max(2.0);
        let nahe: Vec<P2> = rand.iter().copied().filter(|p| {
            let t = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / (len * len);
            let abst = ((p[0] - a[0]) * d[1] - (p[1] - a[1]) * d[0]).abs() / len;
            t > 0.1 && t < 0.9 && abst < tol
        }).collect();
        gs.push(gerade(&nahe).unwrap_or((a, [d[0] / len, d[1] / len])));
    }
    let mut ecken = q;
    for k in 0..4 {
        if let Some(p) = schnitt(gs[(k + 3) % 4], gs[k]) {
            if (p[0] - q[k][0]).hypot(p[1] - q[k][1]) < 0.05 * (w.max(h) as f64) {
                ecken[k] = p;
            }
        }
    }
    // Reihenfolge: oben links, oben rechts, unten rechts, unten links
    let c = [ecken.iter().map(|p| p[0]).sum::<f64>() / 4.0, ecken.iter().map(|p| p[1]).sum::<f64>() / 4.0];
    let mut e: Vec<P2> = ecken.to_vec();
    e.sort_by(|a, b| (a[1] - c[1]).atan2(a[0] - c[0]).partial_cmp(&(b[1] - c[1]).atan2(b[0] - c[0])).unwrap());
    // atan2 mit y nach unten: aufsteigend = im Uhrzeigersinn auf dem Bildschirm, Start bei oben links suchen
    let start = (0..4).min_by(|&i, &j| (e[i][0] + e[i][1]).partial_cmp(&(e[j][0] + e[j][1])).unwrap()).unwrap();
    e.rotate_left(start);
    let ecken: [P2; 4] = [e[0], e[1], e[2], e[3]].map(|p| [p[0] / s, p[1] / s]);
    let dist = |a: P2, b: P2| (a[0] - b[0]).hypot(a[1] - b[1]);
    let oben = (dist(ecken[0], ecken[1]) + dist(ecken[3], ecken[2])) / 2.0;
    let seite = (dist(ecken[0], ecken[3]) + dist(ecken[1], ecken[2])) / 2.0;
    let (kurz, lang) = papiermass(format);
    let (bw, bh) = if oben > seite { (lang, kurz) } else { (kurz, lang) };
    let bild = entzerren(&voll, &ecken, bw, bh);
    Ok(Papier { bild, breite_mm: bw, hoehe_mm: bh, ecken })
}

/// Homographie, die (0,0),(w,0),(w,h),(0,h) auf die vier Punkte abbildet
fn homographie(dst: &[P2; 4], w: f64, h: f64) -> [f64; 9] {
    let src = [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]];
    let mut a = [[0.0f64; 9]; 8];
    for i in 0..4 {
        let (x, y) = (src[i][0], src[i][1]);
        let (u, v) = (dst[i][0], dst[i][1]);
        a[2 * i] = [x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, u];
        a[2 * i + 1] = [0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, v];
    }
    for c in 0..8 {
        let p = (c..8).max_by(|&i, &j| a[i][c].abs().partial_cmp(&a[j][c].abs()).unwrap()).unwrap();
        a.swap(c, p);
        let d = a[c][c];
        if d.abs() < 1e-12 {
            continue;
        }
        for k in c..9 {
            a[c][k] /= d;
        }
        for r in 0..8 {
            if r != c {
                let f = a[r][c];
                for k in c..9 {
                    a[r][k] -= f * a[c][k];
                }
            }
        }
    }
    [a[0][8], a[1][8], a[2][8], a[3][8], a[4][8], a[5][8], a[6][8], a[7][8], 1.0]
}

fn entzerren(voll: &RgbImage, ecken: &[P2; 4], bw: f64, bh: f64) -> RgbImage {
    let (ow, oh) = ((bw * PX_MM).round() as u32, (bh * PX_MM).round() as u32);
    let hm = homographie(ecken, ow as f64, oh as f64);
    let (fw, fh) = voll.dimensions();
    let mut out = RgbImage::new(ow, oh);
    for y in 0..oh {
        for x in 0..ow {
            let (xf, yf) = (x as f64 + 0.5, y as f64 + 0.5);
            let z = hm[6] * xf + hm[7] * yf + hm[8];
            let u = (hm[0] * xf + hm[1] * yf + hm[2]) / z - 0.5;
            let v = (hm[3] * xf + hm[4] * yf + hm[5]) / z - 0.5;
            let (x0, y0) = (u.floor(), v.floor());
            let (ax, ay) = (u - x0, v - y0);
            let px = |xx: f64, yy: f64| {
                let xi = (xx as i64).clamp(0, fw as i64 - 1) as u32;
                let yi = (yy as i64).clamp(0, fh as i64 - 1) as u32;
                voll.get_pixel(xi, yi).0
            };
            let (p00, p10, p01, p11) = (px(x0, y0), px(x0 + 1.0, y0), px(x0, y0 + 1.0), px(x0 + 1.0, y0 + 1.0));
            let mut c = [0u8; 3];
            for k in 0..3 {
                let v = (p00[k] as f64 * (1.0 - ax) + p10[k] as f64 * ax) * (1.0 - ay) + (p01[k] as f64 * (1.0 - ax) + p11[k] as f64 * ax) * ay;
                c[k] = v.round().clamp(0.0, 255.0) as u8;
            }
            out.put_pixel(x, y, image::Rgb(c));
        }
    }
    out
}

/// Objektwahrscheinlichkeit je Pixel (0..1) auf dem entzerrten Blatt: dunkler oder farbiger als das Papier
pub fn objektkarte(b: &RgbImage) -> Vec<f32> {
    let (w, h) = (b.width() as usize, b.height() as usize);
    let l: Vec<f32> = b.pixels().map(|p| lum(&p.0)).collect();
    let s: Vec<f32> = b.pixels().map(|p| sat(&p.0)).collect();
    let t = otsu(&l, 0.0, 255.0);
    // Hintergrund (ungleichmäßiges Licht) als quadratische Fläche anpassen
    let mut ata = [[0f64; 6]; 6];
    let mut atb = [0f64; 6];
    let mut s_pap = Vec::new();
    for y in (0..h).step_by(3) {
        for x in (0..w).step_by(3) {
            let i = y * w + x;
            if l[i] > t {
                let (u, v) = (x as f64 / w as f64 - 0.5, y as f64 / h as f64 - 0.5);
                let f = [1.0, u, v, u * u, u * v, v * v];
                for r in 0..6 {
                    for c in 0..6 {
                        ata[r][c] += f[r] * f[c];
                    }
                    atb[r] += f[r] * l[i] as f64;
                }
                s_pap.push(s[i]);
            }
        }
    }
    let koef = loesen(ata, atb).unwrap_or([t as f64 + 40.0, 0.0, 0.0, 0.0, 0.0, 0.0]);
    s_pap.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let s0 = s_pap.get(s_pap.len() / 2).copied().unwrap_or(0.05);
    let mut out = vec![0f32; w * h];
    for y in 0..h {
        for x in 0..w {
            let (u, v) = (x as f64 / w as f64 - 0.5, y as f64 / h as f64 - 0.5);
            let bg = (koef[0] + koef[1] * u + koef[2] * v + koef[3] * u * u + koef[4] * u * v + koef[5] * v * v).max(30.0) as f32;
            let i = y * w + x;
            let dunkel = (1.0 - l[i] / bg).clamp(0.0, 1.0);
            let farbe = ((s[i] - s0) * 1.4).clamp(0.0, 1.0);
            out[i] = dunkel.max(farbe);
        }
    }
    out
}

fn loesen(mut a: [[f64; 6]; 6], mut b: [f64; 6]) -> Option<[f64; 6]> {
    for c in 0..6 {
        let p = (c..6).max_by(|&i, &j| a[i][c].abs().partial_cmp(&a[j][c].abs()).unwrap())?;
        a.swap(c, p);
        b.swap(c, p);
        if a[c][c].abs() < 1e-9 {
            return None;
        }
        for r in 0..6 {
            if r != c {
                let f = a[r][c] / a[c][c];
                for k in c..6 {
                    a[r][k] -= f * a[c][k];
                }
                b[r] -= f * b[c];
            }
        }
    }
    Some(std::array::from_fn(|i| b[i] / a[i][i]))
}

/// Maske → Werkzeugkandidaten (zweistufige Schwelle). `empfindlichkeit` 0..1 (0,5 = normal)
pub fn werkzeuge(karte: &[f32], w: usize, h: usize, empfindlichkeit: f64, min_flaeche_mm2: f64) -> (Vec<bool>, f32) {
    let f = (1.5 - empfindlichkeit) as f32;
    let hoch = (otsu(karte, 0.0, 1.0).clamp(0.15, 0.45) * f).clamp(0.08, 0.7);
    let tief = (0.17 * f).clamp(0.06, hoch);
    let rand = (RAND_MM * PX_MM) as usize;
    let innen = |i: usize| {
        let (x, y) = (i % w, i / w);
        x >= rand && y >= rand && x + rand < w && y + rand < h
    };
    let mut m: Vec<bool> = (0..w * h).map(|i| innen(i) && karte[i] > tief).collect();
    m = morph(&morph(&m, w, h, 1, false), w, h, 1, true); // Rauschen weg
    m = morph(&morph(&m, w, h, 3, true), w, h, 3, false); // Lücken schließen
    let min_px = (min_flaeche_mm2 * PX_MM * PX_MM) as usize;
    let (lab, gr) = komponenten(&m, w, h);
    // je Komponente: Anteil kräftiger Pixel und mittlere Stärke
    let mut stark = vec![0usize; gr.len()];
    let mut summe = vec![0f64; gr.len()];
    for i in 0..w * h {
        let l = lab[i] as usize;
        if l > 0 {
            summe[l] += karte[i] as f64;
            if karte[i] > hoch {
                stark[l] += 1;
            }
        }
    }
    let behalten: Vec<bool> = (0..gr.len()).map(|l| {
        l > 0 && gr[l] >= min_px && (stark[l] as f64 >= 0.03 * gr[l] as f64 || summe[l] / gr[l] as f64 > (tief as f64) * 1.7)
    }).collect();
    for i in 0..w * h {
        m[i] = behalten[lab[i] as usize];
    }
    loecher_fuellen(&mut m, w, h);
    (m, hoch)
}

/// Umrisse aller Komponenten einer Maske (Pixelraster → mm, Ursprung oben links)
pub fn umrisse(m: &[bool], w: usize, h: usize, versatz: P2, quelle: &str) -> Vec<Umriss> {
    let (lab, gr) = komponenten(m, w, h);
    let mut out = Vec::new();
    for id in 1..gr.len() {
        let (mut x0, mut y0, mut x1, mut y1) = (w, h, 0, 0);
        for i in 0..w * h {
            if lab[i] == id as u32 {
                let (x, y) = (i % w, i / w);
                x0 = x0.min(x); y0 = y0.min(y); x1 = x1.max(x); y1 = y1.max(y);
            }
        }
        if x1 < x0 {
            continue;
        }
        let rand_px = (RAND_MM * PX_MM) as usize + 2;
        let am_rand = x0 <= rand_px || y0 <= rand_px || x1 + rand_px >= w || y1 + rand_px >= h;
        let maske: Vec<bool> = lab.iter().map(|&v| v == id as u32).collect();
        if let Some(p) = kontur(&maske, w, h, x0, y0, x1, y1) {
            let pts: Vec<P2> = p.iter().map(|q| [q[0] / PX_MM + versatz[0], q[1] / PX_MM + versatz[1]]).collect();
            out.push(umriss_aus(pts, quelle, am_rand));
        }
    }
    out
}

pub fn umriss_aus(pts: Vec<P2>, quelle: &str, am_rand: bool) -> Umriss {
    let pts = rdp_ring(&pts, 0.12);
    let mut a = 0.0;
    let mut g = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
    for i in 0..pts.len() {
        let (p, q) = (pts[i], pts[(i + 1) % pts.len()]);
        a += p[0] * q[1] - q[0] * p[1];
        g = [g[0].min(p[0]), g[1].min(p[1]), g[2].max(p[0]), g[3].max(p[1])];
    }
    Umriss { id: 0, name: String::new(), punkte: pts, flaeche: a.abs() / 2.0, grenzen: g, quelle: quelle.into(), am_rand }
}

/// Äußere Kontur einer Maske per Marching Squares auf leicht geglättetem Feld (Subpixel)
pub fn kontur(m: &[bool], w: usize, h: usize, x0: usize, y0: usize, x1: usize, y1: usize) -> Option<Vec<P2>> {
    let pad = 2usize;
    let (bx, by) = (x0.saturating_sub(pad), y0.saturating_sub(pad));
    let (ex, ey) = ((x1 + pad + 1).min(w), (y1 + pad + 1).min(h));
    let (cw, ch) = (ex - bx + 2, ey - by + 2); // +1 Leerrand auf jeder Seite
    let mut f = vec![0f32; cw * ch];
    for y in by..ey {
        for x in bx..ex {
            if m[y * w + x] {
                f[(y - by + 1) * cw + (x - bx + 1)] = 1.0;
            }
        }
    }
    // 3×3 Weichzeichnen
    let mut g = vec![0f32; cw * ch];
    for y in 1..ch - 1 {
        for x in 1..cw - 1 {
            let mut s = 0.0;
            for dy in 0..3 {
                for dx in 0..3 {
                    let k = [1.0, 2.0, 1.0][dx] * [1.0, 2.0, 1.0][dy];
                    s += k * f[(y + dy - 1) * cw + (x + dx - 1)];
                }
            }
            g[y * cw + x] = s / 16.0;
        }
    }
    let wert = |x: usize, y: usize| g[y * cw + x];
    // Kantenpunkte: Schlüssel = (waagerecht?, x, y)
    let mut segs: Vec<((bool, usize, usize), (bool, usize, usize))> = Vec::new();
    for y in 0..ch - 1 {
        for x in 0..cw - 1 {
            let (a, b, c, d) = (wert(x, y), wert(x + 1, y), wert(x + 1, y + 1), wert(x, y + 1));
            let idx = (a >= 0.5) as u8 | ((b >= 0.5) as u8) << 1 | ((c >= 0.5) as u8) << 2 | ((d >= 0.5) as u8) << 3;
            let top = (true, x, y);
            let bot = (true, x, y + 1);
            let left = (false, x, y);
            let right = (false, x + 1, y);
            let mitte = (a + b + c + d) / 4.0 >= 0.5;
            match idx {
                0 | 15 => {}
                1 | 14 => segs.push((left, top)),
                2 | 13 => segs.push((top, right)),
                3 | 12 => segs.push((left, right)),
                4 | 11 => segs.push((right, bot)),
                6 | 9 => segs.push((top, bot)),
                7 | 8 => segs.push((left, bot)),
                5 => if mitte { segs.push((left, bot)); segs.push((top, right)); } else { segs.push((left, top)); segs.push((right, bot)); },
                10 => if mitte { segs.push((left, top)); segs.push((right, bot)); } else { segs.push((left, bot)); segs.push((top, right)); },
                _ => {}
            }
        }
    }
    let punkt = |k: (bool, usize, usize)| -> P2 {
        let (hz, x, y) = k;
        let (va, vb, ox, oy) = if hz { (wert(x, y), wert(x + 1, y), 1.0, 0.0) } else { (wert(x, y), wert(x, y + 1), 0.0, 1.0) };
        let t = if (vb - va).abs() < 1e-6 { 0.5 } else { ((0.5 - va) / (vb - va)).clamp(0.0, 1.0) as f64 };
        // Feldindex → Pixelmitte im Gesamtbild
        let px = x as f64 + ox * t + bx as f64 - 1.0 + 0.5;
        let py = y as f64 + oy * t + by as f64 - 1.0 + 0.5;
        [px, py]
    };
    let mut nach: std::collections::HashMap<(bool, usize, usize), Vec<usize>> = Default::default();
    for (i, s) in segs.iter().enumerate() {
        nach.entry(s.0).or_default().push(i);
        nach.entry(s.1).or_default().push(i);
    }
    let mut benutzt = vec![false; segs.len()];
    let mut best: Option<(f64, Vec<P2>)> = None;
    for start in 0..segs.len() {
        if benutzt[start] {
            continue;
        }
        let mut ring = Vec::new();
        let mut cur = start;
        let mut k = segs[start].0;
        loop {
            benutzt[cur] = true;
            ring.push(punkt(k));
            let s = segs[cur];
            let next_k = if s.0 == k { s.1 } else { s.0 };
            k = next_k;
            let Some(nx) = nach.get(&k).and_then(|l| l.iter().copied().find(|&j| !benutzt[j])) else { break };
            cur = nx;
        }
        if ring.len() < 8 {
            continue;
        }
        let mut a = 0.0;
        for i in 0..ring.len() {
            let (p, q) = (ring[i], ring[(i + 1) % ring.len()]);
            a += p[0] * q[1] - q[0] * p[1];
        }
        if best.as_ref().is_none_or(|b| a.abs() > b.0) {
            best = Some((a.abs(), ring));
        }
    }
    best.map(|b| b.1)
}

/// Ramer-Douglas-Peucker für geschlossene Ringe
pub fn rdp_ring(p: &[P2], eps: f64) -> Vec<P2> {
    if p.len() < 8 {
        return p.to_vec();
    }
    // am weitesten entfernte Punkte als Anker
    let far = (1..p.len()).max_by(|&i, &j| {
        let d = |k: usize| (p[k][0] - p[0][0]).hypot(p[k][1] - p[0][1]);
        d(i).partial_cmp(&d(j)).unwrap()
    }).unwrap();
    let mut a = rdp(&p[0..=far], eps);
    let mut zweite: Vec<P2> = p[far..].to_vec();
    zweite.push(p[0]);
    let b = rdp(&zweite, eps);
    a.pop();
    a.extend_from_slice(&b[..b.len() - 1]);
    a
}

fn rdp(p: &[P2], eps: f64) -> Vec<P2> {
    if p.len() < 3 {
        return p.to_vec();
    }
    let (a, b) = (p[0], p[p.len() - 1]);
    let d = [b[0] - a[0], b[1] - a[1]];
    let l = d[0].hypot(d[1]).max(1e-12);
    let (mut idx, mut dmax) = (0, 0.0);
    for (i, q) in p.iter().enumerate().take(p.len() - 1).skip(1) {
        let dist = ((q[0] - a[0]) * d[1] - (q[1] - a[1]) * d[0]).abs() / l;
        if dist > dmax {
            dmax = dist;
            idx = i;
        }
    }
    if dmax > eps {
        let mut l1 = rdp(&p[..=idx], eps);
        let l2 = rdp(&p[idx..], eps);
        l1.pop();
        l1.extend(l2);
        l1
    } else {
        vec![a, b]
    }
}
