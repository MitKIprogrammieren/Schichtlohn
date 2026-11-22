// Meldewerk – eigenes WhatsApp-Benachrichtigungs-Gateway für SchichtLohn, Home Assistant und alle Werke.
// Läuft als verknüpftes Gerät (wie WhatsApp Web) an der Absender-Nummer und schickt Meldungen nur an den Empfänger.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import baileys, { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } from 'baileys';
import QRCode from 'qrcode';
import pino from 'pino';

const makeWASocket = baileys.default || baileys.makeWASocket || baileys;
// libsignal schreibt beim Sitzungswechsel interne Schlüssel ins Protokoll – diese Zeilen nicht ausgeben
const STILL = /^(Closing (open )?session|Removing old closed session|Decrypted message with closed session|Migrating session|Session error)/;
for (const k of ['log', 'info', 'warn']) { const alt = console[k].bind(console); console[k] = (...a) => { if (!STILL.test(String(a[0] ?? ''))) alt(...a); }; }
const HIER = path.dirname(fileURLToPath(import.meta.url));
const DATEN = process.env.DATEN || '/daten';
const PORT = Number(process.env.PORT || 8088);
const AUTH = path.join(DATEN, 'auth');
const BILDER = path.join(DATEN, 'bilder');
const VERLAUF = path.join(DATEN, 'verlauf.jsonl');
const EINST = path.join(DATEN, 'einstellungen.json');
const SEITE = fs.readFileSync(process.env.SEITE || path.join(HIER, 'index.html'), 'utf8');
fs.mkdirSync(BILDER, { recursive: true });
// App-Symbol: das Kopfzeilen-Logo der Seite auf dunklem Grund
const LOGO_INNEN = (SEITE.match(/<svg viewBox="0 0 48 48">([\s\S]*?)<\/svg>/) || [])[1] || '';
const LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="10.5" fill="#1d1f23"/>' +
  '<g transform="translate(24 24) scale(.86) translate(-24 -25)">' + LOGO_INNEN + '</g></svg>';

// ---------- Einstellungen ----------
const STANDARD = { empfaenger: '', empfaenger_name: '', schluessel: '', aufbewahrung_tage: 365, absender_loeschen: true, archivieren: true };
function einstLaden() {
  let e = {};
  try { e = JSON.parse(fs.readFileSync(EINST, 'utf8')); } catch {}
  e = { ...STANDARD, ...e };
  if (!e.schluessel) { e.schluessel = crypto.randomBytes(16).toString('hex'); einstSpeichern(e); }
  return e;
}
function einstSpeichern(e) { fs.writeFileSync(EINST + '.tmp', JSON.stringify(e, null, 2)); fs.renameSync(EINST + '.tmp', EINST); }
let EIN = einstLaden();

// ---------- Verlauf ----------
let VERL = [];
try { VERL = fs.readFileSync(VERLAUF, 'utf8').split('\n').filter(Boolean).map(z => JSON.parse(z)); } catch {}
function verlaufSchreiben() {
  fs.writeFileSync(VERLAUF + '.tmp', VERL.map(v => JSON.stringify(v)).join('\n') + (VERL.length ? '\n' : ''));
  fs.renameSync(VERLAUF + '.tmp', VERLAUF);
}
function aufraeumen() {
  const tage = Number(EIN.aufbewahrung_tage) || 0;
  if (tage <= 0) return; // 0 = unbegrenzt
  const grenze = Date.now() - tage * 86400000;
  const weg = VERL.filter(v => v.zeit < grenze);
  if (!weg.length) return;
  for (const v of weg) if (v.bild) fs.rm(path.join(BILDER, v.bild), () => {});
  VERL = VERL.filter(v => v.zeit >= grenze);
  verlaufSchreiben();
}
setInterval(aufraeumen, 6 * 3600000);

