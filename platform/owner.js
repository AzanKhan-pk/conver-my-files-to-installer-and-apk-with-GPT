const $=id=>document.getElementById(id);
let token=sessionStorage.getItem("savevido_owner_token")||"";
const api="/api/metrics";
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function time(s){return s?new Intl.DateTimeFormat("en-PK",{dateStyle:"medium",timeStyle:"short",timeZone:"Asia/Karachi"}).format(new Date(s)):"—";}
function downloadFeedback(x){const blob=new Blob([JSON.stringify(x,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="savevido-feedback-"+x.id+".json";a.click();URL.revokeObjectURL(url);}
async function copyFeedbackUrl(value){try{await navigator.clipboard.writeText(value);$("status").textContent="URL copied to clipboard.";}catch(_){$("status").textContent="Could not copy URL. Open it and copy manually.";}}
async function deleteFeedback(id){if(!confirm("Delete this feedback permanently?"))return;const r=await fetch(api+"?feedback_id="+encodeURIComponent(id),{method:"DELETE",headers:{Authorization:"Bearer "+token}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||"Delete failed");load();}
function link(url,label){return url?'<a class="map" target="_blank" rel="noopener noreferrer" href="'+esc(url)+'">'+esc(label)+'</a>':"—";}
async function load(){
 $("status").textContent="Loading private analytics…";
 try{
  const r=await fetch(api,{headers:{Authorization:"Bearer "+token},cache:"no-store"});
  if(r.status===401)throw new Error("Your access token was not accepted.");
  if(!r.ok)throw new Error("Analytics service returned "+r.status);
  const d=await r.json(),t=d.totals||{},feedbacks=d.feedbacks||[];
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
