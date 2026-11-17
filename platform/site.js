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

const ANALYTICS_ENDPOINT = "https://savevido-owner-dashboard-azankhan-pks-projects.vercel.app/api/track";
function trackPageView(){
  try{
    if(localStorage.getItem("savevido_analytics_optout")==="1") return;
    fetch(ANALYTICS_ENDPOINT,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_type:"page_view",platform:"web",session_id:getSessionId(),page_path:location.pathname}),keepalive:true}).catch(()=>{});
  }catch(_){}
}
trackPageView();
setInterval(trackPageView,120000);
