const $=id=>document.getElementById(id);let token=sessionStorage.getItem("savevido_owner_token")||"";const api="/api/metrics";
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function time(s){return s?new Date(s).toLocaleString():"—";}
async function load(){
 $("status").textContent="Loading private analytics…";
 try{
  const r=await fetch(api,{headers:{Authorization:"Bearer "+token},cache:"no-store"});
  if(r.status===401)throw new Error("Your access token was not accepted.");
  if(!r.ok)throw new Error("Analytics service returned "+r.status);
  const d=await r.json(),t=d.totals||{},u=d.user_totals||{};
  $("profiles-complete").textContent=Number(u.profiles_complete||0).toLocaleString();$("profiles-incomplete").textContent=Number(u.profiles_incomplete||0).toLocaleString();$("accounts-total").textContent=Number(u.total_accounts||0).toLocaleString();
  $("users").innerHTML=(d.users||[]).map(x=>`<tr><td>${esc(x.email)}</td><td>${esc(x.nickname||"—")}</td><td>${esc(x.whatsapp_number||"—")}</td><td>${x.email_verified?"Yes":"No"}</td><td>${x.profile_complete?"Complete":"Incomplete"}</td><td>${esc(time(x.account_created_at))}</td></tr>`).join("")||`<tr><td colspan="6">No accounts yet</td></tr>`;
  $("downloads").textContent=Number(t.downloads||0).toLocaleString();$("views").textContent=Number(t.page_views||0).toLocaleString();
  $("visitors").textContent=Number(t.visitors||0).toLocaleString();$("active").textContent=Number(t.active_sessions||0).toLocaleString();
  $("updated").textContent="Updated "+new Date(d.generated_at).toLocaleTimeString();
  const days=d.daily||[],max=Math.max(1,...days.map(x=>Number(x.page_views||0)));
  $("chart").innerHTML=days.map(x=>'<div class="bar" title="'+esc(x.date)+': '+Number(x.page_views||0)+' views" style="height:'+Math.max(4,Number(x.page_views||0)/max*145)+'px"><span>'+esc(x.date.slice(5))+'</span></div>').join("");
  $("platforms").innerHTML=(d.platforms||[]).map(x=>'<tr><td>'+esc(x.platform)+'</td><td>'+Number(x.visitors).toLocaleString()+'</td></tr>').join("")||'<tr><td colspan="2">No data yet</td></tr>';
  $("countries").innerHTML=(d.countries||[]).map(x=>{const q=[x.city,x.country_code].filter(Boolean).join(", "),url="https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(q);return '<tr><td>'+esc(x.country_code)+'</td><td>'+esc(x.city||"—")+'</td><td>'+Number(x.visitors).toLocaleString()+'</td><td>'+(q?'<a class="map" target="_blank" rel="noopener" href="'+url+'">Open map</a>':"—")+'</td></tr>';}).join("")||'<tr><td colspan="4">No location data yet</td></tr>';
  $("events").innerHTML=(d.events||[]).map(x=>'<tr><td>'+esc(time(x.created_at))+'</td><td>'+esc(x.event_type)+'</td><td>'+esc(x.platform)+'</td><td>'+esc([x.city,x.country_code].filter(Boolean).join(", "))+'</td><td>'+esc([x.source_host,x.referrer_host,x.page_path,x.app_version,x.file_type].filter(Boolean).join(" · "))+'</td></tr>').join("")||'<tr><td colspan="5">No events yet</td></tr>';
  $("errors").innerHTML=(d.errors||[]).map(x=>'<tr><td>'+esc(time(x.created_at))+'</td><td>'+esc(x.platform)+'</td><td>'+esc([x.error_code,x.error_message,x.source_host,x.app_version].filter(Boolean).join(": ")||"Download failed")+'</td><td>'+esc([x.city,x.country_code].filter(Boolean).join(", "))+'</td></tr>').join("")||'<tr><td colspan="4">No reported failures yet</td></tr>';
  $("status").textContent="Connected. Dashboard refreshes every 30 seconds.";
 }catch(e){$("status").textContent=e.message;if(String(e.message).includes("token")){sessionStorage.removeItem("savevido_owner_token");token="";$("dashboard").classList.add("hidden");$("login").classList.remove("hidden");}}
}
$("signin").addEventListener("click",()=>{token=$("token").value.trim();if(!token){$("login-status").textContent="Enter your access token.";return;}sessionStorage.setItem("savevido_owner_token",token);$("login").classList.add("hidden");$("dashboard").classList.remove("hidden");load();});
$("refresh").addEventListener("click",load);$("logout").addEventListener("click",()=>{sessionStorage.removeItem("savevido_owner_token");token="";$("token").value="";$("dashboard").classList.add("hidden");$("login").classList.remove("hidden");});
if(token){$("login").classList.add("hidden");$("dashboard").classList.remove("hidden");load();}
setInterval(()=>{if(token&&!$("dashboard").classList.contains("hidden"))load();},30000);
