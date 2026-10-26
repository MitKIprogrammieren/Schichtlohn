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
const B={spools:[],printers:[],status:{},groups:new Map(),usage:[],loaded:false,err:"",at:0,subs:{ent:[],meta:[]},loading:null,ws:null,wsT:null,reloadT:null,stateMap:{}};
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
function gkey(s){return [s.brand||"",s.material||"",s.subtype||"",hexOf(s.rgba),W(s)].join("|").toLowerCase()}
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

async function anlegen(f,restG){const s=await req("POST","/inventory/spools",Object.assign({},f,{weight_used:Math.max(0,Math.round((f.label_weight-restG)*10)/10)}));return s}
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
      const [spools,printers,usage]=await Promise.all([req("GET","/inventory/spools?include_archived=true"),req("GET","/printers/").catch(()=>[]),req("GET","/inventory/usage?limit=500").catch(()=>[])]);
      B.spools=Array.isArray(spools)?spools:[];B.printers=Array.isArray(printers)?printers:[];B.usage=Array.isArray(usage)?usage:[];
      const st=await Promise.all(B.printers.map(p=>req("GET","/printers/"+p.id+"/status").catch(()=>null)));
      B.printers.forEach((p,i)=>{if(st[i])B.status[p.id]=st[i]});
      gruppieren();zustaende();B.loaded=true;B.err="";B.at=Date.now();
    }catch(e){B.err=e.message;console.warn("Bambuddy",e);if(window.toast&&!B.loaded)toast("Bambuddy: "+e.message)}
    finally{B.loading=null;verteilen()}})();
  return B.loading}
function bald(){clearTimeout(B.reloadT);B.reloadT=setTimeout(()=>laden(true),600)}
function verbinden(){
  if(!on()||B.ws)return;
  let ws;try{ws=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+API()+"/ws")}catch(e){return}
  B.ws=ws;
  ws.onmessage=ev=>{let m;try{m=JSON.parse(ev.data)}catch(e){return}
    if(/^(inventory_changed|spool_assignment_changed|spool_auto_assigned|spool_usage_logged|print_complete)$/.test(m.type))bald();
    else if(m.type==="printer_status"&&m.printer_id!=null&&m.data&&m.data.ams){B.status[m.printer_id]=Object.assign(B.status[m.printer_id]||{},m.data);clearTimeout(B.wsT);B.wsT=setTimeout(()=>{zustaende();try{LGN.onStates&&LGN.onStates()}catch(e){}},1500)}};
  const ping=setInterval(()=>{try{ws.readyState===1&&ws.send('{"type":"ping"}')}catch(e){}},30000);
  ws.onclose=()=>{clearInterval(ping);B.ws=null;setTimeout(verbinden,10000)};}
setInterval(()=>{if(on()&&!document.hidden)laden(false)},60000);
document.addEventListener("visibilitychange",()=>{if(on()&&!document.hidden)laden(true)});

/* Abos für das Lager */
function subscribe(art,cb){B.subs[art].push(cb);if(B.loaded)setTimeout(()=>cb(art==="ent"?items():verbrauch()),0);else laden(true);verbinden();
  return ()=>{B.subs[art]=B.subs[art].filter(f=>f!==cb)}}

window.BBY={on,svc,istSorte,subscribe,laden,states:()=>B.stateMap,name:pre=>NAMEN[pre],_B:B,_sorte:sorte,_felder:felder,_ziele:ziele};
})();
