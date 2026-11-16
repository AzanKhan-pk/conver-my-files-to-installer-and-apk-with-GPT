const { createHash } = require("node:crypto");
const { getSql, send } = require("./_db");

module.exports = async function handler(req, res) {
  if (req.method !== "POST") return send(res, 405, { error: "Method not allowed" });
  if (!String(req.headers["content-type"] || "").includes("application/json")) {
    return send(res, 415, { error: "JSON required" });
  }

  try {
    const body = typeof req.body === "string" ? JSON.parse(req.body) : (req.body || {});
    const sessionId = String(body.session_id || "");
    const eventType = String(body.event_type || "");
    if (!/^[a-zA-Z0-9-]{20,80}$/.test(sessionId)) return send(res, 400, { error: "Invalid session" });
    if (!["page_view", "app_open"].includes(eventType)) return send(res, 400, { error: "Unsupported event" });

    const platform = ["web", "windows", "android", "microsoft_store"].includes(body.platform)
      ? body.platform : "web";
    const sessionHash = createHash("sha256").update(sessionId).digest("hex");
    const sql = getSql();

    await sql`
      INSERT INTO platform_sessions (session_hash, platform, last_seen_at)
      VALUES (${sessionHash}, ${platform}, NOW())
      ON CONFLICT (session_hash) DO UPDATE
      SET platform = EXCLUDED.platform, last_seen_at = NOW()
    `;

    await sql`
      INSERT INTO platform_events (event_type, platform, session_hash)
      SELECT ${eventType}, ${platform}, ${sessionHash}
      WHERE NOT EXISTS (
        SELECT 1 FROM platform_events
        WHERE event_type = ${eventType}
          AND session_hash = ${sessionHash}
          AND created_at > NOW() - INTERVAL '30 minutes'
      )
    `;

    return send(res, 200, { ok: true });
  } catch (error) {
    console.error("Analytics tracking failed:", error.message);
    return send(res, 500, { error: "Analytics temporarily unavailable" });
  }
};
