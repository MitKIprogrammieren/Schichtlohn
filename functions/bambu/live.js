// SchichtLohn: Live-Status der Bambu-Drucker über die Bambu-Cloud (MQTT über TLS, wie Bambu Handy und Tiger Touch).
// Der Browser kann keinen MQTT-Broker auf Port 8883 erreichen. Diese Function öffnet je Abruf eine kurze Sitzung,
// abonniert device/<Seriennummer>/report, fragt einmal "pushall" an (nur Lesen) und gibt eine knappe Zusammenfassung zurück.
// Es werden keine Befehle gesendet, die am Drucker etwas ändern, und es wird nichts gespeichert oder protokolliert.
import { connect } from "cloudflare:sockets";

const BROKER = { global: "us.mqtt.bambulab.com", cn: "cn.mqtt.bambulab.com" };
const API = { global: "https://api.bambulab.com", cn: "https://api.bambulab.cn" };
const MAX_DEVICES = 12;
const WAIT_MS = 7000;      // längstens so lange auf Berichte warten
const SETTLE_MS = 600;     // nach dem letzten erwarteten Bericht noch kurz Nachzügler sammeln
const MAX_PACKET = 512 * 1024;

function cors(req) {
  return {
    "Access-Control-Allow-Origin": req.headers.get("Origin") || "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
}
const json = (req, status, obj) => new Response(JSON.stringify(obj), { status, headers: { ...cors(req), "Content-Type": "application/json" } });

// ---- MQTT 3.1.1, nur das Nötigste (QoS 0) ----
const enc = new TextEncoder();
const dec = new TextDecoder();
function str(s) { const b = enc.encode(s); const o = new Uint8Array(2 + b.length); o[0] = b.length >> 8; o[1] = b.length & 255; o.set(b, 2); return o; }
function cat(parts) { let n = 0; for (const p of parts) n += p.length; const o = new Uint8Array(n); let i = 0; for (const p of parts) { o.set(p, i); i += p.length; } return o; }
function varlen(n) { const o = []; do { let d = n % 128; n = Math.floor(n / 128); if (n > 0) d |= 128; o.push(d); } while (n > 0); return Uint8Array.from(o); }
function packet(type, body) { return cat([Uint8Array.of(type), varlen(body.length), body]); }
function connectPkt(clientId, user, pass) {
  return packet(0x10, cat([str("MQTT"), Uint8Array.of(4, 0xC2, 0, 60), str(clientId), str(user), str(pass)]));
}
function subscribePkt(id, topics) {
  return packet(0x82, cat([Uint8Array.of(id >> 8, id & 255), ...topics.map((t) => cat([str(t), Uint8Array.of(0)]))]));
}
function publishPkt(topic, payload) { return packet(0x30, cat([str(topic), enc.encode(payload)])); }

// Liest Pakete aus dem Datenstrom: liefert {type, flags, body}
function makeParser() {
  let buf = new Uint8Array(0);
  return function feed(chunk) {
    buf = cat([buf, chunk]);
    const out = [];
    for (;;) {
      if (buf.length < 2) break;
      let mul = 1, len = 0, i = 1, b;
      do { if (i >= buf.length) return out; b = buf[i++]; len += (b & 127) * mul; mul *= 128; if (i > 5) throw new Error("Ungültiges Paket"); } while (b & 128);
      if (len > MAX_PACKET) throw new Error("Bericht zu groß");
      if (buf.length < i + len) break;
      out.push({ type: buf[0] >> 4, flags: buf[0] & 15, body: buf.subarray(i, i + len) });
      buf = buf.slice(i + len);
    }
    return out;
  };
}

// ---- Bericht zusammenfassen ----
function merge(a, b) {
  if (!a || typeof a !== "object" || Array.isArray(a) || !b || typeof b !== "object" || Array.isArray(b)) return b;
  const o = { ...a };
  for (const k of Object.keys(b)) o[k] = merge(a[k], b[k]);
  return o;
}
const num = (v) => (typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" && !isNaN(+v) ? +v : null);
const unpack = (v) => { const n = num(v); return n == null ? [null, null] : [n & 0xffff, (n >>> 16) & 0xffff]; };
function color(c) { return typeof c === "string" && /^[0-9a-f]{6,8}$/i.test(c) ? "#" + c.slice(0, 6).toUpperCase() : null; }
function tray(t) {
  if (!t || typeof t !== "object") return null;
  const type = t.tray_type || "";
  return { id: num(t.id), type, sub: t.tray_sub_brands || "", color: type ? color(t.tray_color) : null, remain: num(t.remain) != null && num(t.remain) >= 0 ? num(t.remain) : null, empty: !type };
}
function summarize(p) {
  if (!p) return null;
  const o = {
    state: p.gcode_state || null,          // IDLE, PREPARE, RUNNING, PAUSE, FINISH, FAILED
    percent: num(p.mc_percent),
    remaining: num(p.mc_remaining_time),   // Minuten
    layer: num(p.layer_num), layers: num(p.total_layer_num),
    file: p.subtask_name || (p.gcode_file ? String(p.gcode_file).split("/").pop() : null),
    stage: num(p.stg_cur),
    error: num(p.print_error) || null,
    nozzle: num(p.nozzle_temper), nozzleTarget: num(p.nozzle_target_temper),
    bed: num(p.bed_temper), bedTarget: num(p.bed_target_temper),
    chamber: num(p.chamber_temper),
    speed: num(p.spd_lvl),
    nozzles: null, activeNozzle: null,
    ams: [], external: [], trayNow: null,
    light: null,
  };
  // H2-Reihe und neuere: Temperaturen gepackt (aktuell | Ziel << 16) im device-Block
  const dev = p.device;
  if (dev && typeof dev === "object") {
    const ext = dev.extruder;
    if (ext && Array.isArray(ext.info)) {
      o.activeNozzle = ((num(ext.state) || 0) >> 4) & 15;
      o.nozzles = ext.info.map((e) => { const [t, tg] = unpack(e.temp); return { id: num(e.id), temp: t, target: tg }; });
      const act = o.nozzles.find((n) => n.id === o.activeNozzle) || o.nozzles[0];
      if (act) { o.nozzle = act.temp; o.nozzleTarget = act.target; }
    }
    if (dev.bed && dev.bed.info) { const [t, tg] = unpack(dev.bed.info.temp); if (t != null) { o.bed = t; o.bedTarget = tg; } }
    if (dev.ctc && dev.ctc.info) { const [t] = unpack(dev.ctc.info.temp); if (t != null) o.chamber = t; }
  }
  const ams = p.ams;
  if (ams && Array.isArray(ams.ams)) {
    o.ams = ams.ams.slice(0, 8).map((u) => ({
      id: num(u.id), humidity: num(u.humidity_raw) ?? null, humidityLevel: num(u.humidity), temp: num(u.temp),
      trays: Array.isArray(u.tray) ? u.tray.map(tray).filter(Boolean) : [],
    }));
    o.trayNow = num(ams.tray_now);
  }
  if (Array.isArray(p.vir_slot)) o.external = p.vir_slot.map(tray).filter(Boolean);
  else if (p.vt_tray) o.external = [tray(p.vt_tray)].filter(Boolean);
  if (Array.isArray(p.lights_report)) {
    const l = p.lights_report.find((x) => /chamber_light$/.test(x.node || "")) || p.lights_report[0];
    if (l) o.light = l.mode === "on";
  }
  return o;
}

async function uidFor(token, region) {
  const r = await fetch(API[region] + "/v1/design-user-service/my/preference", {
    headers: { Authorization: "Bearer " + token, Accept: "application/json", "User-Agent": "bambu_network_agent/01.09.05.01" },
  });
  if (r.status === 401 || r.status === 403) return { err: 401 };
  if (!r.ok) return { err: r.status };
  const j = await r.json().catch(() => ({}));
  return j && j.uid ? { uid: String(j.uid) } : { err: 502 };
}

export async function onRequest({ request }) {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(request) });
  if (request.method !== "POST") return json(request, 405, { message: "Methode nicht erlaubt" });
  const auth = request.headers.get("Authorization") || "";
  const m = auth.match(/^Bearer ([\w.\-~+/=]{10,4096})$/);
  if (!m) return json(request, 401, { message: "Nicht bei der Bambu-Cloud angemeldet" });
  const token = m[1];
  let req;
  try { req = JSON.parse((await request.text()).slice(0, 4000) || "{}"); } catch (e) { return json(request, 400, { message: "Ungültiges JSON" }); }
  const region = req.region === "cn" ? "cn" : "global";
  const serials = [...new Set([].concat(req.serials || []).filter((s) => typeof s === "string" && /^[A-Z0-9]{8,24}$/i.test(s)))].slice(0, MAX_DEVICES);
  if (!serials.length) return json(request, 400, { message: "Keine Drucker angegeben" });

  let uid = typeof req.uid === "string" && /^\d{3,20}$/.test(req.uid) ? req.uid : "";
  if (!uid) {
    const u = await uidFor(token, region).catch(() => ({ err: 502 }));
    if (u.err) return json(request, u.err === 401 ? 401 : 502, { message: u.err === 401 ? "Bambu-Anmeldung abgelaufen" : "Bambu-Konto nicht lesbar" });
    uid = u.uid;
  }

  const reports = {};
  const seenFull = new Set();
  let socket;
  try {
    socket = connect({ hostname: BROKER[region], port: 8883 }, { secureTransport: "on", allowHalfOpen: false });
    const w = socket.writable.getWriter();
    const r = socket.readable.getReader();
    const parse = makeParser();
    const cid = "schichtlohn-" + crypto.randomUUID().slice(0, 12);
    await w.write(connectPkt(cid, "u_" + uid, token));

    const deadline = Date.now() + WAIT_MS;
    let connected = false, settleAt = 0;
    const timeout = (ms) => new Promise((res) => setTimeout(() => res({ timeout: true }), Math.max(0, ms)));
    while (true) {
      const now = Date.now();
      const until = settleAt ? Math.min(settleAt, deadline) : deadline;
      if (now >= until) break;
      const res = await Promise.race([r.read(), timeout(until - now)]);
      if (res.timeout) break;
      if (res.done) break;
      for (const pk of parse(res.value)) {
        if (pk.type === 2) { // CONNACK
          const rc = pk.body[1];
          if (rc !== 0) {
            try { socket.close(); } catch (e) {}
            return json(request, rc === 4 || rc === 5 ? 401 : 502, { message: rc === 4 || rc === 5 ? "Bambu-Cloud lehnt die Anmeldung ab – bitte neu anmelden" : "Bambu-Cloud lehnt die Verbindung ab (" + rc + ")" });
          }
          connected = true;
          await w.write(subscribePkt(1, serials.map((s) => `device/${s}/report`)));
          for (const s of serials) await w.write(publishPkt(`device/${s}/request`, JSON.stringify({ pushing: { sequence_id: "0", command: "pushall", version: 1, push_target: 1 } })));
        } else if (pk.type === 3) { // PUBLISH
          const tl = (pk.body[0] << 8) | pk.body[1];
          const topic = dec.decode(pk.body.subarray(2, 2 + tl));
          let off = 2 + tl;
          if ((pk.flags >> 1) & 3) off += 2; // Paket-ID bei QoS > 0
          const sn = (topic.match(/^device\/([^/]+)\/report$/) || [])[1];
          if (!sn || !serials.includes(sn)) continue;
          let msg;
          try { msg = JSON.parse(dec.decode(pk.body.subarray(off))); } catch (e) { continue; }
          if (msg && msg.print) {
            reports[sn] = merge(reports[sn] || {}, msg.print);
            if (msg.print.gcode_state && (msg.print.ams || msg.print.command === "push_status")) seenFull.add(sn);
          }
        }
      }
      if (connected && !settleAt && serials.every((s) => seenFull.has(s))) settleAt = Date.now() + SETTLE_MS;
    }
    try { await w.write(Uint8Array.of(0xE0, 0)); } catch (e) {} // DISCONNECT
    if (!connected) return json(request, 504, { message: "Bambu-Cloud-Broker antwortet nicht" });
  } catch (e) {
    return json(request, 502, { message: "Bambu-Cloud-Broker nicht erreichbar" });
  } finally {
    try { socket && socket.close(); } catch (e) {}
  }

  const printers = {};
  for (const s of serials) printers[s] = reports[s] ? { online: true, ...summarize(reports[s]) } : { online: false };
  return json(request, 200, { uid, at: Date.now(), printers });
}
