const { getSql, send } = require("./_db");

const ALLOWED_ORIGINS = new Set([
  "https://savevido-central-platform.vercel.app",
  "https://savevido-owner-dashboard.vercel.app",
  "http://127.0.0.1:5000",
  "http://localhost:5000"
]);

function clean(value, max) {
  return String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, max);
}
function cleanText(value, max) {
  return String(value ?? "").replace(/\r\n?/g, "\n").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "").trim().slice(0, max);
}
function safeSourceUrl(value) {
  const raw = clean(value, 2048);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    url.username = "";
    url.password = "";
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (!["v", "list", "video_id", "id", "p", "t"].includes(key.toLowerCase())) url.searchParams.delete(key);
    }
    return url.toString().slice(0, 1200);
  } catch (_) { return null; }
}
function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value) && value.length <= 254;
}
function validWhatsapp(value) {
  return /^\+[1-9][0-9]{7,14}$/.test(value);
}
function cors(req, res) {
  const origin = String(req.headers.origin || "");
  if (origin && !ALLOWED_ORIGINS.has(origin)) return false;
  if (origin) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");
  return true;
}

module.exports = async function handler(req, res) {
  if (!cors(req, res)) return send(res, 403, { error: "Origin not allowed" });
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return send(res, 405, { error: "Method not allowed" });
  try {
    if (!String(req.headers["content-type"] || "").includes("application/json")) return send(res, 415, { error: "JSON required" });
    const body = typeof req.body === "string" ? JSON.parse(req.body) : (req.body || {});
    if (clean(body.website, 200)) return send(res, 200, { ok: true, message: "Thanks. Your feedback was received." });
    const nickname = clean(body.nickname, 80);
    const email = clean(body.email, 254).toLowerCase();
    const whatsapp = clean(body.whatsapp_number, 24);
    const message = cleanText(body.message, 4000);
    if (nickname.length < 2) return send(res, 400, { error: "Please enter your name (at least 2 characters)." });
    if (!message || message.length < 3) return send(res, 400, { error: "Please enter your feedback message." });
    if (!email && !whatsapp) return send(res, 400, { error: "Enter an email address or WhatsApp number." });
    if (email && !validEmail(email)) return send(res, 400, { error: "Please enter a valid email address." });
    if (whatsapp && !validWhatsapp(whatsapp)) return send(res, 400, { error: "Use WhatsApp international format, e.g. +923001234567." });
    const locationAllowed = body.location_consent === true;
    const lat = locationAllowed && Number.isFinite(Number(body.latitude)) ? Number(body.latitude) : null;
    const lon = locationAllowed && Number.isFinite(Number(body.longitude)) ? Number(body.longitude) : null;
    const accuracy = locationAllowed && Number.isFinite(Number(body.location_accuracy_m)) ? Math.min(100000, Math.max(0, Number(body.location_accuracy_m))) : null;
    if ((lat === null) !== (lon === null) || (lat !== null && (lat < -90 || lat > 90 || lon < -180 || lon > 180))) {
      return send(res, 400, { error: "The shared location is invalid. Please retry without location or share it again." });
    }
    const sourceUrl = safeSourceUrl(body.source_url);
    const sourceApp = clean(body.source_app, 120) || "SaveVido";
    const errorDetails = cleanText(body.error_details, 2000);
    const sql = getSql();
    await sql`INSERT INTO savevido_feedbacks
      (nickname,email,whatsapp_number,message,source_url,source_app,error_details,
       location_latitude,location_longitude,location_accuracy_m,location_consent_at)
      VALUES (${nickname},${email || null},${whatsapp || null},${message},${sourceUrl},
       ${sourceApp},${errorDetails || null},${lat},${lon},${accuracy},
       ${lat !== null ? new Date().toISOString() : null})`;
    return send(res, 201, { ok: true, message: "Thank you. Your feedback was saved securely." });
  } catch (error) {
    console.error("Feedback submission failed:", error.message);
    return send(res, 503, { error: "Feedback could not be saved right now. Please try again later." });
  }
};
