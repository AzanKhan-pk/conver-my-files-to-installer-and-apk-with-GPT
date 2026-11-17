const { createHash } = require("node:crypto");
const { getSql, send } = require("./_db");
const ALLOWED_ORIGINS = new Set(["https://savevido-central-platform.vercel.app","https://savevido-central-platform-azankhan-pks-projects.vercel.app"]);
function clean(value,max=120){return String(value||"").replace(/[\u0000-\u001f\u007f]/g,"").trim().slice(0,max);}
function safeCity(value){try{return clean(decodeURIComponent(String(value||"").replace(/\+/g,"%20")),80);}catch(_){return clean(value,80);}}
function hostOnly(value){try{return new URL(value).hostname.toLowerCase().slice(0,180);}catch(_){return "";}}
module.exports=async function handler(req,res){
 const origin=String(req.headers.origin||"");
 if(origin&&!ALLOWED_ORIGINS.has(origin))return send(res,403,{error:"Origin not allowed"});
 if(origin)res.setHeader("Access-Control-Allow-Origin",origin);
 res.setHeader("Vary","Origin");res.setHeader("Access-Control-Allow-Methods","POST, OPTIONS");res.setHeader("Access-Control-Allow-Headers","Content-Type");
 if(req.method==="OPTIONS")return res.status(204).end();
 if(req.method!=="POST")return send(res,405,{error:"Method not allowed"});
 if(!String(req.headers["content-type"]||"").includes("application/json"))return send(res,415,{error:"JSON required"});
 try{
  const body=typeof req.body==="string"?JSON.parse(req.body):(req.body||{});
  const sessionId=clean(body.session_id,80),eventType=clean(body.event_type,40);
  if(!/^[a-zA-Z0-9-]{20,80}$/.test(sessionId))return send(res,400,{error:"Invalid session"});
  if(!["page_view","app_open","download_click"].includes(eventType))return send(res,400,{error:"Unsupported event"});
  const platform=["web","windows","android","microsoft_store"].includes(body.platform)?body.platform:"web";
  const sessionHash=createHash("sha256").update(sessionId).digest("hex");
  const countryCode=clean(req.headers["x-vercel-ip-country"],2).toUpperCase()||null;
  const city=safeCity(req.headers["x-vercel-ip-city"])||null;
  const referrerHost=hostOnly(req.headers.referer)||null;
  const pagePath=clean(body.page_path,120).split("?")[0].split("#")[0]||"/";
  const sql=getSql();
  await sql`INSERT INTO platform_sessions(session_hash,platform,last_seen_at,country_code,city,referrer_host)
   VALUES(${sessionHash},${platform},NOW(),${countryCode},${city},${referrerHost})
   ON CONFLICT(session_hash) DO UPDATE SET platform=EXCLUDED.platform,last_seen_at=NOW(),
   country_code=COALESCE(EXCLUDED.country_code,platform_sessions.country_code),
   city=COALESCE(EXCLUDED.city,platform_sessions.city),
   referrer_host=COALESCE(EXCLUDED.referrer_host,platform_sessions.referrer_host)`;
  await sql`INSERT INTO platform_events(event_type,platform,session_hash,country_code,city,referrer_host,page_path)
   SELECT ${eventType},${platform},${sessionHash},${countryCode},${city},${referrerHost},${pagePath}
   WHERE NOT EXISTS(SELECT 1 FROM platform_events WHERE event_type=${eventType} AND session_hash=${sessionHash} AND created_at>NOW()-INTERVAL '30 minutes')`;
  return send(res,200,{ok:true});
 }catch(error){console.error("Analytics tracking failed:",error.message);return send(res,503,{error:"Analytics temporarily unavailable"});}
};
