// Paketwerk – Paketverfolgung für alle Bestellungen.
// Pakete kommen aus Versandmails (Gmail per IMAP), von Hand oder aus dem Rechnungs-Modul von SchichtLohn.
// Den Status holt es bei DHL (eigene Schnittstelle) und bei 17TRACK (alle anderen Versender),
// Änderungen gehen über das Meldewerk als WhatsApp und – je nach Einstellung – als Alexa-Ansage raus.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { ImapFlow } from 'imapflow';
import { simpleParser } from 'mailparser';

const HIER = path.dirname(fileURLToPath(import.meta.url));
const DATEN = process.env.DATEN || '/daten';
const PORT = Number(process.env.PORT || 8088);
const PAKETE = path.join(DATEN, 'pakete.json');
const EINST = path.join(DATEN, 'einstellungen.json');
const SEITE = () => fs.readFileSync(process.env.SEITE || path.join(HIER, 'index.html'), 'utf8');
fs.mkdirSync(DATEN, { recursive: true });

const LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="10.5" fill="#1d1f23"/>' +
  '<g transform="translate(24 24) scale(.82) translate(-24 -24)"><path fill="#e8e8ea" d="M24 5 41 14v20L24 43 7 34V14z"/>' +
  '<path fill="#1d1f23" d="M24 23 9.5 15.4 11 14.6 24 21.4 37 14.6l1.5.8zM23 24h2v17h-2z"/>' +
  '<path fill="#19d36b" d="M16 9.4 31.6 17.6v6.2l-4 2.1v-6.2L12.2 11.4z"/></g></svg>';

// ---------- Speicher ----------
function jsonLesen(datei, standard) { try { return JSON.parse(fs.readFileSync(datei, 'utf8')); } catch { return standard; } }
function jsonSchreiben(datei, wert) { fs.writeFileSync(datei + '.tmp', JSON.stringify(wert, null, 1)); fs.renameSync(datei + '.tmp', datei); }

const STANDARD = {
  imap_host: 'imap.gmail.com', imap_port: 993, imap_user: '', imap_pass: '', mail_tage: 14, mail_min: 10,
  dhl_key: '', t17_key: '', intervall_min: 45,
  mw_url: process.env.MW_URL || 'http://192.168.1.30:8077', mw_schluessel: '',
  sl_url: process.env.SL_URL || 'http://192.168.1.30:8093', sl_token: '', rechnungen: true, rechnung_tage: 14,
  archiv_tage: 3,
  melden: { unterwegs: false, zoll: true, zustellung: true, abholbereit: true, zugestellt: true, problem: true },
  alexa: { zustellung: true, zugestellt: true, abholbereit: false, problem: false },
};
const GEHEIM = ['imap_pass', 'dhl_key', 't17_key', 'mw_schluessel', 'sl_token'];
const MASKE = '••••••';
let EIN = { ...STANDARD, ...jsonLesen(EINST, {}) };
EIN.melden = { ...STANDARD.melden, ...(EIN.melden || {}) };
EIN.alexa = { ...STANDARD.alexa, ...(EIN.alexa || {}) };
// Schlüssel können auch in der .env des Stacks stehen (T17_KEY, DHL_KEY, IMAP_PASS, MW_SCHLUESSEL)
for (const [k, v] of [['t17_key', 'T17_KEY'], ['dhl_key', 'DHL_KEY'], ['imap_pass', 'IMAP_PASS'], ['mw_schluessel', 'MW_SCHLUESSEL']]) if (!EIN[k] && process.env[v]) EIN[k] = process.env[v];

let DB = jsonLesen(PAKETE, null) || { pakete: [], ignoriert: [], mails: [], dhl_tag: '', dhl_anzahl: 0 };
const ZUSTAND = { mail: { zeit: 0, fehler: '', neu: 0 }, rechnungen: { zeit: 0, fehler: '', neu: 0 }, abfrage: { zeit: 0, fehler: '' } };
function speichern() {
  DB.mails = DB.mails.slice(-3000);
  DB.ignoriert = DB.ignoriert.slice(-1000);
  jsonSchreiben(PAKETE, DB);
}