// ---------- WhatsApp ----------
const W = { sock: null, verbunden: false, qr: null, nummer: '', name: '', fehler: '', start: 0 };
const GESENDET = new Map(); // id -> message (für Wiederholungsanfragen von WhatsApp)
const log = pino({ level: process.env.LOG || 'warn' });

function jid(nr) {
  const t = String(nr || '').trim();
  if (/@(g\.us|s\.whatsapp\.net)$/.test(t)) return t; // Gruppe oder fertige WhatsApp-Kennung
  const d = t.replace(/\D/g, '').replace(/^00/, '');
  return d ? d + '@s.whatsapp.net' : '';
}

// Gruppen, in denen die Absender-Nummer ist (kurz zwischengespeichert)
const GRUPPEN = { liste: [], zeit: 0 };
async function gruppen(neu) {
  if (!W.verbunden) return GRUPPEN.liste;
  if (neu || Date.now() - GRUPPEN.zeit > 10 * 60000) {
    const g = await W.sock.groupFetchAllParticipating();
    GRUPPEN.liste = Object.values(g || {}).map(x => ({ id: x.id, name: x.subject || x.id, teilnehmer: (x.participants || []).length }))
      .sort((a, b) => a.name.localeCompare(b.name, 'de'));
    GRUPPEN.zeit = Date.now();
  }
  return GRUPPEN.liste;
}

// Ziel einer Meldung: leer = Standard-Empfänger; sonst Gruppenname, „ich“, Nummer oder WhatsApp-Kennung
async function zielFinden(ziel) {
  const z = String(ziel || '').trim();
  if (!z) return { jid: jid(EIN.empfaenger), name: EIN.empfaenger_name || '' };
  if (/^(ich|mich|mir|standard)$/i.test(z)) return { jid: jid(EIN.empfaenger), name: EIN.empfaenger_name || '' };
  if (/@/.test(z) || /^\+?[\d\s/-]{8,}$/.test(z)) return { jid: jid(z), name: z };
  const g = (await gruppen()).find(x => x.name.toLowerCase() === z.toLowerCase()) || (await gruppen(true)).find(x => x.name.toLowerCase() === z.toLowerCase());
  if (!g) throw new Error('Gruppe „' + z + '“ nicht gefunden – ist die Absender-Nummer drin?');
  return { jid: g.id, name: g.name };
}

async function verbinden() {
  W.start = Date.now();
  const { state, saveCreds } = await useMultiFileAuthState(AUTH);
  let version;
  try { ({ version } = await fetchLatestBaileysVersion()); } catch {}
  const sock = makeWASocket({
    auth: state, logger: log, version,
    browser: ['Meldewerk', 'Chrome', '1.0'],
    markOnlineOnConnect: false, syncFullHistory: false,
    getMessage: async key => GESENDET.get(key.id)?.message,
  });
  W.sock = sock;
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async u => {
    if (u.qr) { W.qr = await QRCode.toDataURL(u.qr, { margin: 1, width: 320 }); W.verbunden = false; }
    if (u.connection === 'open') {
      W.verbunden = true; W.qr = null; W.fehler = '';
      W.nummer = (sock.user?.id || '').split(':')[0].split('@')[0];
      W.name = sock.user?.name || '';
      console.log('Verbunden als', W.nummer);
      warteschlange();
    }
    if (u.connection === 'close') {
      W.verbunden = false;
      const code = u.lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.log('Abgemeldet – neuer QR-Code folgt');
        W.nummer = ''; W.fehler = 'Gerät wurde abgemeldet. Bitte neu verknüpfen.';
        fs.rmSync(AUTH, { recursive: true, force: true });
      } else {
        W.fehler = u.lastDisconnect?.error?.message || '';
      }
      setTimeout(() => verbinden().catch(e => console.error('Verbinden fehlgeschlagen:', e)), 3000);
    }
  });
}

