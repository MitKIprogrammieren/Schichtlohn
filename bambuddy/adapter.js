/* ===== SchichtLohn im Bambuddy-Modus =====
   Läuft nur, wenn SchichtLohn über den Bambuddy-Zusatz (bambuddy/ in diesem Repo) ausgeliefert wird.
   Der Zusatz setzt window.SL_BAMBUDDY = {api:"/api/v1"} und leitet /api/ an Bambuddy weiter (gleiche Adresse, kein CORS nötig).

   Das Lager arbeitet mit Sorten (Marke, Material, Farbe, Anzahl Rollen, Reste). Bambuddy führt einzelne Spulen.
   Dieser Adapter fasst gleiche Spulen zu einer Sorte zusammen und übersetzt Änderungen am Lager in Spulen-Aufrufe:
   + Rolle = neue Spule, − Rolle = Spule leer und archiviert, Rest ändern = weight_used der Spule.
   Bambuddy bucht Bambu-Drucke nach Druckende selbst ab; der Verlauf erscheint in der Lager-Statistik.
   AMS-Belegung und Feuchte kommen aus Bambuddys Druckerstatus, im Format, das das Lager von Home Assistant kennt. */
(function(){
"use strict";
const API=()=>window.SL_BAMBUDDY&&window.SL_BAMBUDDY.api;
const on=()=>!!API();
const B={spools:[],printers:[],status:{},assign:[],groups:new Map(),usage:[],loaded:false,err:"",at:0,subs:{ent:[],meta:[]},loading:null,ws:null,wsT:null,reloadT:null,stateMap:{}};
const NOTE="SL:";
const EXTRA=["besonderheiten","refills","codes","codes_refill","durchmesser","bett_min","bett_max","trocknen_c","trocknen_h","fcode","ams_farben","ausfuehrung","farbe_name"];

async function req(method,path,body){
  let r;try{r=await fetch(API()+path,{method,headers:body?{"Content-Type":"application/json"}:{},body:body?JSON.stringify(body):undefined,credentials:"same-origin"})}
  catch(e){throw new Error("Bambuddy nicht erreichbar")}
  let d=null;try{d=await r.json()}catch(e){}
  if(!r.ok){const det=d&&d.detail;const msg=typeof det==="string"?det:Array.isArray(det)?det.map(x=>x.msg||JSON.stringify(x)).join("; "):(d&&d.message);
    const e=new Error(r.status===401||r.status===403?"Bambuddy verlangt eine Anmeldung bzw. einen API-Schlüssel (siehe Anleitung)":(msg||"Bambuddy HTTP "+r.status));e.status=r.status;throw e}
  return d}

/* --- Spulen → Sorten --- */
const hexOf=s=>s&&/^[0-9a-f]{6}/i.test(String(s))?"#"+String(s).slice(0,6).toLowerCase():"#888888";
const W=s=>Number(s.label_weight)>0?Number(s.label_weight):1000;
const rest=s=>Math.max(0,W(s)-(Number(s.weight_used)||0));
const aktiv=s=>!s.archived_at&&rest(s)>0.5;
function extra(s){const n=String(s.note||"");if(n.startsWith(NOTE)){try{return JSON.parse(n.slice(NOTE.length))||{}}catch(e){}}return null}
function gkey(s){return [s.brand||"",s.material||"",s.subtype||"",s.color_name||"",hexOf(s.rgba),W(s)].join("|").toLowerCase()}
function hash(t){let h=5381;for(let i=0;i<t.length;i++)h=((h<<5)+h+t.charCodeAt(i))|0;return (h>>>0).toString(36)}
function gruppieren(){
  const m=new Map();
  for(const s of B.spools){const k=gkey(s);if(!m.has(k))m.set(k,{uid:"bb_"+hash(k),key:k,all:[]});m.get(k).all.push(s)}
  const grenze=Date.now()-180*864e5;const out=new Map();
  for(const g of m.values()){
    g.active=g.all.filter(aktiv).sort((a,b)=>rest(b)-rest(a));
    const ref=g.active[0]||g.all.slice().sort((a,b)=>String(b.updated_at||"").localeCompare(String(a.updated_at||"")))[0];
    const x=g.all.map(extra).find(Boolean)||{};
    if(!g.active.length&&(x.geloescht||!g.all.some(s=>new Date(s.archived_at||s.updated_at||0).getTime()>grenze)))continue; // gelöschte bzw. lange leere Sorten nicht zeigen
    g.ref=ref;g.x=x;out.set(g.uid,g)}
  B.groups=out}
function sorte(g){
  const s=g.ref,x=g.x,gew=W(s);
  const reste=g.active.map(rest).filter(r=>r<gew-0.5).map(Math.round).sort((a,b)=>a-b);
  const bes=Array.isArray(x.besonderheiten)?x.besonderheiten:(s.subtype&&!/^basic$/i.test(s.subtype)?[s.subtype]:[]);
  const d={v:2,hersteller:s.brand||"",material:s.material||"",farbe:s.color_name||"",hex:hexOf(s.rgba),besonderheiten:bes,gewicht:gew,spulen:g.active.length,reste,
    preis:s.cost_per_kg!=null?Number(s.cost_per_kg):null,duese_min:s.nozzle_temp_min??null,duese_max:s.nozzle_temp_max??null,bambu_id:s.slicer_filament||"",bambuddy:g.all.map(z=>z.id)};
  for(const k of EXTRA)if(x[k]!=null&&d[k]==null)d[k]=x[k];
  if(d.refills!=null)d.refills=Math.min(d.refills,d.spulen);
  return d}
const summaryOf=d=>[d.hersteller,d.material,d.farbe].filter(Boolean).join(" ")+(d.besonderheiten&&d.besonderheiten.length?` (${d.besonderheiten.join(", ")})`:"");
function items(){return [...B.groups.values()].map(g=>{const d=sorte(g);return {uid:g.uid,summary:summaryOf(d),status:"needs_action",description:JSON.stringify(d)}})}

/* --- Sorte → Spulenfelder --- */
function felder(d){
  const x={};for(const k of EXTRA)if(d[k]!=null&&!(Array.isArray(d[k])&&!d[k].length))x[k]=d[k];
  const bes=Array.isArray(d.besonderheiten)?d.besonderheiten:[];
  const note=Object.keys(x).length?NOTE+JSON.stringify(x):null;
  const hex=/^#[0-9a-f]{6}$/i.test(String(d.hex||""))?String(d.hex).slice(1).toUpperCase()+"FF":null;
  const num=v=>v===""||v==null||!Number.isFinite(Number(v))?null:Number(v);
  return {brand:d.hersteller||null,material:String(d.material||"PLA").slice(0,50),subtype:bes.length?bes.join(", ").slice(0,50):null,color_name:d.farbe||null,rgba:hex,
    label_weight:Math.round(Number(d.gewicht)>0?Number(d.gewicht):1000),cost_per_kg:num(d.preis),nozzle_temp_min:num(d.duese_min),nozzle_temp_max:num(d.duese_max),
    slicer_filament:d.bambu_id||null,note:note&&note.length<=500?note:null}}
const GLEICH=["brand","material","subtype","color_name","rgba","label_weight","cost_per_kg","nozzle_temp_min","nozzle_temp_max","slicer_filament","note"];
function unterschied(s,f){const p={};for(const k of GLEICH){const a=s[k]??null,b=f[k]??null;if(k==="rgba"?String(a||"").toUpperCase()!==String(b||"").toUpperCase():String(a)!==String(b)){
  if(k==="note"&&b===null&&a&&!String(a).startsWith(NOTE))continue; // eigene Notizen aus Bambuddy nicht löschen
  if(k==="slicer_filament"&&b===null)continue;
  p[k]=b}}return p}
function ziele(d){const n=Math.max(0,Math.round(Number(d.spulen)||0));const gew=Number(d.gewicht)>0?Number(d.gewicht):1000;
  const reste=(Array.isArray(d.reste)?d.reste:[]).map(Number).filter(r=>r>0&&r<gew).slice(0,n);
  return [...Array(n-reste.length).fill(gew),...reste].sort((a,b)=>b-a)}

async function anlegen(f,restG){const wu=Math.max(0,Math.round((f.label_weight-restG)*10)/10);
  /* ein angebrochener Rest beim Anlegen ist kein Verbrauch: Bambuddys Zähler „Gesamtverbrauch“ beginnt bei 0 */
  const s=await req("POST","/inventory/spools",Object.assign({},f,{weight_used:wu,weight_used_baseline:wu}));return s}
async function leeren(s){await req("PATCH","/inventory/spools/"+s.id,{weight_used:W(s),weight_locked:true});await req("POST","/inventory/spools/"+s.id+"/archive")}
async function abgleichen(g,d){
  const f=felder(d);
  for(const s of g.all){const p=unterschied(s,f);if(Object.keys(p).length)await req("PATCH","/inventory/spools/"+s.id,p)}
  const t=ziele(d),act=g.active.slice().sort((a,b)=>rest(b)-rest(a));
  for(let i=0;i<Math.max(t.length,act.length);i++){
    if(i<t.length&&i<act.length){const s=act[i];if(Math.abs(rest(Object.assign({},s,{label_weight:f.label_weight}))-t[i])>0.5)await req("PATCH","/inventory/spools/"+s.id,{weight_used:Math.max(0,Math.round((f.label_weight-t[i])*10)/10)})}
    else if(i<t.length){
      // erst eine archivierte Spule derselben Sorte wiederverwenden (z. B. versehentlich − gedrückt), sonst neu anlegen
      const alt=g.all.find(s=>s.archived_at&&!s._re);
      if(alt&&t[i]>=f.label_weight-0.5){alt._re=true;await req("POST","/inventory/spools/"+alt.id+"/restore");await req("PATCH","/inventory/spools/"+alt.id,Object.assign({},f,{weight_used:0}))}
      else await anlegen(f,t[i])}
    else await leeren(act[i])}}
async function neu(d){const f=felder(d);const t=ziele(d);
  if(!t.length){const s=await anlegen(f,0);await req("POST","/inventory/spools/"+s.id+"/archive");return}
  const voll=t.filter(x=>x>=f.label_weight-0.5).length;
  if(voll>1)await req("POST","/inventory/spools/bulk",{spool:Object.assign({},f,{weight_used:0}),quantity:voll});else if(voll===1)await anlegen(f,f.label_weight);
  for(const r of t.slice(voll))await anlegen(f,r)}
async function loeschen(g){
  const x=Object.assign({},g.x,{geloescht:true});const note=NOTE+JSON.stringify(x);
  for(const s of g.all){if(!s.archived_at)await req("PATCH","/inventory/spools/"+s.id,{weight_used:W(s),weight_locked:true,note:note.length<=500?note:NOTE+'{"geloescht":true}'});else await req("PATCH","/inventory/spools/"+s.id,{note:note.length<=500?note:NOTE+'{"geloescht":true}'});
    if(!s.archived_at)await req("POST","/inventory/spools/"+s.id+"/archive")}}

/* Wird vom Lager für todo.filament aufgerufen (nur Sorten; „Nicht zugeordnet“ bleibt im Browser) */
async function svc(service,data){
  if(service==="add_item"){await neu(JSON.parse(data.description||"{}"))}
  else if(service==="update_item"){const g=B.groups.get(data.item);if(!g)throw new Error("Sorte nicht mehr in Bambuddy – bitte neu laden");
    const d=data.description!=null?JSON.parse(data.description):sorte(g);await abgleichen(g,d)}
  else if(service==="remove_item"){for(const id of [].concat(data.item)){const g=B.groups.get(id);if(g)await loeschen(g)}}
  else throw new Error("Nicht unterstützt: "+service);
  await laden(true)}
const istSorte=(service,data)=>{
  if(service==="add_item"){try{return !JSON.parse(data.description||"{}").typ}catch(e){return false}}
  return [].concat(data&&data.item||[]).some(i=>String(i).startsWith("bb_"))};
/* --- Drucker und AMS im Format der HA-Sensoren (sensor.bb<ID>_ams_<n>_slot_<m>) --- */
const NAMEN={};
function zustaende(){
  const st={};
  for(const p of B.printers){const s=B.status[p.id];if(!s)continue;const pre="bb"+p.id;NAMEN[pre]=p.name;
    for(const u of s.ams||[]){const n=Number(u.id)>=128?Number(u.id):Number(u.id)+1;
      if(u.humidity!=null)st[`sensor.${pre}_ams_${n}_luftfeuchtigkeit`]={entity_id:`sensor.${pre}_ams_${n}_luftfeuchtigkeit`,state:String(u.humidity),attributes:{}};
      for(const t of u.tray||[]){const id=`sensor.${pre}_ams_${n}_slot_${Number(t.id)+1}`;const leer=!t.tray_type;
        st[id]={entity_id:id,state:leer?"empty":(t.tray_sub_brands||t.tray_type),attributes:{name:t.tray_sub_brands||t.tray_type||"",type:t.tray_type||"",color:t.tray_color?"#"+t.tray_color:"",remain:t.remain,filament_id:t.tray_info_idx||"",empty:leer}}}}
    (s.vt_tray||[]).forEach((t,i)=>{if(!t.tray_type)return;const id=`sensor.${pre}_externalspool${i?i+1:""}_externe_spule`;
      st[id]={entity_id:id,state:t.tray_sub_brands||t.tray_type,attributes:{name:t.tray_sub_brands||t.tray_type,type:t.tray_type,color:t.tray_color?"#"+t.tray_color:"",remain:t.remain,filament_id:t.tray_info_idx||"",empty:false}}})}
  B.stateMap=st}

/* --- Verbrauch aus Bambuddy (für die Lager-Statistik, nur lesen) --- */
function verbrauch(){
  const sp=new Map(B.spools.map(s=>[s.id,s]));const pr=new Map(B.printers.map(p=>[p.id,p.name]));
  return B.usage.map(u=>{const s=sp.get(u.spool_id);const g=s?B.groups.get("bb_"+hash(gkey(s))):null;const d=g?sorte(g):null;const preis=s&&s.cost_per_kg!=null?Number(s.cost_per_kg):null;
    const x={typ:"verbrauch",v:1,zeit:u.created_at,drucker:pr.get(u.printer_id)||"",ort:"AMS",sorte:d?summaryOf(d):(s?[s.brand,s.material,s.color_name].filter(Boolean).join(" "):"Spule "+u.spool_id),uid:g?g.uid:"",
      hersteller:s&&s.brand||"",material:s&&s.material||"",hex:s?hexOf(s.rgba):"#888888",gramm:Math.round((Number(u.weight_used)||0)*10)/10,preis,kosten:u.cost!=null?Number(u.cost):(preis?Math.round(u.weight_used/1000*preis*100)/100:null),
      anlass:(u.status==="completed"?"Druck fertig":u.status==="failed"?"Druck fehlgeschlagen":"Druck abgebrochen")+(u.print_name?" · "+u.print_name:"")+" (Bambuddy)",quelle:"bambuddy:"+u.id,auto:true};
    return {uid:"bu_"+u.id,summary:x.sorte,status:"completed",description:JSON.stringify(x)}})}

/* --- Einmaliger Import aus einer Lager-Datei (z. B. aus dem Home-Assistant-FilamentLager) --- */
const IMP="schichtlohn_bambuddy_import";
async function importieren(daten,fortschritt){
  const sorten=(daten&&Array.isArray(daten.sorten)?daten.sorten:Array.isArray(daten)?daten:[]).filter(x=>x&&!x.typ&&x.material);
  if(!sorten.length)throw new Error("In der Datei sind keine Sorten");
  await laden(true);
  const schon=new Set([...B.groups.values()].map(g=>g.key));
  const r={neu:0,schon:0,fehler:[]};
  for(let i=0;i<sorten.length;i++){const d=sorten[i];
    const f=felder(d);const k=[f.brand||"",f.material||"",f.subtype||"",f.color_name||"",hexOf(f.rgba),f.label_weight].join("|").toLowerCase();
    if(schon.has(k)){r.schon++}
    else{try{await neu(d);schon.add(k);r.neu++}catch(e){r.fehler.push(summaryOf(d)+": "+e.message)}}
    fortschritt&&fortschritt(i+1,sorten.length)}
  try{localStorage.setItem(IMP,new Date().toISOString())}catch(e){}
  await laden(true);return r}
function importModal(){
  if(!window.modal)return;
  modal("Bestand importieren",`<div class="stack">
    <div class="hint">Wähle die Datei <b>filamentlager-import.json</b>. Für jede Rolle wird in Bambuddy eine Spule angelegt, mit Resten, Preis und Farbe. Sorten, die es in Bambuddy schon gibt, werden übersprungen – ein zweiter Import legt also nichts doppelt an.</div>
    <input type="file" id="bbImpFile" accept="application/json,.json">
    <div class="hint" id="bbImpMsg" role="status"></div></div>`,
    `<button class="btn ghost" data-act="close">Schließen</button>`);
  const inp=document.getElementById("bbImpFile");
  inp.addEventListener("change",async()=>{const f=inp.files&&inp.files[0];if(!f)return;const msg=document.getElementById("bbImpMsg");inp.disabled=true;
    try{const daten=JSON.parse(await f.text());
      const r=await importieren(daten,(n,g)=>{msg.textContent=`Importiere … ${n} von ${g} Sorten`});
      msg.innerHTML=`Fertig: ${r.neu} Sorten angelegt${r.schon?`, ${r.schon} gab es schon`:""}.`+(r.fehler.length?`<br>Nicht übernommen (${r.fehler.length}):<br>`+r.fehler.slice(0,20).map(x=>window.esc?esc(x):x).join("<br>"):"");
      window.toast&&toast("Import fertig: "+r.neu+" Sorten")}
    catch(e){msg.textContent="Fehler: "+e.message;inp.disabled=false}})}
/* Knopf „Import“ unten rechts, solange Bambuddy noch (fast) leer ist oder mit ?import=1 */
function knopf(){
  if(!on())return;let b=document.getElementById("bbImpBtn");
  const zeigen=B.loaded&&(B.spools.length<5||/[?&]import=1/.test(location.search));
  if(!zeigen){if(b)b.remove();return}
  if(b)return;b=document.createElement("button");b.id="bbImpBtn";b.type="button";b.className="btn pri";b.textContent="Bestand importieren";
  b.style.cssText="position:fixed;right:16px;bottom:16px;z-index:50;box-shadow:0 6px 20px rgba(0,0,0,.25)";
  b.onclick=importModal;document.body.appendChild(b)}

/* --- Automatische Fach-Zuordnung in Bambuddy ---
   Bambuddy bucht nach Druckende nur von der Spule ab, die einem AMS-Fach zugeordnet ist.
   Ist ein belegtes Fach noch ohne Zuordnung, sucht das Lager die passende Sorte (gleiches Filamentprofil,
   ähnliche Farbe – dieselbe Regel wie „Fächer ohne Zuordnung“) und ordnet eine ihrer Spulen zu.
   Wird die Rolle getauscht, löst Bambuddy die alte Zuordnung selbst; danach wird neu zugeordnet. */
const ZTOL=2700; // strenger als die Anzeige im Lager: hier wird später echt abgebucht
const generisch=fid=>!fid||/^GF.99$/i.test(String(fid));
const rgb=h=>[1,3,5].map(i=>parseInt(String(h).slice(i,i+2),16)||0);
const abstand=(a,b)=>{const u=rgb(a),v=rgb(b);return u.reduce((s,x,i)=>s+(x-v[i])**2,0)};
const versucht=new Map();let zLaeuft=false;
function faecher(){const out=[];
  for(const p of B.printers){const st=B.status[p.id];if(!st||st.connected===false)continue;
    for(const u of st.ams||[])for(const t of u.tray||[]){if(!t.tray_type)continue;out.push({printer:p,ams_id:Number(u.id),tray_id:Number(t.id),t})}
    (st.vt_tray||[]).forEach(t=>{if(!t||!t.tray_type)return;const id=Number(t.id);out.push({printer:p,ams_id:255,tray_id:Number.isFinite(id)&&id>=254?id-254:0,t})})}
  return out}
function sorteFuer(t){const fid=t.tray_info_idx;if(generisch(fid))return null;const hex="#"+String(t.tray_color||"").slice(0,6).toLowerCase();
  let best=null,bd=Infinity;
  for(const g of B.groups.values()){if(!g.active||!g.active.length)continue;const d=sorte(g);if(d.bambu_id!==fid)continue;
    const di=Math.min(...[d.hex,...(d.ams_farben||[])].map(x=>abstand(x,hex)));if(di<bd){bd=di;best=g}}
  return best&&bd<=ZTOL?best:null}
function spuleFuer(g,t,belegt){const frei=g.active.filter(s=>!belegt.has(s.id));if(!frei.length)return null;
  const rem=Number(t.remain);
  if(rem>=0&&rem<=100){const soll=rem/100;return frei.slice().sort((a,b)=>Math.abs(rest(a)/W(a)-soll)-Math.abs(rest(b)/W(b)-soll))[0]}
  const an=frei.filter(s=>rest(s)<W(s)-0.5).sort((a,b)=>rest(a)-rest(b));return an[0]||frei[0]}
async function zuordnen(){
  if(!on()||zLaeuft||!B.loaded)return;zLaeuft=true;let neu=0;
  try{const hat=new Set(B.assign.map(a=>`${a.printer_id}|${a.ams_id}|${a.tray_id}`));const belegt=new Set(B.assign.map(a=>a.spool_id));
    for(const f of faecher()){const k=`${f.printer.id}|${f.ams_id}|${f.tray_id}`;if(hat.has(k))continue;
      const fp=k+"|"+(f.t.tray_info_idx||"")+"|"+(f.t.tray_color||"");const v=versucht.get(fp);if(v&&Date.now()-v<10*60e3)continue;
      const g=sorteFuer(f.t);if(!g)continue;const s=spuleFuer(g,f.t,belegt);if(!s)continue;
      versucht.set(fp,Date.now()); // nur echte Versuche merken: kein zweiter Aufruf, falls Bambuddy ablehnt
      try{const a=await req("POST","/inventory/assignments",{spool_id:s.id,printer_id:f.printer.id,ams_id:f.ams_id,tray_id:f.tray_id});
        B.assign.push(a&&a.spool_id?a:{spool_id:s.id,printer_id:f.printer.id,ams_id:f.ams_id,tray_id:f.tray_id});belegt.add(s.id);hat.add(k);neu++}
      catch(e){console.warn("Bambuddy Zuordnung",k,e)}}
    if(neu&&window.toast)toast(`${neu} ${neu===1?"Fach":"Fächer"} in Bambuddy zugeordnet`)}
  finally{zLaeuft=false}}

/* --- Laden, Live-Aktualisierung --- */
function verteilen(){
  const e=items(),m=verbrauch();
  B.subs.ent.forEach(f=>{try{f(e)}catch(x){console.warn(x)}});
  B.subs.meta.forEach(f=>{try{f(m)}catch(x){console.warn(x)}});
  try{window.LGN&&LGN.onStates&&LGN.onStates()}catch(x){}}
async function laden(force){
  if(!on())return;if(B.loading)return B.loading;if(!force&&Date.now()-B.at<5000)return;
  B.loading=(async()=>{
    try{
      const [spools,printers,usage,assign]=await Promise.all([req("GET","/inventory/spools?include_archived=true"),req("GET","/printers/").catch(()=>[]),req("GET","/inventory/usage?limit=500").catch(()=>[]),req("GET","/inventory/assignments").catch(()=>null)]);
      B.spools=Array.isArray(spools)?spools:[];B.printers=Array.isArray(printers)?printers:[];B.usage=Array.isArray(usage)?usage:[];if(Array.isArray(assign))B.assign=assign;
      const st=await Promise.all(B.printers.map(p=>req("GET","/printers/"+p.id+"/status").catch(()=>null)));
      B.printers.forEach((p,i)=>{if(st[i])B.status[p.id]=st[i]});
      gruppieren();zustaende();B.loaded=true;B.err="";B.at=Date.now();
      grundlinie();
      setTimeout(zuordnen,0);
    }catch(e){B.err=e.message;console.warn("Bambuddy",e);if(window.toast&&!B.loaded)toast("Bambuddy: "+e.message)}
    finally{B.loading=null;verteilen();try{knopf()}catch(e){}}})();
  return B.loading}
/* Einmalig: beim Import mitgebrachte Reste nicht als Verbrauch zählen (Bambuddys „Gesamtverbrauch“) */
const GL="schichtlohn_bambuddy_grundlinie_v1";let glLaeuft=false;
async function grundlinie(){
  try{if(localStorage.getItem(GL))return}catch(e){return}
  if(glLaeuft)return;glLaeuft=true;
  try{const mitLog=new Set(B.usage.map(u=>u.spool_id));
    const ids=B.spools.filter(s=>!(Number(s.weight_used_baseline)>0)&&Number(s.weight_used)>0&&!mitLog.has(s.id)).map(s=>s.id);
    for(let i=0;i<ids.length;i+=200)await req("POST","/inventory/spools/reset-consumed-counter-bulk",{spool_ids:ids.slice(i,i+200)});
    try{localStorage.setItem(GL,new Date().toISOString())}catch(e){}
    if(ids.length)bald()}
  catch(e){console.warn("Bambuddy Grundlinie",e)}finally{glLaeuft=false}}
function bald(){clearTimeout(B.reloadT);B.reloadT=setTimeout(()=>laden(true),600)}
function verbinden(){
  if(!on()||B.ws)return;
  let ws;try{ws=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+API()+"/ws")}catch(e){return}
  B.ws=ws;
  ws.onmessage=ev=>{let m;try{m=JSON.parse(ev.data)}catch(e){return}
    if(/^(inventory_changed|spool_assignment_changed|missing_spool_assignment|spool_auto_assigned|spool_usage_logged|print_complete)$/.test(m.type))bald();
    else if(m.type==="printer_status"&&m.printer_id!=null&&m.data&&m.data.ams){B.status[m.printer_id]=Object.assign(B.status[m.printer_id]||{},m.data);clearTimeout(B.wsT);B.wsT=setTimeout(()=>{zustaende();try{LGN.onStates&&LGN.onStates()}catch(e){}zuordnen()},1500)}};
  const ping=setInterval(()=>{try{ws.readyState===1&&ws.send('{"type":"ping"}')}catch(e){}},30000);
  ws.onclose=()=>{clearInterval(ping);B.ws=null;setTimeout(verbinden,10000)};}
setInterval(()=>{if(on()&&!document.hidden)laden(false)},60000);
document.addEventListener("visibilitychange",()=>{if(on()&&!document.hidden)laden(true)});

/* Abos für das Lager */
function subscribe(art,cb){B.subs[art].push(cb);if(B.loaded)setTimeout(()=>cb(art==="ent"?items():verbrauch()),0);else laden(true);verbinden();
  return ()=>{B.subs[art]=B.subs[art].filter(f=>f!==cb)}}

window.BBY={on,svc,istSorte,subscribe,laden,importieren,importModal,zuordnen,_faecher:faecher,_sorteFuer:sorteFuer,states:()=>B.stateMap,name:pre=>NAMEN[pre],_B:B,_sorte:sorte,_felder:felder,_ziele:ziele};
})();
