const $=id=>document.getElementById(id);
$("year").textContent=new Date().getFullYear();

function getSessionId(){
  const key="savevido_analytics_session";
  let value=localStorage.getItem(key);
  if(!value){
    value=(crypto.randomUUID?crypto.randomUUID():("sv-"+Date.now()+"-"+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2)));
    localStorage.setItem(key,value);
  }
  return value;
}
const ANALYTICS_ENDPOINT="https://savevido-owner-dashboard.vercel.app/api/track";
function trackPageView(){
  try{
    if(localStorage.getItem("savevido_analytics_consent")!=="accepted")return;
    fetch(ANALYTICS_ENDPOINT,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_type:"page_view",platform:"web",session_id:getSessionId(),page_path:location.pathname}),keepalive:true}).catch(()=>{});
  }catch(_){}
}
function setupAnalyticsConsent(){
  const banner=$("analytics-consent"),choice=localStorage.getItem("savevido_analytics_consent");
  if(!choice&&banner)banner.style.display="block";
  $("analytics-accept")?.addEventListener("click",()=>{
    localStorage.setItem("savevido_analytics_consent","accepted");
    if(banner)banner.style.display="none";
    trackPageView();
  });
  $("analytics-decline")?.addEventListener("click",()=>{
    localStorage.setItem("savevido_analytics_consent","declined");
    if(banner)banner.style.display="none";
  });
}
async function loadPlatformData(){
  try{
    const releaseRes=await fetch("/release-config.json?ts="+Date.now(),{cache:"no-store"});
    if(releaseRes.ok){
      const r=await releaseRes.json(),channels=r.channels||{};
      const win=channels.windows||{},android=channels.android||{},store=channels.microsoft_store||{};
      $("windows-version").textContent=win.version||win.status||"Not published";
      $("android-version").textContent=android.version||android.status||"In development";
      $("store-version").textContent=store.version||store.status||"Not published";
      $("update-status").textContent=r.update_service?.status||"Connected";
      if($("windows-status"))$("windows-status").textContent=win.status||"Not published";
      const versionLabel=$("windows-download-version");
      if(versionLabel)versionLabel.textContent=win.version?("Version "+win.version):"Version not published";
      const androidVersionLabel=$("android-download-version");
      if(androidVersionLabel)androidVersionLabel.textContent=android.version?("Version "+android.version):"In development";
      const storeVersionLabel=$("store-download-version");
      if(storeVersionLabel)storeVersionLabel.textContent=store.version?("Version "+store.version):"Not published";
      if($("android-status"))$("android-status").textContent=android.status||"In development";
      if($("store-status"))$("store-status").textContent=store.status||"Not submitted";
      const winLink=$("windows-download");
      if(winLink&&win.download_url){winLink.href=win.download_url;winLink.textContent="Download Windows installer";winLink.removeAttribute("aria-disabled");}
      else if(winLink){winLink.removeAttribute("href");winLink.setAttribute("aria-disabled","true");winLink.textContent="Download unavailable until verified";}
    }
  }catch(_){}
}
setupAnalyticsConsent();
trackPageView();
setInterval(trackPageView,120000);
loadPlatformData();
setInterval(loadPlatformData,30000);
