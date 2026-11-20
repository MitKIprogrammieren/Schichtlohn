//! Höhenfelder (Lithophane, Relief) als geschlossene Körper, aufgeteilt in Kacheln, die aufs Druckbett passen.
use crate::mesh::{Mesh, V3};

#[derive(Clone)]
pub struct Grid {
    pub nx: usize,
    pub ny: usize,
    /// Abstand der Gitterpunkte in mm
    pub dx: f64,
    pub dy: f64,
    /// Höhe (mm) je Gitterpunkt, Zeile 0 = unten (y = 0)
    pub h: Vec<f64>,
}

impl Grid {
    pub fn at(&self, x: usize, y: usize) -> f64 {
        self.h[y * self.nx + x]
    }
    pub fn width(&self) -> f64 {
        (self.nx - 1) as f64 * self.dx
    }
    pub fn height(&self) -> f64 {
        (self.ny - 1) as f64 * self.dy
    }
    pub fn max_h(&self) -> f64 {
        self.h.iter().cloned().fold(0.0, f64::max)
    }
    /// Rand mit fester Höhe setzen
    pub fn set_border(&mut self, size_mm: f64, height: f64) {
        if size_mm <= 0.0 {
            return;
        }
        for y in 0..self.ny {
            for x in 0..self.nx {
                let px = x as f64 * self.dx;
                let py = y as f64 * self.dy;
                let d = px.min(py).min(self.width() - px).min(self.height() - py);
                if d < size_mm - 1e-9 {
                    self.h[y * self.nx + x] = height;
                }
            }
        }
    }
    /// Spiegeln in X (z. B. für Innen-Lithophane)
    pub fn mirror_x(&mut self) {
        for y in 0..self.ny {
            self.h[y * self.nx..(y + 1) * self.nx].reverse();
        }
    }

    /// Geschlossener Körper für den Bereich [x0..=x1] × [y0..=y1] (Gitterindizes).
    pub fn solid(&self, x0: usize, x1: usize, y0: usize, y1: usize) -> Mesh {
        let mut m = Mesh::new();
        let p = |x: usize, y: usize, z: f64| -> V3 { [x as f64 * self.dx, y as f64 * self.dy, z] };
        let top = |x: usize, y: usize| p(x, y, self.at(x, y));
        // Oberseite
        for y in y0..y1 {
            for x in x0..x1 {
                let (a, b, c, d) = (top(x, y), top(x + 1, y), top(x + 1, y + 1), top(x, y + 1));
                // Diagonale entlang der kleineren Höhendifferenz
                if (a[2] - c[2]).abs() <= (b[2] - d[2]).abs() {
                    m.push(a, b, c);
                    m.push(a, c, d);
                } else {
                    m.push(a, b, d);
                    m.push(b, c, d);
                }
            }
        }
        // Randschleife gegen den Uhrzeigersinn
        let mut ring: Vec<(usize, usize)> = Vec::new();
        for x in x0..x1 {
            ring.push((x, y0));
        }
        for y in y0..y1 {
            ring.push((x1, y));
        }
        for x in (x0 + 1..=x1).rev() {
            ring.push((x, y1));
        }
        for y in (y0 + 1..=y1).rev() {
            ring.push((x0, y));
        }
        let center: V3 = [
            (x0 + x1) as f64 * 0.5 * self.dx,
            (y0 + y1) as f64 * 0.5 * self.dy,
            0.0,
        ];
        for i in 0..ring.len() {
            let (px, py) = ring[i];
            let (qx, qy) = ring[(i + 1) % ring.len()];
            let p0 = p(px, py, 0.0);
            let q0 = p(qx, qy, 0.0);
            m.quad(p0, q0, top(qx, qy), top(px, py));
            m.push(center, q0, p0);
        }
        m
    }

    /// Aufteilen in Kacheln mit max. Kantenlänge `max_w` × `max_h` (mm).
    /// Liefert (Spalte, Zeile, Netz).
    pub fn tiles(&self, max_w: f64, max_h: f64) -> Vec<(usize, usize, Mesh)> {
        let cols = ((self.width() / max_w).ceil() as usize).max(1);
        let rows = ((self.height() / max_h).ceil() as usize).max(1);
        let split = |n: usize, parts: usize| -> Vec<usize> {
            (0..=parts).map(|i| (i * (n - 1) + parts / 2) / parts).collect()
        };
        let xs = split(self.nx, cols);
        let ys = split(self.ny, rows);
        let mut out = Vec::new();
        for r in 0..rows {
            for c in 0..cols {
                if xs[c + 1] > xs[c] && ys[r + 1] > ys[r] {
                    out.push((c, r, self.solid(xs[c], xs[c + 1], ys[r], ys[r + 1])));
                }
            }
        }
        out
    }

    /// verkleinerte Kopie für die Vorschau
    pub fn downsample(&self, max_points: usize) -> Grid {
        let step = (((self.nx * self.ny) as f64 / max_points as f64).sqrt().ceil() as usize).max(1);
        if step == 1 {
            return self.clone();
        }
        let nx = (self.nx - 1) / step + 1;
        let ny = (self.ny - 1) / step + 1;
        let mut h = Vec::with_capacity(nx * ny);
        for y in 0..ny {
            for x in 0..nx {
                h.push(self.at((x * step).min(self.nx - 1), (y * step).min(self.ny - 1)));
            }
        }
        Grid { nx, ny, dx: self.width() / (nx - 1) as f64, dy: self.height() / (ny - 1) as f64, h }
    }
}

/// Helligkeit 0..1 aus Bild, auf nx × ny umgerechnet; Zeile 0 = unten.
pub fn luminance(img: &image::DynamicImage, nx: usize, ny: usize) -> Vec<f64> {
    let g = img.to_luma16();
    let r = image::imageops::resize(&g, nx as u32, ny as u32, image::imageops::FilterType::Triangle);
    let mut out = vec![0.0; nx * ny];
    for y in 0..ny {
        for x in 0..nx {
            let v = r.get_pixel(x as u32, (ny - 1 - y) as u32).0[0] as f64 / 65535.0;
            out[y * nx + x] = v;
        }
    }
    out
}

pub fn box_blur(v: &mut [f64], nx: usize, ny: usize, radius: usize) {
    if radius == 0 {
        return;
    }
    let mut tmp = v.to_vec();
    blur_pass(v, &mut tmp, nx, ny, radius, true);
    blur_pass(&tmp, v, nx, ny, radius, false);
}

fn blur_pass(src: &[f64], dst: &mut [f64], nx: usize, ny: usize, radius: usize, horizontal: bool) {
    {
        for y in 0..ny {
            for x in 0..nx {
                let mut s = 0.0;
                let mut n = 0.0;
                for k in -(radius as i64)..=(radius as i64) {
                    let (xx, yy) = if horizontal { (x as i64 + k, y as i64) } else { (x as i64, y as i64 + k) };
                    if xx >= 0 && yy >= 0 && (xx as usize) < nx && (yy as usize) < ny {
                        s += src[yy as usize * nx + xx as usize];
                        n += 1.0;
                    }
                }
                dst[y * nx + x] = s / n;
            }
        }
    }
}
