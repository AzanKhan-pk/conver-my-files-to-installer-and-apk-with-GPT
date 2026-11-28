const $=id=>document.getElementById(id);
let token=sessionStorage.getItem("savevido_owner_token")||"";
const api="/api/metrics";
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function time(s){return s?new Intl.DateTimeFormat("en-PK",{dateStyle:"medium",timeStyle:"short",timeZone:"Asia/Karachi"}).format(new Date(s)):"—";}
function downloadFeedback(x){const blob=new Blob([JSON.stringify(x,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="savevido-feedback-"+x.id+".json";a.click();URL.revokeObjectURL(url);}
async function copyFeedbackUrl(value){try{await navigator.clipboard.writeText(value);$("status").textContent="URL copied to clipboard.";}catch(_){$("status").textContent="Could not copy URL. Open it and copy manually.";}}
async function deleteFeedback(id){if(!confirm("Delete this feedback permanently?"))return;const r=await fetch(api+"?feedback_id="+encodeURIComponent(id),{method:"DELETE",headers:{Authorization:"Bearer "+token}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||"Delete failed");load();}
function link(url,label){return url?'<a class="map" target="_blank" rel="noopener noreferrer" href="'+esc(url)+'">'+esc(label)+'</a>':"—";}
function renderDownloadEvents(events){
 if(!events||!events.length)return '<span class="muted">No download activity shared.</span>';
 return '<details><summary>'+events.length+' recent events</summary><div style="min-width:240px;max-width:560px">'+events.map(function(e){
  const kind=esc(String(e.event_type||"").replaceAll("_"," ")),date=esc(time(e.created_at));
  const url=e.source_url?link(e.source_url,"Open source URL"):esc(e.source_host||"Source not shared");
  const err=e.error_message?'<div style="white-space:pre-wrap;color:#ffb4a9">'+esc(e.error_code||"Error")+': '+esc(e.error_message)+'</div>':"";
  return '<div style="padding:8px 0;border-bottom:1px solid var(--line)"><small>'+date+'</small><br><strong>'+kind+'</strong> · '+url+err+'</div>';
 }).join("")+'</div></details>';
}
function renderRegisteredUsers(users){
 $("registered-users").innerHTML=(users||[]).map(function(u){
  const active=u.active_now?'<strong style="color:var(--lime)">Active now</strong>':'<span class="muted">Inactive</span>';
  const email=u.email?'<a class="map" href="mailto:'+esc(u.email)+'">'+esc(u.email)+'</a>':"—";
  const phone=u.whatsapp_number?'<a class="map" target="_blank" rel="noopener noreferrer" href="https://wa.me/'+esc(u.whatsapp_number.replace(/[^0-9]/g,""))+'">'+esc(u.whatsapp_number)+'</a>':"—";
  const permissions=[u.allow_email?"Email allowed":"Email not allowed",u.allow_whatsapp?"WhatsApp allowed":"WhatsApp not allowed"].map(esc).join("<br>");
  const coords=u.location_latitude!==null&&u.location_longitude!==null&&Number.isFinite(Number(u.location_latitude))&&Number.isFinite(Number(u.location_longitude));
  const map=coords?link("https://www.google.com/maps?q="+encodeURIComponent(u.location_latitude+","+u.location_longitude),"Open shared location"):"Not shared";
  return '<tr><td>'+active+'<br><small>'+esc(time(u.last_seen_at))+'</small></td><td>'+esc(u.nickname)+'</td><td>'+email+'</td><td>'+phone+'</td><td>'+permissions+'</td><td>'+map+'</td><td>'+Number(u.today_success_downloads||0).toLocaleString()+'</td><td>'+renderDownloadEvents(u.download_events)+'</td></tr>';
 }).join("")||'<tr><td colspan="8">No registered submissions yet</td></tr>';
}
function renderUnregisteredUsers(users){
 $("unregistered-users").innerHTML=(users||[]).map(function(u){
  const active=u.active_now?'<strong style="color:var(--lime)">Active now</strong>':'<span class="muted">Inactive</span>';
  const location=[u.city,u.country_code].filter(Boolean).join(", ");
  const map=location?link("https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(location),"Open approximate map"):"Not available";
  return '<tr><td>'+active+'<br><small>'+esc(time(u.last_seen_at))+'</small></td><td>Anonymous · '+esc(u.session_label)+'</td><td>'+map+'</td><td>'+Number(u.today_success_downloads||0).toLocaleString()+'</td><td>'+renderDownloadEvents(u.download_events)+'</td></tr>';
 }).join("")||'<tr><td colspan="5">No anonymous sessions yet</td></tr>';
}
async function load(){
 $("status").textContent="Loading private analytics…";
 try{
  const r=await fetch(api,{headers:{Authorization:"Bearer "+token},cache:"no-store"});
  if(r.status===401)throw new Error("Your access token was not accepted.");
  if(!r.ok)throw new Error("Analytics service returned "+r.status);
  const d=await r.json(),t=d.totals||{},feedbacks=d.feedbacks||[];
  renderRegisteredUsers(d.registered_users||[]);
  renderUnregisteredUsers(d.unregistered_users||[]);
  $("downloads").textContent=Number(t.downloads||0).toLocaleString();
  $("views").textContent=Number(t.page_views||0).toLocaleString();
  $("visitors").textContent=Number(t.visitors||0).toLocaleString();
  $("active").textContent=Number(t.active_sessions||0).toLocaleString();
  $("updated").textContent="Updated "+new Date(d.generated_at).toLocaleTimeString();
  const days=d.daily||[],max=Math.max(1,...days.map(x=>Number(x.page_views||0)));
  $("chart").innerHTML=days.map(x=>'<div class="bar" title="'+esc(x.date)+': '+Number(x.page_views||0)+' views" style="height:'+Math.max(4,Number(x.page_views||0)/max*145)+'px"><span>'+esc(x.date.slice(5))+'</span></div>').join("");
  $("platforms").innerHTML=(d.platforms||[]).map(x=>'<tr><td>'+esc(x.platform)+'</td><td>'+Number(x.visitors).toLocaleString()+'</td></tr>').join("")||'<tr><td colspan="2">No data yet</td></tr>';
  $("countries").innerHTML=(d.countries||[]).map(x=>{const q=[x.city,x.country_code].filter(Boolean).join(", "),url="https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(q);return '<tr><td>'+esc(x.country_code)+'</td><td>'+esc(x.city||"—")+'</td><td>'+Number(x.visitors).toLocaleString()+'</td><td>'+(q?link(url,"Open map"):"—")+'</td></tr>';}).join("")||'<tr><td colspan="4">No location data yet</td></tr>';
  $("events").innerHTML=(d.events||[]).map(x=>'<tr><td>'+esc(time(x.created_at))+'</td><td>'+esc(x.event_type)+'</td><td>'+esc(x.platform)+'</td><td>'+esc([x.city,x.country_code].filter(Boolean).join(", "))+'</td><td>'+esc([x.source_host,x.referrer_host,x.page_path,x.app_version,x.file_type].filter(Boolean).join(" · "))+'</td></tr>').join("")||'<tr><td colspan="5">No events yet</td></tr>';
  $("errors").innerHTML=(d.errors||[]).map(x=>'<tr><td>'+esc(time(x.created_at))+'</td><td>'+esc(x.platform)+'</td><td>'+esc([x.error_code,x.error_message,x.source_host,x.app_version].filter(Boolean).join(": ")||"Download failed")+'</td><td>'+esc([x.city,x.country_code].filter(Boolean).join(", "))+'</td></tr>').join("")||'<tr><td colspan="4">No reported failures yet</td></tr>';
  $("feedback-count").textContent=feedbacks.length+" reports";
  $("feedbacks").innerHTML=feedbacks.map(x=>{
    const coords=Number.isFinite(Number(x.location_latitude))&&Number.isFinite(Number(x.location_longitude))&&x.location_latitude!==null&&x.location_longitude!==null;
    const mapUrl=coords?"https://www.google.com/maps?q="+encodeURIComponent(x.location_latitude+","+x.location_longitude):"";
    const contactEmail=x.email?'<a class="map" href="mailto:'+encodeURIComponent(x.email)+'">'+esc(x.email)+'</a>':"—";
    const phone=x.whatsapp_number?'<a class="map" target="_blank" rel="noopener noreferrer" href="https://wa.me/'+esc(x.whatsapp_number.replace(/[^0-9]/g,""))+'">'+esc(x.whatsapp_number)+'</a>':"—";
    const source=x.source_url?link(x.source_url,"Open source URL"):esc(x.source_app||"SaveVido");
    const sourceCopy=x.source_url?'<button type="button" data-copy-url="'+esc(x.source_url)+'">Copy URL</button>':"";
    const actions='<button type="button" data-download-feedback="'+esc(x.id)+'">Download</button> <button type="button" data-delete-feedback="'+esc(x.id)+'">Delete</button>';
    const location=coords?link(mapUrl,"Open shared location")+'<br><small>'+esc(time(x.location_consent_at))+' · ±'+esc(Math.round(Number(x.location_accuracy_m)||0))+' m</small>':"Not shared";
    return '<tr><td>'+esc(time(x.created_at))+'</td><td>'+esc(x.nickname)+'</td><td>'+contactEmail+'</td><td>'+phone+'</td><td style="white-space:pre-wrap;min-width:240px">'+esc(x.message)+'</td><td>'+source+'<br>'+sourceCopy+'<br><small>'+esc(x.source_app||"")+'</small></td><td style="white-space:pre-wrap">'+esc(x.error_details||"—")+'</td><td>'+location+'</td><td>'+actions+'</td></tr>';
  }).join("")||'<tr><td colspan="9">No feedback received yet</td></tr>';
  $("status").textContent="Connected. Dashboard refreshes every 30 seconds.";
  $("feedbacks").querySelectorAll("[data-copy-url]").forEach(b=>b.addEventListener("click",()=>copyFeedbackUrl(b.dataset.copyUrl)));
  $("feedbacks").querySelectorAll("[data-download-feedback]").forEach(b=>b.addEventListener("click",()=>{const item=feedbacks.find(x=>x.id===b.dataset.downloadFeedback);if(item)downloadFeedback(item);}));
  $("feedbacks").querySelectorAll("[data-delete-feedback]").forEach(b=>b.addEventListener("click",()=>deleteFeedback(b.dataset.deleteFeedback).catch(e=>alert(e.message))));
 }catch(e){
  $("status").textContent=e.message;
  if(String(e.message).includes("token")){sessionStorage.removeItem("savevido_owner_token");token="";$("dashboard").classList.add("hidden");$("login").classList.remove("hidden");}
 }
}
$("signin").addEventListener("click",()=>{token=$("token").value.trim();if(!token){$("login-status").textContent="Enter your access token.";return;}sessionStorage.setItem("savevido_owner_token",token);$("login").classList.add("hidden");$("dashboard").classList.remove("hidden");load();});
$("refresh").addEventListener("click",load);
$("logout").addEventListener("click",()=>{sessionStorage.removeItem("savevido_owner_token");token="";$("token").value="";$("dashboard").classList.add("hidden");$("login").classList.remove("hidden");});
if(token){$("login").classList.add("hidden");$("dashboard").classList.remove("hidden");load();}
setInterval(()=>{if(token&&!$("dashboard").classList.contains("hidden"))load();},30000);