async function bildHolen(quelle) {
  if (!quelle) return null;
  if (quelle.startsWith('data:')) return Buffer.from(quelle.split(',')[1] || '', 'base64');
  const r = await fetch(quelle, { signal: AbortSignal.timeout(20000) });
  if (!r.ok) throw new Error('Bild nicht abrufbar (' + r.status + ')');
  const b = Buffer.from(await r.arrayBuffer());
  if (b.length > 15 * 1024 * 1024) throw new Error('Bild zu groß');
  return b;
}

async function zustellen(eintrag) {
  if (!W.verbunden) throw new Error('nicht verbunden');
  const zf = await zielFinden(eintrag.ziel);
  const ziel = zf.jid;
  if (!ziel) throw new Error('Kein Empfänger eingestellt');
  eintrag.an = zf.name || (ziel.endsWith('@g.us') ? 'Gruppe' : '');
  let inhalt;
  if (eintrag.bild) {
    const buf = fs.readFileSync(path.join(BILDER, eintrag.bild));
    inhalt = { image: buf, caption: eintrag.text };
  } else inhalt = { text: eintrag.text };
  const msg = await W.sock.sendMessage(ziel, inhalt);
  GESENDET.set(msg.key.id, msg);
  if (GESENDET.size > 200) GESENDET.delete(GESENDET.keys().next().value);
  // Absender-Seite sauber halten: kurz warten, dann „Für mich löschen“ und archivieren
  setTimeout(async () => {
    const ts = Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000);
    if (EIN.absender_loeschen) {
      try { await W.sock.chatModify({ deleteForMe: { deleteMedia: false, key: msg.key, timestamp: ts } }, ziel); }
      catch (e) { console.warn('Löschen beim Absender fehlgeschlagen:', e.message); }
    }
    if (EIN.archivieren) {
      try { await W.sock.chatModify({ archive: true, lastMessages: [{ key: msg.key, messageTimestamp: msg.messageTimestamp }] }, ziel); }
      catch (e) { console.warn('Archivieren fehlgeschlagen:', e.message); }
    }
  }, 4000);
  return msg.key.id;
}

let laeuft = false;
async function warteschlange() {
  if (laeuft) return; laeuft = true;
  try {
    for (const v of VERL.filter(v => v.status === 'wartet')) {
      if (!W.verbunden) break;
      try { v.wa_id = await zustellen(v); v.status = 'gesendet'; v.gesendet = Date.now(); v.fehler = ''; }
      catch (e) { v.fehler = e.message; if (!/nicht verbunden|Kein Empfänger/.test(e.message)) v.status = 'fehler'; }
    }
    verlaufSchreiben();
  } finally { laeuft = false; }
}
setInterval(warteschlange, 60000);

async function melden({ text, quelle, bild, titel, ziel }) {
  text = String(text || '').trim();
  titel = String(titel || '').trim();
  if (titel) text = '*' + titel + '*' + (text ? '\n' + text : '');
  if (!text && !bild) throw Object.assign(new Error('Text fehlt'), { code: 400 });
  const e = { id: crypto.randomUUID(), zeit: Date.now(), quelle: String(quelle || 'sonstige').slice(0, 24).toLowerCase(), text: text.slice(0, 4000), status: 'wartet', fehler: '' };
  if (ziel) e.ziel = String(ziel).slice(0, 120);
  if (bild) {
    try { const b = await bildHolen(bild); if (b?.length) { e.bild = e.id + '.jpg'; fs.writeFileSync(path.join(BILDER, e.bild), b); } }
    catch (err) { e.fehler = 'Bild: ' + err.message; }
  }
  VERL.push(e);
  alexaAnsagen(e).catch(() => {});
  try { e.wa_id = await zustellen(e); e.status = 'gesendet'; e.gesendet = Date.now(); }
  catch (err) { e.fehler = err.message; if (!/nicht verbunden|Kein Empfänger/.test(err.message)) e.status = 'fehler'; }
  verlaufSchreiben();
  return e;
}

