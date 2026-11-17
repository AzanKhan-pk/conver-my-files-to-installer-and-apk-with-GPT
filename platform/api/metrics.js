const { timingSafeEqual } = require("node:crypto");
const { getSql, send } = require("./_db");
function authorized(req){
 const expected=process.env.ADMIN_DASHBOARD_TOKEN||"",supplied=String(req.headers.authorization||"").replace(/^Bearer\s+/i,"");
 if(!expected||!supplied)return false;
 const a=Buffer.from(expected),b=Buffer.from(supplied);
 return a.length===b.length&&timingSafeEqual(a,b);
}
module.exports=async function handler(req,res){
 if(req.method!=="GET")return send(res,405,{error:"Method not allowed"});
 if(!authorized(req))return send(res,401,{error:"Unauthorized"});
 try{
  const sql=getSql();
  const [totals,daily,countries,platforms,recentErrors,recentEvents]=await Promise.all([
   sql`SELECT (SELECT COUNT(*)::int FROM platform_events WHERE event_type IN ('download_succeeded','download_served')) AS downloads,
    (SELECT COUNT(*)::int FROM platform_events WHERE event_type='page_view') AS page_views,
    (SELECT COUNT(*)::int FROM platform_sessions) AS visitors,
    (SELECT COUNT(*)::int FROM platform_sessions WHERE last_seen_at>NOW()-INTERVAL '5 minutes') AS active_sessions,
    (SELECT COUNT(*)::int FROM platform_events WHERE event_type='download_failed') AS failed_downloads`,
   sql`SELECT day::date::text AS date,COUNT(e.id) FILTER(WHERE e.event_type='page_view')::int AS page_views,
    COUNT(e.id) FILTER(WHERE e.event_type IN ('download_succeeded','download_served'))::int AS downloads
    FROM generate_series(CURRENT_DATE-INTERVAL '13 days',CURRENT_DATE,INTERVAL '1 day') day
    LEFT JOIN platform_events e ON e.created_at>=day AND e.created_at<day+INTERVAL '1 day'
    GROUP BY day ORDER BY day`,
   sql`SELECT COALESCE(country_code,'Unknown') AS country_code,COALESCE(MAX(city),'') AS city,COUNT(DISTINCT session_hash)::int AS visitors
    FROM platform_sessions GROUP BY country_code ORDER BY visitors DESC LIMIT 20`,
   sql`SELECT platform,COUNT(*)::int AS visitors FROM platform_sessions GROUP BY platform ORDER BY visitors DESC`,
   sql`SELECT event_type,platform,COALESCE(country_code,'') AS country_code,COALESCE(city,'') AS city,
    COALESCE(error_code,'') AS error_code,COALESCE(error_message,'') AS error_message,created_at
    FROM platform_events WHERE event_type='download_failed' ORDER BY created_at DESC LIMIT 30`,
   sql`SELECT event_type,platform,COALESCE(artifact,'') AS artifact,COALESCE(country_code,'') AS country_code,
    COALESCE(city,'') AS city,COALESCE(referrer_host,'') AS referrer_host,COALESCE(page_path,'') AS page_path,created_at
    FROM platform_events ORDER BY created_at DESC LIMIT 40`
  ]);
  return send(res,200,{totals:totals[0]||{},daily,countries,platforms,errors:recentErrors,events:recentEvents,generated_at:new Date().toISOString()});
 }catch(error){console.error("Private analytics query failed:",error.message);return send(res,503,{error:"Analytics temporarily unavailable"});}
};
