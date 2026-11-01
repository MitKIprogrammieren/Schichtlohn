// Bambu-Rechnungen – Home-Assistant-Karte (custom:bambu-rechnungen-card)
// Speicher: SchichtLohn-Server (Listen rechnungen_bambu/_amazon/_aliexpress, über HA-Ingress), eine Rechnung pro Eintrag, JSON in der Beschreibung.
// Die To-do-Listen todo.*_rechnungen sind nur noch der Eingang für die Bestellmail-Automationen: die Karte holt neue Einträge
// (Bestellungen und Erstattungen) beim Öffnen ab, trägt sie auf dem Server ein und leert den Eingang.
// Neue Rechnung: PDF aus dem Bambu Lab EU-Store auf die Karte ziehen oder auswählen → wird gelesen, eingetragen
// und die Filamentpreise (bezahlter Preis pro Rolle) über die Farbnummer ins SchichtLohn-Lager geschrieben.
// Optionen: entity (Standard todo.bambu_rechnungen), lager_app (Standard 7c128fa3_schichtlohn), preise_ins_lager (true)
(()=>{
const VERSION='2.1.1';
const PB_LEER="data:image/svg+xml,"+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#9aa0a6" stroke-width="1.4" stroke-linejoin="round"><path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/></svg>');
const SL_LISTE={bambu:'rechnungen_bambu',amazon:'rechnungen_amazon',aliexpress:'rechnungen_aliexpress'};
const SEITE=150;
/* Erstattung aus der Mail auf eine Bestellung anwenden (gleiche Regeln wie früher in der Automation); null = schon gezählt */
function erstattungAnwenden(j,e){const refs=j.refs||[];const key=e.datum+'|'+e.betrag;if(refs.includes(key))return null;
  const alt=+j.erst||0,b=+e.betrag||0;const ne=(!refs.length&&Math.abs(alt-b)<0.01)?alt:alt+b;let tr=false;
  let items=(j.items||[]).map(a=>{const hit=(e.asin&&a[4]===e.asin)||(e.titel&&String(a[0]).slice(0,35).toLowerCase()===String(e.titel).slice(0,35).toLowerCase());if(hit)tr=true;return [a[0],a[1],a[2],a[3],a[4],hit?1:(a.length>5?a[5]:0)]});
  if(!tr&&ne>=(+j.net||0)-0.01)items=items.map(a=>[...a.slice(0,5),1]);
  return Object.assign({},j,{erst:Math.round(ne*100)/100,refs:[...refs,key],items})}
const PDFJS='https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/';

function blParsePages(pages){
  const all=pages.flat(), txt=all.map(i=>i.s).join(' ');
  const g=re=>{const m=txt.match(re);return m?m[1]:null}, f=s=>s==null?null:parseFloat(s);
  const find=(p,s)=>p.find(i=>i.s.trim()===s);
  const rec={i:g(/Invoice Number:\s*(\S+)/),o:g(/Order Number:\s*(EN\d+)/),d:g(/Payment Date:\s*(\d{4}-\d{2}-\d{2})/),m:g(/#([A-Za-z]+)/)};
  const after=lab=>{const pg=pages.find(p=>p.some(i=>i.s.trim()===lab));if(!pg)return null;const it=pg.find(i=>i.s.trim()===lab);const c=pg.filter(j=>Math.abs(j.y-it.y)<3&&j.x>it.x&&/^-?€[\d.]+$/.test(j.s.trim())).sort((a,b)=>b.x-a.x)[0];return c?f(c.s.replace(/[€]/g,'')):null};
  rec.sub=after('Items Subtotal');rec.ship=after('Shipping')||0;rec.tot=after('Grand total');rec.net=after('Net payment');
  const items=[];
  for(const p of pages){
    const q=find(p,'Qty'); if(!q) continue;
    const top=q.y-4, endIt=find(p,'Items Subtotal'), bottom=endIt?endIt.y+4:60;
    const inT=i=>i.y<top&&i.y>bottom;
    const rows=[];
    p.filter(i=>inT(i)&&i.x<q.x-20&&i.s.trim()).sort((a,b)=>b.y-a.y||a.x-b.x).forEach(i=>{const r=rows.find(r=>Math.abs(r.y-i.y)<2.5);if(r){r.s+=(i.x-r.e>1.5?' ':'')+i.s;r.e=i.x+i.w}else rows.push({y:i.y,s:i.s,e:i.x+i.w})});
    const groups=[];rows.forEach(r=>{const last=groups[groups.length-1];if(last&&last[last.length-1].y-r.y<20)last.push(r);else groups.push([r])});
    for(const gr of groups){
      const k=gr.findIndex(r=>/^SKU:/.test(r.s.trim())); if(k<0) continue;
      const name=gr.slice(0,k).map(r=>r.s.trim()).join(' ');
      const vi=gr.findIndex(r=>/^Variant:/.test(r.s.trim()));
      const variant=vi<0?'':gr.slice(vi).map(r=>r.s.trim()).join(' ').replace(/^Variant:\s*/,'');
      const yHi=gr[0].y+6, yLo=gr[gr.length-1].y-6;
      const qc=p.find(i=>inT(i)&&/^\d+$/.test(i.s.trim())&&Math.abs(i.x-q.x)<25&&i.y<=yHi&&i.y>=yLo);
      let sub=0; if(qc){const c=p.filter(j=>Math.abs(j.y-qc.y)<3&&/^€[\d.]+$/.test(j.s.trim())).sort((a,b)=>b.x-a.x)[0]; if(c)sub=f(c.s.slice(1));}
      items.push({n:name,v:variant.replace(/\s+/g,' ').trim(),q:qc?+qc.s:1,s:sub});
    }
  }
  rec.items=items; rec.check=Math.round(items.reduce((a,b)=>a+b.s,0)*100)/100;
  return rec;
}
const FILRE=/\b(PLA|PETG|ABS|ASA|PC|TPU|PA\d*|PAHT|PPA|PPS|PET|PVA|HIPS|Support|Filament)\b/;
function kat(n,v,c){ if(FILRE.test(n)&&!/Plate|Hotend|Glue|Swatch|Nozzle/i.test(n)&&(c||/filament|refill|spool|spule|nachfüll|1 ?kg/i.test(v||''))) return 'Filament'; if(/Bambu Lab (H2|X1|P1|A1|P2)|Automatisches Material|Automatic Material/i.test(n)) return 'Drucker'; return 'Zubehör'; }
function code(v){const m=(v||'').match(/\((\d{5})\)/);return m?m[1]:''}
let pdfReady=null;
function loadPdf(){ if(window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
  if(!pdfReady) pdfReady=new Promise((ok,err)=>{const s=document.createElement('script');s.src=PDFJS+'pdf.min.js';s.onload=()=>{window.pdfjsLib.GlobalWorkerOptions.workerSrc=PDFJS+'pdf.worker.min.js';ok(window.pdfjsLib)};s.onerror=()=>{pdfReady=null;err(new Error('PDF-Leser konnte nicht geladen werden. Prüfe die Internetverbindung.'))};document.head.appendChild(s)});
  return pdfReady; }
async function readPdf(file){ const lib=await loadPdf(); const doc=await lib.getDocument({data:new Uint8Array(await file.arrayBuffer())}).promise; const pages=[];
  for(let p=1;p<=doc.numPages;p++){const tc=await (await doc.getPage(p)).getTextContent();pages.push(tc.items.map(i=>({s:i.str,x:i.transform[4],y:i.transform[5],w:i.width})))}
  return blParsePages(pages); }

const eur=v=>(v||0).toLocaleString('de-DE',{style:'currency',currency:'EUR'});
const dm=s=>{if(!s)return'';const [y,m,d]=s.split('-');return `${d}.${m}.${y}`};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm=s=>String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[-+]/g,' ');
const METH={Gift:'Gutschein',KLARNA:'Klarna',Klarna:'Klarna',Paypal:'PayPal',PayPal:'PayPal'};


/* ---------- Inventar: alles außer Filament, nach Gruppen ---------- */
const GRUPPEN=[
 ['drucker','Drucker',n=>/^(Pre-order )?Bambu Lab (H2[CDS]?|X1|P1|P2|A1)\b/i.test(n)&&!/Hotend|Plate|AMS/i.test(n)],
 ['ams','AMS',n=>/(Automatisches Material|Automatic Material)/i.test(n)],
 ['hotend','Hotends & Düsen',n=>/Hotend|Nozzle(?! Wiper)/i.test(n)&&!/Fan|Plate|Sock/i.test(n)],
 ['platte','Druckplatten',n=>/Plate|PEI|Effect Sheet/i.test(n)&&!/Glue/i.test(n)],
 ['ersatz','Ersatzteile & Zubehör',n=>/Fan for Hotend|Heater|Thermistor|\bSock\b|Extruder|Housing|Cable|Feeder|Shaft|Wiper|Funnel|Connector|Adapter|Hub|PTFE|Holder|Switch/i.test(n)],
 ['laser','Laser & Schneiden',n=>/Cutting|Blade|Cardstock|Kraft Paper|Vinyl|Decal|Transfer Tape|Laser/i.test(n)],
 ['elektronik','Elektronik & Bauteile',n=>/Motor|WS2812|Button Module|LED Lamp|Charger|Micro Fan|Encoder/i.test(n)],
 ['schraube','Schrauben & Kleinteile',n=>/Screw|Dowel|Spring|Balls|Bearing|Belt/i.test(n)],
 ['pflege','Werkzeug & Pflege',n=>/Glue|Scraper|Lubricant|Grease|Spray|Swatches|Reusable Spool|Air Filter/i.test(n)],
 ['ersatz','Ersatzteile & Zubehör',n=>true]];
function gruppe(n){for(const [k,,f] of GRUPPEN) if(f(n)) return k; return 'ersatz'}
const GNAME=Object.fromEntries(GRUPPEN.map(g=>[g[0],g[1]]));
const GLISTE=['drucker','ams','hotend','platte','ersatz','laser','elektronik','schraube','pflege'].map(k=>[k,GNAME[k]]);
/* ---------- Amazon ---------- */
const AZ_GRUPPEN=[
 ['werkzeug','Werkzeug',/werkzeug|lötkolben|lötstation|zange|schraubendreher|schraubenzieher|bitsatz|bit-?set|cuttermesser|entgrat|feile|bohrer|säge|schleif|pinzette|messschieber|multimeter|heißluft|gewindeschneid|einschmelz/i],
 ['druck3d','3D-Druck-Zubehör',/druckplatte|bauplatte|druckbett|düse|nozzle|hotend|bambu|3d[- ]?druck|extruder|ptfe|filamenttrockner|trockenbox|spulenhalter|creality|elegoo|anycubic|bigtreetech|klipper|prusa|resin|\bpei\b|filament/i],
 ['elektronik','Elektronik & Kabel',/kabel|adapter|stecker|\busb|esp32|esp8266|esp-?\d|arduino|raspberry|sensor|\bled\b|netzteil|akku|batterie|ladegerät|xt60|platine|entwicklungsboard|modul|zigbee|schalter|relais|lautsprecher|kopfhörer|hdmi|\bssd\b|festplatte|speicherkarte|microsd|router|switch|steckdose|smartphone|handy|iphone|ipad|tablet|notebook|laptop|macbook|monitor|\bnas\b|kamera|drucker/i],
 ['kleben','Kleben & Chemie',/kleber|klebstoff|sekundenkleber|aktivator|spray|\böl\b|schmierfett|fett\b|reiniger|isopropanol|alkohol|epoxid|\black\b|grundierung/i],
 ['haushalt','Haushalt & Wohnen',/küche|haushalt|lampe|leuchte|möbel|aufbewahrung|regal|teppich|kissen|bettw|handtuch|tasse|topf|pfanne|staubsauger|waschmittel|spülmaschine/i],
 ['kinder','Kinder & Spielzeug',/spielzeug|kinder|montessori|baby|lego|puzzle|ab \d+ jahren?/i],
 ['sonst','Sonstiges',/./]];
function azGruppe(n){for(const [k,,re] of AZ_GRUPPEN) if(re.test(n||'')) return k; return 'sonst'}
const AZ_GLISTE=AZ_GRUPPEN.map(g=>[g[0],g[1]]);
const AZ_GNAME=Object.fromEntries(AZ_GLISTE);
function azKat(n){return /filament/i.test(n)&&/1[,.]75|\d ?kg|\bpla\b|petg|\babs\b|\basa\b|\btpu\b/i.test(n)&&!/trockner|halter|box|sensor|cutter|schneider|schlauch|ptfe|tube|düse|nozzle|hotend|extruder|platte|kupplung|stecker|waage|reiniger|sauger|dryer|holder/i.test(n)?'Filament':'Zubehör'}
const SRC={bambu:{titel:'Bambu-Rechnungen',name:'Bambu Lab'},amazon:{titel:'Amazon-Bestellungen',name:'Amazon',datei:'amazon-bestellungen.json',
    art:id=>`https://www.amazon.de/dp/${id}`,best:o=>`https://www.amazon.de/your-orders/order-details?orderID=${o}`,bei:'Amazon',vk:'Verkauf durch '},
  aliexpress:{titel:'AliExpress-Bestellungen',name:'AliExpress',datei:'aliexpress-bestellungen.json',
    art:id=>`https://www.aliexpress.com/item/${id}.html`,best:o=>`https://www.aliexpress.com/p/order/detail.html?orderId=${o}`,bei:'AliExpress',vk:'Shop: '}};
function invName(n){return n.replace(/^Pre-order\s+/i,'').replace(/\s+Final Payment$/i,'').replace(/\s+3D Printer$/i,'')}

/* ---------- Design – gleiche Möglichkeiten wie in SchichtLohn ---------- */
const STILE={
  bambu:["Bambu Lab",{bg:"#ececee",k:"#ffffff",l:"#dedee2",fg:"#262e30",fg2:"#5b6265",a:"#00ae42",as:"rgba(0,174,66,.12)",st:"#f3f3f5",su:"#f5f5f6",cs:"light"},{bg:"#232326",k:"#2c2c30",l:"#3c3c42",fg:"#e8e8ea",fg2:"#a7a7ae",a:"#00ae42",as:"rgba(0,174,66,.2)",st:"#35353a",su:"#1f1f22",cs:"dark"},6],
  solidcraft:["SolidCraft",{bg:"#eceef2",k:"#fafbfc",l:"#d0d4dc",fg:"#262a32",fg2:"#4a5868",a:"#2678da",as:"#d6e6fa",st:"#eceef2",su:"#f4f6f9",cs:"light"},{bg:"#1c1f26",k:"#272b34",l:"#3f4552",fg:"#dee2e8",fg2:"#949ba8",a:"#3a88ee",as:"#2a466e",st:"#2f343e",su:"#1c1f26",cs:"dark"},8],
  graphit:["Graphit",{bg:"#f4f4f6",k:"#ffffff",l:"#e4e4e8",fg:"#18181b",fg2:"#52525b",a:"#5b5ff0",as:"rgba(91,95,240,.12)",st:"#f1f1f4",su:"#f4f4f6",cs:"light"},{bg:"#0f0f12",k:"#18181c",l:"#2a2a31",fg:"#f4f4f5",fg2:"#a1a1aa",a:"#818cf8",as:"rgba(129,140,248,.18)",st:"#1d1d22",su:"#0b0b0e",cs:"dark"},12],
  nord:["Nord",{bg:"#eceff4",k:"#ffffff",l:"#d8dee9",fg:"#2e3440",fg2:"#4c566a",a:"#5e81ac",as:"rgba(94,129,172,.14)",st:"#e5e9f0",su:"#eef1f6",cs:"light"},{bg:"#2e3440",k:"#3b4252",l:"#4c566a",fg:"#eceff4",fg2:"#d8dee9",a:"#88c0d0",ai:"#1f252e",as:"rgba(136,192,208,.18)",st:"#434c5e",su:"#2a2f3a",cs:"dark"},10],
  ozean:["Ozean",{bg:"#eef5fb",k:"#ffffff",l:"#d7e3ef",fg:"#0b1b2e",fg2:"#3d5470",a:"#0891b2",as:"rgba(8,145,178,.12)",st:"#e8f1f9",su:"#f0f6fb",cs:"light"},{bg:"#0b1220",k:"#111a2e",l:"#1e2a44",fg:"#e6edf7",fg2:"#9fb0cc",a:"#22d3ee",ai:"#04131a",as:"rgba(34,211,238,.16)",st:"#16203a",su:"#08101c",cs:"dark"},14],
  sand:["Sand",{bg:"#f5f1ea",k:"#fffdf9",l:"#e6ddd0",fg:"#2b2420",fg2:"#5e534a",a:"#c2410c",as:"rgba(194,65,12,.12)",st:"#f1ebe1",su:"#f6f1e9",cs:"light"},{bg:"#1c1917",k:"#26221f",l:"#3a332d",fg:"#f5efe6",fg2:"#c9bfb2",a:"#fb923c",ai:"#1c0d02",as:"rgba(251,146,60,.16)",st:"#2f2a26",su:"#171412",cs:"dark"},10],
  kontrast:["Kontrast",{bg:"#ffffff",k:"#ffffff",l:"#1a1a1a",fg:"#000000",fg2:"#1f1f1f",a:"#0047ff",as:"rgba(0,71,255,.12)",st:"#f2f2f2",su:"#f7f7f7",cs:"light"},{bg:"#000000",k:"#0d0d0d",l:"#3d3d3d",fg:"#ffffff",fg2:"#dcdcdc",a:"#ffd400",ai:"#000000",as:"rgba(255,212,0,.18)",st:"#141414",su:"#000000",cs:"dark"},4]};
const DESIGN_STD={quelle:"schichtlohn",vorlage:"standard",stil:"",modus:"auto",akzent:"",ecken:null,rahmen:true,schatten:"aus",deckkraft:100,hintergrund:"standard",hgfarbe:"#20242a",dichte:"normal"};
const DESIGN_VORLAGEN={standard:["Standard",{}],glas:["Glas",{ecken:16,rahmen:true,schatten:"leicht",deckkraft:55,hintergrund:"verlauf"}],flach:["Flach & eckig",{ecken:0,rahmen:true,schatten:"aus",deckkraft:100,hintergrund:"standard"}],weich:["Weich & rund",{ecken:22,rahmen:false,schatten:"weich",deckkraft:100,hintergrund:"standard"}],schwebend:["Schwebend",{ecken:12,rahmen:false,schatten:"stark",deckkraft:100,hintergrund:"verlauf"}],durchsichtig:["Durchsichtig",{ecken:14,rahmen:true,schatten:"aus",deckkraft:30,hintergrund:"durchsichtig"}]};
const DESIGN_FARBEN=["#00ae42","#3fd47f","#1e88e5","#7c4dff","#e91e63","#ff6d00","#f5b400","#00acc1","#8d6e63","#607d8b"];
const SCHATTEN={leicht:"0 1px 2px rgba(0,0,0,.10),0 3px 10px rgba(0,0,0,.08)",weich:"0 8px 28px rgba(0,0,0,.16)",stark:"0 14px 34px rgba(0,0,0,.38),0 2px 6px rgba(0,0,0,.2)"};
function hexRgb(h){h=String(h||"").replace("#","");if(h.length===3)h=h.split("").map(c=>c+c).join("");const n=parseInt(h,16);return Number.isFinite(n)&&h.length===6?[n>>16&255,n>>8&255,n&255]:null}
const inkOn=rgb=>(0.299*rgb[0]+0.587*rgb[1]+0.114*rgb[2])/255>0.62?"#111":"#fff";
function designVars(d,dunkel){
  const x=STILE[d.stil]; let v;
  if(x){const o=dunkel?x[2]:x[1];v={pg:o.bg,k:o.k,line:o.l,fg:o.fg,mut:o.fg2,ac:o.a,acs:o.as,acon:o.ai||"#fff",acink:o.a,chip:o.st,soft:o.su,cs:o.cs,r:x[3]};}
  else v={pg:"var(--primary-background-color,#ececee)",k:"var(--card-background-color,#fff)",line:"var(--divider-color,rgba(0,0,0,.12))",fg:"var(--primary-text-color,#262e30)",mut:"var(--secondary-text-color,#5b6265)",ac:"#00ae42",acs:"rgba(0,174,66,"+(dunkel?".2":".12")+")",acon:"#fff",acink:dunkel?"#4fdc85":"#007a2f",chip:"rgba(127,127,127,.14)",soft:"var(--secondary-background-color,rgba(0,0,0,.04))",cs:dunkel?"dark":"light",r:10};
  const a=hexRgb(d.akzent); if(a){v.ac=d.akzent;v.acink=d.akzent;v.acs=`rgba(${a.join(",")},.16)`;v.acon=inkOn(a)}
  if(d.ecken!=null)v.r=Math.max(0,Math.min(28,+d.ecken));
  const p=Math.max(10,Math.min(100,+d.deckkraft||100));
  let pgbg=d.hintergrund==="durchsichtig"?"transparent":d.hintergrund==="farbe"&&hexRgb(d.hgfarbe)?d.hgfarbe:d.hintergrund==="verlauf"?`radial-gradient(900px 520px at 90% -10%,color-mix(in srgb,${v.ac} 22%,transparent),transparent 62%),radial-gradient(800px 480px at -10% 110%,color-mix(in srgb,${v.ac} 14%,transparent),transparent 60%),${v.pg}`:v.pg;
  if(d.hintergrund==="farbe"&&hexRgb(d.hgfarbe)&&p<70){const g=hexRgb(d.hgfarbe),hell=(0.299*g[0]+0.587*g[1]+0.114*g[2])/255>0.55;v.fg=hell?"#1d2326":"#f3f5f7";v.mut=hell?"#3f474b":"#d3d8de"}
  const pad=d.dichte==="kompakt"?10:d.dichte==="luftig"?22:14, gap=d.dichte==="kompakt"?10:d.dichte==="luftig"?20:14;
  return `--pg:${pgbg};--k:${p<100?`color-mix(in srgb,${v.k} ${p}%,transparent)`:v.k};--kblur:${p<100?"blur(14px) saturate(1.15)":"none"};--line:${v.line};--fg:${v.fg};--mut:${v.mut};--ac:${v.ac};--ac-soft:${v.acs};--ac-on:${v.acon};--ac-ink:${v.acink};--chip:${v.chip};--soft:${v.soft};--r:${v.r}px;--rs:${Math.max(2,Math.round(v.r*.6))}px;--kb:${d.rahmen?"1px solid "+v.line:"1px solid transparent"};--ks:${SCHATTEN[d.schatten]||"none"};--pad:${pad}px;--gap:${gap}px;color-scheme:${v.cs}`;
}


const CSS=`
:host{display:block}
ha-card{background:var(--pg);border:0;box-shadow:none;border-radius:var(--ha-card-border-radius,12px);padding:var(--pad);display:grid;gap:var(--gap);color:var(--fg);font-size:14px;position:relative;overflow:hidden}
.tile{background:var(--k);border:var(--kb);box-shadow:var(--ks);border-radius:var(--r);backdrop-filter:var(--kblur);-webkit-backdrop-filter:var(--kblur)}
.head{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;justify-content:space-between;padding:2px 2px 0}
.hr{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
h2{margin:0;font-size:1.45rem;font-weight:700;display:flex;gap:9px;align-items:center}
h2 i{width:11px;height:11px;border-radius:3px;background:var(--ac);display:inline-block}
.sub{color:var(--mut);margin:2px 0 0;font-size:.9rem}
.seg{display:inline-flex;background:var(--chip);border-radius:calc(var(--rs) + 3px);padding:3px;flex-wrap:wrap}
.seg button{font:inherit;font-size:.85rem;border:0;background:none;color:var(--mut);padding:5px 11px;border-radius:var(--rs);cursor:pointer}
.seg button[aria-pressed=true]{background:var(--k);color:var(--fg);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.15)}
.ico{font:inherit;font-size:.85rem;border:0;background:var(--chip);color:var(--fg);padding:6px 11px;border-radius:var(--rs);cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.ico[aria-pressed=true]{background:var(--ac);color:var(--ac-on)}
.box{padding:var(--pad);display:grid;gap:12px}
.drop{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-style:dashed!important}
.drop.over{border-color:var(--ac)!important;background:var(--ac-soft)}
.drop b{display:block}.drop span{color:var(--mut);font-size:.85rem}
.drop .txt{flex:1;min-width:200px}
.mehr{display:block;margin:12px auto 0}
.btn{font:inherit;font-weight:600;border:0;border-radius:var(--rs);padding:9px 14px;background:var(--ac);color:var(--ac-on);cursor:pointer}
.btn.ghost{background:var(--chip);color:var(--fg)}
.log{display:grid;gap:6px}
.msg{border-radius:var(--rs);padding:9px 12px;font-size:.88rem;background:var(--soft);border-left:3px solid var(--mut)}
.msg.ok{border-left-color:var(--ac)}.msg.warn{border-left-color:#e0a100}.msg.err{border-left-color:#d93025}
.msg small{display:block;color:var(--mut);margin-top:3px}
.search{position:relative}
.search input{box-sizing:border-box;width:100%;font:inherit;font-size:1rem;padding:11px 38px 11px 40px;border-radius:var(--rs);border:1.5px solid var(--line);background:var(--soft);color:var(--fg);outline:none}
.search input:focus{border-color:var(--ac)}
.search svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--mut)}
.search .x{position:absolute;right:6px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--mut);font-size:1.2rem;cursor:pointer;padding:4px 8px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.sp{flex:1}
.chip{font:inherit;font-size:.85rem;border:0;background:var(--chip);color:var(--fg);padding:6px 12px;border-radius:999px;cursor:pointer}
.chip[aria-pressed=true]{background:var(--ac);color:var(--ac-on);font-weight:600}
.quick{font-size:.83rem;color:var(--mut)}
.quick button{font:inherit;border:0;background:none;color:var(--ac-ink);cursor:pointer;padding:0 4px;text-decoration:underline;text-underline-offset:3px}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));overflow:hidden}
.stat{padding:10px 14px;min-width:0;border-left:1px solid var(--line)}
.stat:first-child{border-left:0}
.stat b{display:block;font-size:1.15rem;font-variant-numeric:tabular-nums}
.stat span{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
@media (max-width:620px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat:nth-child(3){border-left:0}.stat:nth-child(n+3){border-top:1px solid var(--line)}.hs{display:none}}
.count{color:var(--mut);font-size:.85rem;margin:0;padding:0 2px}
.tbl{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th{text-align:left;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);font-weight:600;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap;background:var(--soft)}
th button{all:unset;cursor:pointer}
th[aria-sort=ascending] button::after{content:" ▲"}th[aria-sort=descending] button::after{content:" ▼"}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.date{white-space:nowrap;color:var(--mut);font-variant-numeric:tabular-nums}
.pbw{display:flex;gap:13px;align-items:flex-start}.pbw>div{min-width:0}
.pb{width:64px;height:64px;flex:none;border-radius:var(--rs);object-fit:contain;background:#fff;border:1px solid var(--line);cursor:pointer;padding:2px;box-sizing:border-box}
.pb.leer{background:var(--soft);padding:14px;opacity:.8}
.ret .pb{opacity:.45;filter:grayscale(1)}
.nm{font-weight:600}.var{color:var(--mut);font-size:.84rem}
.code{font-family:ui-monospace,Menlo,monospace;font-size:.76rem;background:var(--ac-soft);color:var(--ac-ink);padding:1px 6px;border-radius:5px;margin-left:6px;white-space:nowrap}
.tag{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;padding:2px 7px;border-radius:5px;background:var(--chip);color:var(--mut);white-space:nowrap}
.tag.f{background:var(--ac-soft);color:var(--ac-ink)}
.ord{font-family:ui-monospace,Menlo,monospace;font-size:.74rem;color:var(--mut)}
mark{background:#ffe27a;color:#1d2420;border-radius:2px}
.invs{display:grid;gap:var(--gap)}
details{overflow:hidden}
summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:auto 1fr auto;gap:4px 12px;align-items:center;padding:12px 14px}
summary::-webkit-details-marker{display:none}
details[open] summary{border-bottom:1px solid var(--line)}
.when{font-weight:600;font-variant-numeric:tabular-nums}
.meta{color:var(--mut);font-size:.84rem;min-width:0}
.sum{font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
.sum small{display:block;font-weight:400;color:var(--mut);font-size:.76rem}
.foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;padding:9px 14px;background:var(--soft);border-top:1px solid var(--line);font-size:.78rem;color:var(--mut)}
.foot .ord{overflow-wrap:anywhere}
.del{font:inherit;font-size:.8rem;border:0;background:none;color:#d93025;cursor:pointer;padding:2px 4px}
.empty{padding:30px 14px;text-align:center;color:var(--mut)}
.ds h3{margin:0;font-size:1.05rem}
.fld{display:grid;gap:7px}
.fld>span{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);font-weight:600}
.stile,.vorl{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px}
.st,.vl{font:inherit;font-size:.8rem;border:1.5px solid var(--line);background:var(--soft);color:var(--fg);border-radius:var(--rs);padding:8px;cursor:pointer;display:grid;gap:6px;justify-items:center}
.st[aria-pressed=true],.vl[aria-pressed=true]{border-color:var(--ac);box-shadow:0 0 0 1px var(--ac)}
.st i{display:flex;width:100%;height:34px;border-radius:4px;overflow:hidden}
.st i u{flex:1;display:flex;align-items:center;justify-content:center}
.st i b{width:62%;height:62%;border:1px solid;border-radius:3px;display:flex;gap:2px;align-items:flex-end;padding:2px}
.st i s{display:block;flex:1;height:4px;border-radius:2px}
.st i.std{background:linear-gradient(90deg,var(--card-background-color,#fff) 50%,var(--primary-background-color,#ececee) 50%)}
.vl i{width:100%;height:34px;border:1px solid var(--line);background:var(--k);display:grid;gap:4px;padding:6px;box-sizing:border-box;align-content:center}
.vl i b{display:block;height:5px;background:var(--line)}
.farb{display:flex;flex-wrap:wrap;gap:7px;align-items:center}
.fb{width:28px;height:28px;border-radius:50%;border:2px solid transparent;cursor:pointer;padding:0;font:inherit;font-size:.68rem}
.fb[aria-pressed=true]{border-color:var(--fg)}
.fb.stil{width:auto;padding:0 10px;border-radius:999px;background:var(--chip);color:var(--fg)}
.fb.eig{position:relative;overflow:hidden;background:conic-gradient(red,yellow,lime,cyan,blue,magenta,red);display:grid;place-items:center;color:#fff;font-weight:700}
.fb.eig input{position:absolute;inset:0;opacity:0;cursor:pointer}
input[type=range]{width:100%;accent-color:var(--ac)}
.hint{color:var(--mut);font-size:.8rem}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.src{justify-self:start}
.src button{font-size:.95rem;padding:7px 16px;font-weight:600;display:inline-flex;gap:8px;align-items:center}
.src small{font-size:.72rem;font-weight:500;color:var(--mut);background:var(--soft);border-radius:999px;padding:1px 7px}
.ret .nm,.ret .nm a{text-decoration:line-through;opacity:.65}
.tag.rt{background:rgba(224,161,0,.16);color:#a87400}
.nm a{color:inherit;text-decoration:none}.nm a:hover{text-decoration:underline}
.foot a{color:var(--ac-ink)}
button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--ac);outline-offset:2px}
`;

class BambuRechnungenCard extends HTMLElement{
  setConfig(c){this._c=Object.assign({entity:'todo.bambu_rechnungen',amazon_entity:'todo.amazon_rechnungen',aliexpress_entity:'todo.aliexpress_rechnungen',lager_app:'7c128fa3_schichtlohn',preise_ins_lager:true},c||{});this._by=this._by||{bambu:null,amazon:null,aliexpress:null};this._uns=this._uns||{};
    this.st=this.st||{src:'bambu',q:'',k:'',y:'',view:'art',sort:'d',dir:-1,log:[],del:null,ds:false}; this._d=this._d||Object.assign({},DESIGN_STD); }
  get _data(){return this._by[this.st.src]}
  get _ent(){return this._entOf(this.st.src)}
  _entOf(s){return s==='bambu'?this._c.entity:this._c[s+'_entity']}
  getCardSize(){return 12}
  static getStubConfig(){return {}}
  set hass(h){const first=!this._h;this._h=h;if(first){this._build();this._subscribe();this._loadDesign()}
    const dk=!!(h.themes&&h.themes.darkMode); if(dk!==this._dark){this._dark=dk;this._applyDesign()}}
  disconnectedCallback(){document.removeEventListener('visibilitychange',this._vis)}
  connectedCallback(){if(!this._vis)this._vis=()=>{if(document.visibilityState==='visible'&&this._h&&Date.now()-(this._zuletzt||0)>60000)this._laden(this.st.src)};document.addEventListener('visibilitychange',this._vis);if(this._h&&this._zuletzt)this._laden(this.st.src)}
  _subscribe(){ if(!this._h) return; const erst=this.st.src; this._laden(erst).then(()=>{for(const k of Object.keys(SRC))if(k!==erst)this._laden(k)}); }
  /* SchichtLohn-Server über HA-Ingress (gleiche Sitzung wie die Preisübernahme ins Lager) */
  async _api(pfad,opt,nochmal){ const base=await this._lagerBase(); const r=await fetch(base+pfad,Object.assign({credentials:'same-origin'},opt||{}));
    if((r.status===401||r.status===403)&&!nochmal){this._lb=null;return this._api(pfad,opt,true)}
    const j=await r.json().catch(()=>null); if(!r.ok) throw new Error((j&&j.fehler)||('SchichtLohn-Server antwortet mit '+r.status)); return j||{}; }
  _json(m,b){return {method:m,headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}}
  async _holen(src){ return (await this._api('/api/listen/'+SL_LISTE[src])).items||[]; }
  async _neu(src){ this._setItems(src,await this._holen(src)); }
  async _svc(src,service,data,still){ const r=await this._api('/api/listen/'+SL_LISTE[src],this._json('POST',{service,data})); if(!still) await this._neu(src); return r; }
  async _laden(src){ if(this._lauf&&this._lauf[src]) return this._lauf[src]; this._lauf=this._lauf||{};
    return this._lauf[src]=(async()=>{ try{ await this._neu(src); this._zuletzt=Date.now(); await this._einsammeln(src); }
      catch(e){ if(src===this.st.src){this._err='Rechnungen konnten nicht geladen werden: '+(e.message||e);this._render()} }
      finally{ this._lauf[src]=null; } })(); }
  /* Eingang (HA-To-do-Liste) abholen: neue Bestellungen auf den Server, Erstattungen anwenden, Eingang leeren.
     Beim ersten Mal ist das der Umzug aller alten Einträge – vorher wird eine Sicherung auf dem Server abgelegt. */
  async _einsammeln(src){ const ent=this._entOf(src); let ha;
    try{ ha=(await this._h.callWS({type:'todo/item/list',entity_id:ent})).items||[]; }catch(e){ return; }
    if(!ha.length) return;
    const srv=await this._holen(src); const byO=new Map();
    for(const it of srv){ try{const j=JSON.parse(it.description||'');if(j&&j.o)byO.set(j.o,{uid:it.uid,j})}catch(e){} }
    const neu=[],erst=[],weg=[];
    for(const it of ha){ let j=null; try{j=JSON.parse(it.description||'')}catch(e){} if(!j) continue;
      if(j.typ==='erstattung'){erst.push({it,j});continue}
      if(!j.o) continue;
      if(!byO.has(j.o)){ neu.push({uid:it.uid,summary:it.summary||'',status:it.status||'needs_action',description:it.description}); byO.set(j.o,{uid:it.uid,j}); }
      weg.push(it.uid); }
    if(neu.length){
      if(!srv.length&&neu.length>20){ const lm={t:'',h:`Ziehe ${neu.length} ${SRC[src].name}-Bestellungen auf den SchichtLohn-Server um …`}; this.st.log.push(lm); this._render();
        await this._api('/api/daten/rechnungen_sicherung_'+src,this._json('PUT',{wert:{zeit:new Date().toISOString(),liste:ent,items:ha}}));
        await this._api('/api/listen/'+SL_LISTE[src],this._json('PUT',{items:neu}));
        const k=await this._holen(src); this.st.log=this.st.log.filter(m=>m!==lm);
        if(k.length<neu.length){ this._log('err',`Umzug der ${SRC[src].name}-Bestellungen unvollständig (${k.length} von ${neu.length}) – die Liste ${ent} bleibt unverändert.`); return; }
        this._log('ok',`${neu.length} ${SRC[src].name}-Bestellungen sind jetzt auf dem SchichtLohn-Server – die Karte lädt dadurch viel schneller.`); }
      else for(const n of neu){ try{ await this._svc(src,'add_item',{uid:n.uid,item:n.summary,description:n.description},true); }catch(e){ const i=weg.indexOf(n.uid); if(i>=0) weg.splice(i,1); } } }
    for(const {it,j} of erst){ const z=byO.get(j.o); if(!z) continue;
      const nj=erstattungAnwenden(z.j,j);
      if(nj){ try{ await this._svc(src,'update_item',{item:z.uid,description:JSON.stringify(nj)},true); z.j=nj; }catch(e){ continue; } }
      weg.push(it.uid); }
    for(let i=0;i<weg.length;i+=200){ try{ await this._h.callService('todo','remove_item',{item:weg.slice(i,i+200)},{entity_id:ent}); }catch(e){} }
    await this._neu(src); }
  _setItems(src,items){ const data=[];
    for(const it of items){ let j=null; try{j=JSON.parse(it.description||'')}catch(e){} if(!j||!j.o) continue; j.uid=it.uid;
      if(src!=='bambu'){ j.items=(j.items||[]).map(a=>({n:a[0],v:a[1]?SRC[src].vk+a[1]:'',q:a[2]||1,s:a[3]||0,c:'',asin:a[4]||'',r0:!!a[5],ret:!!a[5]||!!j.storno,k:azKat(a[0])})); j.pay=j.storno?0:(j.net||0)-(j.erst||0); }
      else { j.items=(j.items||[]).map(a=>Array.isArray(a)?{n:a[0],v:a[1],q:a[2],s:a[3],c:a[4]||code(a[1]),k:a[5]||kat(a[0],a[1],a[4]||code(a[1]))}:a); j.pay=j.net||0; }
      data.push(j); }
    data.sort((a,b)=>(b.d||'').localeCompare(a.d||'')); this._by[src]=data; if(src===this.st.src){this._err=null;this._render()} }
  /* ---- Design ---- */
  async _loadDesign(){ try{const r=await this._h.callWS({type:'frontend/get_user_data',key:'bambu_rechnungen_design'});if(r&&r.value)this._d=Object.assign({},DESIGN_STD,r.value)}catch(e){}
    this._applyDesign(); if(this._d.quelle==='schichtlohn') await this._loadSl(); this._render(); }
  async _loadSl(){ try{const base=await this._lagerBase();const r=await fetch(base+'/api/daten/cfg',{credentials:'same-origin'});if(!r.ok)throw 0;const j=await r.json();const w=j&&('wert' in j)?j.wert:j;
      this._sl=(w&&w.design)?w.design:{};this._slOk=true}catch(e){this._sl=null;this._slOk=false} this._applyDesign(); }
  _eff(){ return this._d.quelle==='schichtlohn'?Object.assign({},DESIGN_STD,this._sl||{},{quelle:'schichtlohn'}):this._d }
  _applyDesign(){ const el=this.shadowRoot&&this.shadowRoot.getElementById('dv'); if(!el) return; const d=this._eff();
    const dunkel=d.modus==='dunkel'?true:d.modus==='hell'?false:(this._h&&this._h.themes&&'darkMode' in this._h.themes?this._h.themes.darkMode:matchMedia('(prefers-color-scheme: dark)').matches);
    const css=`:host{${designVars(d,dunkel)}}`; if(el.textContent!==css) el.textContent=css; }
  _setDesign(neu,neuZeichnen){ this._d=Object.assign({},this._d,neu); this._applyDesign(); clearTimeout(this._dsT);
    this._dsT=setTimeout(()=>{this._h.callWS({type:'frontend/set_user_data',key:'bambu_rechnungen_design',value:this._d}).catch(()=>{})},500);
    if(neuZeichnen) this._render(); }
  _build(){ this.attachShadow({mode:'open'}); this.shadowRoot.innerHTML=`<style>${CSS}</style><style id="dv"></style><ha-card><div id="root" style="display:contents"></div><input type="file" id="file" accept="application/pdf,.pdf,application/json,.json" multiple hidden></ha-card>`;
    this._applyDesign();
    const card=this.shadowRoot.querySelector('ha-card');
    card.addEventListener('dragover',e=>{e.preventDefault();this.shadowRoot.querySelector('.drop')?.classList.add('over')});
    card.addEventListener('dragleave',e=>{if(!card.contains(e.relatedTarget))this.shadowRoot.querySelector('.drop')?.classList.remove('over')});
    card.addEventListener('drop',e=>{e.preventDefault();this.shadowRoot.querySelector('.drop')?.classList.remove('over');const fs=[...(e.dataTransfer?.files||[])].filter(f=>/\.(pdf|json)$/i.test(f.name));if(fs.length)this._import(fs)});
    this.shadowRoot.getElementById('file').addEventListener('change',e=>{const fs=[...e.target.files];e.target.value='';if(fs.length)this._import(fs)});
    this._render(); }
  _designHTML(){ const d=this._d, sl=d.quelle==='schichtlohn';
    const chips=(k,l,w)=>`<div class="row">${l.map(([v,t])=>`<button class="chip" data-dk="${k}" data-dv="${esc(String(v))}" aria-pressed="${String(w)===String(v)}">${t}</button>`).join('')}</div>`;
    let h=`<section class="tile box ds"><div class="row"><h3>Design</h3><span class="sp"></span><div class="seg"><button data-dk="quelle" data-dv="schichtlohn" aria-pressed="${sl}">Wie SchichtLohn</button><button data-dk="quelle" data-dv="eigen" aria-pressed="${!sl}">Eigenes</button></div></div>`;
    if(sl) return h+`<p class="hint" style="margin:0">${this._slOk===false?'SchichtLohn ist gerade nicht erreichbar, deshalb gilt das Standard-Design. Für die Übernahme braucht es einen Administrator-Zugang.':this._slOk?'Stil, Akzentfarbe und Kacheln kommen aus deinen SchichtLohn-Einstellungen. Ändere das Design dort, dann passt sich diese Karte mit an.':'Lade das Design aus SchichtLohn …'}</p>
      <div class="row"><button class="btn ghost" data-dsakt="kopie">Als eigenes Design übernehmen und anpassen</button>${this._slOk?'<button class="btn ghost" data-dsakt="neu">Neu laden</button>':''}</div></section>`;
    const ok=s=>s;
    h+=`<div class="fld"><span>Stil</span><div class="stile"><button class="st" data-dk="stil" data-dv="" aria-pressed="${!d.stil}"><i class="std"></i>Standard</button>${Object.entries(STILE).map(([k,[t,hl,dk]])=>`<button class="st" data-dk="stil" data-dv="${k}" aria-pressed="${d.stil===k}"><i><u style="background:${hl.bg}"><b style="background:${hl.k};border-color:${hl.l}"><s style="background:${hl.a}"></s><s style="background:${hl.fg2}"></s></b></u><u style="background:${dk.bg}"><b style="background:${dk.k};border-color:${dk.l}"><s style="background:${dk.a}"></s><s style="background:${dk.fg2}"></s></b></u></i>${t}</button>`).join('')}</div><span class="hint" style="text-transform:none;letter-spacing:0;font-weight:400">Jeder Stil hat eine helle und eine dunkle Fassung.</span></div>
    <div class="fld"><span>Kacheln</span><div class="vorl">${Object.entries(DESIGN_VORLAGEN).map(([k,[t,o]])=>{const x=Object.assign({},DESIGN_STD,o),r=x.ecken==null?10:x.ecken;return `<button class="vl" data-vorlage="${k}" aria-pressed="${d.vorlage===k}"><i style="border-radius:${r}px;${x.rahmen?'':'border-color:transparent;'}${SCHATTEN[x.schatten]?`box-shadow:${SCHATTEN[x.schatten]};`:''}${x.deckkraft<100?`background:color-mix(in srgb,var(--k) ${x.deckkraft}%,transparent);`:''}"><b style="border-radius:${Math.round(r*.6)}px"></b><b style="border-radius:${Math.round(r*.6)}px;width:60%"></b></i>${t}</button>`}).join('')}</div></div>
    <div class="fld"><span>Hell oder dunkel</span>${chips('modus',[['auto','Wie Home Assistant'],['hell','Immer hell'],['dunkel','Immer dunkel']],d.modus)}</div>
    <div class="fld"><span>Akzentfarbe</span><div class="farb"><button class="fb stil" data-dk="akzent" data-dv="" aria-pressed="${!d.akzent}">Stil</button>${DESIGN_FARBEN.map(f=>`<button class="fb" data-dk="akzent" data-dv="${f}" style="background:${f}" aria-label="Farbe ${f}" aria-pressed="${(d.akzent||'').toLowerCase()===f}"></button>`).join('')}<label class="fb eig" title="Eigene Farbe">+<input type="color" id="ds_akzent" value="${esc(d.akzent||'#00ae42')}"></label></div></div>
    <div class="fld"><span>Ecken</span>${chips('ecken',[['','Standard'],[0,'Eckig'],[6,'Leicht rund'],[14,'Rund'],[24,'Sehr rund']],d.ecken==null?'':d.ecken)}<input type="range" id="ds_ecken" min="0" max="28" step="1" value="${d.ecken==null?10:d.ecken}" aria-label="Rundung der Ecken"></div>
    <div class="cols"><div class="fld"><span>Rahmen um Kacheln</span>${chips('rahmen',[[true,'Mit Rahmen'],[false,'Ohne']],d.rahmen)}</div><div class="fld"><span>Schatten</span>${chips('schatten',[['aus','Keiner'],['leicht','Leicht'],['weich','Weich'],['stark','Stark']],d.schatten)}</div></div>
    <div class="fld"><span id="ds_decklab">Kacheln: ${d.deckkraft>=100?'deckend':d.deckkraft+' % deckend'}</span><input type="range" id="ds_deck" min="10" max="100" step="5" value="${d.deckkraft}" aria-label="Deckkraft der Kacheln"></div>
    <div class="fld"><span>Hintergrund</span>${chips('hintergrund',[['standard','Standard'],['verlauf','Farbverlauf'],['farbe','Eigene Farbe'],['durchsichtig','Durchsichtig']],d.hintergrund)}${d.hintergrund==='farbe'?`<label class="hint"><input type="color" id="ds_hg" value="${esc(d.hgfarbe)}"> Farbe wählen</label>`:''}${d.hintergrund==='durchsichtig'?'<span class="hint" style="text-transform:none;letter-spacing:0;font-weight:400">Dahinter scheint der Dashboard-Hintergrund durch.</span>':''}</div>
    <div class="fld"><span>Abstände</span>${chips('dichte',[['kompakt','Kompakt'],['normal','Normal'],['luftig','Luftig']],d.dichte)}</div>
    <div class="row"><button class="btn ghost" data-dsakt="reset">Alles zurücksetzen</button><span class="hint">Gilt sofort und auf allen Geräten mit deinem Home-Assistant-Benutzer.</span></div></section>`;
    return h; }
  _inventar(){ const m=new Map();
    const az=this.st.src!=='bambu';
    for(const r of (this._data||[])) for(const it of r.items){ if(it.k==='Filament'||it.ret) continue;
      const anz=/^Pre-order/i.test(it.n)&&!/Final Payment/i.test(it.n)?0:it.q;
      const name=az?it.n:invName(it.n), key=name+'|'+(anz&&!az?it.v:'');
      let e=m.get(key); if(!e){e={n:name,v:anz?it.v:'',g:az?azGruppe(it.n):gruppe(it.n),q:0,s:0,kaeufe:[]};m.set(key,e)}
      if(!anz){ const p=[...m.values()].find(x=>x.n===name&&x!==e&&x.q); if(p){p.s+=it.s;m.delete(key);continue} }
      if(it.asin&&!e.asin)e.asin=it.asin; if(!e.pv)e.pv=it.v; e.q+=anz; e.s+=it.s; e.kaeufe.push({d:r.d,o:r.o,q:anz,s:it.s}); }
    const L=[...m.values()]; L.forEach(e=>{e.kaeufe.sort((a,b)=>b.d.localeCompare(a.d));e.last=e.kaeufe[0]?.d||'';const k=e.kaeufe.find(x=>x.q);e.u=k?k.s/k.q:0});
    return L; }
  /* Produktbild: der SchichtLohn-Server sucht es (Amazon/AliExpress per Artikel-ID, Bambu per Name) und hält es vor */
  _pbq(it){const src=this.st.src;const p={quelle:src,id:src==='bambu'?'':(it.asin||''),n:it.n||'',v:src==='bambu'?(it.v||''):''};return p}
  _pb(it){ if(!this._lb) return ''; const p=this._pbq(it);
    const t=(this._pbv&&this._pbv[JSON.stringify(p)])||'';
    return `<img class="pb" loading="lazy" decoding="async" alt="" src="${esc(this._lb+'/api/produktbild?'+new URLSearchParams(p)+(t?'&t='+t:''))}" data-pb="${esc(JSON.stringify(p))}">`; }
  async _pbSetzen(p){ const url=prompt('Bildadresse für „'+p.n.slice(0,60)+'“ einfügen (Rechtsklick aufs Produktbild im Shop → Bildadresse kopieren).\nLeer lassen = wieder automatisch suchen.','');
    if(url===null) return; try{ await this._api('/api/produktbild',this._json('PUT',Object.assign({},p,{url:url.trim()}))); this._pbv=this._pbv||{}; this._pbv[JSON.stringify(p)]=Date.now(); this._render(); }
    catch(e){ this._log('err',esc(e.message||e)); } }
  _rows(){ const R=[];(this._data||[]).forEach(r=>r.items.forEach(it=>R.push({...it,d:r.d,o:r.o,storno:!!r.storno,u:it.q?it.s/it.q:it.s})));return R; }
  _hit(it){const st=this.st;if(!st.q)return true;const hay=norm(it.n+' '+it.v+' '+it.c+' '+it.o+' '+it.k+(it.ret?(it.storno?' storniert':' zurückgegeben'):''));return norm(st.q).split(/\s+/).filter(Boolean).every(w=>hay.includes(w))}
  _hl(s){const st=this.st;let out=esc(s);if(!st.q)return out;norm(st.q).split(/\s+/).filter(w=>w.length>1).forEach(w=>{out=out.replace(new RegExp('('+w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'),'<mark>$1</mark>')});return out}
  _bestandHTML(inY){ const st=this.st; const gq=st.g||'';
    let L=this._inventar().filter(e=>e.kaeufe.some(k=>inY(k.d))&&(!gq||e.g===gq)&&(!st.q||this._hit({n:e.n,v:e.v,c:'',o:e.kaeufe.map(k=>k.o).join(' '),k:(this.st.src!=='bambu'?AZ_GNAME:GNAME)[e.g]})));
    const az=st.src!=='bambu', GL=az?AZ_GLISTE:GLISTE, GN=az?Object.fromEntries(AZ_GLISTE):GNAME;
    const sum=L.reduce((a,e)=>a+e.s,0), cnt=g=>L.filter(e=>e.g===g).reduce((a,e)=>a+e.q,0);
    const head=az?`<div class="tile stats"><div class="stat"><b>${cnt('druck3d')}</b><span>3D-Druck-Zubehör</span></div><div class="stat"><b>${cnt('werkzeug')}</b><span>Werkzeug</span></div><div class="stat"><b>${L.reduce((a,e)=>a+e.q,0)}</b><span>Teile gesamt</span></div><div class="stat"><b>${eur(sum)}</b><span>Wert (Kaufpreis)</span></div></div>
      <p class="count">${L.length} Artikel${st.q||gq?' gefunden':''} · ohne Filament und ohne zurückgegebene Artikel</p>`:`<div class="tile stats"><div class="stat"><b>${cnt('drucker')}</b><span>Drucker</span></div><div class="stat"><b>${cnt('ams')}</b><span>AMS</span></div><div class="stat"><b>${L.filter(e=>!['drucker','ams'].includes(e.g)).reduce((a,e)=>a+e.q,0)}</b><span>Teile & Zubehör</span></div><div class="stat"><b>${eur(sum)}</b><span>Wert (Kaufpreis)</span></div></div>
      <p class="count">${L.length} Artikel${st.q||gq?' gefunden':''} · Mengen laut Bestellungen, ohne Filament</p>`;
    if(!L.length) return head+`<div class="tile empty">Nichts gefunden.</div>`;
    const so=st.isort||'g';
    return head+GL.map(([g,t])=>{const G=L.filter(e=>e.g===g);if(!G.length)return '';
      G.sort((a,b)=>so==='d'?b.last.localeCompare(a.last):so==='s'?b.s-a.s:a.n.localeCompare(b.n,'de'));
      return `<div class="tile tbl"><table><thead><tr><th colspan="2">${t} <span style="font-weight:400">· ${G.reduce((a,e)=>a+e.q,0)} Stück · ${eur(G.reduce((a,e)=>a+e.s,0))}</span></th><th class="num hs">Zuletzt</th><th class="num">Menge</th><th class="num hs">Stückpreis</th></tr></thead><tbody>
        ${G.map(e=>`<tr title="${esc(e.kaeufe.map(k=>dm(k.d)+': '+(k.q||'Anzahlung')+' × – '+k.o).join('\n'))}"><td colspan="2"><div class="pbw">${this._pb({n:e.n,v:e.pv||e.v,asin:e.asin})}<div><div class="nm">${this._hl(e.n)}</div>${e.v&&!az?`<div class="var">${this._hl(e.v)}</div>`:''}<div class="ord">${e.kaeufe.length>1?e.kaeufe.length+' Käufe, ':''}gesamt ${eur(e.s)}</div></div></div></td><td class="num date hs">${dm(e.last)}</td><td class="num"><b>${e.q}</b></td><td class="num hs">${e.u?eur(e.u):'–'}</td></tr>`).join('')}</tbody></table></div>`}).join('')
      +`<div class="row"><span class="hint">Sortieren:</span><div class="seg">${[['g','Name'],['d','Zuletzt gekauft'],['s','Wert']].map(([k,l])=>`<button data-isort="${k}" aria-pressed="${so===k}">${l}</button>`).join('')}</div></div>`; }
  _render(){ const root=this.shadowRoot?.getElementById('root'); if(!root) return; const st=this.st; const data=this._data||[];
    const sig=[st.src,st.q,st.k,st.y,st.view,st.sort,st.dir,st.g].join('|'); if(sig!==this._sig){this._sig=sig;st.n=SEITE} st.n=st.n||SEITE;
    const mehr=n=>n>st.n?`<button class="btn ghost mehr" id="mehr">Weitere ${Math.min(n-st.n,300)} von noch ${n-st.n} anzeigen</button>`:'';
    const years=[...new Set(data.map(r=>(r.d||'').slice(0,4)).filter(Boolean))].sort();
    const inY=d=>!st.y||(d||'').startsWith(st.y);
    const rows=this._rows().filter(it=>inY(it.d)&&(!st.k||it.k===st.k)&&this._hit(it));
    rows.sort((a,b)=>{const x=a[st.sort],y=b[st.sort];return (typeof x==='string'?x.localeCompare(y,'de'):x-y)*st.dir||b.d.localeCompare(a.d)});
    const filtered=!!(st.q||st.k); const invs=data.filter(r=>inY(r.d));
    const paid=filtered?rows.filter(r=>!r.ret).reduce((s,r)=>s+r.s,0):invs.reduce((s,r)=>s+(r.pay||0),0); const az=st.src!=='bambu'; const ruck=data.reduce((a,r)=>a+r.items.filter(i=>i.ret).length,0);
    const fil=rows.filter(r=>r.k==='Filament'&&!r.ret);const nf=fil.reduce((s,r)=>s+r.q,0);
    const total=data.reduce((s,r)=>s+(r.pay||0),0); const ohne=data.filter(r=>r.ohne).length;
    const hitO=new Set(rows.map(r=>r.o)); const vis=invs.filter(r=>!filtered||hitO.has(r.o));
    const focus=this.shadowRoot.activeElement?.id; const caret=this.shadowRoot.getElementById('q')?.selectionStart;
    root.innerHTML=`
    <div class="seg src" role="tablist" aria-label="Quelle">${Object.entries(SRC).map(([k,s])=>`<button data-src="${k}" role="tab" aria-pressed="${st.src===k}">${s.name}<small>${this._by[k]?this._by[k].length:'…'}</small></button>`).join('')}</div>
    <div class="head"><div><h2><i></i>${SRC[st.src].titel}</h2><p class="sub">${data.length?`${data.length} Bestellungen${ohne?` (${ohne} ohne Rechnung)`:''}${ruck?` · ${ruck} Artikel zurückgegeben oder storniert`:''}${data.filter(r=>r.storno).length?` · ${data.filter(r=>r.storno).length} storniert`:''} · ${dm(data[data.length-1].d)} bis ${dm(data[0].d)} · ${eur(total)} bezahlt${az?' (nach Erstattungen)':''}`:(this._err?esc(this._err):this._by[st.src]?(az?`Noch keine ${SRC[st.src].name}-Bestellungen. Zieh die Export-Datei auf die Karte.`:'Noch keine Rechnungen.'):'Lade Rechnungen …')}</p></div>
      <div class="hr"><div class="seg" role="group" aria-label="Ansicht"><button data-v="art" aria-pressed="${st.view==='art'}">Artikel</button><button data-v="inv" aria-pressed="${st.view==='inv'}">Rechnungen</button><button data-v="bestand" aria-pressed="${st.view==='bestand'}">Inventar</button></div>
      <button class="ico" id="dsbtn" aria-pressed="${st.ds}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2a10 10 0 0 0 0 20c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4A5.6 5.6 0 0 0 22 9.8C22 5.5 17.5 2 12 2z"/></svg>Design</button></div></div>
    ${st.ds?this._designHTML():''}
    <div class="tile box drop"><div class="txt">${az?`<b>${SRC[st.src].name}-Bestellungen importieren</b><span>Export-Datei (${SRC[st.src].datei}) hierher ziehen oder auswählen. Schon vorhandene Bestellungen werden nur aktualisiert, z. B. bei späteren Rücksendungen.</span>`:`<b>Neue Rechnung hinzufügen</b><span>PDF aus dem Bambu Lab EU-Store hierher ziehen oder auswählen. Filamentpreise ${this._c.preise_ins_lager?'werden automatisch ins SchichtLohn-Lager übernommen':'werden nicht ins Lager übernommen'}.</span>`}</div>
      <button class="btn" id="pick">${az?'Datei auswählen':'PDF auswählen'}</button></div>
    ${st.log.length?`<div class="tile box log">${st.log.map(m=>`<div class="msg ${m.t}">${m.h}</div>`).join('')}<div><button class="btn ghost" id="clrlog">Meldungen ausblenden</button></div></div>`:''}
    <div class="tile box"><div class="search"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="search" placeholder="${az?'Suchen: Filament, Kabel, Verkäufer, Bestellnummer …':'Suchen: PLA Matte, Schwarz, 11103, Hotend …'}" aria-label="Artikel suchen" autocomplete="off" value="${esc(st.q)}">${st.q?'<button class="x" id="clr" aria-label="Suche leeren">×</button>':''}</div>
    <div class="row"><div class="row" role="group" aria-label="Kategorie">${st.view==='bestand'?[['','Alles'],...(az?AZ_GLISTE:GLISTE)].map(([k,l])=>`<button class="chip" data-g="${k}" aria-pressed="${(st.g||'')===k}">${l}</button>`).join(''):(az?[['','Alles'],['Filament','Filament'],['Zubehör','Alles andere']]:[['','Alles'],['Filament','Filament'],['Drucker','Drucker & AMS'],['Zubehör','Zubehör & Ersatzteile']]).map(([k,l])=>`<button class="chip" data-k="${k}" aria-pressed="${st.k===k}">${l}</button>`).join('')}</div><span class="sp"></span>
      <div class="seg" role="group" aria-label="Jahr"><button data-y="" aria-pressed="${!st.y}">Alle Jahre</button>${years.map(y=>`<button data-y="${y}" aria-pressed="${st.y===y}">${y}</button>`).join('')}</div></div>
    <div class="quick">Schnell suchen: ${(az?['Filament','PETG','Druckplatte','Kabel','Werkzeug','Kleber','zurückgegeben']:['PLA Matte','PETG HF','ABS-GF','Silk','Schwarz','Refill','Hotend']).map(s=>`<button data-s="${s}">${s}</button>`).join('')}</div></div>
    ${st.view==='bestand'?this._bestandHTML(inY):`<div class="tile stats"><div class="stat"><b>${eur(paid)}</b><span>${filtered?'Summe der Treffer':'bezahlt'}</span></div><div class="stat"><b>${rows.reduce((s,r)=>s+r.q,0)}</b><span>Stück</span></div><div class="stat"><b>${nf}</b><span>Filament-Rollen</span></div><div class="stat"><b>${nf?eur(fil.reduce((s,r)=>s+r.s,0)/nf):'–'}</b><span>Ø bezahlt pro Rolle</span></div></div>
    <p class="count">${st.view==='art'?`${rows.length} Positionen${filtered?' gefunden':''}`:`${vis.length} Bestellungen`}</p>
    ${st.view==='art'?`<div class="tile tbl"><table><thead><tr>${[['d','Datum',''],['n','Artikel',''],[null,'Art','hs'],['q','Menge','num'],['u','Stückpreis','num'],['s','Summe','num']].map(([k,l,c])=>`<th class="${c}" ${k?`aria-sort="${st.sort===k?(st.dir>0?'ascending':'descending'):'none'}"`:''}>${k?`<button data-sort="${k}">${l}</button>`:l}</th>`).join('')}</tr></thead><tbody>
      ${rows.length?rows.slice(0,st.n).map(r=>`<tr><td class="date">${dm(r.d)}</td><td${r.ret?' class="ret"':''}><div class="pbw">${this._pb(r)}<div><div class="nm">${r.asin&&az?`<a href="${SRC[st.src].art(r.asin)}" target="_blank" rel="noopener">${this._hl(r.n)}</a>`:this._hl(r.n)}${r.c?`<span class="code">${this._hl(r.c)}</span>`:''}</div>${r.v?`<div class="var">${this._hl(r.v)}</div>`:''}<div class="ord">${r.o}</div></div></div></td><td class="hs">${r.ret?`<span class="tag rt">${r.storno?'storniert':'zurückgegeben'}</span>`:`<span class="tag${r.k==='Filament'?' f':''}">${r.k==='Drucker'?'Drucker & AMS':r.k==='Zubehör'&&az?AZ_GNAME[azGruppe(r.n)]:r.k}</span>`}</td><td class="num">${r.q}</td><td class="num">${eur(r.u)}</td><td class="num">${eur(r.s)}</td></tr>`).join(''):`<tr><td colspan="6" class="empty">${data.length?'Nichts gefunden. Probier einen kürzeren Begriff, z. B. nur die Farbe oder die Farbnummer.':'Noch keine Rechnungen. Zieh eine PDF auf die Karte.'}</td></tr>`}
      </tbody></table></div>${mehr(rows.length)}`
    :`<div class="invs">${vis.length?vis.slice(0,st.n).map(r=>{const its=r.items.filter(it=>!filtered||((!st.k||it.k===st.k)&&this._hit(it)));const pcs=r.items.reduce((s,i)=>s+i.q,0);const m=METH[r.m]||r.m||'';
      return `<details class="tile"${filtered?' open':''}><summary><span class="when">${dm(r.d)}</span><span class="meta">${pcs} Stück${m?' · '+esc(m):''}${r.ship?' · Versand '+eur(r.ship):''}${r.ohne?' · <span class="tag">ohne Rechnung</span>':''}<br><span class="ord">${r.o}${r.i?' · Rechnung '+esc(r.i):''}</span></span><span class="sum">${eur(r.pay)}${r.storno?'<small>storniert</small>':r.erst?`<small>${eur(r.erst)} erstattet</small>`:''}${r.tot&&r.tot!==r.net?`<small>von ${eur(r.tot)}${r.gift?', Rest per Gutschein':r.disc?' vor Rabatt':', Rest per Gutschein'}</small>`:''}</span></summary>
      <div class="tbl"><table><tbody>${its.map(it=>`<tr><td${it.ret?' class="ret"':''}>${it.ret?`<span class="tag rt" style="float:right">${r.storno?'storniert':'zurückgegeben'}</span>`:''}<div class="pbw">${this._pb(it)}<div><div class="nm">${this._hl(it.n)}${it.c?`<span class="code">${this._hl(it.c)}</span>`:''}</div>${it.v?`<div class="var">${this._hl(it.v)}</div>`:''}</div></div></td><td class="num">${it.q} ×</td><td class="num">${eur(it.s)}</td></tr>`).join('')}</tbody></table></div>
      <div class="foot"><span class="ord">${az?`<a href="${SRC[st.src].best(r.o)}" target="_blank" rel="noopener">Bestellung bei ${SRC[st.src].bei} öffnen</a>`:r.ohne?'Keine Rechnung im Shop – Daten aus der Bestellübersicht':r.file?'PDF: '+esc(r.file):''}</span>${az?`<button class="del" style="color:var(--ac-ink)" data-storno="${r.uid}">${r.storno?'Storno aufheben':'Als storniert markieren'}</button>`:''}${st.del===r.uid?`<span>Wirklich entfernen? <button class="del" data-delok="${r.uid}">Ja, entfernen</button> <button class="del" style="color:var(--mut)" data-delno="1">Abbrechen</button></span>`:`<button class="del" data-del="${r.uid}">Entfernen</button>`}</div></details>`}).join('')+mehr(vis.length):`<div class="empty tile">Keine Bestellung passt zur Suche.</div>`}</div>`}`}`;
    const $=s=>root.querySelectorAll(s);
    $('img.pb').forEach(i=>{i.onerror=()=>{i.onerror=null;i.src=PB_LEER;i.classList.add('leer');i.title='Kein Bild gefunden – antippen, um eine Bildadresse einzutragen'};
      i.onclick=ev=>{ev.preventDefault();ev.stopPropagation();try{this._pbSetzen(JSON.parse(i.dataset.pb))}catch(e){}}});
    const q=root.querySelector('#q'); q.addEventListener('input',()=>{st.q=q.value.trim();clearTimeout(this._qt);this._qt=setTimeout(()=>this._render(),180)});
    root.querySelector('#mehr')?.addEventListener('click',()=>{st.n+=300;this._render()}); if(focus==='q'){q.focus();try{q.setSelectionRange(caret,caret)}catch(e){}}
    root.querySelector('#clr')?.addEventListener('click',()=>{st.q='';this._render();root.querySelector('#q')?.focus()});
    root.querySelector('#pick').addEventListener('click',()=>this.shadowRoot.getElementById('file').click());
    root.querySelector('#clrlog')?.addEventListener('click',()=>{st.log=[];this._render()});
    root.querySelector('#dsbtn').addEventListener('click',()=>{st.ds=!st.ds;this._render()});
    $('[data-v]').forEach(b=>b.onclick=()=>{st.view=b.dataset.v;this._render()});
    $('[data-src]').forEach(b=>b.onclick=()=>{if(st.src===b.dataset.src)return;st.src=b.dataset.src;st.k='';st.g='';st.y='';st.q='';st.log=[];this._err=null;this._render()});
    $('.chip[data-g]').forEach(b=>b.onclick=()=>{st.g=b.dataset.g;this._render()});
    $('[data-isort]').forEach(b=>b.onclick=()=>{st.isort=b.dataset.isort;this._render()});
    $('.chip[data-k]').forEach(b=>b.onclick=()=>{st.k=b.dataset.k;this._render()});
    $('[data-y]').forEach(b=>b.onclick=()=>{st.y=b.dataset.y;this._render()});
    $('[data-s]').forEach(b=>b.onclick=()=>{st.q=b.dataset.s;this._render()});
    $('[data-sort]').forEach(b=>b.onclick=()=>{const k=b.dataset.sort;if(st.sort===k)st.dir*=-1;else{st.sort=k;st.dir=k==='n'?1:-1}this._render()});
    $('[data-del]').forEach(b=>b.onclick=e=>{e.preventDefault();st.del=b.dataset.del;this._render()});
    $('[data-storno]').forEach(b=>b.onclick=async e=>{e.preventDefault();const r=(this._data||[]).find(x=>x.uid===b.dataset.storno);if(!r)return;
      const an=!r.storno; const desc=this._shopDesc(Object.assign({},r,{storno:an?1:0}));
      try{await this._svc(st.src,'update_item',{item:r.uid,description:JSON.stringify(desc)});this._log('ok',`<b>${esc(r.o)}</b> ${an?'als storniert markiert – zählt nicht mehr bei Betrag und Inventar':'wieder als normale Bestellung gezählt'}.`)}catch(x){this._log('err','Ändern hat nicht geklappt: '+esc(x.message||x))}});
    $('[data-delno]').forEach(b=>b.onclick=e=>{e.preventDefault();st.del=null;this._render()});
    $('[data-delok]').forEach(b=>b.onclick=async e=>{e.preventDefault();const uid=b.dataset.delok;st.del=null;try{await this._svc(st.src,'remove_item',{item:uid})}catch(x){this._log('err','Entfernen hat nicht geklappt: '+esc(x.message||x))}});
    /* Design-Bedienelemente */
    $('[data-dk]').forEach(b=>b.onclick=async()=>{const k=b.dataset.dk;let v=b.dataset.dv;
      if(k==='rahmen')v=v==='true'; else if(k==='ecken')v=v===''?null:+v;
      const neu={[k]:v}; if(!['quelle','modus','stil','akzent'].includes(k))neu.vorlage='';
      this._setDesign(neu,true); if(k==='quelle'&&v==='schichtlohn'){await this._loadSl();this._render()} });
    $('[data-vorlage]').forEach(b=>b.onclick=()=>{const k=b.dataset.vorlage;this._setDesign(Object.assign({vorlage:k},DESIGN_STD,DESIGN_VORLAGEN[k][1],{quelle:'eigen',stil:this._d.stil,modus:this._d.modus,akzent:this._d.akzent,hgfarbe:this._d.hgfarbe,vorlage:k}),true)});
    $('[data-dsakt]').forEach(b=>b.onclick=async()=>{const a=b.dataset.dsakt;
      if(a==='kopie')this._setDesign(Object.assign({},this._eff(),{quelle:'eigen'}),true);
      if(a==='neu'){await this._loadSl();this._render()}
      if(a==='reset')this._setDesign(Object.assign({},DESIGN_STD,{quelle:'eigen'}),true)});
    const rg=(id,f)=>{const el=root.querySelector('#'+id);if(!el)return;el.addEventListener('input',()=>f(el.value,false));el.addEventListener('change',()=>f(el.value,true))};
    rg('ds_ecken',(v,r)=>this._setDesign({ecken:+v,vorlage:''},r));
    rg('ds_deck',(v,r)=>{this._setDesign({deckkraft:+v,vorlage:''},r);const l=root.querySelector('#ds_decklab');if(l)l.textContent='Kacheln: '+(+v>=100?'deckend':v+' % deckend')});
    rg('ds_akzent',(v,r)=>this._setDesign({akzent:v},r));
    rg('ds_hg',(v,r)=>this._setDesign({hgfarbe:v,vorlage:''},r));
  }
  _shopDesc(r){ return {v:1,o:r.o,d:r.d||'',net:r.net,tot:r.tot??null,ship:r.ship||0,erst:r.erst||0,storno:r.storno?1:0,...(r.mail?{mail:true}:{}),items:r.items.map(x=>[x.n,(x.v||'').replace(/^(Verkauf durch |Shop: )/,''),x.q,x.s,x.asin||'',(x.r0&&!r.storno)?1:0])} }
  _log(t,h){this.st.log.push({t,h});this._render()}
  async _importShop(f){ let j; try{j=JSON.parse(await f.text())}catch(e){throw new Error('Die Datei ist keine gültige Export-Datei.')}
    const L=(j&&j.orders)||[]; if(!L.length) throw new Error('In der Datei sind keine Bestellungen.');
    const src=SRC[j.quelle]&&j.quelle!=='bambu'?j.quelle:(/aliexpress/i.test(j.quelle||f.name)?'aliexpress':'amazon'); const vorh=new Map((this._by[src]||[]).map(r=>[r.o,r])); let neu=0,akt=0,gleich=0,fehl=0;
    this._log('','Importiere '+L.length+' '+SRC[src].name+'-Bestellungen …'); const lm=this.st.log[this.st.log.length-1];
    for(let i=0;i<L.length;i++){ const o=L[i]; if(!o||!o.o) continue;
      const desc=JSON.stringify({v:1,o:o.o,d:o.d||'',net:o.net??o.tot??o.sum??0,tot:o.tot??null,ship:o.ship||0,erst:o.erst||0,storno:o.storno?1:0,items:(o.items||[]).map(a=>[a[0],a[1]||'',a[2]||1,a[3]??0,a[4]||'',(a[5]&&!o.storno)?1:0])});
      try{ const alt=vorh.get(o.o);
        if(!alt){await this._svc(src,'add_item',{item:`${o.d||''} · ${o.o}`,description:desc},true);neu++}
        else{ const altj=JSON.stringify(this._shopDesc(alt)).replace(/,"mail":true/,'');
          if(altj!==desc){await this._svc(src,'update_item',{item:alt.uid,description:desc},true);akt++}else gleich++ } }catch(e){fehl++}
      if(i%20===0){lm.h=`Importiere … ${i+1} von ${L.length}`;this._render()} }
    this.st.log=this.st.log.filter(m=>m!==lm); try{await this._neu(src)}catch(e){}
    this._log(fehl?'warn':'ok',`${SRC[src].name}-Import fertig: ${neu} neu, ${akt} aktualisiert, ${gleich} unverändert${fehl?`, ${fehl} fehlgeschlagen`:''}.`); }
  async _import(files){ for(const f of files){ try{
      if(/\.json$/i.test(f.name)){ await this._importShop(f); continue; }
      this._log('','Lese '+esc(f.name)+' …');
      const x=await readPdf(f); this.st.log.pop();
      if(!x.o||!x.items.length){this._log('err',`<b>${esc(f.name)}</b>: Das sieht nicht nach einer Rechnung aus dem Bambu Lab EU-Store aus.`);continue}
      if((this._data||[]).some(r=>r.o===x.o)){this._log('warn',`<b>${x.o}</b> ist schon eingetragen.`);continue}
      const items=x.items.map(it=>{const c=code(it.v);return [it.n,it.v,it.q,it.s,c,kat(it.n,it.v,c)]});
      const desc={v:1,o:x.o,i:x.i,d:x.d,net:x.net,tot:x.tot,ship:x.ship,m:METH[x.m]||x.m,file:`${x.d}_${x.o}.pdf`,items};
      await this._svc('bambu','add_item',{item:`${x.d} · ${x.o}`,description:JSON.stringify(desc)});
      const warn=x.sub!=null&&Math.abs(x.check-x.sub)>0.02?`<small>Hinweis: Die Positionen ergeben ${eur(x.check)}, auf der Rechnung stehen ${eur(x.sub)}. Bitte kurz prüfen.</small>`:'';
      this._log('ok',`<b>${dm(x.d)} · ${x.o}</b> eingetragen: ${items.length} Positionen, ${eur(x.net)} bezahlt.${warn}`);
      if(this._c.preise_ins_lager) await this._preise(x.d,items);
    }catch(e){this.st.log=this.st.log.filter(m=>!m.h.startsWith('Lese '));this._log('err',`<b>${esc(f.name)}</b>: ${esc(e.message||e)}`)} } }
  async _lagerBase(){ if(this._lb) return this._lb;
    const info=await this._h.callWS({type:'supervisor/api',endpoint:`/addons/${this._c.lager_app}/info`,method:'get'});
    const s=await this._h.callWS({type:'supervisor/api',endpoint:'/ingress/session',method:'post'});
    document.cookie=`ingress_session=${s.session};path=/api/hassio_ingress/;SameSite=Strict${location.protocol==='https:'?';Secure':''}`;
    this._lb=info.ingress_entry; return this._lb; }
  async _preise(datum,items){
    const fil=items.filter(a=>a[5]==='Filament'&&a[4]&&a[2]>0); if(!fil.length) return;
    try{
      const base=await this._lagerBase();
      const r=await fetch(base+'/api/listen/todo.filament',{credentials:'same-origin'}); if(!r.ok) throw new Error('Lager antwortet nicht ('+r.status+')');
      const lager=(await r.json()).items||[];
      const done=[],skip=[],miss=[];
      for(const [n,v,q,s,c] of fil){
        const refill=/refill|nachfüll/i.test(v); const preis=Math.round(s/q*100)/100;
        const cand=lager.map(x=>{let j=null;try{j=JSON.parse(x.description)}catch(e){}return j?{x,j}:null}).filter(e=>e&&String(e.j.fcode||'')===c&&/bambu/i.test(e.j.hersteller||''));
        if(!cand.length){miss.push(`${n} ${v.split(' / ')[0]}`);continue}
        const best=cand.find(e=>(e.j.ausfuehrung==='refill')===refill)||cand[0];
        if(best.j.preis_datum&&best.j.preis_datum>datum){skip.push(best.x.summary);continue}
        const alt=best.j.preis; best.j.preis=preis; best.j.preis_datum=datum; best.j.preis_quelle='Bambu-Rechnung';
        const w=await fetch(base+'/api/listen/todo.filament',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({service:'update_item',data:{item:best.x.uid,description:JSON.stringify(best.j)}})});
        if(w.ok) done.push(`${esc(best.x.summary.replace(/^Bambu Lab /,''))}: ${alt!=null?eur(alt)+' → ':''}${eur(preis)}`); else miss.push(best.x.summary+' (Fehler '+w.status+')');
      }
      if(done.length) this._log('ok',`Lagerpreise aktualisiert (${done.length}):<small>${done.join(' · ')}</small>`);
      if(skip.length) this._log('warn',`Nicht überschrieben, weil im Lager schon ein neuerer Rechnungspreis steht:<small>${skip.map(esc).join(' · ')}</small>`);
      if(miss.length) this._log('warn',`Nicht im Lager gefunden (Farbnummer fehlt dort):<small>${miss.map(esc).join(' · ')}</small>`);
    }catch(e){this._lb=null;this._log('err','Preise konnten nicht ins Lager übernommen werden: '+esc(e.message||e)+'<small>Dafür braucht es einen Administrator-Zugang und den laufenden SchichtLohn-Server.</small>')}
  }
}
if(!customElements.get('bambu-rechnungen-card')) customElements.define('bambu-rechnungen-card',BambuRechnungenCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='bambu-rechnungen-card')) window.customCards.push({type:'bambu-rechnungen-card',name:'Bambu-Rechnungen',description:'Bambu-Lab-Rechnungen durchsuchen und neue PDFs einlesen'});
console.info('%c Bambu-Rechnungen %c '+VERSION,'background:#00ae42;color:#fff;border-radius:3px 0 0 3px;padding:1px 4px','background:#333;color:#fff;border-radius:0 3px 3px 0;padding:1px 4px');
})();