// ---------- Home Assistant: Skript „Meldewerk senden“ löst das Ereignis meldewerk_senden aus ----------
// Adresse und Token kommen aus den Einstellungen der Oberfläche, sonst aus der .env
const haUrl = () => String(EIN.ha_url || process.env.HA_URL || '').replace(/\/+$/, '');
const haToken = () => String(EIN.ha_token || process.env.HA_TOKEN || '');
const HA = { verbunden: false, fehler: '', ws: null };

async function haApi(pfad, daten) {
  const r = await fetch(haUrl() + pfad, { method: daten ? 'POST' : 'GET', signal: AbortSignal.timeout(20000),
    headers: { Authorization: 'Bearer ' + haToken(), 'Content-Type': 'application/json' }, body: daten ? JSON.stringify(daten) : undefined });
  if (!r.ok) throw new Error('Home Assistant antwortet mit ' + r.status);
  return r.json();
}

// ---------- Alexa über Home Assistant (Alexa Media Player) ----------
const ALEXA = { mediaplayer: false, geraete: [], zeit: 0 };
async function alexaLaden(neu) {
  if (!HA.verbunden) return ALEXA;
  if (!neu && Date.now() - ALEXA.zeit < 5 * 60000) return ALEXA;
  try {
    const dienste = await haApi('/api/services');
    const notify = (dienste.find(d => d.domain === 'notify') || {}).services || {};
    ALEXA.mediaplayer = Object.keys(notify).some(k => k === 'alexa_media' || k.startsWith('alexa_media'));
    const st = await haApi('/api/states');
    ALEXA.geraete = st.filter(x => x.entity_id.startsWith('media_player.') && x.attributes && 'last_called' in x.attributes)
      .map(x => ({ id: x.entity_id, name: x.attributes.friendly_name || x.entity_id, art: x.attributes.device_family || x.attributes.model || 'Echo', online: x.state !== 'unavailable' }))
      .sort((a, b) => a.name.localeCompare(b.name, 'de'));
    ALEXA.zeit = Date.now();
  } catch (e) { console.warn('Alexa-Geräte:', e.message); }
  return ALEXA;
}
function alexaStatus() {
  const a = EIN.alexa || {};
  return { mediaplayer: ALEXA.mediaplayer, ruhe: a.ruhe || '', quellen: a.quellen || {},
    geraete: ALEXA.geraete.map(g => ({ ...g, an: !!(a.geraete || {})[g.id] })) };
}
function nachtruhe() {
  const m = /^(\d{1,2})-(\d{1,2})$/.exec((EIN.alexa || {}).ruhe || '');
  if (!m) return false;
  const h = Number(new Intl.DateTimeFormat('de-DE', { hour: 'numeric', hour12: false, timeZone: process.env.TZ || 'Europe/Berlin' }).format(new Date()));
  const von = Number(m[1]), bis = Number(m[2]);
  return von > bis ? (h >= von || h < bis) : (h >= von && h < bis);
}
async function alexaAnsagen(e) {
  const a = EIN.alexa || {};
  const ziele = Object.entries(a.geraete || {}).filter(([, an]) => an).map(([id]) => id);
  if (!ziele.length || !HA.verbunden || (a.quellen || {})[e.quelle] === false || e.quelle === 'test' && !e.alexa_test || nachtruhe()) return;
  await alexaLaden();
  if (!ALEXA.mediaplayer) return;
  const text = e.text.replace(/\*([^*\n]+)\*/g, '$1').replace(/\n+/g, '. ').replace(/[\u{1F300}-\u{1FAFF}\u2600-\u27BF\uFE0F]/gu, '').trim();
  try { await haApi('/api/services/notify/alexa_media', { message: text, target: ziele, data: { type: 'announce' } }); e.alexa = true; }
  catch (err) { console.warn('Alexa-Ansage:', err.message); }
}

