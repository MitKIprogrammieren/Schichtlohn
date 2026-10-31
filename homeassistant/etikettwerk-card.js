// Etikettwerk – Etiketten für Phomemo M110 und M20 Pro (custom:etikettwerk-card).
// Wird in Home Assistant über einen kleinen Lader von jsDelivr geholt, siehe homeassistant/etikettwerk-loader.js.
function etikettwerkQuelle(){/*@@
<title>Etikettwerk</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#eef1ee;--panel:#ffffff;--ink:#17201a;--mute:#5c6a60;--line:#d5ddd7;
  --accent:#00a33e;--accent-ink:#ffffff;--soft:#e2f4e8;--roll:#dfe4e0;--danger:#c0392b;--warn:#a86b00;
  --f-ui:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#121614;--panel:#1b201d;--ink:#e6ece8;--mute:#93a198;--line:#2c342f;
  --accent:#1fc35a;--accent-ink:#06210f;--soft:#173322;--roll:#0d100e;--danger:#ff7a6b;--warn:#e7a93a;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#121614;--panel:#1b201d;--ink:#e6ece8;--mute:#93a198;--line:#2c342f;
  --accent:#1fc35a;--accent-ink:#06210f;--soft:#173322;--roll:#0d100e;--danger:#ff7a6b;--warn:#e7a93a;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-ui);font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding-block:16px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:16px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{display:flex;align-items:baseline;gap:10px}
.brand h1{font-size:22px;font-weight:600;margin:0;letter-spacing:-.01em;text-wrap:balance}
.brand span{font-family:var(--f-mono);font-size:12px;color:var(--mute)}
.status{font-size:12px;padding:5px 10px;border-radius:999px;border:1px solid var(--line);background:var(--panel);display:flex;gap:6px;align-items:center}
.status i{width:8px;height:8px;border-radius:50%;background:var(--mute);display:inline-block}
.status.on i{background:var(--accent)}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:16px;align-items:start}
@media (max-width:860px){.grid{grid-template-columns:minmax(0,1fr)}.grid>.side{display:contents}.vorschau{position:sticky;top:0;z-index:5;padding:8px;gap:6px;box-shadow:0 8px 18px rgba(0,0,0,.22)}.stage{padding:22px 8px 8px;min-height:0}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:12px;min-width:0}
.panel h2{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);margin:0}
.printers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.pbtn{text-align:left;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:10px;cursor:pointer;font:inherit;display:flex;flex-direction:column;gap:2px}
.pbtn b{font-weight:600}.pbtn small{color:var(--mute);font-family:var(--f-mono);font-size:11px}
.pbtn[aria-pressed="true"]{border:2px solid var(--accent);padding:9px;background:var(--soft)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:5px 11px;font:500 12px var(--f-mono);cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}
.row>label{flex:1 1 90px;min-width:0}
label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--mute)}
input,select,textarea{font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 8px;width:100%;min-width:0}
textarea{resize:vertical;min-height:44px}
input:focus-visible,select:focus-visible,textarea:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
input[type=range]{padding:0;accent-color:var(--accent)}
input[type=checkbox]{width:auto;accent-color:var(--accent)}
.check{flex-direction:row;align-items:center;gap:6px;color:var(--ink);font-size:13px}
.btn{font:500 13px var(--f-ui);border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:7px;padding:8px 12px;cursor:pointer;display:inline-flex;gap:6px;align-items:center;justify-content:center}
.btn:hover{border-color:var(--mute)}
.btn.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:600}
.btn.danger{color:var(--danger)}
.stage{background:var(--roll);border-radius:10px;padding:28px 12px;display:flex;justify-content:center;align-items:center;overflow-x:auto;position:relative;min-height:240px}
.stage .ruler{position:absolute;top:8px;left:12px;font:11px var(--f-mono);color:var(--mute)}
#cv{background:#fff;border-radius:4px;box-shadow:0 1px 0 rgba(0,0,0,.08),0 6px 20px rgba(0,0,0,.12);touch-action:none;cursor:crosshair;max-width:100%;height:auto}
.els{display:flex;flex-direction:column;gap:6px}
.el{display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:7px;padding:7px 9px;cursor:pointer;background:var(--panel);color:var(--ink);font:inherit;text-align:left;width:100%}
.el[aria-pressed="true"]{border-color:var(--accent);background:var(--soft)}
.el .k{font:500 11px var(--f-mono);color:var(--mute);width:58px;flex:none}
.el .v{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.add{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
.note{font-size:12px;line-height:1.5;color:var(--mute);background:var(--bg);border-radius:8px;padding:10px}
.note b{color:var(--ink);font-weight:600}
.msg{font-size:13px;min-height:18px}
.msg.err{color:var(--danger)}.msg.ok{color:var(--accent)}.msg.warn{color:var(--warn)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden}.bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .15s}
.meta{font:12px var(--f-mono);color:var(--mute);text-align:center}
.side{display:flex;flex-direction:column;gap:16px;min-width:0}
.logos{display:grid;grid-template-columns:repeat(auto-fill,minmax(72px,1fr));gap:8px}
.logo{position:relative;aspect-ratio:1;max-width:100%;background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px;cursor:pointer;display:grid;place-items:center}
.logo img{max-width:100%;max-height:100%;object-fit:contain}
.logo:hover{border-color:var(--accent)}
.logo .x{position:absolute;top:2px;right:2px;width:22px;height:22px;border-radius:50%;border:1px solid var(--line);background:var(--panel);color:var(--danger);font:600 13px/1 var(--f-ui);cursor:pointer;display:grid;place-items:center;padding:0}
.logo.up{background:transparent;border-style:dashed;color:var(--mute);font-size:12px;text-align:center;line-height:1.3}
.logo.up input{position:absolute;inset:0;opacity:0;cursor:pointer}
.weg{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
.wegb{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:8px;font:500 13px var(--f-ui);cursor:pointer}
.wegb[aria-pressed="true"]{background:var(--soft);border-color:var(--accent);color:var(--ink)}
.pbtn .ok{color:var(--accent)}.pbtn .aus{color:var(--warn)}
#haBox,#btBox{display:flex;flex-direction:column;gap:10px}
.slbox{display:flex;flex-direction:column;gap:10px}
.sllist{display:flex;flex-direction:column;gap:6px;max-height:300px;overflow-y:auto;padding-right:2px}
.sp{display:flex;gap:10px;align-items:center;border:1px solid var(--line);border-radius:7px;padding:7px 9px;background:var(--panel);color:var(--ink);font:inherit;text-align:left;cursor:pointer;width:100%}
.sp[aria-pressed="true"]{border:2px solid var(--accent);padding:6px 8px;background:var(--soft)}
.sp .dot{width:14px;height:14px;border-radius:50%;flex:none;border:1px solid var(--line)}
.sp .n{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sp .c{font:12px var(--f-mono);color:var(--mute);flex:none}
.slslots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.slmode{font:600 11px var(--f-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
@media (prefers-reduced-motion:reduce){.bar>i{transition:none}}
</style>
<div class="wrap">
  <header>
    <div class="brand"><h1>Etikettwerk</h1><span>Etiketten für Phomemo M110 · M20 Pro</span></div>
    <div class="status" id="status"><i></i><span id="statusTxt">Nicht verbunden</span></div>
  </header>
  <div class="grid">
    <div class="side">
      <section class="panel vorschau">
        <div class="stage"><span class="ruler" id="ruler">40 × 30 mm</span><canvas id="cv" width="320" height="240" aria-label="Etikettenvorschau"></canvas></div>
        <div class="meta" id="meta"></div>
      </section>
      <section class="panel">
        <div class="row">
          <label for="tpl">Vorlage<select id="tpl">
            <option value="box">Lagerbox / Regal</option>
            <option value="adresse">Absender / Adresse</option>
            <option value="vorrat">Vorrat mit Datum</option>
            <option value="inventar">Gerät / Inventar mit QR</option>
            <option value="preis">Preisschild</option>
            <option value="ordner">Ordner / Akte</option>
            <option value="kabel">Kabelfahne</option>
            <option value="filament">Filament-Spule</option>
            <option value="leer">Leer</option>
          </select></label>
          <button class="btn" id="saveDesign">Entwurf merken</button>
          <button class="btn" id="loadDesign">Entwurf laden</button>
        </div>
      </section>
      <section class="panel">
        <h2>Elemente</h2>
        <div class="add">
          <button class="btn" data-add="text">+ Text</button>
          <button class="btn" data-add="barcode">+ Barcode</button>
          <button class="btn" data-add="qr">+ QR-Code</button>
          <button class="btn" data-add="image">+ Bild</button>
          <button class="btn" data-add="line">+ Linie</button>
          <button class="btn" data-add="box">+ Rahmen</button>
        </div>
        <div class="els" id="els"></div>
        <div id="props" class="panel" style="padding:12px;background:var(--bg)"></div>
      </section>
      <section class="panel">
        <h2>Logos</h2>
        <div class="logos" id="logos"></div>
        <div class="note">Antippen setzt das Logo aufs Etikett. Die Logos bleiben in diesem Browser gespeichert.</div>
      </section>
    </div>
    <div class="side">
      <section class="panel" id="slPanel">
        <div class="row" style="justify-content:space-between;align-items:center"><h2>SchichtLohn</h2><span class="status" id="slStatus"><i></i><span id="slStatusTxt">Nicht geladen</span></span></div>
        <div class="row">
          <label for="slUrl">Server<input id="slUrl" type="url" placeholder="https://schichtlohn.dein-tailnet.ts.net" autocomplete="off" spellcheck="false"></label>
          <button class="btn" id="slLoad">Spulen laden</button>
        </div>
        <div id="slBody" hidden>
          <div class="slbox">
            <input id="slQ" type="search" placeholder="Suchen: PLA, Bambu, Schwarz" aria-label="Spulen durchsuchen">
            <div class="sllist" id="slList"></div>
            <div class="chips" id="slFmt"></div>
            <label class="check" for="slHoch"><input type="checkbox" id="slHoch"> Hochkant (um 90° gedreht auf derselben Rolle)</label>
            <div class="slslots" id="slSlots"></div>
            <div class="row">
              <button class="btn" id="slLogos">Herstellerlogos übernehmen</button>
              <button class="btn" id="slFrei">Freies Etikett</button>
            </div>
            <div class="note" id="slNote">Das Etikett ist dasselbe wie in SchichtLohn und auf der Waage. Der QR-Code öffnet die Rolle in SchichtLohn.</div>
          </div>
        </div>
      </section>
      <section class="panel">
        <h2>Drucker</h2>
        <div class="weg" id="weg">
          <button class="wegb" data-weg="ha" aria-pressed="false">Über Home Assistant</button>
          <button class="wegb" data-weg="bt" aria-pressed="false">Direkt per Bluetooth</button>
        </div>
        <div id="haBox">
          <div class="printers" id="haPrinters"></div>
          <div class="note" id="haNote">Suche die Druckbrücke in Home Assistant …</div>
        </div>
        <div id="btBox" hidden>
          <div class="printers" id="printers"></div>
          <div class="row">
            <button class="btn primary" id="connect" style="flex:1">Per Bluetooth verbinden</button>
            <button class="btn" id="disconnect">Trennen</button>
          </div>
          <div class="note" id="btNote"></div>
        </div>
      </section>
      <section class="panel">
        <h2>Etikett</h2>
        <div class="chips" id="sizes"></div>
        <div class="row">
          <label for="lw">Breite mm<input id="lw" type="number" min="10" max="80" step="1"></label>
          <label for="lh">Höhe mm<input id="lh" type="number" min="5" max="200" step="1"></label>
          <label for="media">Material<select id="media">
            <option value="10">Etiketten mit Lücke</option>
            <option value="11">Endlos</option>
            <option value="38">Schwarzmarke</option>
          </select></label>
        </div>
        <label class="check" for="rot"><input type="checkbox" id="rot"> Um 90° drehen (quer drucken)</label>
      </section>
      <section class="panel">
        <h2>Druck</h2>
        <div class="row">
          <label for="copies">Anzahl<input id="copies" type="number" min="1" max="99" value="1"></label>
          <label for="speed">Tempo<select id="speed"><option value="1">1 langsam</option><option value="2">2</option><option value="3" selected>3</option><option value="4">4</option><option value="5">5 schnell</option></select></label>
        </div>
        <label for="dens">Schwärzung <span id="densOut">10</span><input id="dens" type="range" min="1" max="15" step="1" value="10"></label>
        <label for="thr">Schwelle für Bilder <span id="thrOut">128</span><input id="thr" type="range" min="40" max="220" step="1" value="128"></label>
        <label class="check" for="dither"><input type="checkbox" id="dither" checked> Bilder rastern (Dithering)</label>
        <button class="btn primary" id="print">Drucken</button>
        <div class="bar"><i id="prog"></i></div>
        <div class="msg" id="msg"></div>
      </section>
    </div>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jsbarcode/3.11.6/JsBarcode.all.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcode-generator/1.4.4/qrcode.min.js"></script>
<script>
const PRINTERS={
  m110:{name:"M110",dpi:203,head:384,maxW:50,sprache:"escpos",info:"203 dpi · 48 mm Kopf"},
  m20p:{name:"M20 Pro",dpi:300,head:576,maxW:50,sprache:"tspl",info:"300 dpi · 20–50 mm"}
};
const SIZES=[[40,30],[50,30],[30,20],[50,25],[40,20],[25,15],[50,50],[50,80]];
const S={printer:"m110",w:40,h:30,media:10,rot:false,els:[],sel:0};
const $=id=>document.getElementById(id);
let uid=1;
const imgCache=new Map();
function tpl(name){
  const W=S.w,H=S.h;
  if(name==="filament")return[
    {t:"text",x:2,y:2,w:W-4,size:5.5,bold:true,align:"left",text:"PLA Basic"},
    {t:"text",x:2,y:9,w:W-4,size:3.2,bold:false,align:"left",text:"Bambu Lab · Schwarz"},
    {t:"text",x:2,y:13.5,w:W-4,size:3,bold:false,align:"left",text:"1,75 mm · 220 °C · 1 kg"},
    {t:"barcode",x:2,y:H-11,w:W-16,h:9,data:"4006381333931",text:false},
    {t:"qr",x:W-12,y:H-12,w:10,data:"https://bambuddy.local/spool/42"}];
  if(name==="box")return[
    {t:"box",x:1,y:1,w:W-2,h:H-2,stroke:0.5},
    {t:"text",x:3,y:3,w:W-6,size:3,bold:false,align:"left",text:"Regal B · Fach 3"},
    {t:"text",x:3,y:8,w:W-6,size:7,bold:true,align:"left",text:"M3 Schrauben"},
    {t:"line",x:3,y:17,w:W-6,h:0,stroke:0.4},
    {t:"text",x:3,y:19,w:W-6,size:3.2,bold:false,align:"left",text:"DIN 912 · 8–20 mm"}];
  const heute=new Date().toLocaleDateString("de-DE");
  if(name==="adresse")return[
    {t:"text",x:2,y:2,w:W-4,size:3,bold:false,align:"left",text:"Absender"},
    {t:"text",x:2,y:6.5,w:W-4,size:4.2,bold:true,align:"left",text:"Max Mustermann"},
    {t:"text",x:2,y:12,w:W-4,size:3.6,bold:false,align:"left",text:"Musterstraße 12\n10115 Berlin"}];
  if(name==="vorrat")return[
    {t:"text",x:2,y:2,w:W-4,size:6,bold:true,align:"left",text:"Tomatensoße"},
    {t:"text",x:2,y:10,w:W-4,size:3.4,bold:false,align:"left",text:"Eingefroren: "+heute},
    {t:"text",x:2,y:15,w:W-4,size:3.4,bold:false,align:"left",text:"Haltbar bis: 3 Monate"},
    {t:"line",x:2,y:H-6,w:W-4,h:0,stroke:0.3},
    {t:"text",x:2,y:H-5,w:W-4,size:3,bold:false,align:"right",text:"2 Portionen"}];
  if(name==="inventar")return[
    {t:"text",x:2,y:2,w:W-16,size:3,bold:false,align:"left",text:"Eigentum von"},
    {t:"text",x:2,y:6,w:W-16,size:4.5,bold:true,align:"left",text:"Werkstatt"},
    {t:"text",x:2,y:12,w:W-16,size:3.2,bold:false,align:"left",text:"Akkuschrauber\nInv.-Nr. 0042"},
    {t:"qr",x:W-13,y:2,w:11,data:"https://example.com/inventar/0042"},
    {t:"barcode",x:2,y:H-8,w:W-4,h:6,data:"INV0042",text:false}];
  if(name==="preis")return[
    {t:"text",x:2,y:2,w:W-4,size:3.6,bold:false,align:"center",text:"Bambu-Halter, PETG"},
    {t:"text",x:2,y:7.5,w:W-4,size:10,bold:true,align:"center",text:"4,90 €"},
    {t:"barcode",x:6,y:H-8,w:W-12,h:6,data:"ART-1001",text:false}];
  if(name==="ordner")return[
    {t:"text",x:1,y:2,w:W-2,size:4,bold:false,align:"center",text:"2026"},
    {t:"line",x:3,y:8,w:W-6,h:0,stroke:0.4},
    {t:"text",x:1,y:10,w:W-2,size:7,bold:true,align:"center",text:"Rechnungen"},
    {t:"text",x:1,y:H-6,w:W-2,size:3.2,bold:false,align:"center",text:"Jan – Dez"}];
  if(name==="kabel")return[
    {t:"text",x:1,y:2,w:W-2,size:4.5,bold:true,align:"center",text:"NAS DsCLoud"},
    {t:"line",x:2,y:H/2,w:W-4,h:0,stroke:0.3},
    {t:"text",x:1,y:H/2+2,w:W-2,size:4.5,bold:true,align:"center",text:"NAS DsCLoud"}];
  return[];
}
function setEls(a){
  // Aufräumen: übereinanderliegende Logos (gleiche Stelle) aus der alten Fassung – das zuletzt eingefügte bleibt
  const ort=e=>e.t==="image"?e.x+"|"+e.y:null,letzte=new Map();a.forEach((e,i)=>{const k=ort(e);if(k)letzte.set(k,i);});
  S.els=a.filter((e,i)=>{const k=ort(e);return !k||letzte.get(k)===i;}).map(e=>({...e,id:uid++}));S.sel=S.els[0]?.id||0;}
function px(){return PRINTERS[S.printer].dpi/25.4;}
function dims(){const k=px();return{w:Math.round(S.w*k),h:Math.round(S.h*k)};}
function drawLabel(ctx,k,forPrint){
  const W=S.w*k,H=S.h*k;
  ctx.fillStyle="#fff";ctx.fillRect(0,0,W,H);
  ctx.fillStyle="#000";ctx.strokeStyle="#000";ctx.textBaseline="top";
  for(const e of S.els){
    if(e.t==="text"){
      ctx.font=`${e.bold?600:400} ${e.size*k}px "IBM Plex Sans", Arial, sans-serif`;
      ctx.textAlign=e.align;
      const ax=e.align==="left"?e.x:e.align==="center"?e.x+e.w/2:e.x+e.w;
      String(e.text).split("\n").forEach((ln,i)=>ctx.fillText(ln,ax*k,(e.y+i*e.size*1.15)*k,e.w*k));
    }else if(e.t==="barcode"){
      try{const c=document.createElement("canvas");
        JsBarcode(c,e.data||"0",{format:"CODE128",displayValue:!!e.text,margin:0,height:100,width:2,fontSize:28});
        ctx.imageSmoothingEnabled=false;ctx.drawImage(c,e.x*k,e.y*k,e.w*k,e.h*k);
      }catch(err){ctx.font=`${3*k}px sans-serif`;ctx.textAlign="left";ctx.fillText("Barcode ungültig",e.x*k,e.y*k);}
    }else if(e.t==="qr"){
      try{const q=qrcode(0,"M");q.addData(e.data||" ");q.make();const n=q.getModuleCount(),m=e.w*k/n;
        for(let r=0;r<n;r++)for(let c=0;c<n;c++)if(q.isDark(r,c))ctx.fillRect(Math.floor(e.x*k+c*m),Math.floor(e.y*k+r*m),Math.ceil(m),Math.ceil(m));
      }catch(err){}
    }else if(e.t==="line"){
      ctx.lineWidth=Math.max(1,e.stroke*k);ctx.beginPath();ctx.moveTo(e.x*k,e.y*k);ctx.lineTo((e.x+e.w)*k,(e.y+(e.h||0))*k);ctx.stroke();
    }else if(e.t==="box"){
      ctx.lineWidth=Math.max(1,e.stroke*k);ctx.strokeRect(e.x*k,e.y*k,e.w*k,e.h*k);
    }else if(e.t==="image"&&e.src){
      const im=imgCache.get(e.src);
      if(im&&im.complete&&im.naturalWidth){
        if(!e.invert)ctx.drawImage(im,e.x*k,e.y*k,e.w*k,e.h*k);
        else{const w=Math.max(1,Math.round(e.w*k)),h=Math.max(1,Math.round(e.h*k)),t=document.createElement("canvas");t.width=w;t.height=h;
          const tx=t.getContext("2d");tx.fillStyle="#fff";tx.fillRect(0,0,w,h);tx.drawImage(im,0,0,w,h);
          const d=tx.getImageData(0,0,w,h);for(let i=0;i<d.data.length;i+=4){d.data[i]=255-d.data[i];d.data[i+1]=255-d.data[i+1];d.data[i+2]=255-d.data[i+2];}
          tx.putImageData(d,0,0);ctx.drawImage(t,e.x*k,e.y*k,w,h);}
      }
    }
    if(!forPrint&&e.id===S.sel){
      const b=bounds(e);ctx.save();ctx.setLineDash([4,3]);ctx.lineWidth=1.5;ctx.strokeStyle="#00a33e";
      ctx.strokeRect(b.x*k-2,b.y*k-2,b.w*k+4,b.h*k+4);ctx.restore();ctx.strokeStyle="#000";
    }
  }
}
function bounds(e){
  if(e.t==="text"){const n=String(e.text).split("\n").length;return{x:e.x,y:e.y,w:e.w,h:e.size*1.15*n};}
  if(e.t==="qr")return{x:e.x,y:e.y,w:e.w,h:e.w};
  if(e.t==="line")return{x:e.x,y:e.y-1,w:e.w,h:Math.max(2,e.h||0)};
  return{x:e.x,y:e.y,w:e.w,h:e.h};
}
let viewK=8;
const maxH=()=>window.matchMedia("(max-width:860px)").matches?Math.min(190,innerHeight*0.26):360;
function render(){
  if(S.mode==="sl")return slRender();
  const cv=$("cv"),stageW=Math.min(cv.parentElement.clientWidth-24,640);
  viewK=Math.max(3,Math.min(12,stageW/S.w,maxH()/S.h));
  const dpr=window.devicePixelRatio||1;
  cv.width=Math.round(S.w*viewK*dpr);cv.height=Math.round(S.h*viewK*dpr);
  cv.style.width=S.w*viewK+"px";cv.style.height=S.h*viewK+"px";
  const ctx=cv.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);drawLabel(ctx,viewK,false);
  const d=dims(),p=PRINTERS[S.printer];
  $("ruler").textContent=`${S.w} × ${S.h} mm`;
  $("meta").textContent=`${p.name}: ${S.rot?d.h:d.w} × ${S.rot?d.w:d.h} Punkte bei ${p.dpi} dpi`;
}
function renderPrinters(){
  $("printers").innerHTML=Object.entries(PRINTERS).map(([k,p])=>`<button class="pbtn" data-p="${k}" aria-pressed="${S.printer===k}"><b>${p.name}</b><small>${p.info}</small></button>`).join("");
}
function renderSizes(){
  $("sizes").innerHTML=SIZES.map(([w,h])=>`<button class="chip" data-s="${w}x${h}" aria-pressed="${S.w===w&&S.h===h}">${w}×${h}</button>`).join("");
  $("lw").value=S.w;$("lh").value=S.h;$("media").value=S.media;$("rot").checked=S.rot;
}
const KIND={text:"Text",barcode:"Barcode",qr:"QR-Code",image:"Bild",line:"Linie",box:"Rahmen"};
function label(e){return e.t==="text"?e.text:e.t==="barcode"||e.t==="qr"?e.data:e.t==="image"?(e.name||"Bild"):`${e.w} mm`;}
function renderEls(){
  $("els").innerHTML=S.els.length?S.els.map(e=>`<button class="el" data-id="${e.id}" aria-pressed="${e.id===S.sel}"><span class="k">${KIND[e.t]}</span><span class="v">${esc(label(e))}</span></button>`).join(""):`<div class="note">Noch keine Elemente. Füge oben Text, Barcode oder QR-Code hinzu.</div>`;
  renderProps();
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function num(id,lab,v,step=0.5){return`<label for="${id}">${lab}<input id="${id}" data-f="${id.slice(2)}" type="number" step="${step}" value="${+(+v).toFixed(2)}"></label>`;}
function renderProps(){
  const e=S.els.find(x=>x.id===S.sel),P=$("props");
  if(!e){P.innerHTML=`<div class="note">Element anklicken oder auf dem Etikett antippen, um es zu bearbeiten. Ziehen verschiebt es.</div>`;return;}
  let h="";
  if(e.t==="text")h+=`<label for="p_text">Text<textarea id="p_text" data-f="text">${esc(e.text)}</textarea></label>
    <div class="row">${num("p_size","Schrift mm",e.size,0.1)}<label for="p_align">Ausrichtung<select id="p_align" data-f="align">
    ${["left","center","right"].map(a=>`<option value="${a}"${e.align===a?" selected":""}>${{left:"links",center:"Mitte",right:"rechts"}[a]}</option>`).join("")}</select></label></div>
    <label class="check" for="p_bold"><input type="checkbox" id="p_bold" data-f="bold"${e.bold?" checked":""}> Fett</label>`;
  if(e.t==="barcode")h+=`<label for="p_data">Inhalt (Code 128)<input id="p_data" data-f="data" value="${esc(e.data)}"></label>
    <label class="check" for="p_text2"><input type="checkbox" id="p_text2" data-f="text"${e.text?" checked":""}> Ziffern darunter</label>`;
  if(e.t==="qr")h+=`<label for="p_data">Inhalt (Text oder Link)<input id="p_data" data-f="data" value="${esc(e.data)}"></label>`;
  if(e.t==="image")h+=`<label for="p_file">Bild wählen<input id="p_file" type="file" accept="image/*"></label>
    <label class="check" for="p_invert"><input type="checkbox" id="p_invert" data-f="invert"${e.invert?" checked":""}> Farben umkehren</label>
    ${e.src?`<button class="btn" id="keepLogo">In Logos merken</button>`:""}`;
  h+=`<div class="row">${num("p_x","X mm",e.x)}${num("p_y","Y mm",e.y)}${num("p_w",e.t==="qr"?"Größe mm":"Breite mm",e.w)}${e.t==="barcode"||e.t==="image"||e.t==="box"?num("p_h","Höhe mm",e.h):""}${e.t==="line"||e.t==="box"?num("p_stroke","Stärke mm",e.stroke,0.1):""}</div>
  <div class="row"><button class="btn" id="dup">Duplizieren</button><button class="btn" id="center">Waagrecht mittig</button><button class="btn danger" id="del">Löschen</button></div>`;
  P.innerHTML=h;
}
document.addEventListener("click",ev=>{
  const t=ev.target.closest("button");if(!t)return;
  if(t.dataset.p){S.printer=t.dataset.p;renderPrinters();clampSize();render();persist();}
  else if(t.dataset.s){const[w,h]=t.dataset.s.split("x").map(Number);S.w=w;S.h=h;clampSize();renderSizes();render();persist();}
  else if(t.dataset.add)addEl(t.dataset.add);
  else if(t.dataset.id){S.sel=+t.dataset.id;renderEls();render();}
  else if(t.id==="del"){S.els=S.els.filter(e=>e.id!==S.sel);S.sel=S.els[0]?.id||0;renderEls();render();persist();}
  else if(t.id==="dup"){const e=S.els.find(x=>x.id===S.sel);if(e){const c={...e,id:uid++,y:e.y+3};S.els.push(c);S.sel=c.id;renderEls();render();persist();}}
  else if(t.id==="center"){const e=S.els.find(x=>x.id===S.sel);if(e){e.x=+((S.w-e.w)/2).toFixed(2);renderProps();render();persist();}}
  else if(t.id==="keepLogo"){const e=S.els.find(x=>x.id===S.sel),im=e&&imgCache.get(e.src);
    if(e&&im)addLogo({src:e.src,name:e.name||"Logo",ratio:(im.naturalHeight||1)/(im.naturalWidth||1)});}
  else if(t.id==="saveDesign"){try{localStorage.setItem("etikettwerk.entwurf",JSON.stringify(snap()));say("Entwurf gemerkt","ok");}catch(e){say("Speichern geht in diesem Browser nicht","err");}}
  else if(t.id==="loadDesign"){try{const d=JSON.parse(localStorage.getItem("etikettwerk.entwurf")||"null");if(d){restore(d);say("Entwurf geladen","ok");}else say("Noch kein Entwurf gemerkt","warn");}catch(e){say("Kein Entwurf lesbar","err");}}
  else if(t.id==="connect")connect();
  else if(t.id==="disconnect")disconnect();
  else if(t.id==="print")printLabel();
});
function addEl(kind){
  const base={text:{t:"text",x:2,y:2,w:S.w-4,size:4,bold:false,align:"left",text:"Neuer Text"},
    barcode:{t:"barcode",x:2,y:S.h-12,w:S.w-4,h:10,data:"123456789",text:true},
    qr:{t:"qr",x:S.w-14,y:2,w:12,data:"https://"},
    image:{t:"image",x:2,y:2,w:15,h:15,src:"",name:"Bild"},
    line:{t:"line",x:2,y:S.h/2,w:S.w-4,h:0,stroke:0.4},
    box:{t:"box",x:1,y:1,w:S.w-2,h:S.h-2,stroke:0.5}}[kind];
  const e={...base,id:uid++};S.els.push(e);S.sel=e.id;renderEls();render();persist();
}
document.addEventListener("input",ev=>{
  const t=ev.target;
  if(t.dataset.f){const e=S.els.find(x=>x.id===S.sel);if(!e)return;const f=t.dataset.f;
    e[f]=t.type==="checkbox"?t.checked:t.type==="number"?(parseFloat(t.value)||0):t.value;
    const b=document.querySelector(`.el[data-id="${e.id}"] .v`);if(b)b.textContent=label(e);
    render();persist();return;}
  if(t.id==="lw"||t.id==="lh"){S.w=Math.max(10,+$("lw").value||S.w);S.h=Math.max(5,+$("lh").value||S.h);clampSize(true);
    document.querySelectorAll(".chip").forEach(c=>c.setAttribute("aria-pressed",c.dataset.s===`${S.w}x${S.h}`));render();persist();}
  if(t.id==="tpl"){if(S.mode==="sl")slFreiModus();setEls(tpl(t.value));renderEls();render();persist();say("Vorlage geladen","ok");}
  if(t.id==="media"){S.media=+t.value;persist();}
  if(t.id==="rot"){S.rot=t.checked;render();persist();}
  if(t.id==="dens")$("densOut").textContent=t.value;
  if(t.id==="thr")$("thrOut").textContent=t.value;
});
function readImage(f){
  return new Promise((ok,fail)=>{
    const r=new FileReader();
    r.onerror=()=>fail(new Error("Datei nicht lesbar"));
    r.onload=()=>{const im=new Image();
      im.onerror=()=>fail(new Error("Kein gültiges Bild"));
      im.onload=()=>{
        const iw=im.naturalWidth||800,ih=im.naturalHeight||800,s=Math.min(1,800/Math.max(iw,ih));
        const c=document.createElement("canvas");c.width=Math.max(1,Math.round(iw*s));c.height=Math.max(1,Math.round(ih*s));
        c.getContext("2d").drawImage(im,0,0,c.width,c.height);
        const src=c.toDataURL("image/png"),out=new Image();
        out.onload=()=>{imgCache.set(src,out);ok({src,ratio:c.height/c.width,name:f.name.replace(/\.[^.]+$/,"")});};out.src=src;
      };im.src=r.result;};
    r.readAsDataURL(f);
  });
}
// Weißen bzw. durchsichtigen Rand um ein Logo abschneiden, damit es bündig mit der Schrift sitzt
const trimCache=new Map();
function trimLogo(src){if(trimCache.has(src))return Promise.resolve(trimCache.get(src));
  return new Promise(ok=>{const im=new Image();const fertig=r=>{trimCache.set(src,r);ok(r);};
    im.onerror=()=>ok({src,ratio:0});
    im.onload=()=>{const w=im.naturalWidth,h=im.naturalHeight;if(!w||!h)return fertig({src,ratio:0});
      const c=document.createElement("canvas");c.width=w;c.height=h;const x=c.getContext("2d");x.drawImage(im,0,0);let d;
      try{d=x.getImageData(0,0,w,h).data;}catch(e){return fertig({src,ratio:h/w});}
      let x0=w,y0=h,x1=-1,y1=-1;
      for(let y=0;y<h;y++)for(let i=0;i<w;i++){const p=(y*w+i)*4;if(d[p+3]<40)continue;if(0.299*d[p]+0.587*d[p+1]+0.114*d[p+2]>235)continue;
        if(i<x0)x0=i;if(i>x1)x1=i;if(y<y0)y0=y;if(y>y1)y1=y;}
      if(x1<0||(x1-x0>=w-2&&y1-y0>=h-2))return fertig({src,ratio:h/w});
      const cw=x1-x0+1,ch=y1-y0+1,o=document.createElement("canvas");o.width=cw;o.height=ch;
      const ox=o.getContext("2d");ox.fillStyle="#fff";ox.fillRect(0,0,cw,ch);ox.drawImage(c,x0,y0,cw,ch,0,0,cw,ch);
      const s2=o.toDataURL("image/png"),n=new Image();n.onload=()=>{imgCache.set(s2,n);fertig({src:s2,ratio:ch/cw});};n.src=s2;};
    im.src=src;});}
// Logo antippen: Ist ein Logo/Bild ausgewählt, wird es ausgetauscht (gleiche Höhe und linke Kante).
// Sonst kommt ein neues Logo dazu – linksbündig mit der Schrift.
async function placeLogo(L){
  const t=await trimLogo(L.src),ratio=t.ratio||L.ratio||1;
  // Logos passen in ein einheitliches Feld (max. 18 × 4 mm), damit lange und kurze Logos gleich wirken
  const fit=x=>{const mw=Math.max(4,Math.min(18,S.w-x-2)),mh=Math.max(2,Math.min(4,S.h-4));let w=mw,h=w*ratio;if(h>mh){h=mh;w=h/ratio;}return {w:+w.toFixed(1),h:+h.toFixed(1)};};
  const sel=S.els.find(x=>x.id===S.sel&&x.t==="image");
  if(sel){Object.assign(sel,{src:t.src,name:L.name,invert:false},fit(sel.x));
    renderEls();render();renderProps();persist();say(`Logo gegen ${L.name} getauscht`,"ok");return;}
  const txt=S.els.filter(x=>x.t==="text"&&x.align!=="right");
  const links=txt.length?Math.min(...txt.map(x=>x.align==="center"?2:x.x)):2;
  const e={t:"image",x:links,y:2,src:t.src,name:L.name,invert:false,id:uid++,...fit(links)};
  S.els.push(e);S.sel=e.id;renderEls();render();persist();
}
document.addEventListener("change",async ev=>{
  const t=ev.target;
  if(t.id==="p_file"){const f=t.files[0];if(!f)return;
    try{const L=await readImage(f),e=S.els.find(x=>x.id===S.sel);
      e.src=L.src;e.name=L.name;e.h=+(e.w*L.ratio).toFixed(1);renderEls();render();persist();}
    catch(err){say(err.message,"err");}}
  if(t.id==="logoUp"){
    for(const f of t.files){try{const L=await readImage(f);addLogo(L);}catch(err){say(`${f.name}: ${err.message}`,"err");}}
    t.value="";}
});
let LOGOS=[];
function loadLogos(){try{LOGOS=JSON.parse(localStorage.getItem("etikettwerk.logos")||"[]");}catch(e){LOGOS=[];}
  LOGOS.forEach(L=>{if(!imgCache.has(L.src)){const im=new Image();im.onload=render;im.src=L.src;imgCache.set(L.src,im);}});}
function saveLogos(){try{localStorage.setItem("etikettwerk.logos",JSON.stringify(LOGOS));return true;}
  catch(e){say("Logo-Speicher ist voll oder gesperrt. Lösche ein Logo oder nimm eine kleinere Datei.","err");return false;}}
function addLogo(L){
  if(LOGOS.some(x=>x.src===L.src)){say("Dieses Logo ist schon gespeichert","warn");return;}
  LOGOS.push({id:Date.now().toString(36)+Math.random().toString(36).slice(2,6),name:L.name,src:L.src,ratio:L.ratio});
  if(saveLogos()){renderLogos();say(`Logo „${L.name}“ gespeichert`,"ok");}else LOGOS.pop();
}
function renderLogos(){
  $("logos").innerHTML=LOGOS.map(L=>`<div class="logo" data-logo="${L.id}" role="button" tabindex="0" title="${esc(L.name)}" aria-label="Logo ${esc(L.name)} einsetzen">
      <img src="${L.src}" alt=""><button class="x" data-dellogo="${L.id}" aria-label="Logo ${esc(L.name)} löschen">×</button></div>`).join("")
    +`<label class="logo up" for="logoUp">Logo<br>hochladen<input id="logoUp" type="file" accept="image/*" multiple></label>`;
}
$("logos").addEventListener("click",ev=>{
  const del=ev.target.closest("[data-dellogo]");
  if(del){ev.stopPropagation();const id=del.dataset.dellogo;
    if(del.dataset.armed){LOGOS=LOGOS.filter(L=>L.id!==id);saveLogos();renderLogos();say("Logo gelöscht","ok");}
    else{del.dataset.armed="1";del.textContent="?";say("Zum Löschen nochmal auf ? tippen","warn");setTimeout(()=>{if(del.isConnected){delete del.dataset.armed;del.textContent="×";}},3000);}
    return;}
  const t=ev.target.closest("[data-logo]");if(t){const L=LOGOS.find(x=>x.id===t.dataset.logo);if(L)placeLogo(L);}
});
$("logos").addEventListener("keydown",ev=>{if((ev.key==="Enter"||ev.key===" ")&&ev.target.dataset.logo){ev.preventDefault();ev.target.click();}});
function clampSize(quiet){
  const p=PRINTERS[S.printer],across=S.rot?S.h:S.w,maxMm=p.head/p.dpi*25.4;
  if(across>maxMm+2.5&&!quiet)say(`Hinweis: Der Druckkopf des ${p.name} ist ${maxMm.toFixed(0)} mm breit, Ränder werden abgeschnitten.`,"warn");
}
let drag=null;
$("cv").addEventListener("pointerdown",ev=>{
  if(S.mode==="sl")return;
  const r=$("cv").getBoundingClientRect(),mx=(ev.clientX-r.left)/viewK,my=(ev.clientY-r.top)/viewK;
  const hit=[...S.els].reverse().find(e=>{const b=bounds(e);return mx>=b.x&&mx<=b.x+b.w&&my>=b.y&&my<=b.y+b.h;});
  if(!hit){S.sel=0;renderEls();render();return;}
  S.sel=hit.id;drag={id:hit.id,dx:mx-hit.x,dy:my-hit.y};$("cv").setPointerCapture(ev.pointerId);renderEls();render();
});
$("cv").addEventListener("pointermove",ev=>{
  if(!drag)return;const r=$("cv").getBoundingClientRect(),e=S.els.find(x=>x.id===drag.id);
  e.x=Math.round(((ev.clientX-r.left)/viewK-drag.dx)*2)/2;e.y=Math.round(((ev.clientY-r.top)/viewK-drag.dy)*2)/2;render();
});
$("cv").addEventListener("pointerup",()=>{if(drag){drag=null;renderProps();persist();}});
function snap(){return{printer:S.printer,w:S.w,h:S.h,media:S.media,rot:S.rot,els:S.els.map(({id,...r})=>r)};}
function restore(d){Object.assign(S,{printer:d.printer||"m110",w:d.w||40,h:d.h||30,media:d.media||10,rot:!!d.rot});setEls(d.els||[]);
  S.els.forEach(e=>{if(e.t==="image"&&e.src&&!imgCache.has(e.src)){const im=new Image();im.onload=render;im.src=e.src;imgCache.set(e.src,im);}});
  renderPrinters();renderSizes();renderEls();render();}
function persist(){try{localStorage.setItem("etikettwerk.zuletzt",JSON.stringify(snap()));}catch(e){}}
async function quelle(dpi){
  if(S.mode==="sl")return slDruckCanvas(dpi);
  const k=dpi/25.4,w=Math.round(S.w*k),h=Math.round(S.h*k);
  const c=document.createElement("canvas");c.width=w;c.height=h;drawLabel(c.getContext("2d"),k,true);
  if(!S.rot)return c;
  const r=document.createElement("canvas");r.width=h;r.height=w;const rx=r.getContext("2d");rx.translate(h,0);rx.rotate(Math.PI/2);rx.drawImage(c,0,0);return r;
}
function bitmap(src,W){
  W=Math.max(8,Math.ceil(W/8)*8);const H=src.height,off=Math.floor((W-src.width)/2);
  const o=document.createElement("canvas");o.width=W;o.height=H;const ox=o.getContext("2d");ox.fillStyle="#fff";ox.fillRect(0,0,W,H);ox.drawImage(src,off,0);
  const id=ox.getImageData(0,0,W,H).data,thr=+$("thr").value,dith=$("dither").checked;
  const g=new Float32Array(W*H);for(let i=0;i<W*H;i++)g[i]=0.299*id[i*4]+0.587*id[i*4+1]+0.114*id[i*4+2];
  const wb=W/8,out=new Uint8Array(wb*H);
  for(let y=0;y<H;y++)for(let xx=0;xx<W;xx++){
    const i=y*W+xx,v=g[i],b=v<thr?1:0;
    if(dith&&v>8&&v<247){const err=v-(b?0:255);
      if(xx+1<W)g[i+1]+=err*7/16;if(y+1<H){if(xx>0)g[i+W-1]+=err*3/16;g[i+W]+=err*5/16;if(xx+1<W)g[i+W+1]+=err/16;}}
    if(b)out[y*wb+(xx>>3)]|=0x80>>(xx&7);
  }
  return{wb,h:H,data:out};
}
const enc=t=>new TextEncoder().encode(t);
function verbinden(parts){const len=parts.reduce((a,b)=>a+b.length,0),all=new Uint8Array(len);let o=0;for(const p of parts){all.set(p,o);o+=p.length;}return all;}
async function job(){
  const p=PRINTERS[S.printer],copies=Math.max(1,Math.min(99,+$("copies").value||1)),dens=+$("dens").value,parts=[];
  const src=await quelle(p.dpi);
  if(p.sprache==="tspl"){
    const r=bitmap(src,src.width),bmm=Math.round(r.wb*8/p.dpi*25.4),hmm=Math.round(r.h/p.dpi*25.4);
    const td=Math.max(1,Math.min(15,Math.floor((dens*7+5)/10))),gap=S.media===11?"GAP 0 mm, 0 mm":"GAP 4.6 mm, 0 mm";
    parts.push(enc(`SPEED 1\r\nSIZE ${bmm} mm,${hmm} mm\r\nREFERENCE 0,0\r\n${gap}\r\nOFFSET 0 mm\r\nDIRECTION 0,0\r\nDENSITY ${td}\r\nCLS\r\n`));
    for(let y0=0;y0<r.h;y0+=24){const z=Math.min(24,r.h-y0),teil=r.data.slice(y0*r.wb,(y0+z)*r.wb);
      if(teil.every(v=>v===0))continue;
      for(let i=0;i<teil.length;i++)teil[i]=~teil[i]&255;
      parts.push(enc(`BITMAP 0,${y0},${r.wb},${z},0,`),teil,enc("\r\n"));}
    parts.push(enc(`PRINT 1,${Math.min(10,copies)}\r\n`));
    return verbinden(parts);
  }
  const r=bitmap(src,p.head);
  for(let n=0;n<copies;n++){
    parts.push(new Uint8Array([0x1b,0x4e,0x0d,+$("speed").value,0x1b,0x4e,0x04,dens,0x1f,0x11,S.media]));
    parts.push(new Uint8Array([0x1d,0x76,0x30,0x00,r.wb&255,r.wb>>8,r.h&255,r.h>>8]));
    parts.push(r.data);
    parts.push(new Uint8Array([0x1f,0xf0,0x05,0x00,0x1f,0xf0,0x03,0x00]));
  }
  return verbinden(parts);
}
let dev=null,chr=null;
const SVC=[0xff00,0xffe0,0x18f0,0xae30,"49535343-fe7d-4ae5-8fa9-9fafd205e455","e7810a71-73ae-499d-8c15-faa9aef0c3f2"];
const HA={ok:false,liste:[],wahl:"",basis:"",grund:""};
const haModell=m=>m==="m20pro"?"m20p":"m110";
function haBasis(){try{if(window.parent!==window&&parent.location.origin&&parent.location.origin!=="null")return parent.location.origin;}catch(e){}
  return /^https?:$/.test(location.protocol)?location.origin:"";}
async function haLaden(){
  HA.basis=haBasis();HA.ok=false;
  if(!HA.basis){HA.grund="Druck über Home Assistant geht nur, wenn Etikettwerk in Home Assistant läuft.";return renderWeg();}
  try{const r=await fetch(HA.basis+"/api/m20_druckbruecke/drucker",{cache:"no-store"});const j=await r.json().catch(()=>({}));
    if(r.status===403)HA.grund="Über Home Assistant druckst du nur im Heimnetz, also mit der lokalen HA-Adresse. Über Nabu Casa oder Tailscale sperrt die Druckbrücke ab.";
    else if(!r.ok||!j.ok)HA.grund=r.status===404?"Die Druckbrücke ist in Home Assistant nicht eingerichtet.":(j.text||"Druckbrücke antwortet mit "+r.status);
    else{HA.ok=true;HA.liste=j.drucker||[];if(!HA.liste.some(d=>d.id===HA.wahl))HA.wahl=(HA.liste.find(d=>d.standard)||HA.liste[0]||{}).id||"";}
  }catch(e){HA.grund="Druckbrücke nicht erreichbar.";}
  if(!S.weg)S.weg=HA.ok?"ha":"bt";
  if(S.weg==="ha"&&HA.ok&&HA.wahl){const m=haModell(HA.wahl);if(S.printer!==m){S.printer=m;renderPrinters();render();}}
  renderWeg();
}
function renderWeg(){
  const w=S.weg||"bt";
  document.querySelectorAll("[data-weg]").forEach(b=>b.setAttribute("aria-pressed",b.dataset.weg===w));
  $("haBox").hidden=w!=="ha";$("btBox").hidden=w!=="bt";
  $("haPrinters").innerHTML=HA.ok?HA.liste.map(d=>`<button class="pbtn" data-ha="${esc(d.id)}" aria-pressed="${d.id===HA.wahl}"><b>${esc(d.name)}</b><small class="${d.erreichbar?"ok":"aus"}">${d.erreichbar?"erreichbar":"nicht erreichbar"}${d.standard?" · Standard":""}${d.beschaeftigt?" · druckt":""}</small></button>`).join(""):"";
  const fehlt=HA.ok&&!HA.liste.some(d=>d.modell==="m110")?" Den M110 fügst du unter Einstellungen → Geräte & Dienste → Druckbrücke Phomemo hinzu.":"";
  $("haNote").innerHTML=HA.ok?`<b>Über die Druckbrücke und den BT-Proxy.</b> Geht auch vom iPhone, solange du im Heimnetz bist.${fehlt}`:`<b>Nicht verfügbar.</b> ${esc(HA.grund)} <button class="btn" id="haNeu" style="margin-top:6px">Erneut suchen</button>`;
  $("statusTxt").textContent=w==="ha"?(HA.ok?`Über Home Assistant · ${(HA.liste.find(d=>d.id===HA.wahl)||{}).name||"kein Drucker"}`:"Home Assistant nicht erreichbar"):(chr?`${dev&&dev.name||"Drucker"} verbunden`:"Nicht verbunden");
  $("status").classList.toggle("on",w==="ha"?HA.ok:!!chr);
}
function b64(u8){let s="";for(let i=0;i<u8.length;i+=0x8000)s+=String.fromCharCode.apply(null,u8.subarray(i,i+0x8000));return btoa(s);}
async function haDrucken(){
  if(!HA.ok){say(HA.grund||"Druckbrücke nicht erreichbar","err");return;}
  const bar=$("prog");bar.style.width="30%";say("Sende an Home Assistant …","");
  try{
    const src=await quelle(203.2),r=bitmap(src,src.width);
    const titel=S.mode==="sl"?((slGewaehlt()||{}).it||{}).summary||"Spulen-Etikett":(S.els.find(e=>e.t==="text")||{}).text||"Etikett";
    const res=await fetch(HA.basis+"/api/m20_druckbruecke/drucken",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({breite:r.wb*8,hoehe:r.h,daten:b64(r.data),kopien:Math.max(1,Math.min(10,+$("copies").value||1)),dichte:+$("dens").value,titel:String(titel).split("\n")[0].slice(0,80),drucker:HA.wahl})});
    const j=await res.json().catch(()=>({}));
    if(!res.ok||!j.ok)throw new Error(j.text||"Druckbrücke antwortet mit "+res.status);
    bar.style.width="100%";say(j.text||"Druckauftrag angenommen","ok");setTimeout(()=>bar.style.width="0",1500);
  }catch(e){bar.style.width="0";say("Druck über Home Assistant fehlgeschlagen: "+e.message,"err");}
}
document.addEventListener("click",ev=>{
  const w=ev.target.closest("[data-weg]");if(w){S.weg=w.dataset.weg;try{localStorage.setItem("etikettwerk.weg",S.weg);}catch(e){}
    if(S.weg==="ha"&&HA.wahl){S.printer=haModell(HA.wahl);renderPrinters();render();}renderWeg();return;}
  const h=ev.target.closest("[data-ha]");if(h){HA.wahl=h.dataset.ha;S.printer=haModell(HA.wahl);renderPrinters();render();renderWeg();return;}
  if(ev.target.closest("#haNeu")){$("haNote").textContent="Suche die Druckbrücke …";haLaden();}
});
function bleOk(){return !!(navigator.bluetooth&&navigator.bluetooth.requestDevice);}
function noteBt(){
  $("btNote").innerHTML=bleOk()
   ?`<b>Bereit.</b> Drucker einschalten, „Verbinden“ tippen und den Phomemo in der Liste wählen. Der M20 Pro bekommt dieselben TSPL-Befehle wie über die Druckbrücke.`
   :`<b>Bluetooth ist hier nicht verfügbar.</b> Gestalten geht überall, gedruckt wird nur in Chrome oder Edge am Mac oder PC, und nur wenn die Seite über https oder localhost geöffnet ist. Safari und das iPhone können kein Web-Bluetooth.`;
}
async function connect(){
  if(!bleOk()){say("Dieser Browser kann kein Web-Bluetooth. Öffne die Seite in Chrome am Mac.","err");return;}
  try{
    dev=await navigator.bluetooth.requestDevice({filters:[{namePrefix:"M110"},{namePrefix:"M20"},{namePrefix:"Q"},{namePrefix:"Mr.in"},{namePrefix:"Phomemo"}],optionalServices:SVC});
    dev.addEventListener("gattserverdisconnected",()=>{chr=null;setStatus(false);});
    const srv=await dev.gatt.connect();chr=null;
    for(const s of await srv.getPrimaryServices()){
      for(const c of await s.getCharacteristics()){if(c.properties.writeWithoutResponse||c.properties.write){chr=c;break;}}
      if(chr)break;
    }
    if(!chr)throw new Error("Keine beschreibbare Schnittstelle gefunden");
    const n=dev.name||"";if(/M20/i.test(n)){S.printer="m20p";renderPrinters();render();}else if(/M110/i.test(n)){S.printer="m110";renderPrinters();render();}
    setStatus(true,n);say("Verbunden","ok");
  }catch(e){
    if(e.name==="NotFoundError")say("Keinen Drucker gewählt","warn");
    else if(e.name==="SecurityError")say("Bluetooth ist in diesem Fenster gesperrt. Öffne die Datei direkt in Chrome.","err");
    else say("Verbindung fehlgeschlagen: "+e.message,"err");
  }
}
function disconnect(){if(dev&&dev.gatt.connected)dev.gatt.disconnect();chr=null;setStatus(false);}
function setStatus(on,n){if(S.weg==="ha")return renderWeg();$("status").classList.toggle("on",on);$("statusTxt").textContent=on?`${n||"Drucker"} verbunden`:"Nicht verbunden";}
async function printLabel(){
  if(S.weg==="ha")return haDrucken();
  if(!chr){say("Erst mit dem Drucker verbinden","warn");return;}
  let data;try{data=await job();}catch(e){say("Etikett konnte nicht erstellt werden: "+e.message,"err");return;}
  const CH=180,bar=$("prog");
  say("Drucke …","");
  try{
    for(let i=0;i<data.length;i+=CH){
      const part=data.slice(i,i+CH);
      if(chr.properties.writeWithoutResponse)await chr.writeValueWithoutResponse(part);else await chr.writeValue(part);
      if(i%(CH*20)===0)await new Promise(r=>setTimeout(r,12));
      bar.style.width=Math.round((i+CH)/data.length*100)+"%";
    }
    bar.style.width="100%";say(`Gesendet: ${(data.length/1024).toFixed(1)} KB`,"ok");
    setTimeout(()=>bar.style.width="0",1500);
  }catch(e){say("Druck abgebrochen: "+e.message,"err");bar.style.width="0";}
}
function say(t,c){const m=$("msg");m.textContent=t;m.className="msg "+(c||"");}
const SL={items:[],uid:"",fmt:"classic",hoch:false,slots:null,q:"",vor:null,lauf:0};
const slSlug=n=>String(n||"").trim().toLowerCase().replace(/ä/g,"ae").replace(/ö/g,"oe").replace(/ü/g,"ue").replace(/ß/g,"ss").replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"");
function slBase(){let b=($("slUrl").value||"").trim().replace(/\/+$/,"");if(b&&!/^https?:\/\//i.test(b))b="https://"+b;return b.replace(/\/app$/,"");}
function slStandardUrl(){return /\.ts\.net$/.test(location.hostname)&&/schichtlohn/.test(location.hostname)?location.origin:"";}
const slAufHA=()=>/^\/local\//.test(location.pathname);
window.LAGER={logoUrls(name){const s=slSlug(name);if(!s)return [];const out=[],ext=["png","webp","svg","jpg"];
  if(slAufHA())ext.forEach(e=>out.push({u:"/local/hersteller/"+s+"."+e}));
  const b=slBase();if(b)ext.forEach(e=>out.push({u:b+"/hersteller/"+s+"."+e}));return out;}};
function slOpt(){try{const o=JSON.parse(localStorage.getItem("etikettwerk.sl")||"{}")||{};return o;}catch(e){return {};}}
function slOptSave(){try{localStorage.setItem("etikettwerk.sl",JSON.stringify({url:$("slUrl").value.trim(),fmt:SL.fmt,hoch:SL.hoch,slots:SL.slots}));}catch(e){}}
function slStatus(t,on){$("slStatus").classList.toggle("on",!!on);$("slStatusTxt").textContent=t;}
async function slFetch(pfad,opt){const r=await fetch(slBase()+pfad,Object.assign({headers:{"Content-Type":"application/json"}},opt||{}));
  if(!r.ok)throw new Error(r.status===401?"Der Server verlangt einen Schlüssel":"Server antwortet mit "+r.status);return r.json();}
const slDesc=it=>{try{return JSON.parse(it.description||"{}")||{};}catch(e){return {};}};
let slLib=null;
function slLibLaden(){if(window.Etikett)return Promise.resolve();if(slLib)return slLib;
  slLib=fetch(slBase()+"/app/").then(r=>{if(!r.ok)throw new Error("App antwortet mit "+r.status);return r.text();}).then(t=>{
    const a=t.indexOf("window.Etikett=(()=>{");if(a<0)throw new Error("Etikett-Teil in SchichtLohn nicht gefunden");
    const b=t.indexOf("\n})();",a);if(b<0)throw new Error("Etikett-Teil unvollständig");
    (0,eval)(t.slice(a,b+6));if(!window.Etikett)throw new Error("Etikett-Teil fehlt");}).catch(e=>{slLib=null;throw e;});return slLib;}
async function slLaden(){
  if(!slBase()){say("Trag die Adresse des SchichtLohn-Servers ein","warn");return;}
  slStatus("Lädt …");
  try{const r=await slFetch("/api/listen/todo.filament");
    SL.items=(r.items||[]).map(it=>({it,d:slDesc(it)})).filter(x=>x.d.material&&!x.d.typ)
      .sort((a,b)=>(a.d.hersteller||"").localeCompare(b.d.hersteller||"","de")||(a.it.summary||"").localeCompare(b.it.summary||"","de"));
    await slLibLaden();if(!Etikett.formatVon(SL.fmt))SL.fmt="classic";slStatus(`${SL.items.length} Sorten`,true);$("slBody").hidden=false;slOptSave();slListe();slFormate();slSlotsZeichnen();
  }catch(e){slStatus("Fehler");
    const tip=location.protocol==="https:"&&/^http:/.test(slBase())?" Die Seite läuft über https, der Server über http – der Browser blockt das. Nimm die Tailscale-Adresse mit https.":
      " Prüfe die Adresse und ob dieser Rechner im Tailnet ist.";
    say("SchichtLohn nicht erreichbar: "+e.message+"."+tip,"err");}
}
function slRest(d){const sp=Number.isFinite(Number(d.spulen))?Number(d.spulen):1,gew=Number(d.gewicht)>0?Number(d.gewicht):1000;
  const rs=(Array.isArray(d.reste)?d.reste:[]).map(Number).filter(x=>x>0&&x<gew).slice(0,Math.max(0,sp));return rs.length?Math.round(Math.min(...rs)):0;}
function slSorte(x){const d=x.d,n=v=>{if(v===null||v===undefined||v==="")return -1;const z=Number(v);return Number.isFinite(z)?z:-1;};
  return {hersteller:d.hersteller||"",material:d.material||"",besonderheiten:Array.isArray(d.besonderheiten)?d.besonderheiten:[],farbe:d.farbe||"",hex:d.hex||"",fcode:d.fcode?String(d.fcode):"",summary:x.it.summary||"",
    duese_min:n(d.duese_min),duese_max:n(d.duese_max),bett_min:n(d.bett_min),bett_max:n(d.bett_max),trocknen_c:n(d.trocknen_c),trocknen_h:n(d.trocknen_h),
    flow:n(d.flow),td:n(d.td),mvs:n(d.mvs),k:n(d.k),kammer:n(d.kammer),schwund:n(d.schwund),buegeln_tempo:n(d.buegeln_tempo),buegeln_flow:n(d.buegeln_flow),
    ams:d.ams===true||d.ams===false?d.ams:null,ams_modelle:d.ams_modelle?String(d.ams_modelle):"",sku:d.sku?String(d.sku):"",
    durchmesser:Number(d.durchmesser)||1.75,gewicht:Number(d.gewicht)>0?Number(d.gewicht):1000,leer_g:n(d.leer_g),ort:d.ort||"",getrocknet:d.getrocknet||""};}
function slListe(){
  const q=SL.q.toLowerCase().split(/\s+/).filter(Boolean);
  const l=SL.items.filter(x=>{const t=[x.it.summary,x.d.hersteller,x.d.material,x.d.farbe,(x.d.besonderheiten||[]).join(" ")].join(" ").toLowerCase();return q.every(w=>t.includes(w));});
  $("slList").innerHTML=l.length?l.map(x=>{const sp=Number.isFinite(Number(x.d.spulen))?Number(x.d.spulen):1;const hex=/^#[0-9a-f]{6}$/i.test(x.d.hex||"")?x.d.hex:"#888888";
    return `<button class="sp" data-sl="${esc(x.it.uid)}" aria-pressed="${x.it.uid===SL.uid}"><span class="dot" style="background:${hex}"></span><span class="n">${esc(x.it.summary||x.d.material)}</span><span class="c">${sp} ${sp===1?"Rolle":"Rollen"}</span></button>`;}).join("")
    :`<div class="note">Keine Sorte passt zur Suche.</div>`;
}
function slFormate(){$("slFmt").innerHTML=Object.entries(Etikett.FORMATE).map(([k,f])=>`<button class="chip" data-slf="${k}" aria-pressed="${k===SL.fmt}">${esc(f.name)} ${f.b}×${f.h}</button>`).join("");$("slHoch").checked=SL.hoch;}
function slSlotsZeichnen(){
  if(!Array.isArray(SL.slots))SL.slots=Etikett.STANDARD_SLOTS.slice(0,4);while(SL.slots.length<4)SL.slots.push("keine");
  const f=Etikett.formatVon(SL.fmt)||Etikett.FORMATE.classic;
  $("slSlots").innerHTML=f.werte?SL.slots.slice(0,4).map((v,i)=>`<label for="slSlot${i}">Zeile ${i+1}<select id="slSlot${i}" data-slot="${i}">${Etikett.FELDER.map(([k,t])=>`<option value="${k}"${k===v?" selected":""}>${esc(t)}</option>`).join("")}<option value="keine"${v==="keine"?" selected":""}>Keine</option></select></label>`).join("")
    :`<div class="note" style="grid-column:1/-1">Dieses Format zeigt keine Zusatzzeilen.</div>`;
}
const slGewaehlt=()=>SL.items.find(x=>x.it.uid===SL.uid);
const slNeueId=()=>{const z="ABCDEFGHJKLMNPQRSTUVWXYZ23456789";const a=crypto.getRandomValues(new Uint8Array(6));return "SL-"+Array.from(a,b=>z[b%32]).join("");};
async function slIdSichern(x){if(x.d.sl_id)return String(x.d.sl_id);
  const id=slNeueId(),d=Object.assign({},x.d,{sl_id:id});
  try{await slFetch("/api/listen/todo.filament",{method:"POST",body:JSON.stringify({service:"update_item",data:{item:x.it.uid,description:JSON.stringify(d)}})});
    x.d=d;x.it.description=JSON.stringify(d);return id;}
  catch(e){say("Etikett-Nummer konnte nicht gespeichert werden, das Etikett kommt ohne QR-Code","warn");return "";}}
const slQr=id=>id?slBase()+"/app/?rolle="+encodeURIComponent(id):"";
function slZeichenOpt(x,id,skala){return {format:SL.fmt,slots:SL.slots,rgb:"text",eigene:"",hochkant:SL.hoch,rest:slRest(x.d),id,qr:slQr(id),leerStandard:250,skala};}
async function slWaehlen(uid){
  const x=SL.items.find(y=>y.it.uid===uid);if(!x)return;SL.uid=uid;S.mode="sl";slListe();
  x.id=await slIdSichern(x);await slVorschau();}
async function slVorschau(){const x=slGewaehlt();if(!x||S.mode!=="sl")return;const n=++SL.lauf;
  const c=document.createElement("canvas");
  try{const r=await Etikett.zeichnen(c,slSorte(x),slZeichenOpt(x,x.id||"",3));if(n!==SL.lauf)return;SL.vor=c;
    $("slNote").textContent=r&&r.weg&&r.weg.length?`Passt nicht mehr drauf: ${r.weg.join(", ")}`:`QR-Code öffnet ${x.id||"–"} in SchichtLohn.`;}
  catch(e){say("SchichtLohn-Etikett konnte nicht gezeichnet werden: "+e.message,"err");return;}
  render();}
function slMasse(){const f=Etikett.formatVon(SL.fmt)||Etikett.FORMATE.classic;return SL.hoch&&f.b>f.h?{b:f.h,h:f.b,f}:{b:f.b,h:f.h,f};}
function slRender(){
  const cv=$("cv"),m0=slMasse();
  const m=SL.vor?{b:+(SL.vor.width/24).toFixed(1),h:+(SL.vor.height/24).toFixed(1),f:m0.f}:m0;
  const stageW=Math.min(cv.parentElement.clientWidth-24,640);viewK=Math.max(3,Math.min(12,stageW/m.b,maxH()/m.h));
  const dpr=window.devicePixelRatio||1,W=m.b*viewK,H=m.h*viewK;
  cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);cv.style.width=W+"px";cv.style.height=H+"px";
  const ctx=cv.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle="#fff";ctx.fillRect(0,0,W,H);
  if(SL.vor){ctx.imageSmoothingEnabled=true;ctx.drawImage(SL.vor,0,0,W,H);}
  const p=PRINTERS[S.printer],x=slGewaehlt();
  $("ruler").textContent=`${m.f.name} · ${m.b} × ${m.h} mm`;
  $("meta").innerHTML=`<span class="slmode">SchichtLohn</span> · ${esc(x?x.it.summary:"")} · ${p.name}, ${p.dpi} dpi`;
}
async function slDruckCanvas(dpi){const x=slGewaehlt();if(!x)throw new Error("Keine Sorte gewählt");
  const c=document.createElement("canvas");
  await Etikett.zeichnen(c,slSorte(x),slZeichenOpt(x,x.id||"",dpi/203.2));
  const ctx=c.getContext("2d");const d=ctx.getImageData(0,0,c.width,c.height),px=d.data;
  for(let i=0;i<px.length;i+=4){const a=px[i+3]/255;const l=(0.299*px[i]+0.587*px[i+1]+0.114*px[i+2])*a+255*(1-a);const v=l<140?0:255;px[i]=px[i+1]=px[i+2]=v;px[i+3]=255;}
  ctx.putImageData(d,0,0);
  if(c.dataset.drehen!=="1")return c;
  const g=document.createElement("canvas");g.width=c.height;g.height=c.width;const gx=g.getContext("2d");
  gx.fillStyle="#fff";gx.fillRect(0,0,g.width,g.height);gx.translate(g.width,0);gx.rotate(Math.PI/2);gx.drawImage(c,0,0);return g;}
function slFreiModus(){if(S.mode!=="sl")return;S.mode="frei";SL.uid="";slListe();render();}
async function slLogosHolen(){
  const marken=[...new Set(SL.items.map(x=>x.d.hersteller).filter(Boolean))];let neu=0,fehlt=[];
  say(`Hole Logos für ${marken.length} Hersteller …`,"");
  for(const m of marken){let ok=false;
    for(const {u} of LAGER.logoUrls(m)){
      try{const im=new Image();im.crossOrigin="anonymous";im.src=u;await im.decode();
        const s=Math.min(1,800/Math.max(im.naturalWidth,im.naturalHeight)),c=document.createElement("canvas");
        c.width=Math.max(1,Math.round(im.naturalWidth*s));c.height=Math.max(1,Math.round(im.naturalHeight*s));c.getContext("2d").drawImage(im,0,0,c.width,c.height);
        const src=c.toDataURL("image/png");
        if(!LOGOS.some(L=>L.src===src||L.name===m)){const o=new Image();o.src=src;imgCache.set(src,o);
          LOGOS.push({id:Date.now().toString(36)+Math.random().toString(36).slice(2,6),name:m,src,ratio:c.height/c.width});neu++;}
        ok=true;break;
      }catch(e){}
    }
    if(!ok)fehlt.push(m);
  }
  if(neu&&!saveLogos()){LOGOS.splice(LOGOS.length-neu,neu);renderLogos();return;}
  renderLogos();
  say(`${neu} Logos übernommen`+(fehlt.length?` · ohne Logo: ${fehlt.join(", ")}`:""),fehlt.length?"warn":"ok");
}
$("slLoad").addEventListener("click",slLaden);
$("slFrei").addEventListener("click",slFreiModus);
$("slLogos").addEventListener("click",slLogosHolen);
$("slList").addEventListener("click",ev=>{const b=ev.target.closest("[data-sl]");if(b)slWaehlen(b.dataset.sl);});
$("slFmt").addEventListener("click",ev=>{const b=ev.target.closest("[data-slf]");if(!b)return;SL.fmt=b.dataset.slf;slFormate();slSlotsZeichnen();slOptSave();slVorschau();});
$("slQ").addEventListener("input",ev=>{SL.q=ev.target.value;slListe();});
$("slHoch").addEventListener("change",ev=>{SL.hoch=ev.target.checked;slOptSave();slVorschau();});
$("slSlots").addEventListener("change",ev=>{const t=ev.target;if(t.dataset.slot===undefined)return;SL.slots[+t.dataset.slot]=t.value;slOptSave();slVorschau();});
$("slUrl").addEventListener("keydown",ev=>{if(ev.key==="Enter"){ev.preventDefault();slLaden();}});
document.addEventListener("click",ev=>{if(S.mode==="sl"&&ev.target.closest("#els,.add,#sizes,#loadDesign,#logos .logo:not(.up)"))slFreiModus();},true);
(function(){const o=slOpt();$("slUrl").value=o.url||slStandardUrl();if(o.fmt)SL.fmt=o.fmt;SL.hoch=!!o.hoch;if(Array.isArray(o.slots))SL.slots=o.slots;})();
loadLogos();renderLogos();
try{const d=JSON.parse(localStorage.getItem("etikettwerk.zuletzt")||"null");if(d&&d.els)restore(d);else throw 0;}
catch(e){setEls(tpl("box"));renderPrinters();renderSizes();renderEls();render();}
noteBt();
try{S.weg=localStorage.getItem("etikettwerk.weg")||"";}catch(e){}
renderWeg();haLaden();
window.addEventListener("resize",render);
document.fonts&&document.fonts.ready.then(render);
</script>

@@*/}
const ETW_T=etikettwerkQuelle.toString(),ETW_H=ETW_T.slice(ETW_T.indexOf("/*@@")+5,ETW_T.lastIndexOf("@@*/"));
class EtikettwerkCard extends HTMLElement{
  setConfig(c){this._c=c||{};}
  set hass(h){if(this._f)return;
    const s=this.shadowRoot||this.attachShadow({mode:"open"});
    const st=document.createElement("style");
    st.textContent=":host{display:block}iframe{display:block;width:100%;height:calc(100vh - var(--header-height,56px) - 16px);min-height:640px;border:0;border-radius:var(--ha-card-border-radius,12px);background:transparent}";
    const f=document.createElement("iframe");f.setAttribute("allow","bluetooth; clipboard-write");f.title="Etikettwerk";
    f.srcdoc='<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'+ETW_H+'</body></html>';
    s.append(st,f);this._f=f;}
  getCardSize(){return 12;}
  getGridOptions(){return {columns:"full",rows:"auto"};}
}
if(!customElements.get("etikettwerk-card"))customElements.define("etikettwerk-card",EtikettwerkCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==="etikettwerk-card"))window.customCards.push({type:"etikettwerk-card",name:"Etikettwerk",description:"Etiketten für Phomemo M110 und M20 Pro, mit SchichtLohn-Spulenetiketten"});
