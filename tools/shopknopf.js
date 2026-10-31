/* „An SchichtLohn senden“: läuft auf einer vom Nutzer selbst geöffneten Shopseite (Lesezeichen oder iPhone-Kurzbefehl).
   Liest Produktname, Varianten und Preise aus der Seite und öffnet SchichtLohn mit diesen Daten (?shop=…).
   Es wird nichts im Hintergrund abgerufen – außer bei Shopify-Shops die Produktdaten derselben Seite (ein Aufruf).
   Platzhalter: __BASE__ (Adresse der SchichtLohn-App), __KURZ__ (1 = iPhone-Kurzbefehl, gibt die Adresse per completion() zurück).
   Diese Datei ist die lesbare Quelle; die App baut daraus den Knopf (SL_SHOPKNOPF in app/index.html, per tools/shopknopf.py). */
(async () => {
  const B = "__BASE__", KURZ = __KURZ__;
  const DG = { v: 4, h: location.hostname, p: location.pathname.slice(0, 80) };  /* was der Knopf gesehen hat – geht nur mit, wenn nichts gefunden wurde */
  const num = (v) => {
    if (v == null || v === "") return 0;
    if (typeof v === "number") return v;
    let s = String(v).replace(/[^\d.,]/g, "");
    if (/,\d{1,2}$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
    else s = s.replace(/,(?=\d{3}\b)/g, "").replace(/,/g, ".");
    return parseFloat(s) || 0;
  };
  const meta = (k) => { const m = document.querySelector('meta[property="' + k + '"],meta[name="' + k + '"],meta[itemprop="' + k + '"]'); return m ? m.getAttribute("content") || "" : ""; };
  let T = meta("og:title") || document.title || "", C = "", V = [], M = "";
  const seen = new Set();
  const add = (n, p, np, sku, ean) => {
    p = num(p); np = num(np);
    if (!(p > 0)) return;
    n = String(n || "").replace(/\s+/g, " ").trim();
    const k = n + "|" + p;
    if (seen.has(k)) return;
    seen.add(k);
    V.push({ n, p: Math.round(p * 100) / 100, np: np > p ? Math.round(np * 100) / 100 : 0, s: sku ? String(sku) : "", e: ean ? String(ean) : "" });
  };
  const walk = (o, f, d) => {
    if (!o || typeof o !== "object" || (d = d || 0) > 12) return;
    if (Array.isArray(o)) { o.forEach((x) => walk(x, f, d + 1)); return; }
    f(o);
    for (const k in o) if (o[k] && typeof o[k] === "object") walk(o[k], f, d + 1);
  };

  /* 1. Shopify: Produktdaten derselben Seite (genaueste Quelle, mit allen Varianten) */
  /* bei /products/… immer versuchen: der iPhone-Kurzbefehl sieht window.Shopify nicht, und neuere Shops laden nicht mehr von cdn.shopify.com */
  if (/\/products\/[^/?#]+/.test(location.pathname)) {
    try {
      const r = await fetch(location.pathname.match(/^.*\/products\/[^/?#]+/)[0] + ".js", { credentials: "include" });
      DG.sf = r.status + " " + (r.headers.get("content-type") || "").slice(0, 30);
      if (r.ok && /json|javascript/.test(r.headers.get("content-type") || "")) {
        const p = await r.json();
        T = p.title || T;
        M = p.vendor || M;
        C = (window.Shopify && Shopify.currency && Shopify.currency.active) || meta("og:price:currency") || meta("product:price:currency") || "";
        (p.variants || []).forEach((v) => add(v.title === "Default Title" ? "" : v.title, v.price / 100, (v.compare_at_price || 0) / 100, v.sku, v.barcode));
        DG.sv = (p.variants || []).length;
      }
    } catch (e) { DG.se = String(e && e.message || e).slice(0, 80); }
  }

  /* 2. Strukturierte Produktdaten (JSON-LD), wie sie Suchmaschinen lesen */
  if (!V.length) {
    document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => {
      let j;
      try { j = JSON.parse(s.textContent); } catch (e) { return; }
      walk(j, (o) => {
        const t = [].concat(o["@type"] || []);
        if (t.includes("ProductGroup") && o.name) T = o.name;
        if (!t.includes("Product")) return;
        if (o.brand && !M) M = typeof o.brand === "string" ? o.brand : (o.brand.name || "");
        [].concat(o.offers || []).forEach((x) => {
          if (!x) return;
          const liste = x.offers ? [].concat(x.offers) : [x];
          liste.forEach((y) => {
            if (!y) return;
            if (y.priceCurrency) C = y.priceCurrency;
            const ps = y.priceSpecification ? [].concat(y.priceSpecification) : [];
            const preis = y.price != null ? y.price : (y.lowPrice != null && (y.highPrice == null || num(y.highPrice) === num(y.lowPrice)) ? y.lowPrice : (ps[0] && ps[0].price));
            const normal = (ps.find((q) => /ListPrice|StrikethroughPrice/i.test(q.priceType || "")) || {}).price;
            add(y.name || o.name, preis, normal, y.sku || o.sku, y.gtin13 || y.gtin || o.gtin13 || o.gtin || o.gtin12);
          });
        });
      });
    });
  }

  /* 3. Seitendaten moderner Shops (z. B. Next.js): größte Liste von Einträgen mit Name und Preis */
  if (V.length < 2) {
    const PK = /^(price|salePrice|sellingPrice|finalPrice|currentPrice|priceAmount|discountPrice)$/i, NK = ["name", "title", "skuName", "variantName", "optionName", "displayName", "color", "colorName"];
    let best = null;
    document.querySelectorAll('script#__NEXT_DATA__,script[type="application/json"]').forEach((s) => {
      let j;
      try { j = JSON.parse(s.textContent); } catch (e) { return; }
      walk(j, (o) => {
        for (const k in o) {
          const a = o[k];
          if (!Array.isArray(a) || a.length < 2) continue;
          const ok = a.filter((x) => x && typeof x === "object" && Object.keys(x).some((q) => PK.test(q)) && NK.some((q) => typeof x[q] === "string"));
          if (ok.length >= 2 && (!best || ok.length > best.length)) best = ok;
        }
      });
    });
    if (best) {
      const roh = best.map((x) => num(x[Object.keys(x).find((q) => PK.test(q))] && typeof x[Object.keys(x).find((q) => PK.test(q))] === "object" ? (x[Object.keys(x).find((q) => PK.test(q))].amount || x[Object.keys(x).find((q) => PK.test(q))].value) : x[Object.keys(x).find((q) => PK.test(q))]));
      const cent = roh.every((p) => p >= 500 && Number.isInteger(p));
      best.forEach((x, i) => {
        const n = NK.map((q) => x[q]).filter((q) => typeof q === "string").slice(0, 2).join(" · ");
        const ok = Object.keys(x).find((q) => /^(originalPrice|listPrice|regularPrice|compareAtPrice|marketPrice)$/i.test(q));
        add(n, cent ? roh[i] / 100 : roh[i], ok ? (cent ? num(x[ok]) / 100 : x[ok]) : 0, x.sku || x.skuCode || x.id, x.ean || x.gtin || x.barcode);
      });
    }
  }

  /* 4. Letzter Versuch: Preis-Angaben im Seitenkopf (ein Preis, die gerade gewählte Variante) */
  if (!V.length) {
    C = meta("product:price:currency") || meta("og:price:currency") || meta("priceCurrency") || C;
    add("", meta("product:price:amount") || meta("og:price:amount") || meta("price"), 0, "", "");
  }

  /* Farbauswahl der Seite (Farbfelder): gilt nur ein Preis, übernimmt SchichtLohn ihn für alle diese Farben */
  const F = [];
  if (V.length <= 1) {
    const sel = '[class*="color" i] [title],[class*="color" i] [aria-label],[class*="colour" i] [aria-label],[class*="swatch" i] [aria-label],[class*="swatch" i] [title],[class*="sku" i] [aria-label],[data-color],[data-colour]';
    document.querySelectorAll(sel).forEach((el) => {
      const n = String(el.getAttribute("data-color") || el.getAttribute("data-colour") || el.getAttribute("aria-label") || el.getAttribute("title") || "").replace(/\s+/g, " ").trim();
      if (n && n.length <= 40 && !/warenkorb|cart|close|schließen|menü|menu|search|suche|\d+\s*(kg|g)\b|spule|spool|refill/i.test(n) && !F.includes(n)) F.push(n);
    });
  }

  if (!V.length) {
    const m ="SchichtLohn: Auf dieser Seite wurde kein Preis gefunden. Öffne die Produktseite einer Filamentsorte und versuche es dort.";
    DG.ld = document.querySelectorAll('script[type="application/ld+json"]').length;
    DG.nx = !!document.querySelector("script#__NEXT_DATA__");
    DG.mp = meta("product:price:amount") || meta("og:price:amount") || "";
    const dg = encodeURIComponent(JSON.stringify(DG));
    if (KURZ) completion(B + (B.indexOf("?") >= 0 ? "&" : "?") + "shop=leer&d=" + dg); else alert(m + "\n\n" + JSON.stringify(DG));
    return;
  }
  /* kompakt verpacken: Varianten als [Name ohne Produkttitel, Preis, Normalpreis, EAN], dann komprimiert (iOS kürzt sehr lange Adressen) */
  const tt = String(T).replace(/\s+/g, " ").trim(), tl = tt.toLowerCase();
  const vv = V.slice(0, 60).map((x) => { let n = x.n; if (tl && n.toLowerCase().indexOf(tl) === 0) n = n.slice(tt.length).replace(/^[\s\-–|·,/]+/, ""); const r = [n, x.p]; if (x.np || x.e) r.push(x.np || 0); if (x.e) r.push(x.e); return r; });
  const daten = { u: location.href.split("#")[0].slice(0, 300), t: tt.slice(0, 120), c: C || "EUR", b: String(M || "").slice(0, 60), v: vv, f: F.slice(0, 30) };
  const b64u = (bytes) => { let bin = ""; for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]); return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); };
  const roh = new TextEncoder().encode(JSON.stringify(daten));
  let wert = "";
  try {
    if (window.CompressionStream) {
      const st = new Blob([roh]).stream().pipeThrough(new CompressionStream("deflate-raw"));
      wert = "1z" + b64u(new Uint8Array(await new Response(st).arrayBuffer()));
    }
  } catch (e) { wert = ""; }
  if (!wert) wert = "1j" + b64u(roh);
  const ziel = B + (B.indexOf("?") >= 0 ? "&" : "?") + "shop=" + wert;
  if (KURZ) { completion(ziel); return; }
  const w = window.open(ziel, "_blank");
  if (!w) location.href = ziel;
})();
