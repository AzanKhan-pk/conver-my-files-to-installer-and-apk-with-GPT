const { getSql, send } = require("./_db");

const ORIGINS = new Set(["https://savevido-central-platform.vercel.app"]);
const JWKS_URL = process.env.NEON_AUTH_JWKS_URL;
let jwks;
function clean(v,n=120){return String(v??"").replace(/[\u0000-\u001f\u007f]/g,"").trim().slice(0,n);}
function cors(req,res){
 const origin=String(req.headers.origin||"");
 if(origin&&!ORIGINS.has(origin))return false;
 if(origin){res.setHeader("Access-Control-Allow-Origin",origin);res.setHeader("Vary","Origin");}
 res.setHeader("Access-Control-Allow-Methods","GET, PUT, DELETE, OPTIONS");
 res.setHeader("Access-Control-Allow-Headers","Authorization, Content-Type");
 res.setHeader("Cache-Control","no-store");
 return true;
}
async function userId(req){
 if(!JWKS_URL)throw new Error("Auth verification is not configured");
 const { createRemoteJWKSet, jwtVerify } = await import("jose");
 const token=String(req.headers.authorization||"").replace(/^Bearer\s+/i,"");
 if(!token)throw new Error("Unauthorized");
 jwks ||= createRemoteJWKSet(new URL(JWKS_URL));
 const issuer=process.env.NEON_AUTH_BASE_URL;
 if(!issuer)throw new Error("Auth issuer is not configured");
 let payload;
 try{
  const verified=await jwtVerify(token,jwks,{algorithms:["EdDSA"],issuer});
  payload=verified.payload;
 }catch(_){throw new Error("Unauthorized");}
 const sub=String(payload.sub||"");
 if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(sub))throw new Error("Unauthorized");
 return sub;
}
module.exports=async function handler(req,res){
 if(!cors(req,res))return send(res,403,{error:"Origin not allowed"});
 if(req.method==="OPTIONS")return res.status(204).end();
 if(!["GET","PUT","DELETE"].includes(req.method))return send(res,405,{error:"Method not allowed"});
 try{
  const id=await userId(req),sql=getSql();
  if(req.method==="DELETE"){
   await sql`DELETE FROM savevido_user_profiles WHERE auth_user_id=${id}`;
   await sql`DELETE FROM savevido_privacy_preferences WHERE auth_user_id=${id}`;
   return send(res,200,{ok:true,message:"Saved profile and preferences cleared. Your sign-in account remains active."});
  }
  if(req.method==="GET"){
   const [profiles,prefs]=await Promise.all([
    sql`SELECT nickname,whatsapp_number,profile_reminders_enabled,last_profile_review_at,created_at,updated_at FROM savevido_user_profiles WHERE auth_user_id=${id} LIMIT 1`,
    sql`SELECT analytics_opt_in,location_sharing_enabled FROM savevido_privacy_preferences WHERE auth_user_id=${id} LIMIT 1`
   ]);
   return send(res,200,{profile:profiles[0]||null,preferences:prefs[0]||{analytics_opt_in:false,location_sharing_enabled:false}});
  }
  if(!String(req.headers["content-type"]||"").includes("application/json"))return send(res,415,{error:"JSON required"});
  if(Number(req.headers["content-length"]||0)>4096)return send(res,413,{error:"Payload too large"});
  const body=typeof req.body==="string"?JSON.parse(req.body):(req.body||{});
  const nickname=clean(body.nickname,40),whatsapp=clean(body.whatsapp_number,24);
  if(nickname.length<2)return send(res,400,{error:"Nickname must be 2–40 characters."});
  if(whatsapp&&!/^\+[1-9][0-9]{7,14}$/.test(whatsapp))return send(res,400,{error:"WhatsApp must use international format, e.g. +923001234567."});
  const analytics=body.analytics_opt_in===true,location=body.location_sharing_enabled===true;
  const reminders=body.profile_reminders_enabled!==false;
  await sql`INSERT INTO savevido_user_profiles(auth_user_id,nickname,whatsapp_number,contact_consent_at,profile_reminders_enabled,last_profile_review_at,updated_at)
   VALUES(${id},${nickname},${whatsapp||null},${whatsapp?new Date().toISOString():null},${reminders},NOW(),NOW())
   ON CONFLICT(auth_user_id) DO UPDATE SET nickname=EXCLUDED.nickname,whatsapp_number=EXCLUDED.whatsapp_number,
   contact_consent_at=CASE WHEN EXCLUDED.whatsapp_number IS NULL THEN NULL ELSE COALESCE(savevido_user_profiles.contact_consent_at,NOW()) END,
   profile_reminders_enabled=EXCLUDED.profile_reminders_enabled,last_profile_review_at=NOW(),updated_at=NOW()`;
  await sql`INSERT INTO savevido_privacy_preferences(auth_user_id,analytics_opt_in,location_sharing_enabled,updated_at)
   VALUES(${id},${analytics},${location},NOW())
   ON CONFLICT(auth_user_id) DO UPDATE SET analytics_opt_in=EXCLUDED.analytics_opt_in,
   location_sharing_enabled=EXCLUDED.location_sharing_enabled,updated_at=NOW()`;
  return send(res,200,{ok:true,message:"Profile and privacy settings saved."});
 }catch(error){
  const message=String(error.message||"");
  if(message==="Unauthorized")return send(res,401,{error:"Please sign in again."});
  console.error("Profile API failed:",message);
  return send(res,503,{error:"Profile service is temporarily unavailable."});
 }
};
