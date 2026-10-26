// SchichtLohn: schmale Weiterleitung zur Creality-Cloud (die Creality-API erlaubt keine Aufrufe direkt aus dem Browser).
// Freigegeben sind nur Anmeldung (Passwort oder Bestätigung in der Creality-Cloud-App per QR-Code), Druckerliste und Druckhistorie.
// Es wird nichts gespeichert oder protokolliert. Creality bietet dafür keine offizielle Schnittstelle; ändert Creality etwas, kann es ausfallen.
const REGIONS = {
  global: { id: "https://id.creality.com", api: "https://api.crealitycloud.com", client: "f9c302ecc29c59a0a6e921ff39a073ca" },
  cn: { id: "https://id.creality.cn", api: "https://api.crealitycloud.cn", client: "8ea5010984fa52a298f12110af8b05d0" },
};
const APP_VER = "7.3.28";
// host "id" = Anmeldung, "api" = Daten (braucht Anmeldeschlüssel)
const ROUTES = {
  "login": { host: "id", to: "/api/cxy/account/v2/loginV2" },
  "qr/new": { host: "id", to: "/api/cxy/account/v2/qrLogin" },
  "qr/query": { host: "id", to: "/api/cxy/account/v2/qrQuery" },
  "devices": { host: "api", to: "/api/rest/print/cluster/devices/getDeviceList" },
  "history": { host: "api", to: "/api/cxy/v3/print/record/list" },
  // nur Lesen: Abfrage an den Drucker über die Cloud (z. B. CFS-Belegung). Keine Befehle, die etwas ändern.
  "rpc": { host: "api", to: "/api/rest/iotrouter/rpc/twoway/" },
};
function cors(req) {
  return {
    "Access-Control-Allow-Origin": req.headers.get("Origin") || "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Authorization,Content-Type,X-Creality-Uid",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
}
const json = (req, status, obj) => new Response(JSON.stringify(obj), { status, headers: { ...cors(req), "Content-Type": "application/json" } });
function hdr(extra) {
  return {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "__CXY_REQUESTID_": crypto.randomUUID(),
    "__CXY_OS_LANG_": "0",
    "__CXY_PLATFORM_": "2",
    "__CXY_DUID_": "schichtlohn",
    "__CXY_BRAND_": "creality",
    "__CXY_TIMEZONE_": "3600",
    ...extra,
  };
}

// Vorschaubilder der Druckhistorie liegen auf Creality-CDNs ohne CORS: nur Creality-Server, nur GET, max. 6 MB.
const MEDIA = ["creality.com", "crealitycloud.com", "creality.cn", "crealitycloud.cn"];
function sniff(b) {
  const u = new Uint8Array(b.slice(0, 12));
  if (u[0] === 0x89 && u[1] === 0x50 && u[2] === 0x4e && u[3] === 0x47) return "image/png";
  if (u[0] === 0xff && u[1] === 0xd8 && u[2] === 0xff) return "image/jpeg";
  if (u[0] === 0x52 && u[1] === 0x49 && u[2] === 0x46 && u[3] === 0x46 && u[8] === 0x57 && u[9] === 0x45) return "image/webp";
  return "";
}
async function cover(request) {
  let u;
  try { u = new URL(new URL(request.url).searchParams.get("u") || ""); } catch (e) { return json(request, 400, { message: "Adresse fehlt" }); }
  const host = u.hostname.toLowerCase();
  if (u.protocol !== "https:" || !MEDIA.some((d) => host === d || host.endsWith("." + d))) return json(request, 403, { message: "Nur Bilder von Creality-Servern" });
  let res;
  try { res = await fetch(u.toString(), { cf: { cacheTtl: 86400, cacheEverything: true } }); } catch (e) { return json(request, 502, { message: "Bild nicht erreichbar" }); }
  if (!res.ok) return json(request, res.status, { message: "Bild nicht abrufbar (HTTP " + res.status + ")" });
  const buf = await res.arrayBuffer();
  if (buf.byteLength > 6e6) return json(request, 413, { message: "Bild zu groß" });
  const ct = sniff(buf);
  if (!ct) return json(request, 415, { message: "Kein Bild" });
  return new Response(buf, { status: 200, headers: { ...cors(request), "Content-Type": ct, "Cache-Control": "public, max-age=86400" } });
}

export async function onRequest(ctx) {
  const { request, params } = ctx;
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(request) });
  const path = [].concat(params.path || []).join("/");
  if (path === "cover") return request.method === "GET" ? cover(request) : json(request, 405, { message: "Methode nicht erlaubt" });
  const r = ROUTES[path];
  if (!r) return json(request, 404, { message: "Unbekannter Pfad" });
  if (request.method !== "POST") return json(request, 405, { message: "Methode nicht erlaubt" });
  const reg = REGIONS[new URL(request.url).searchParams.get("region") === "cn" ? "cn" : "global"];
  let body = {};
  let ziel = r.to;
  try { body = await request.json(); } catch (e) { body = {}; }
  if (!body || typeof body !== "object" || Array.isArray(body)) body = {};
  let h;
  if (r.host === "id") {
    h = hdr({ "__CXY_APP_ID_": "creality_account", "__CXY_APP_VER_": "0.0.1", "__CXY_PLATFORM_": "pc" });
    if (path === "login") {
      const account = String(body.account || "").trim();
      body = { type: account.includes("@") ? 2 : 1, account, password: String(body.password || ""), clientId: reg.client };
    } else if (path === "qr/query") {
      body = { identical: String(body.identical || "") };
    } else body = {};
  } else {
    const auth = request.headers.get("Authorization") || "";
    const token = auth.replace(/^Bearer\s+/i, "");
    const uid = request.headers.get("X-Creality-Uid") || "";
    if (!token || !uid) return json(request, 401, { message: "Nicht angemeldet" });
    h = hdr({ "__CXY_APP_ID_": "cxy-gen2", "__CXY_APP_VER_": APP_VER, "__CXY_TOKEN_": token, "__CXY_UID_": uid });
    if (path === "rpc") {
      const tb = String(body.tbId || "");
      if (!/^[0-9a-f-]{20,40}$/i.test(tb)) return json(request, 400, { message: "Ungültige Drucker-ID" });
      const ERLAUBT = ["cfsList", "boxsInfo", "ReqPrinterPara", "reqMaterials"];
      const k = String(body.get || "");
      if (!ERLAUBT.includes(k)) return json(request, 400, { message: "Abfrage nicht erlaubt" });
      ziel = r.to + encodeURIComponent(tb);
      body = { method: "get", params: { [k]: 1 } };
    } else if (path === "devices") body = { page: 1, pageSize: 50 };
    else body = { page: Math.max(1, Math.min(200, Number(body.page) || 1)), pageSize: Math.max(1, Math.min(100, Number(body.pageSize) || 50)), deviceName: String(body.deviceName || "") };
  }
  let res;
  try { res = await fetch((r.host === "id" ? reg.id : reg.api) + ziel, { method: "POST", headers: h, body: JSON.stringify(body) }); }
  catch (e) { return json(request, 502, { message: "Creality-Cloud nicht erreichbar" }); }
  let d = null;
  try { d = await res.json(); } catch (e) { d = null; }
  if (!res.ok || !d) return json(request, 502, { message: "Creality-Cloud antwortet nicht wie erwartet (HTTP " + res.status + ")" });
  if (d.code === 4 || d.code === 5) return json(request, 401, { message: d.msg || "Anmeldung abgelaufen", code: d.code });
  if (d.code !== 0) return json(request, 400, { message: d.msg || "Fehler " + d.code, code: d.code });
  return json(request, 200, { result: d.result ?? null });
}
