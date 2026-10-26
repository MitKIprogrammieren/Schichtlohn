// SchichtLohn: Abgleich zwischen Geräten und „Handy als Scanner“.
// Alles, was hier ankommt, ist im Browser verschlüsselt (AES-GCM). Der Schlüssel steckt im Sync-Code bzw. im QR-Code
// und wird nie hierher geschickt – gespeichert werden nur unlesbare Daten. Speicher: Cloudflare KV (Bindung „SYNC“).
const MAX_DOC = 4_000_000;        // max. Größe eines Teils (verschlüsselt, Base64)
const MAX_ALL = 20_000_000;       // max. Gesamtgröße eines Datensatzes
const SCAN_TTL = 7 * 24 * 3600;   // Briefkasten fürs Handy: 7 Tage nach dem letzten Scan
const ID = /^[0-9a-f]{32,64}$/;

function cors(req) {
  return {
    "Access-Control-Allow-Origin": req.headers.get("Origin") || "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
}
const json = (req, status, obj) => new Response(JSON.stringify(obj), { status, headers: { ...cors(req), "Content-Type": "application/json" } });

/* Optional: Datensatz an ein Creality- oder Bambu-Konto binden. Geprüft wird beim Anbieter, ob die Anmeldung echt ist. */
const merk = new Map();
async function konto(k) {
  if (!k || typeof k !== "object") return null;
  const key = JSON.stringify(k);
  const m = merk.get(key);
  if (m && m.bis > Date.now()) return m.id;
  let id = null;
  if (k.art === "creality") {
    const api = k.region === "cn" ? "https://api.crealitycloud.cn" : "https://api.crealitycloud.com";
    const r = await fetch(api + "/api/rest/print/cluster/devices/getDeviceList", {
      method: "POST",
      headers: { "Content-Type": "application/json", "__CXY_APP_ID_": "cxy-gen2", "__CXY_APP_VER_": "7.3.28", "__CXY_PLATFORM_": "2", "__CXY_OS_LANG_": "0",
        "__CXY_REQUESTID_": crypto.randomUUID(), "__CXY_TOKEN_": String(k.token || ""), "__CXY_UID_": String(k.uid || "") },
      body: JSON.stringify({ page: 1, pageSize: 1 }),
    });
    const d = await r.json().catch(() => null);
    if (r.ok && d && d.code === 0 && k.uid) id = "creality:" + String(k.uid);
  } else if (k.art === "bambu") {
    const api = k.region === "cn" ? "https://api.bambulab.cn" : "https://api.bambulab.com";
    const r = await fetch(api + "/v1/design-user-service/my/preference", { headers: { Authorization: "Bearer " + String(k.token || ""), "User-Agent": "bambu_network_agent/01.09.05.01" } });
    const d = await r.json().catch(() => null);
    const uid = d && (d.uid ?? d.uidStr);
    if (r.ok && uid) id = "bambu:" + String(uid);
  }
  if (id) merk.set(key, { id, bis: Date.now() + 600000 });
  return id;
}

export async function onRequest(ctx) {
  const { request, params, env } = ctx;
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(request) });
  if (request.method !== "POST") return json(request, 405, { message: "Methode nicht erlaubt" });
  if (!env.SYNC) return json(request, 503, { message: "Der Sync-Speicher ist auf dem Server noch nicht eingerichtet." });
  const path = [].concat(params.path || []).join("/");
  let b = {};
  try { b = await request.json(); } catch (e) { b = {}; }
  if (!b || typeof b !== "object") b = {};

  /* ---- Sync über die Anmeldung: je Creality-/Bambu-Konto ein Sync-Code ----
     Wer sich mit demselben Konto anmeldet, bekommt denselben Code. Der Code liegt dafür im eigenen KV-Speicher. */
  if (path === "konto") {
    let wer = null;
    try { wer = await konto(b.konto); } catch (e) { wer = null; }
    if (!wer) return json(request, 401, { message: "Anmeldung bei Creality bzw. Bambu ist abgelaufen. Bitte neu anmelden." });
    const key = "a:" + wer;
    const alt = await env.SYNC.get(key);
    if (alt) return json(request, 200, { code: alt, neu: false });
    const code = String(b.code || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!/^[A-HJ-NP-Z2-9]{20}$/.test(code)) return json(request, 200, { code: null });
    const fein = code.match(/.{4}/g).join("-");
    await env.SYNC.put(key, fein);
    return json(request, 200, { code: fein, neu: true });
  }

  /* ---- Datensatz abgleichen ---- */
  if (path === "pull" || path === "push") {
    const sid = String(b.sid || "");
    if (!ID.test(sid)) return json(request, 400, { message: "Ungültiger Sync-Code" });
    const key = "s:" + sid;
    const raw = await env.SYNC.get(key);
    const rec = raw ? JSON.parse(raw) : { v: 0, owner: null, docs: {}, del: {} };
    let wer = null;
    if (rec.owner || b.konto) {
      try { wer = await konto(b.konto); } catch (e) { wer = null; }
      if (rec.owner && wer !== rec.owner) return json(request, 403, { message: "Dieser Sync ist an ein Konto gebunden. Melde dich auf diesem Gerät mit demselben Creality- oder Bambu-Konto an.", gebunden: rec.owner.split(":")[0] });
    }
    if (path === "pull") {
      const own = rec.owner ? rec.owner.split(":")[0] : null;
      if (Number(b.v) === rec.v && rec.v > 0) return json(request, 200, { v: rec.v, owner: own, same: true });
      // nur seit Version „since“ geänderte Teile mitschicken; die Liste aller Teile (Name → Zeit) immer
      const seit = Number(b.since) || 0, idx = {}, docs = {};
      for (const [n, d] of Object.entries(rec.docs)) { idx[n] = d.t; if ((d.w || 0) > seit) docs[n] = d; }
      return json(request, 200, { v: rec.v, owner: own, idx, docs, del: rec.del || {} });
    }

    // push: je Teil gewinnt der neuere Stand
    const put = b.put && typeof b.put === "object" ? b.put : {};
    const del = Array.isArray(b.del) ? b.del : [];
    const jetzt = Date.now();
    for (const [n, doc] of Object.entries(put)) {
      if (!/^[a-z0-9_:-]{1,80}$/i.test(n) || !doc || typeof doc.d !== "string" || doc.d.length > MAX_DOC) continue;
      const t = Math.min(Number(doc.t) || jetzt, jetzt + 60000);
      const alt = rec.docs[n];
      if (!alt || t >= alt.t) { rec.docs[n] = { t, w: (rec.v || 0) + 1, d: doc.d }; if (rec.del) delete rec.del[n]; }
    }
    rec.del = rec.del || {};
    for (const x of del) {
      const n = String(x.n || x), t = Math.min(Number(x.t) || jetzt, jetzt + 60000);
      const alt = rec.docs[n];
      if (!alt || t >= alt.t) { delete rec.docs[n]; rec.del[n] = t; }
    }
    // alte Löschmarken nach 60 Tagen vergessen
    for (const [n, t] of Object.entries(rec.del)) if (jetzt - t > 60 * 864e5) delete rec.del[n];
    if (b.binden && wer && !rec.owner) rec.owner = wer;
    if (b.loesen && rec.owner && wer === rec.owner) rec.owner = null;
    rec.v = (rec.v || 0) + 1;
    const s = JSON.stringify(rec);
    if (s.length > MAX_ALL) return json(request, 413, { message: "Die Daten sind zu groß für den Sync" });
    await env.SYNC.put(key, s);
    return json(request, 200, { v: rec.v, owner: rec.owner ? rec.owner.split(":")[0] : null });
  }

  /* ---- Handy als Scanner: Briefkasten für verschlüsselte Codes ---- */
  if (path === "scan/send" || path === "scan/poll") {
    const pid = String(b.pid || "");
    if (!ID.test(pid)) return json(request, 400, { message: "Ungültige Kopplung" });
    const key = "p:" + pid;
    const raw = await env.SYNC.get(key);
    const box = raw ? JSON.parse(raw) : { seq: 0, items: [] };
    if (path === "scan/poll") {
      const nach = Number(b.after) || 0;
      return json(request, 200, { seq: box.seq, items: box.items.filter((x) => x.i > nach) });
    }
    if (typeof b.d !== "string" || b.d.length > 4000) return json(request, 400, { message: "Ungültiger Code" });
    box.seq += 1;
    box.items.push({ i: box.seq, d: b.d, t: Date.now() });
    box.items = box.items.slice(-40);
    await env.SYNC.put(key, JSON.stringify(box), { expirationTtl: SCAN_TTL });
    return json(request, 200, { seq: box.seq });
  }
  return json(request, 404, { message: "Unbekannter Pfad" });
}