// ---------- Versender ----------
export const TRAEGER = {
  dhl: { name: 'DHL', link: n => 'https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode=' + n },
  hermes: { name: 'Hermes', link: n => 'https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation#' + n },
  dpd: { name: 'DPD', link: n => 'https://tracking.dpd.de/status/de_DE/parcel/' + n },
  gls: { name: 'GLS', link: n => 'https://www.gls-pakete.de/sendungsverfolgung?trackingNumber=' + n },
  ups: { name: 'UPS', link: n => 'https://www.ups.com/track?loc=de_DE&tracknum=' + n },
  amazon: { name: 'Amazon', link: n => 'https://track.amazon.de/tracking/' + n },
  cainiao: { name: 'Cainiao', link: n => 'https://global.cainiao.com/newDetail.htm?mailNoList=' + n },
  post: { name: 'Post', link: n => 'https://www.deutschepost.de/de/s/sendungsverfolgung.html?piececode=' + n },
  sonst: { name: 'Paket', link: n => 'https://t.17track.net/de#nums=' + n },
};
const HINWEIS = [['dhl', /\bdhl\b/i], ['hermes', /hermes/i], ['dpd', /\bdpd\b/i], ['gls', /\bgls\b/i], ['ups', /\bups\b/i], ['cainiao', /cainiao/i]];
export function traegerRaten(n, text = '') {
  if (/^1Z[0-9A-Z]{16}$/.test(n)) return 'ups';
  if (/^TBA\d{12}$/.test(n)) return 'amazon';
  if (/^(00340434|00340433)\d{12}$/.test(n) || /^JJD\d{16,20}$/.test(n)) return 'dhl';
  if (/^(LP|CN|CAINIAO)[0-9A-Z]{8,}$/.test(n)) return 'cainiao';
  if (/^H\d{19}$/.test(n)) return 'hermes';
  if (/^[A-Z]{2}\d{9}DE$/.test(n)) return 'post';
  for (const [t, re] of HINWEIS) if (re.test(text)) return t;
  if (/^[A-Z]{2}\d{9}[A-Z]{2}$/.test(n)) return 'sonst';
  if (/^0\d{13}$/.test(n)) return 'dpd';
  if (/^\d{12}$/.test(n) || /^\d{20}$/.test(n)) return 'dhl';
  if (/^\d{11}$/.test(n)) return 'gls';
  if (/^\d{14}$/.test(n)) return 'hermes';
  return 'sonst';
}

