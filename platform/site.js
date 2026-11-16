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
function trackPageView(){
  try{
    fetch("/api/track",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_type:"page_view",platform:"web",session_id:getSessionId()}),keepalive:true}).catch(()=>{});
  }catch(_){}
}
async function loadPlatformData(){
  try{
    const metricsRes=await fetch("/api/metrics",{cache:"no-store"});
    if(!metricsRes.ok)throw new Error("metrics unavailable");
    const m=await metricsRes.json();
    if(Number.isFinite(m.total_downloads))$("downloads-total").textContent=m.total_downloads.toLocaleString();
    if(Number.isFinite(m.active_sessions))$("active-users").textContent=m.active_sessions.toLocaleString();
    if(Number.isFinite(m.average_rating)&&m.rating_count>0)$("rating").textContent=m.average_rating.toFixed(1)+"/5";
    if(Number.isFinite(m.rating_count))$("rating-count").textContent=m.rating_count.toLocaleString()+" verified ratings";
    if(Array.isArray(m.daily_downloads)&&m.daily_downloads.length){
      drawChart(m.daily_downloads);
      $("chart-empty").hidden=true;
      $("chart-period").textContent="Last "+m.daily_downloads.length+" days";
    }
    $("downloads-note").textContent="Verified successful file deliveries";
    $("data-status").textContent="Live analytics connected · Updated "+new Date(m.generated_at||Date.now()).toLocaleTimeString();
  }catch(e){
    $("data-status").textContent="Analytics is temporarily unavailable. No sample numbers are displayed.";
  }
  try{
    const releaseRes=await fetch("./release-config.json",{cache:"no-store"});
    if(releaseRes.ok){
      const r=await releaseRes.json();
      $("windows-version").textContent=r.channels?.windows?.version||r.channels?.windows?.status||"Not published";
      $("android-version").textContent=r.channels?.android?.version||r.channels?.android?.status||"In development";
      $("store-version").textContent=r.channels?.microsoft_store?.version||r.channels?.microsoft_store?.status||"Not submitted";
      $("update-status").textContent=r.update_service?.status||"Connected";
    }
  }catch(_){}
}
function drawChart(points){
  const c=$("downloads-chart"),ctx=c.getContext("2d"),dpr=window.devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;
  c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);
  const vals=points.map(p=>Math.max(0,Number(p.downloads)||0)),max=Math.max(1,...vals),step=w/Math.max(1,vals.length-1);
  ctx.strokeStyle="#b8f34c";ctx.lineWidth=2;ctx.beginPath();
  vals.forEach((v,i)=>{const x=i*step,y=h-12-(v/max)*(h-28);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});
  ctx.stroke();ctx.lineTo(w,h);ctx.lineTo(0,h);ctx.closePath();ctx.fillStyle="#b8f34c18";ctx.fill();
}
trackPageView();
setInterval(trackPageView,120000);
loadPlatformData();
setInterval(loadPlatformData,30000);