async function haBild(d) {
  // kamera: camera.xyz → aktuelles Kamerabild; bild: /api/... (aus HA, mit Anmeldung) oder http(s)://…
  let pfad = d.kamera ? '/api/camera_proxy/' + String(d.kamera).trim() : String(d.bild || '').trim();
  if (!pfad) return '';
  if (/^https?:/.test(pfad) || pfad.startsWith('data:')) return pfad;
  const r = await fetch(haUrl() + (pfad.startsWith('/') ? pfad : '/' + pfad), { headers: { Authorization: 'Bearer ' + haToken() }, signal: AbortSignal.timeout(20000) });
  if (!r.ok) throw new Error('Bild aus Home Assistant nicht abrufbar (' + r.status + ')');
  return 'data:' + (r.headers.get('content-type') || 'image/jpeg') + ';base64,' + Buffer.from(await r.arrayBuffer()).toString('base64');
}

function haVerbinden() {
  if (HA.ws) { try { HA.ws.onclose = null; HA.ws.close(); } catch {} HA.ws = null; HA.verbunden = false; }
  clearTimeout(HA.timer);
  if (!haUrl() || !haToken() || typeof WebSocket === 'undefined') return;
  let ws;
  try { ws = HA.ws = new WebSocket(haUrl().replace(/^http/, 'ws') + '/api/websocket'); }
  catch (e) { HA.fehler = e.message; HA.timer = setTimeout(haVerbinden, 30000); return; }
  ws.onmessage = async ev => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === 'auth_required') ws.send(JSON.stringify({ type: 'auth', access_token: haToken() }));
    else if (m.type === 'auth_ok') ws.send(JSON.stringify({ id: 1, type: 'subscribe_events', event_type: 'meldewerk_senden' }));
    else if (m.type === 'auth_invalid') { HA.fehler = 'Home-Assistant-Token ungültig'; console.warn(HA.fehler); }
    else if (m.type === 'result' && m.id === 1 && m.success) { HA.verbunden = true; HA.fehler = ''; console.log('Home Assistant verbunden – warte auf meldewerk_senden'); alexaLaden(true); }
    else if (m.type === 'event' && m.event?.event_type === 'meldewerk_senden') {
      const d = m.event.data || {};
      let bild = '';
      try { bild = await haBild(d); } catch (e) { console.warn(e.message); }
      melden({ titel: d.titel ?? d.title, text: d.text ?? d.message, quelle: d.quelle || 'ha', ziel: d.ziel, bild })
        .catch(e => console.warn('Meldung aus Home Assistant:', e.message));
    }
  };
  ws.onclose = () => { HA.verbunden = false; if (HA.ws === ws) HA.timer = setTimeout(haVerbinden, 15000); };
  ws.onerror = () => { HA.fehler = HA.fehler || 'Home Assistant nicht erreichbar'; };
}

