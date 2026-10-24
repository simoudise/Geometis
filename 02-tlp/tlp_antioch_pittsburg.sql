-- =============================================================================
-- Why did Antioch <-> Pittsburg trips fall from ~3,200/day (Apr 1-12) to ~1,200/day (Apr 13-30)?
-- Run: psql -d contracosta -f tlp_antioch_pittsburg.sql > ap_out.txt 2>&1
-- Aggregates only; no device IDs or coordinates are returned.
-- =============================================================================
\pset footer off
SET client_min_messages = warning;

DROP TABLE IF EXISTS ap;
CREATE TEMP TABLE ap AS
SELECT device_id, start_time::date AS day, travel_mode, total_distance_m, elapsed_time_sec,
       CASE WHEN start_time < '2024-04-13' THEN 'early' ELSE 'late' END AS period
FROM base_trips
WHERE (start_city = 'Antioch' AND end_city = 'Pittsburg')
   OR (start_city = 'Pittsburg' AND end_city = 'Antioch');

-- Q1. By day: trips, devices, trips per device, and share of all kept trips that day.
SELECT a.day, to_char(a.day, 'Dy') AS dow, count(*) AS trips, count(DISTINCT a.device_id) AS devices,
       round(count(*)::numeric / count(DISTINCT a.device_id), 2) AS trips_per_device,
       round(100.0 * count(*) / t.n, 1) AS pct_of_day
FROM ap a JOIN (SELECT start_time::date AS day, count(*) AS n FROM base_trips GROUP BY 1) t USING (day)
GROUP BY a.day, t.n ORDER BY a.day;

-- Q2. Mode mix and trip length, early vs late.
SELECT period, travel_mode, count(*) AS trips,
       round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY period), 1) AS pct,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY total_distance_m) / 1000)::numeric, 2) AS median_km
FROM ap GROUP BY period, travel_mode
HAVING count(*) >= 100
ORDER BY period, trips DESC;

-- Q3. Concentration: how much of the early volume came from heavy users, and did they disappear?
WITH d AS (
  SELECT device_id,
         count(*) FILTER (WHERE period = 'early') AS early_trips,
         count(*) FILTER (WHERE period = 'late')  AS late_trips
  FROM ap GROUP BY device_id
), seen_late AS (                     -- seen anywhere in the five cities after Apr 12
  SELECT DISTINCT device_id FROM base_trips WHERE start_time >= '2024-04-13'
), r AS (
  SELECT d.*, ntile(100) OVER (ORDER BY early_trips DESC) AS pctile,
         (s.device_id IS NOT NULL) AS active_late
  FROM d LEFT JOIN seen_late s USING (device_id)
  WHERE early_trips > 0
)
SELECT CASE WHEN pctile = 1 THEN 'top 1% of early devices'
            WHEN pctile <= 10 THEN 'next 9%'
            ELSE 'remaining 90%' END AS device_group,
       count(*) AS devices,
       sum(early_trips) AS early_trips,
       round(100.0 * sum(early_trips) / sum(sum(early_trips)) OVER (), 1) AS pct_of_early_trips,
       round(avg(early_trips), 1) AS early_trips_per_device,
       round(100.0 * avg(active_late::int), 1) AS pct_still_active_late,
       sum(late_trips) AS their_late_ap_trips
FROM r GROUP BY 1 ORDER BY min(pctile);

-- Q4. Same concentration measure for every other inter-city pair, for comparison.
WITH p AS (
  SELECT device_id, least(start_city, end_city) || ' <-> ' || greatest(start_city, end_city) AS pair, count(*) AS n
  FROM base_trips
  WHERE trip_pair_type = 'inter' AND start_time < '2024-04-13'
  GROUP BY 1, 2
), r AS (
  SELECT pair, n, ntile(100) OVER (PARTITION BY pair ORDER BY n DESC) AS pctile FROM p
)
SELECT pair, sum(n) AS early_trips,
       round(100.0 * sum(n) FILTER (WHERE pctile = 1) / sum(n), 1) AS pct_from_top_1pct_devices
FROM r GROUP BY pair ORDER BY early_trips DESC;
