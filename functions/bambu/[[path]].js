// Schichtlohn: schmale Weiterleitung zur Bambu-Cloud (die Bambu-API erlaubt keine Aufrufe direkt aus dem Browser).
// Nur Anmeldung und Druckhistorie sind freigegeben. Es wird nichts gespeichert oder protokolliert.
const API = { global: "https://api.bambulab.com", cn: "https://api.bambulab.cn" };
const WEB = { global: "https://bambulab.com", cn: "https://bambulab.cn" };
const ROUTES = {
  "user/login": { m: "POST", to: "/v1/user-service/user/login" },
  "user/sendemail/code": { m: "POST", to: "/v1/user-service/user/sendemail/code" },
  "my/tasks": { m: "GET", to: "/v1/user-service/my/tasks", q: ["limit", "after", "deviceId"] },
  "my/bind": { m: "GET", to: "/v1/iot-service/api/user/bind" },
  "tfa": { m: "POST", web: "/api/sign-in/tfa" },
};
const HDR = {
  "User-Agent": "bambu_network_agent/01.09.05.01",
  "X-BBL-Client-Name": "OrcaSlicer",
  "X-BBL-Client-Type": "slicer",
  "X-BBL-Client-Version": "01.09.05.51",
  "X-BBL-Language": "de-DE",
  "X-BBL-OS-Type": "linux",
  "X-BBL-OS-Version": "6.2.0",
  "X-BBL-Agent-Version": "01.09.05.01",
  "X-BBL-Executable-info": "{}",
  "X-BBL-Agent-OS-Type": "linux",
  "Accept": "application/json",
};
function cors(req) {
  return {
    "Access-Control-Allow-Origin": req.headers.get("Origin") || "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
}
const json = (req, status, obj) => new Response(JSON.stringify(obj), { status, headers: { ...cors(req), "Content-Type": "application/json" } });

// Vorschaubilder der Druckhistorie: liegen bei Bambu auf CDN/S3 ohne CORS. Nur Bilder von Bambu-Servern, nur GET, max. 6 MB.
const COVER_HOSTS = [/(^|\.)bambulab\.(com|cn)$/i, /(^|\.)bblmw\.com$/i, /\.amazonaws\.com(\.cn)?$/i, /\.aliyuncs\.com$/i, /(^|\.)bambu-lab\.com$/i];
async function cover(request) {
  if (request.method !== "GET") return json(request, 405, { message: "Methode nicht erlaubt" });
  let u;
  try { u = new URL(new URL(request.url).searchParams.get("u") || ""); } catch (e) { return json(request, 400, { message: "Adresse fehlt" }); }
  if (u.protocol !== "https:" || !COVER_HOSTS.some((re) => re.test(u.hostname))) return json(request, 403, { message: "Nur Bilder von Bambu-Servern" });
  let res;
  try { res = await fetch(u.toString(), { headers: { "User-Agent": HDR["User-Agent"] }, cf: { cacheTtl: 86400, cacheEverything: true } }); }
  catch (e) { return json(request, 502, { message: "Bild nicht erreichbar" }); }
  const ct = res.headers.get("content-type") || "";
  if (!res.ok || !/^image\//i.test(ct)) return json(request, res.ok ? 415 : res.status, { message: "Kein Bild" });
  const buf = await res.arrayBuffer();
  if (buf.byteLength > 6e6) return json(request, 413, { message: "Bild zu groß" });
  return new Response(buf, { status: 200, headers: { ...cors(request), "Content-Type": ct, "Cache-Control": "public, max-age=86400" } });
}

export async function onRequest({ request, params }) {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(request) });
  const path = [].concat(params.path || []).join("/");
  if (path === "cover") return cover(request);
  const r = ROUTES[path];
  if (!r) return json(request, 404, { message: "Unbekannter Pfad" });
  if (request.method !== r.m) return json(request, 405, { message: "Methode nicht erlaubt" });
  const url = new URL(request.url);
  const region = url.searchParams.get("region") === "cn" ? "cn" : "global";
  const headers = { ...HDR };
  const auth = request.headers.get("Authorization");
  if (auth && /^Bearer [\w.\-~+/=]{10,4096}$/.test(auth)) headers.Authorization = auth;
  let body;
  if (r.m === "POST") {
    const t = await request.text();
    if (t.length > 4000) return json(request, 413, { message: "Zu groß" });
    try { JSON.parse(t || "{}"); } catch (e) { return json(request, 400, { message: "Ungültiges JSON" }); }
    body = t || "{}";
    headers["Content-Type"] = "application/json";
  }
  let target;
  if (r.web) target = new URL(WEB[region] + r.web);
  else {
    target = new URL(API[region] + r.to);
    for (const k of r.q || []) { const v = url.searchParams.get(k); if (v && /^[\w.\-:]{1,64}$/.test(v)) target.searchParams.set(k, v); }
  }
  let res;
  try { res = await fetch(target, { method: r.m, headers, body, redirect: "manual" }); }
  catch (e) { return json(request, 502, { message: "Bambu-Cloud nicht erreichbar" }); }
  const text = await res.text();
  if (path === "tfa") {
    // Bei Zwei-Faktor-Anmeldung steckt der Schlüssel im Cookie "token"
    const ck = res.headers.get("set-cookie") || "";
    const m = ck.match(/(?:^|[;,]\s*)token=([^;,\s]+)/);
    if (res.ok && m) return json(request, 200, { accessToken: m[1], expiresIn: 7776000 });
  }
  const ct = res.headers.get("content-type") || "";
  let isJson = /json/i.test(ct);
  if (!isJson && text.trim()) { try { JSON.parse(text); isJson = true; } catch (e) {} }
  // Manche Aufrufe (z. B. Code per Mail senden) antworten mit leerem Text: bei Erfolg als {} weitergeben
  if (!isJson && res.ok) return json(request, 200, {});
  if (!isJson) return json(request, res.status >= 400 ? res.status : 502, { message: `Bambu-Cloud antwortet nicht wie erwartet (HTTP ${res.status})` });
  return new Response(text, { status: res.status, headers: { ...cors(request), "Content-Type": "application/json" } });
}
