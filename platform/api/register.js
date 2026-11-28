const { createHash } = require("node:crypto");
const { getSql, send } = require("./_db");
const ALLOWED_ORIGINS = new Set(["https://savevido-central-platform.vercel.app","https://savevido-central-platform-azankhan-pks-projects.vercel.app","http://127.0.0.1:5000","http://localhost:5000"]);
function clean(v,max=160){return String(v??"").replace(/[\u0000-\u001f\u007f]/g,"").trim().slice(0,max);}
function validEmail(v){return /^[^\s@]+\@[^\s@]+\.[^\s@]{2,}$/.test(v)&&v.length<=254;}
function validPhone(v){return /^\+[1-9][0-9]{7,14}$/.test(v);}
module.exports=async function handler(req,res){
 const origin=String(req.headers.origin||"");if(origin&&!ALLOWED_ORIGINS.has(origin))return send(res,403,{error:"Origin not allowed"});if(origin)res.setHeader("Access-Control-Allow-Origin",origin);
 res.setHeader("Vary","Origin");res.setHeader("Access-Control-Allow-Methods","POST, OPTIONS");res.setHeader("Access-Control-Allow-Headers","Content-Type");res.setHeader("Cache-Control","no-store");
 if(req.method==="OPTIONS")return res.status(204).end();if(req.method!=="POST")return send(res,405,{error:"Method not allowed"});if(!String(req.headers["content-type"]||"").includes("application/json"))return send(res,415,{error:"JSON required"});if(Number(req.headers["content-length"]||0)>8192)return send(res,413,{error:"Payload too large"});
 try{
  const b=typeof req.body==="string"?JSON.parse(req.body):(req.body||{}),sid=clean(b.session_id,80),nickname=clean(b.nickname,80),email=clean(b.email,254).toLowerCase(),phone=clean(b.whatsapp_number,24);
  if(!/^[a-f0-9]{32}$/.test(sid))return send(res,400,{error:"Invalid local session"});
  if(nickname.length<2)return send(res,400,{error:"Please enter your name (at least 2 characters)."});
  if(!email&&!phone)return send(res,400,{error:"Enter an email address or WhatsApp number."});
  if(email&&!validEmail(email))return send(res,400,{error:"Please enter a valid email address."});
  if(phone&&!validPhone(phone))return send(res,400,{error:"Use WhatsApp international format, e.g. +923001234567."});
  const allowEmail=b.allow_email===true,allowWhatsapp=b.allow_whatsapp===true,shareActivity=b.share_activity===true;
  if(allowEmail&&!email)return send(res,400,{error:"An email address is required for email messages."});
  if(allowWhatsapp&&!phone)return send(res,400,{error:"A WhatsApp number is required for WhatsApp messages."});
  const updateLocation=b.update_location===true,loc=updateLocation&&b.location_consent===true;
  const lat=loc&&Number.isFinite(Number(b.latitude))?Number(b.latitude):null,lon=loc&&Number.isFinite(Number(b.longitude))?Number(b.longitude):null;
  const accuracy=loc&&Number.isFinite(Number(b.location_accuracy_m))?Math.min(100000,Math.max(0,Number(b.location_accuracy_m))):null;
  if(loc&&(lat===null||lon===null||lat< -90||lat>90||lon< -180||lon>180))return send(res,400,{error:"Location was selected but is not available. Submit without location or allow it again."});
  const hash=createHash("sha256").update(sid).digest("hex"),sql=getSql();
  await sql`CREATE TABLE IF NOT EXISTS savevido_registrations(session_hash TEXT PRIMARY KEY,nickname TEXT NOT NULL,email TEXT,whatsapp_number TEXT,allow_email BOOLEAN NOT NULL DEFAULT FALSE,allow_whatsapp BOOLEAN NOT NULL DEFAULT FALSE,share_activity BOOLEAN NOT NULL DEFAULT FALSE,location_latitude DOUBLE PRECISION,location_longitude DOUBLE PRECISION,location_accuracy_m DOUBLE PRECISION,location_consent_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`;
  await sql`INSERT INTO savevido_registrations(session_hash,nickname,email,whatsapp_number,allow_email,allow_whatsapp,share_activity,location_latitude,location_longitude,location_accuracy_m,location_consent_at)
   VALUES(${hash},${nickname},${email||null},${phone||null},${allowEmail},${allowWhatsapp},${shareActivity},${lat},${lon},${accuracy},${loc?new Date().toISOString():null})
   ON CONFLICT(session_hash) DO UPDATE SET nickname=EXCLUDED.nickname,email=EXCLUDED.email,whatsapp_number=EXCLUDED.whatsapp_number,allow_email=EXCLUDED.allow_email,allow_whatsapp=EXCLUDED.allow_whatsapp,share_activity=EXCLUDED.share_activity,
   location_latitude=CASE WHEN ${updateLocation} THEN EXCLUDED.location_latitude ELSE savevido_registrations.location_latitude END,
   location_longitude=CASE WHEN ${updateLocation} THEN EXCLUDED.location_longitude ELSE savevido_registrations.location_longitude END,
   location_accuracy_m=CASE WHEN ${updateLocation} THEN EXCLUDED.location_accuracy_m ELSE savevido_registrations.location_accuracy_m END,
   location_consent_at=CASE WHEN ${updateLocation} THEN EXCLUDED.location_consent_at ELSE savevido_registrations.location_consent_at END,updated_at=NOW()`;
  await sql`INSERT INTO platform_sessions(session_hash,platform,last_seen_at) VALUES(${hash},'windows',NOW()) ON CONFLICT(session_hash) DO UPDATE SET platform='windows',last_seen_at=NOW()`;
  return send(res,201,{ok:true,message:"Your details were saved. This is not an account."});
 }catch(error){console.error("Registration submission failed:",error.message);return send(res,503,{error:"Details could not be saved right now. Please try again later."});}
};