// ---------- Sendungsnummern aus Mails ----------
const URLS = [
  [/dhl\.[a-z.]+\/[^\s"'<>]*?(?:piececode|idc|tracking-id|trackingnumber|tracking-number)=([A-Z0-9]{10,39})/gi, 'dhl'],
  [/dpd\.[a-z.]+\/[^\s"'<>]*?parcel\/(\d{14})/gi, 'dpd'],
  [/dpd\.[a-z.]+\/[^\s"'<>]*?(?:parcelNumber|parcelno|query)=(\d{14})/gi, 'dpd'],
  [/hermes[a-z.-]*\.[a-z]+\/[^\s"'<>]*?(?:#|=|\/)(H?\d{14,20})\b/gi, 'hermes'],
  [/gls-[a-z.-]+\/[^\s"'<>]*?(?:match|trackingNumber|trackingnumber)=(\d{11,14})/gi, 'gls'],
  [/ups\.com\/[^\s"'<>]*?(?:tracknum|InquiryNumber1)=(1Z[0-9A-Z]{16})/gi, 'ups'],
  [/cainiao\.com\/[^\s"'<>]*?mailNoList=([A-Z0-9]{8,30})/gi, 'cainiao'],
  [/17track\.net\/[^\s"'<>]*?nums=([A-Z0-9]{8,30})/gi, ''],
];
const STARK = [/\b1Z[0-9A-Z]{16}\b/g, /\bTBA\d{12}\b/g, /\b0034043[34]\d{12}\b/g, /\bJJD\d{16,20}\b/g, /\b[A-Z]{2}\d{9}[A-Z]{2}\b/g, /\bLP\d{14}\b/g];
const WORT = /(?:Sendungsnummer|Sendungs-Nr\.?|Sendungsverfolgungsnummer|Trackingnummer|Tracking-Nummer|Tracking-ID|Tracking ID|Tracking number|Tracking No\.?|Paketnummer|Paket-Nr\.?)\s*[:#]?\s*([A-Z0-9]{8,30})\b/gi;

export function nummernFinden(text, html = '') {
  const gefunden = new Map();
  const dazu = (n, t) => {
    n = String(n).toUpperCase();
    if ((n.match(/\d/g) || []).length < 8 || gefunden.has(n)) return;
    gefunden.set(n, t || traegerRaten(n, text));
  };
  const alles = text + '\n' + html;
  for (const [re, t] of URLS) for (const m of alles.matchAll(re)) dazu(m[1], t);
  for (const re of STARK) for (const m of text.matchAll(re)) dazu(m[0]);
  for (const m of text.matchAll(WORT)) dazu(m[1]);
  return [...gefunden].map(([nummer, traeger]) => ({ nummer, traeger }));
}
export function shopErkennen(text, von = '') {
  const t = (von + ' ' + text).toLowerCase();
  if (/amazon\.|amazon logistics/.test(t)) return 'amazon';
  if (/aliexpress/.test(t)) return 'aliexpress';
  if (/bambulab|bambu lab/.test(t)) return 'bambu';
  return '';
}
export function bestellungFinden(text, shop) {
  if (shop === 'amazon') return (text.match(/\b\d{3}-\d{7}-\d{7}\b/) || [])[0] || '';
  if (shop === 'aliexpress') return (text.match(/(?:Bestell(?:nummer|ung)|Order(?: ID| number| No\.?)?)\D{0,20}(\d{15,17})/i) || [])[1] || '';
  return (text.match(/(?:Bestellnummer|Bestellung|Order(?: number| No\.?)?)\s*[:#]?\s*#?([A-Z0-9][A-Z0-9-]{4,24})\b/i) || [])[1] || '';
}
export function mailStatus(betreff, text) {
  const b = betreff.toLowerCase(), t = text.slice(0, 800).toLowerCase();
  // Der Betreff sagt am zuverlässigsten, worum es geht
  if (/zugestellt|geliefert|delivered|angekommen/.test(b) && !/wird|voraussichtlich|kommt/.test(b)) return 'zugestellt';
  if (/abholbereit|zur abholung|abholen|ready for pickup/.test(b)) return 'abholbereit';
  if (/heute|in zustellung|out for delivery|zustellfahrzeug/.test(b)) return 'zustellung';
  if (/versandt|versendet|verschickt|unterwegs|shipped|dispatched|auf dem weg/.test(b)) return 'unterwegs';
  if (/wurde (heute )?(zugestellt|geliefert)|has been delivered|ist angekommen/.test(t)) return 'zugestellt';
  if (/liegt (zur abholung )?bereit|ist abholbereit|ready for pickup/.test(t)) return 'abholbereit';
  if (/kommt heute|wird heute zugestellt|in zustellung|out for delivery/.test(t)) return 'zustellung';
  if (/wurde versandt|wurde verschickt|ist unterwegs|has been shipped|has shipped/.test(t)) return 'unterwegs';
  return '';
}
const RELEVANT = /versand|versendet|verschickt|unterwegs|zugestellt|zustellung|liefer|geliefert|sendung|paket|shipped|shipment|tracking|delivered|dispatched|abholbereit/i;

// ---------- Pakete ----------
const RANG = { bestellt: 0, angekuendigt: 1, unterwegs: 2, zoll: 2, problem: 3, abholbereit: 3, zustellung: 3, zugestellt: 4 };
const TEXT = {
  bestellt: 'bestellt', angekuendigt: 'angekündigt', unterwegs: 'unterwegs', zoll: 'beim Zoll', zustellung: 'kommt heute',
  abholbereit: 'liegt zur Abholung bereit', zugestellt: 'zugestellt', problem: 'hat ein Problem',
};
const kurz = s => String(s || '').replace(/\s+/g, ' ').trim();
function neuesPaket(d) {
  const p = {
    id: crypto.randomUUID(), nummer: '', traeger: '', titel: '', shop: '', bestellung: '', quelle: 'hand',
    status: 'bestellt', ereignisse: [], erwartet: '', angelegt: Date.now(), geaendert: Date.now(), abgefragt: 0,
    archiviert: false, fehler: '', t17: false, ...d,
  };
  if (p.nummer && !p.traeger) p.traeger = traegerRaten(p.nummer);
  if (p.nummer && p.status === 'bestellt') p.status = 'angekuendigt';
  DB.pakete.unshift(p);
  return p;
}
const name = p => kurz(p.titel) || (TRAEGER[p.traeger]?.name || 'Paket') + ' ' + (p.nummer || p.bestellung);

async function statusSetzen(p, neu, { stumm = false, info = '' } = {}) {
  if (!neu || neu === p.status) return;
  const alt = p.status;
  p.status = neu;
  p.geaendert = Date.now();
  if (neu !== 'zugestellt') p.archiviert = false;
  if (stumm || !EIN.melden[neu]) return;
  const versender = TRAEGER[p.traeger]?.name || ({ amazon: 'Amazon', aliexpress: 'AliExpress', bambu: 'Bambu Lab' })[p.shop] || 'Paket';
  const text = '📦 ' + versender + ': ' + name(p) + (info ? '\n' + info : '');
  const titel = 'Paket ' + TEXT[neu];
  try { await melden(titel, text, !!EIN.alexa[neu]); }
  catch (e) { console.warn('Meldewerk:', e.message, '(vorher', alt + ')'); }
}
async function melden(titel, text, alexa) {
  if (!EIN.mw_url || !EIN.mw_schluessel) throw new Error('Meldewerk nicht eingerichtet');
  const r = await fetch(EIN.mw_url.replace(/\/+$/, '') + '/api/senden', {
    method: 'POST', headers: { 'content-type': 'application/json', 'x-schluessel': EIN.mw_schluessel },
    body: JSON.stringify({ titel, text, quelle: 'paketwerk', alexa }), signal: AbortSignal.timeout(20000),
  });
  if (!r.ok) throw new Error('Meldewerk antwortet ' + r.status);
}

// ---------- Status abfragen ----------
function dhlStatus(s) {
  const code = s?.status?.statusCode, d = (s?.status?.description || s?.status?.status || '').toLowerCase();
  if (code === 'delivered') return 'zugestellt';
  if (code === 'failure') return 'problem';
  if (/filiale|packstation|abholbereit|abholung/.test(d)) return 'abholbereit';
  if (/zustellfahrzeug|in zustellung|out for delivery|wird heute/.test(d)) return 'zustellung';
  if (code === 'transit') return 'unterwegs';
  return 'angekuendigt';
}
async function dhlAbfragen(p) {
  const heute = new Date().toISOString().slice(0, 10);
  if (DB.dhl_tag !== heute) { DB.dhl_tag = heute; DB.dhl_anzahl = 0; }
  if (DB.dhl_anzahl >= 240) throw new Error('DHL-Tageskontingent aufgebraucht');
  DB.dhl_anzahl++;
  const r = await fetch('https://api-eu.dhl.com/track/shipments?language=de&trackingNumber=' + encodeURIComponent(p.nummer),
    { headers: { 'DHL-API-Key': EIN.dhl_key, accept: 'application/json' }, signal: AbortSignal.timeout(20000) });
  if (r.status === 404) return { status: p.status === 'bestellt' ? 'angekuendigt' : p.status, ereignisse: p.ereignisse, hinweis: 'DHL kennt die Nummer noch nicht' };
  if (r.status === 401 || r.status === 403) throw new Error('DHL-Schlüssel noch nicht freigeschaltet (kann bis zu 24 Std. dauern)');
  if (!r.ok) throw new Error('DHL antwortet ' + r.status);
  const s = (await r.json()).shipments?.[0];
  if (!s) return null;
  return {
    status: dhlStatus(s),
    erwartet: s.estimatedTimeOfDelivery || s.estimatedDeliveryTimeFrame?.estimatedFrom || '',
    ereignisse: (s.events || []).map(e => ({ zeit: e.timestamp, text: kurz(e.description || e.status), ort: kurz(e.location?.address?.addressLocality) })),
  };
}
const T17 = { NotFound: 'angekuendigt', InfoReceived: 'angekuendigt', InTransit: 'unterwegs', AvailableForPickup: 'abholbereit', OutForDelivery: 'zustellung', DeliveryFailure: 'problem', Exception: 'problem', Expired: 'problem', Delivered: 'zugestellt' };
async function t17(pfad, body) {
  const r = await fetch('https://api.17track.net/track/v2.2/' + pfad, {
    method: 'POST', headers: { '17token': EIN.t17_key, 'content-type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(25000),
  });
  if (!r.ok) throw new Error('17TRACK antwortet ' + r.status);
  const j = await r.json();
  if (j.code !== 0) throw new Error('17TRACK: ' + (j.data?.errors?.[0]?.message || 'Fehler ' + j.code));
  return j.data || {};
}
const T17_CODE = { dhl: 7041, post: 7041 };
async function t17Abfragen(p, carrier) {
  if (!p.t17) {
    const d = await t17('register', [{ number: p.nummer, lang: 'de', ...(carrier ? { carrier } : {}) }]);
    const abgelehnt = d.rejected?.[0];
    if (abgelehnt && abgelehnt.error?.code !== -18019901) throw new Error('17TRACK: ' + (abgelehnt.error?.message || 'Nummer abgelehnt'));
    p.t17 = true;
  }
  const t = (await t17('gettrackinfo', [{ number: p.nummer, ...(carrier ? { carrier } : {}) }])).accepted?.[0]?.track_info;
  if (!t) return null;
  const ls = t.latest_status || {};
  let status = T17[ls.status] || 'angekuendigt';
  if (status === 'unterwegs' && /Customs/i.test(ls.sub_status || '')) status = 'zoll';
  const ev = (t.tracking?.providers || []).flatMap(pr => pr.events || []);
  return {
    status,
    erwartet: t.time_metrics?.estimated_delivery_date?.from || '',
    ereignisse: ev.map(e => ({ zeit: e.time_iso || e.time_utc, text: kurz(e.description), ort: kurz(e.location) })),
  };
}
async function abfragen(p) {
  if (!p.nummer) return;
  p.abgefragt = Date.now();
  // Amazon-eigene Sendungen (TBA…) laufen nur über die Amazon-Mails – spart das 17TRACK-Kontingent
  if (p.traeger === 'amazon') { p.fehler = ''; return; }
  let erg = null;
  try {
    // DHL/Post: mit eigenem DHL-Schlüssel direkt, sonst über 17TRACK mit fester Versender-Kennung (DHL Paket = 7041)
    if ((p.traeger === 'dhl' || p.traeger === 'post') && EIN.dhl_key && !DB.dhl_gesperrt) {
      try { erg = await dhlAbfragen(p); }
      catch (e) { if (!/freigeschaltet/.test(e.message) || !EIN.t17_key) throw e; DB.dhl_gesperrt = true; }
    }
    if (!erg && EIN.t17_key) erg = await t17Abfragen(p, T17_CODE[p.traeger]);
    else if (!erg) { p.fehler = 'Kein Schlüssel für ' + (TRAEGER[p.traeger]?.name || 'diesen Versender') + ' – nur Link'; return; }
    p.fehler = erg?.hinweis || '';
  } catch (e) { p.fehler = /fetch failed|abort|timeout/i.test(e.message + e.cause) ? 'Versender gerade nicht erreichbar' : e.message; ZUSTAND.abfrage.fehler = p.fehler; return; }
  if (!erg) return;
  if (erg.ereignisse?.length) p.ereignisse = erg.ereignisse.filter(e => e.zeit || e.text).sort((a, b) => String(b.zeit).localeCompare(String(a.zeit))).slice(0, 40);
  if (erg.erwartet) p.erwartet = erg.erwartet;
  const info = p.ereignisse[0]?.text && erg.status !== 'zugestellt' ? p.ereignisse[0].text : '';
  await statusSetzen(p, erg.status, { info });
}

// ---------- Mails ----------
let mailLaeuft = false;
async function mailsPruefen() {
  if (mailLaeuft || !EIN.imap_user || !EIN.imap_pass) return;
  mailLaeuft = true;
  const imap = new ImapFlow({ host: EIN.imap_host, port: Number(EIN.imap_port) || 993, secure: true, auth: { user: EIN.imap_user, pass: EIN.imap_pass }, logger: false });
  let neu = 0;
  try {
    await imap.connect();
    // Gmail: „Alle Nachrichten“ + Spam durchsuchen, damit Mails in Labels/Ordnern und Fehlsortiertes nicht fehlen
    const ordner = await imap.list();
    const alle = ordner.find(o => o.specialUse === '\\All')?.path;
    const spam = ordner.find(o => o.specialUse === '\\Junk')?.path;
    const postfaecher = [alle || 'INBOX', spam].filter(Boolean);
    const seit = new Date(Date.now() - (Number(EIN.mail_tage) || 14) * 86400000);
    const gesehen = new Set(DB.mails);
    for (const box of postfaecher) {
      const lock = await imap.getMailboxLock(box);
      try {
        const uids = await imap.search({ since: seit }, { uid: true });
        const kopf = [];
        if (uids.length) for await (const m of imap.fetch(uids, { envelope: true, uid: true }, { uid: true })) kopf.push(m);
        for (const m of kopf) {
          const mid = m.envelope?.messageId || box + ':uid:' + m.uid;
          if (gesehen.has(mid)) continue;
          DB.mails.push(mid); gesehen.add(mid);
          if (!RELEVANT.test(m.envelope?.subject || '')) continue;
          const voll = await imap.fetchOne(m.uid, { source: true }, { uid: true });
          if (!voll?.source) continue;
          const mail = await simpleParser(voll.source);
          neu += await mailAuswerten(mail);
        }
      } finally { lock.release(); }
    }
    await imap.logout();
    ZUSTAND.mail = { zeit: Date.now(), fehler: '', neu };
  } catch (e) {
    ZUSTAND.mail = { zeit: Date.now(), fehler: /auth|credential|login/i.test(e.message + (e.responseText || '')) ? 'Anmeldung bei Gmail fehlgeschlagen – App-Passwort prüfen' : e.message, neu };
    try { imap.close(); } catch {}
  } finally { mailLaeuft = false; speichern(); }
}
async function mailAuswerten(mail) {
  const betreff = kurz(mail.subject);
  const text = (mail.text || '').slice(0, 60000);
  const html = typeof mail.html === 'string' ? mail.html.slice(0, 200000) : '';
  const von = mail.from?.text || '';
  const shop = shopErkennen(text + ' ' + html.slice(0, 20000), von);
  const bestellung = bestellungFinden(betreff + '\n' + text, shop);
  const nummern = nummernFinden(text, html).filter(n => n.nummer !== bestellung.replace(/-/g, ''));
  const st = mailStatus(betreff, text);
  const alt = Date.now() - (mail.date ? +mail.date : Date.now()) > 12 * 3600000; // ältere Mails melden nicht
  const titel = kurz((betreff.match(/[„"»](.{3,80}?)[“"«]/) || [])[1] || '');
  let neu = 0;
  if (!nummern.length && !(bestellung && st)) return 0;
  for (const { nummer, traeger } of nummern) {
    let p = DB.pakete.find(x => x.nummer === nummer);
    if (!p) {
      p = DB.pakete.find(x => !x.nummer && bestellung && x.bestellung === bestellung);
      if (p) { p.nummer = nummer; p.traeger = traeger; if (p.status === 'bestellt') p.status = 'angekuendigt'; }
      else if (DB.ignoriert.includes(nummer)) continue;
      else { p = neuesPaket({ nummer, traeger, titel: titel || betreff.slice(0, 80), shop, bestellung, quelle: 'mail', status: 'angekuendigt' }); neu++; }
    }
    if (st && RANG[st] > RANG[p.status]) await statusSetzen(p, st, { stumm: alt });
    if (!alt) p.abgefragt = 0; // gleich nachsehen
  }
  if (!nummern.length && bestellung) {
    let p = DB.pakete.find(x => x.bestellung === bestellung && x.status !== 'zugestellt');
    if (!p && !DB.ignoriert.includes(bestellung) && st !== 'zugestellt') {
      p = neuesPaket({ titel: titel || betreff.slice(0, 80), shop, bestellung, quelle: 'mail', traeger: shop === 'amazon' ? 'amazon' : '' }); neu++;
    }
    if (p && RANG[st] > RANG[p.status]) await statusSetzen(p, st, { stumm: alt });
  }
  return neu;
}

// ---------- Rechnungs-Modul (SchichtLohn) ----------
async function rechnungenHolen() {
  if (!EIN.rechnungen || !EIN.sl_url) return;
  const grenze = Date.now() - (Number(EIN.rechnung_tage) || 14) * 86400000;
  let neu = 0;
  try {
    for (const src of ['amazon', 'aliexpress', 'bambu']) {
      const r = await fetch(EIN.sl_url.replace(/\/+$/, '') + '/api/listen/rechnungen_' + src,
        { headers: EIN.sl_token ? { 'x-token': EIN.sl_token } : {}, signal: AbortSignal.timeout(20000) });
      if (!r.ok) throw new Error('SchichtLohn antwortet ' + r.status);
      for (const it of (await r.json()).items || []) {
        let j; try { j = JSON.parse(it.description || ''); } catch { continue; }
        if (!j?.o || j.storno || j.typ === 'erstattung') continue;
        const t = Date.parse(j.d || '');
        if (!t || t < grenze) continue;
        const o = String(j.o);
        if (DB.ignoriert.includes(o) || DB.pakete.some(p => p.bestellung === o)) continue;
        const pos = (j.items || []).map(a => Array.isArray(a) ? a[0] : a?.n).filter(Boolean);
        const titel = kurz(pos[0] || it.summary || 'Bestellung ' + o).slice(0, 70) + (pos.length > 1 ? ' +' + (pos.length - 1) : '');
        neuesPaket({ titel, shop: src, bestellung: o, quelle: 'rechnung', angelegt: t, traeger: src === 'amazon' ? 'amazon' : '' });
        neu++;
      }
    }
    ZUSTAND.rechnungen = { zeit: Date.now(), fehler: '', neu };
  } catch (e) { ZUSTAND.rechnungen = { zeit: Date.now(), fehler: /fetch failed|ECONN|abort|timeout/i.test(e.message + e.cause) ? 'SchichtLohn nicht erreichbar' : e.message, neu }; }
  if (neu) speichern();
}

// ---------- Ablauf ----------
let letzteMail = 0, letzteRechnung = 0, laeuft = false;
async function runde() {
  if (laeuft) return;
  laeuft = true;
  try {
    const jetzt = Date.now();
    if (jetzt - letzteMail > (Number(EIN.mail_min) || 10) * 60000) { letzteMail = jetzt; await mailsPruefen(); }
    if (jetzt - letzteRechnung > 15 * 60000) { letzteRechnung = jetzt; await rechnungenHolen(); }
    const takt = (Number(EIN.intervall_min) || 45) * 60000;
    for (const p of DB.pakete) {
      if (p.archiviert || !p.nummer || p.status === 'zugestellt' || p.traeger === 'amazon') continue;
      const faellig = p.status === 'zustellung' ? Math.min(takt, 20 * 60000) : takt;
      if (Date.now() - p.abgefragt > faellig) await abfragen(p);
    }
    ZUSTAND.abfrage.zeit = Date.now();
    const archivGrenze = Date.now() - (Number(EIN.archiv_tage) || 3) * 86400000;
    for (const p of DB.pakete) if (!p.archiviert && p.status === 'zugestellt' && p.geaendert < archivGrenze) p.archiviert = true;
    // Bestellungen ohne Sendung nach 30 Tagen ins Archiv
    for (const p of DB.pakete) if (!p.archiviert && !p.nummer && p.status === 'bestellt' && p.angelegt < Date.now() - 30 * 86400000) p.archiviert = true;
    DB.pakete = DB.pakete.filter(p => !p.archiviert || p.geaendert > Date.now() - 120 * 86400000);
    speichern();
  } catch (e) { console.warn('Runde:', e.message); }
  finally { laeuft = false; }
}
setInterval(runde, 60000);
setTimeout(runde, 3000);

// ---------- Web ----------
function senden(res, code, body, typ = 'application/json; charset=utf-8') {
  res.writeHead(code, { 'content-type': typ, 'cache-control': 'no-store', 'access-control-allow-origin': '*', 'access-control-allow-headers': 'content-type' });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
}
async function lesen(req) {
  let b = '';
  for await (const s of req) { b += s; if (b.length > 1e6) throw new Error('zu groß'); }
  try { return JSON.parse(b || '{}'); } catch { return {}; }
}
function oeffentlich() {
  const e = { ...EIN };
  for (const k of GEHEIM) e[k] = e[k] ? MASKE : '';
  return e;
}
function bestellLink(p) {
  if (!p.bestellung) return '';
  if (p.shop === 'amazon') return 'https://www.amazon.de/gp/your-account/order-details?orderID=' + p.bestellung;
  if (p.shop === 'aliexpress') return 'https://www.aliexpress.com/p/order/detail.html?orderId=' + p.bestellung;
  return '';
}
function stand() {
  return {
    pakete: DB.pakete.map(p => ({ ...p, link: p.nummer ? (TRAEGER[p.traeger] || TRAEGER.sonst).link(p.nummer) : bestellLink(p) })),
    einstellungen: oeffentlich(), zustand: ZUSTAND, dhl_heute: DB.dhl_tag === new Date().toISOString().slice(0, 10) ? DB.dhl_anzahl : 0,
    traeger: Object.fromEntries(Object.entries(TRAEGER).map(([k, v]) => [k, v.name])),
  };
}

http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;
  try {
    if (req.method === 'OPTIONS') return senden(res, 204, '');
    if (p === '/' || p === '/index.html') return senden(res, 200, SEITE(), 'text/html; charset=utf-8');
    if (p === '/logo.svg') return senden(res, 200, LOGO, 'image/svg+xml');
    if (p === '/gesund') return senden(res, 200, { ok: true });
    if (p === '/api/stand') return senden(res, 200, stand());

    if (req.method === 'POST' && p === '/api/pakete') {
      const d = await lesen(req);
      const nummer = kurz(d.nummer).replace(/\s/g, '').toUpperCase();
      if (!nummer) return senden(res, 400, { ok: false, text: 'Sendungsnummer fehlt' });
      let pk = DB.pakete.find(x => x.nummer === nummer);
      if (pk) return senden(res, 409, { ok: false, text: 'Diese Sendung gibt es schon', id: pk.id });
      DB.ignoriert = DB.ignoriert.filter(x => x !== nummer);
      pk = neuesPaket({ nummer, titel: kurz(d.titel).slice(0, 80), traeger: TRAEGER[d.traeger] ? d.traeger : traegerRaten(nummer), quelle: 'hand' });
      await abfragen(pk); speichern();
      return senden(res, 200, { ok: true, id: pk.id });
    }
    const m = p.match(/^\/api\/pakete\/([\w-]+)(?:\/(aktualisieren))?$/);
    if (m) {
      const pk = DB.pakete.find(x => x.id === m[1]);
      if (!pk) return senden(res, 404, { ok: false, text: 'Paket nicht gefunden' });
      if (req.method === 'DELETE') {
        if (pk.nummer) DB.ignoriert.push(pk.nummer);
        if (pk.bestellung) DB.ignoriert.push(pk.bestellung);
        DB.pakete = DB.pakete.filter(x => x !== pk); speichern();
        return senden(res, 200, { ok: true });
      }
      if (req.method === 'POST' && m[2]) { await abfragen(pk); speichern(); return senden(res, 200, { ok: true, fehler: pk.fehler }); }
      if (req.method === 'POST') {
        const d = await lesen(req);
        if (typeof d.titel === 'string') pk.titel = kurz(d.titel).slice(0, 80);
        if (typeof d.archiviert === 'boolean') pk.archiviert = d.archiviert;
        if (d.traeger && TRAEGER[d.traeger]) { pk.traeger = d.traeger; pk.t17 = false; }
        if (typeof d.nummer === 'string') {
          const n = d.nummer.replace(/\s/g, '').toUpperCase();
          if (n !== pk.nummer) {
            pk.nummer = n; pk.t17 = false; pk.ereignisse = []; pk.fehler = '';
            if (n && !d.traeger) pk.traeger = traegerRaten(n);
            if (n && pk.status === 'bestellt') pk.status = 'angekuendigt';
            if (n) await abfragen(pk);
          }
        }
        speichern();
        return senden(res, 200, { ok: true });
      }
    }
    if (req.method === 'POST' && p === '/api/aktualisieren') {
      for (const x of DB.pakete) x.abgefragt = 0;
      letzteMail = 0; letzteRechnung = 0;
      await runde();
      return senden(res, 200, { ok: true, zustand: ZUSTAND });
    }
    if (req.method === 'POST' && p === '/api/einstellungen') {
      const d = await lesen(req);
      for (const k of Object.keys(STANDARD)) {
        if (!(k in d)) continue;
        if (GEHEIM.includes(k) && d[k] === MASKE) continue;
        if (k === 'melden' || k === 'alexa') EIN[k] = { ...EIN[k], ...d[k] };
        else EIN[k] = typeof STANDARD[k] === 'number' ? Number(d[k]) || STANDARD[k] : typeof STANDARD[k] === 'boolean' ? !!d[k] : String(d[k]).trim();
      }
      if (d.dhl_key && d.dhl_key !== MASKE) DB.dhl_gesperrt = false; // neuer DHL-Schlüssel: wieder probieren
      jsonSchreiben(EINST, EIN);
      letzteMail = 0; letzteRechnung = 0;
      setTimeout(runde, 500);
      return senden(res, 200, { ok: true, einstellungen: oeffentlich() });
    }
    if (req.method === 'POST' && p === '/api/test') {
      const d = await lesen(req);
      try { await melden('Paket zugestellt', '📦 Testmeldung aus dem Paketwerk', !!d.alexa); return senden(res, 200, { ok: true }); }
      catch (e) { return senden(res, 200, { ok: false, text: e.message }); }
    }
    return senden(res, 404, { ok: false, text: 'Nicht gefunden' });
  } catch (e) {
    console.warn(e);
    return senden(res, 500, { ok: false, text: e.message });
  }
}).listen(PORT, () => console.log('Paketwerk läuft auf Port', PORT));
