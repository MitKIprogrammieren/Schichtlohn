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

    /// Kacheln mit Puzzle-Kante. Nasen greifen in die Nachbarkachel, dazwischen bleibt ein Spalt von `gap` mm.
    /// Liefert (Spalte, Zeile, Netz).
    pub fn puzzle_tiles(&self, max_w: f64, max_h: f64, gap: f64) -> Vec<(usize, usize, Mesh)> {
        let (cx, cy) = (self.nx - 1, self.ny - 1); // Zellen
        // Nasengröße aus der Kachelgröße, Platz für Nasen in der Kachelgröße freihalten
        let r = (max_w.min(max_h) / 10.0).clamp(4.0, 18.0);
        let cols = ((self.width() / (max_w - 4.2 * r)).ceil() as usize).max(1);
        let rows = ((self.height() / (max_h - 4.2 * r)).ceil() as usize).max(1);
        let split = |n: usize, parts: usize| -> Vec<usize> { (0..=parts).map(|i| (i * n + parts / 2) / parts).collect() };
        let xs = split(cx, cols);
        let ys = split(cy, rows);
        let col_of = |i: usize| xs.iter().rposition(|&x| x <= i).unwrap().min(cols - 1);
        let row_of = |j: usize| ys.iter().rposition(|&y| y <= j).unwrap().min(rows - 1);
        let mut tile: Vec<i32> = (0..cx * cy).map(|k| (row_of(k / cx) * cols + col_of(k % cx)) as i32).collect();
        let (dx, dy) = (self.dx, self.dy);
        // Nase: Kopf (Kreis, Radius r) im Abstand 1,15 r von der Kante, Hals 0,9 r breit
        let in_knob = |u: f64, v: f64| -> bool {
            // u: Abstand senkrecht zur Kante (in die Nachbarkachel), v: längs der Kante relativ zur Mitte
            if u < 0.0 {
                return false;
            }
            let head = (u - 1.15 * r).powi(2) + v * v <= r * r;
            let neck = u <= 1.15 * r && v.abs() <= 0.45 * r;
            head || neck
        };
        // senkrechte Kanten
        for c in 1..cols {
            let x_line = xs[c] as f64 * dx;
            for rr in 0..rows {
                let (y0, y1) = (ys[rr] as f64 * dy, ys[rr + 1] as f64 * dy);
                if y1 - y0 < 3.2 * r {
                    continue;
                }
                let ym = (y0 + y1) * 0.5;
                let right = (c + rr) % 2 == 0; // Nase zeigt nach rechts (von Kachel links)
                let (giver, recv) = if right { (rr * cols + c - 1, rr * cols + c) } else { (rr * cols + c, rr * cols + c - 1) };
                for k in 0..tile.len() {
                    if tile[k] != recv as i32 {
                        continue;
                    }
                    let (px, py) = (((k % cx) as f64 + 0.5) * dx, ((k / cx) as f64 + 0.5) * dy);
                    let u = if right { px - x_line } else { x_line - px };
                    if in_knob(u, py - ym) {
                        tile[k] = giver as i32;
                    }
                }
            }
        }
        // waagerechte Kanten
        for rr in 1..rows {
            let y_line = ys[rr] as f64 * dy;
            for c in 0..cols {
                let (x0, x1) = (xs[c] as f64 * dx, xs[c + 1] as f64 * dx);
                if x1 - x0 < 3.2 * r {
                    continue;
                }
                let xm = (x0 + x1) * 0.5;
                let up = (c + rr) % 2 == 1;
                let (giver, recv) = if up { ((rr - 1) * cols + c, rr * cols + c) } else { (rr * cols + c, (rr - 1) * cols + c) };
                for k in 0..tile.len() {
                    if tile[k] != recv as i32 {
                        continue;
                    }
                    let (px, py) = (((k % cx) as f64 + 0.5) * dx, ((k / cx) as f64 + 0.5) * dy);
                    let u = if up { py - y_line } else { y_line - py };
                    if in_knob(u, px - xm) {
                        tile[k] = giver as i32;
                    }
                }
            }
        }
        // Spalt: Zellen der höheren Kachel an der Grenze zu einer niedrigeren entfernen
        let passes = ((gap / dx.min(dy)).ceil() as usize).max(1);
        let nb = |k: usize| -> Vec<usize> {
            let (i, j) = (k % cx, k / cx);
            let mut v = Vec::with_capacity(4);
            if i > 0 { v.push(k - 1); }
            if i + 1 < cx { v.push(k + 1); }
            if j > 0 { v.push(k - cx); }
            if j + 1 < cy { v.push(k + cx); }
            v
        };
        let mut frontier: Vec<usize> = (0..tile.len())
            .filter(|&k| tile[k] >= 0 && nb(k).iter().any(|&n| tile[n] >= 0 && tile[n] < tile[k]))
            .collect();
        let mut owner: Vec<i32> = vec![-1; tile.len()];
        for pass in 0..passes {
            for &k in &frontier {
                owner[k] = tile[k];
                tile[k] = -1;
            }
            if pass + 1 == passes {
                break;
            }
            let mut next = Vec::new();
            for &k in &frontier {
                for n in nb(k) {
                    if tile[n] >= 0 && tile[n] == owner[k] && !next.contains(&n) {
                        next.push(n);
                    }
                }
            }
            frontier = next;
        }
        let mut out = Vec::new();
        for t in 0..cols * rows {
            let m = self.mask_solid(&tile, t as i32);
            if !m.is_empty() {
                out.push((t % cols, t / cols, m));
            }
        }
        out
    }

    /// Körper aus allen Zellen mit `tile[k] == t` (Oberseite, Unterseite, Wände an den Zellkanten)
    fn mask_solid(&self, tile: &[i32], t: i32) -> Mesh {
        let cx = self.nx - 1;
        let cy = self.ny - 1;
        let mut m = Mesh::new();
        let p = |x: usize, y: usize, z: f64| -> V3 { [x as f64 * self.dx, y as f64 * self.dy, z] };
        let top = |x: usize, y: usize| p(x, y, self.at(x, y));
        let inside = |i: i64, j: i64| i >= 0 && j >= 0 && (i as usize) < cx && (j as usize) < cy && tile[j as usize * cx + i as usize] == t;
        for j in 0..cy {
            for i in 0..cx {
                if tile[j * cx + i] != t {
                    continue;
                }
                let (a, b, c, d) = (top(i, j), top(i + 1, j), top(i + 1, j + 1), top(i, j + 1));
                m.push(a, b, c);
                m.push(a, c, d);
                let (a0, b0, c0, d0) = (p(i, j, 0.0), p(i + 1, j, 0.0), p(i + 1, j + 1, 0.0), p(i, j + 1, 0.0));
                m.push(a0, c0, b0);
                m.push(a0, d0, c0);
                let (ii, jj) = (i as i64, j as i64);
                if !inside(ii, jj - 1) {
                    m.quad(a0, b0, b, a);
                }
                if !inside(ii + 1, jj) {
                    m.quad(b0, c0, c, b);
                }
                if !inside(ii, jj + 1) {
                    m.quad(c0, d0, d, c);
                }
                if !inside(ii - 1, jj) {
                    m.quad(d0, a0, a, d);
                }
            }
        }
        m
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