// ---------- HTTP ----------
function senden(res, code, body, typ = 'application/json; charset=utf-8') {
  if (typeof body !== 'string' && !Buffer.isBuffer(body)) body = JSON.stringify(body);
  res.writeHead(code, { 'Content-Type': typ, 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type, X-Schluessel, Authorization' });
  res.end(body);
}
function lesen(req) {
  return new Promise((ok, nein) => {
    const t = []; let n = 0;
    req.on('data', c => { n += c.length; if (n > 20 * 1024 * 1024) { nein(new Error('zu groß')); req.destroy(); } else t.push(c); });
    req.on('end', () => {
      const s = Buffer.concat(t).toString('utf8');
      const typ = req.headers['content-type'] || '';
      if (!s) return ok({});
      try {
        if (typ.includes('json')) return ok(JSON.parse(s));
        if (typ.includes('x-www-form-urlencoded')) return ok(Object.fromEntries(new URLSearchParams(s)));
        try { return ok(JSON.parse(s)); } catch { return ok({ text: s }); }
      } catch (e) { nein(e); }
    });
  });
}
function schluesselOk(req, u, d) {
  const k = req.headers['x-schluessel'] || (req.headers.authorization || '').replace(/^Bearer\s+/i, '') || u.searchParams.get('schluessel') || d?.schluessel;
  return k && crypto.timingSafeEqual(Buffer.from(String(k).padEnd(64).slice(0, 64)), Buffer.from(EIN.schluessel.padEnd(64).slice(0, 64)));
}
function status() {
  return { verbunden: W.verbunden, qr: W.qr, nummer: W.nummer, name: W.name, fehler: W.fehler,
    ha: { an: !!(haUrl() && haToken()), verbunden: HA.verbunden, fehler: HA.fehler, url: haUrl() }, alexa: alexaStatus(), einstellungen: { ...EIN, ha_token: EIN.ha_token ? '••••••' : '' }, wartend: VERL.filter(v => v.status === 'wartet').length, gesamt: VERL.length };
}

http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;
  try {
    if (req.method === 'OPTIONS') return senden(res, 204, '');
    if (p === '/' || p === '/index.html') return senden(res, 200, SEITE, 'text/html; charset=utf-8');
    if (p === '/logo.svg') return senden(res, 200, LOGO, 'image/svg+xml');
    if (p === '/gesund') return senden(res, 200, { ok: true, verbunden: W.verbunden });
    if (p === '/api/status') return senden(res, 200, status());
    if (p === '/api/alexa') { await alexaLaden(u.searchParams.get('neu') === '1'); return senden(res, 200, alexaStatus()); }
    if (req.method === 'POST' && p === '/api/alexa/test') {
      await alexaLaden();
      const ziele = Object.entries((EIN.alexa || {}).geraete || {}).filter(([, an]) => an).map(([id]) => id);
      if (!ALEXA.mediaplayer) return senden(res, 400, { ok: false, text: 'Alexa Media Player ist in Home Assistant noch nicht eingerichtet' });
      if (!ziele.length) return senden(res, 400, { ok: false, text: 'Erst mindestens einen Echo einschalten' });
      await haApi('/api/services/notify/alexa_media', { message: 'Hallo, hier ist das Meldewerk. Ansagen funktionieren.', target: ziele, data: { type: 'announce' } });
      return senden(res, 200, { ok: true });
    }
    if (p === '/api/gruppen') {
      if (!W.verbunden) return senden(res, 200, { ok: false, liste: [], text: 'Nicht verbunden' });
      return senden(res, 200, { ok: true, liste: await gruppen(u.searchParams.get('neu') === '1') });
    }
    if (p === '/api/verlauf') {
      const q = (u.searchParams.get('q') || '').toLowerCase();
      const quelle = u.searchParams.get('quelle') || '';
      const max = Math.min(Number(u.searchParams.get('max') || 200), 2000);
      const liste = VERL.filter(v => (!quelle || v.quelle === quelle) && (!q || v.text.toLowerCase().includes(q))).slice(-max).reverse();
      return senden(res, 200, { liste, quellen: [...new Set(VERL.map(v => v.quelle))] });
    }
    if (p.startsWith('/bilder/')) {
      const name = path.basename(p);
      const f = path.join(BILDER, name);
      if (!/^[\w-]+\.jpg(?![\s\S])/.test(name) || !fs.existsSync(f)) return senden(res, 404, { ok: false });
      return senden(res, 200, fs.readFileSync(f), 'image/jpeg');
    }
    // Schnittstelle für SL, HA & Co. – GET (wie CallMeBot) oder POST
    if (p === '/api/senden') {
      const d = req.method === 'POST' ? await lesen(req) : Object.fromEntries(u.searchParams);
      if (!schluesselOk(req, u, d)) return senden(res, 401, { ok: false, text: 'Schlüssel fehlt oder falsch' });
      const e = await melden({ text: d.text ?? d.message, titel: d.titel ?? d.title, quelle: d.quelle, ziel: d.ziel ?? d.an, bild: d.bild || d.bild_url || d.image });
      return senden(res, e.status === 'fehler' ? 500 : 200, { ok: e.status !== 'fehler', status: e.status, id: e.id, fehler: e.fehler });
    }
    // Ab hier nur die eigene Oberfläche
    if (req.method === 'POST' && p === '/api/test') {
      const d = await lesen(req);
      const e = await melden({ text: d.text || 'Testnachricht vom Meldewerk', quelle: 'test', ziel: d.ziel });
      return senden(res, 200, { ok: e.status !== 'fehler', status: e.status, fehler: e.fehler });
    }
    if (req.method === 'POST' && p === '/api/einstellungen') {
      const d = await lesen(req);
      if ('empfaenger' in d) {
        const t = String(d.empfaenger || '').trim();
        EIN.empfaenger = t.endsWith('@g.us') ? t : t.replace(/[^\d+]/g, '');
        EIN.empfaenger_name = String(d.empfaenger_name || '').slice(0, 120);
      }
      if ('aufbewahrung_tage' in d) EIN.aufbewahrung_tage = Math.max(0, Number(d.aufbewahrung_tage) || 0);
      if ('absender_loeschen' in d) EIN.absender_loeschen = !!d.absender_loeschen;
      if ('archivieren' in d) EIN.archivieren = !!d.archivieren;
      if ('ha_url' in d || 'ha_token' in d) {
        if ('ha_url' in d) EIN.ha_url = String(d.ha_url || '').trim().replace(/\/+$/, '');
        if (d.ha_token && !/^•+$/.test(d.ha_token)) EIN.ha_token = String(d.ha_token).trim();
        if (d.ha_trennen) { EIN.ha_url = ''; EIN.ha_token = ''; }
        setTimeout(haVerbinden, 50);
      }
      if (d.alexa && typeof d.alexa === 'object') {
        const a = EIN.alexa = EIN.alexa || {};
        if (d.alexa.geraet) { a.geraete = a.geraete || {}; a.geraete[d.alexa.geraet] = !!d.alexa.an; }
        if (d.alexa.quelle) { a.quellen = a.quellen || {}; a.quellen[d.alexa.quelle] = !!d.alexa.an; }
        if ('ruhe' in d.alexa) a.ruhe = /^\d{1,2}-\d{1,2}$/.test(d.alexa.ruhe) ? d.alexa.ruhe : '';
      }
      if (d.neuer_schluessel) EIN.schluessel = crypto.randomBytes(16).toString('hex');
      einstSpeichern(EIN); aufraeumen();
      return senden(res, 200, status());
    }
    if (req.method === 'POST' && p === '/api/wiederholen') {
      const d = await lesen(req);
      const v = VERL.find(v => v.id === d.id);
      if (v) { v.status = 'wartet'; v.fehler = ''; await warteschlange(); }
      return senden(res, 200, { ok: !!v, status: v?.status });
    }
    if (req.method === 'POST' && p === '/api/verlauf_loeschen') {
      for (const v of VERL) if (v.bild) fs.rm(path.join(BILDER, v.bild), () => {});
      VERL = []; verlaufSchreiben();
      return senden(res, 200, { ok: true });
    }
    if (req.method === 'POST' && p === '/api/abmelden') {
      try { await W.sock?.logout(); } catch {}
      fs.rmSync(AUTH, { recursive: true, force: true });
      return senden(res, 200, { ok: true });
    }
    senden(res, 404, { ok: false, text: 'Nicht gefunden' });
  } catch (e) {
    senden(res, e.code === 400 ? 400 : 500, { ok: false, text: e.message });
  }
}).listen(PORT, () => console.log('Meldewerk läuft auf Port', PORT));

aufraeumen();
verbinden().catch(e => console.error('Start fehlgeschlagen:', e));
haVerbinden();
