const { getSql, send } = require("./_db");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return send(res, 405, { error: "Method not allowed" });
  try {
    const sql = getSql();
    const [totals, daily] = await Promise.all([
      sql`
        SELECT
          (SELECT COUNT(*)::int FROM platform_events WHERE event_type = 'download_served') AS total_downloads,
          (SELECT COUNT(*)::int FROM platform_sessions WHERE last_seen_at > NOW() - INTERVAL '5 minutes') AS active_sessions,
          (SELECT COALESCE(ROUND(AVG(rating)::numeric, 1), 0) FROM platform_ratings) AS average_rating,
          (SELECT COUNT(*)::int FROM platform_ratings) AS rating_count
      `,
      sql`
        SELECT day::date::text AS date, COALESCE(COUNT(e.id), 0)::int AS downloads
        FROM generate_series(CURRENT_DATE - INTERVAL '13 days', CURRENT_DATE, INTERVAL '1 day') AS day
        LEFT JOIN platform_events e
          ON e.created_at >= day AND e.created_at < day + INTERVAL '1 day'
          AND e.event_type = 'download_served'
        GROUP BY day ORDER BY day
      `
    ]);
    const row = totals[0] || {};
    return send(res, 200, {
      total_downloads: Number(row.total_downloads || 0),
      active_sessions: Number(row.active_sessions || 0),
      average_rating: Number(row.average_rating || 0),
      rating_count: Number(row.rating_count || 0),
      daily_downloads: daily.map(item => ({ date: item.date, downloads: Number(item.downloads || 0) })),
      generated_at: new Date().toISOString()
    });
  } catch (error) {
    console.error("Analytics metrics failed:", error.message);
    return send(res, 503, { error: "Analytics temporarily unavailable" });
  }
};
