const { createHash } = require("node:crypto");
const { getSql, send } = require("./_db");
const ALLOWED_ORIGINS = new Set(["https://savevido-central-platform.vercel.app","https://savevido-central-platform-azankhan-pks-projects.vercel.app"]);
function clean(v,max=160){return String(v||"").replace(/[\u0000-\u001f\u007f]/g,"").trim().slice(0,max);}
function safeCity(v){try{return clean(decodeURIComponent(String(v||"").replace(/\+/g,"%20")),80);}catch(_){return clean(v,80);}}
function hostName(v){const raw=clean(v,220).toLowerCase();if(!raw)return null;try{const u=new URL(raw.includes("://")?raw:"https://"+raw);return /^[a-z0-9.-]+$/.test(u.hostname)?u.hostname.slice(0,180):null;}catch(_){return null;}}
function safeError(v){return clean(v,500).replace(/https?:\/\/\S+/gi,"[source URL hidden]").replace(/(token|password|secret|key)=([^&\s]+)/gi,"$1=[hidden]").slice(0,180);}
function safeSourceUrl(v){const raw=clean(v,2048);if(!raw)return null;try{const u=new URL(raw);if(!["http:","https:"].includes(u.protocol))return null;u.username="";u.password="";u.hash="";for(const k of [...u.searchParams.keys()])if(!["v","list","video_id","id","p","t"].includes(k.toLowerCase()))u.searchParams.delete(k);return u.toString().slice(0,1200);}catch(_){return null;}}
module.exports=async function handler(req,res){
 const origin=String(req.headers.origin||"");if(origin&&!ALLOWED_ORIGINS.has(origin))return send(res,403,{error:"Origin not allowed"});if(origin)res.setHeader("Access-Control-Allow-Origin",origin);
 res.setHeader("Vary","Origin");res.setHeader("Access-Control-Allow-Methods","POST, OPTIONS");res.setHeader("Access-Control-Allow-Headers","Content-Type");
 if(req.method==="OPTIONS")return res.status(204).end();if(req.method!=="POST")return send(res,405,{error:"Method not allowed"});if(!String(req.headers["content-type"]||"").includes("application/json"))return send(res,415,{error:"JSON required"});if(Number(req.headers["content-length"]||0)>8192)return send(res,413,{error:"Payload too large"});
 try{
  const b=typeof req.body==="string"?JSON.parse(req.body):(req.body||{}),sid=clean(b.session_id,80),eventType=clean(b.event_type,40);
  if(!/^[a-zA-Z0-9-]{20,80}$/.test(sid))return send(res,400,{error:"Invalid session"});
  const allowed=["page_view","app_open","app_heartbeat","download_click","download_succeeded","download_failed","download_incomplete"];
  if(!allowed.includes(eventType))return send(res,400,{error:"Unsupported event"});
  const platform=["web","windows","android","microsoft_store"].includes(b.platform)?b.platform:"web";if(eventType!=="page_view"&&platform!=="windows")return send(res,400,{error:"Invalid app platform"});
  const hash=createHash("sha256").update(sid).digest("hex"),country=clean(req.headers["x-vercel-ip-country"],2).toUpperCase()||null,city=safeCity(req.headers["x-vercel-ip-city"])||null,ref=hostName(req.headers.referer),host=hostName(b.source_host),path=clean(b.page_path,120).split("?")[0].split("#")[0]||"/",version=clean(b.app_version,32)||null,type=clean(b.file_type,12)||null,code=clean(b.error_code,60)||null,message=safeError(b.error_message)||null,source=b.share_source_url===true?safeSourceUrl(b.source_url):null;
  // The current Neon CHECK constraint permits the established event labels.
  const storedEventType=eventType==="download_succeeded"?"download_served":(["download_failed","download_incomplete","download_click"].includes(eventType)?"download_started":eventType==="app_heartbeat"?"app_open":eventType);
  const storedErrorCode=eventType==="download_incomplete"?"download_incomplete":code;
  const sql=getSql();await sql`ALTER TABLE platform_events ADD COLUMN IF NOT EXISTS source_url TEXT`;
  await sql`INSERT INTO platform_sessions(session_hash,platform,last_seen_at,country_code,city,referrer_host) VALUES(${hash},${platform},NOW(),${country},${city},${ref}) ON CONFLICT(session_hash) DO UPDATE SET platform=EXCLUDED.platform,last_seen_at=NOW(),country_code=COALESCE(EXCLUDED.country_code,platform_sessions.country_code),city=COALESCE(EXCLUDED.city,platform_sessions.city),referrer_host=COALESCE(EXCLUDED.referrer_host,platform_sessions.referrer_host)`;
  await sql`INSERT INTO platform_events(event_type,platform,session_hash,country_code,city,referrer_host,page_path,source_host,app_version,file_type,error_code,error_message,source_url)
   SELECT ${storedEventType},${platform},${hash},${country},${city},${ref},${eventType==="page_view"?path:null},${host},${version},${type},${storedErrorCode},${message},${source}
   WHERE ${eventType!=="page_view"} OR NOT EXISTS(SELECT 1 FROM platform_events WHERE event_type=${eventType} AND session_hash=${hash} AND created_at>NOW()-INTERVAL '30 minutes')`;
  return send(res,200,{ok:true});
 }catch(error){console.error("Analytics tracking failed:",error.message);return send(res,503,{error:"Analytics temporarily unavailable"});}
};
