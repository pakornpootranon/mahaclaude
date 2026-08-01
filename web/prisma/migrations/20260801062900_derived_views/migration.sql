-- Derived views (docs/03-data-model.md §3). Prisma has no first-class view
-- support, so these ship as a raw-SQL migration; query them via
-- `prisma.$queryRaw` from the web app / SQLAlchemy `Table(..., autoload_with=...)`
-- from the worker, same as any other reflected table.

-- topic_board_v: per enabled topic, hits in the last 48h, status chip,
-- last recommendation time, distinct tickers recently named (FR-V3).
CREATE VIEW topic_board_v AS
SELECT
  t.id AS topic_id,
  t.name,
  t.description,
  t.sensitivity,
  t.enabled,
  COALESCE(hits.hit_count, 0) AS hits_48h,
  CASE
    WHEN COALESCE(hits.hit_count, 0) = 0 THEN 'quiet'
    WHEN COALESCE(hits.hit_count, 0) <= 2 THEN 'active'
    ELSE 'hot'
  END AS status,
  last_rec.last_triggered_at,
  COALESCE(recent_tickers.tickers, ARRAY[]::text[]) AS recent_tickers
FROM topics t
LEFT JOIN LATERAL (
  SELECT count(*) AS hit_count
  FROM analysis_topics at2
  JOIN analyses a ON a.id = at2.analysis_id
  WHERE at2.topic_id = t.id
    AND a.created_at >= now() - interval '48 hours'
) hits ON true
LEFT JOIN LATERAL (
  SELECT max(r.created_at) AS last_triggered_at
  FROM recommendations r
  WHERE r.topic_id = t.id
) last_rec ON true
LEFT JOIN LATERAL (
  SELECT array_agg(DISTINCT ticker) AS tickers
  FROM recommendations r, unnest(r.tickers) AS ticker
  WHERE r.topic_id = t.id
    AND r.created_at >= now() - interval '48 hours'
) recent_tickers ON true;

-- hit_rates_v: per topic and per action, count / avg confidence / hit rate
-- at 1d/3d/7d from outcomes (FR-V4).
CREATE VIEW hit_rates_v AS
SELECT
  r.topic_id,
  t.name AS topic_name,
  r.action,
  count(*) AS recommendation_count,
  avg(r.confidence) AS avg_confidence,
  avg(o.hit_1d::int) FILTER (WHERE o.hit_1d IS NOT NULL) AS hit_rate_1d,
  avg(o.hit_3d::int) FILTER (WHERE o.hit_3d IS NOT NULL) AS hit_rate_3d,
  avg(o.hit_7d::int) FILTER (WHERE o.hit_7d IS NOT NULL) AS hit_rate_7d
FROM recommendations r
LEFT JOIN topics t ON t.id = r.topic_id
LEFT JOIN outcomes o ON o.recommendation_id = r.id
GROUP BY r.topic_id, t.name, r.action;

-- pm_calibration_v: per edge bucket, count / share where price moved toward
-- estimate by 7d / resolution accuracy (FR-V4, Polymarket tab).
CREATE VIEW pm_calibration_v AS
SELECT
  width_bucket(po.edge_points, 0, 100, 10) AS edge_bucket,
  count(*) AS opportunity_count,
  avg(pmo.moved_toward_estimate_7d::int) FILTER (WHERE pmo.moved_toward_estimate_7d IS NOT NULL)
    AS share_moved_toward_estimate_7d,
  avg(pmo.estimate_correct::int) FILTER (WHERE pmo.resolved) AS resolution_accuracy
FROM pm_opportunities po
LEFT JOIN pm_outcomes pmo ON pmo.pm_opportunity_id = po.id
GROUP BY edge_bucket
ORDER BY edge_bucket;

-- spend_mtd_v: sum(cost_usd) from llm_calls in the current Asia/Bangkok month
-- (arch §8 budget guard).
CREATE VIEW spend_mtd_v AS
SELECT
  coalesce(sum(cost_usd), 0) AS spend_usd,
  date_trunc('month', now() AT TIME ZONE 'Asia/Bangkok') AT TIME ZONE 'Asia/Bangkok' AS month_start
FROM llm_calls
WHERE (created_at AT TIME ZONE 'Asia/Bangkok') >=
      date_trunc('month', now() AT TIME ZONE 'Asia/Bangkok');
