-- TLP Phase 2: checks proposed by the second outside review (Fable Chat 2, 12 November 2026) of whether the vendor's
-- trips are routed or observed. Runs on the Mac mini only; prints aggregates only (no ids, coordinates or devices).
-- April 2024 and June 2024. Tests:
--   T4 what "multimodal" covers and the share of trips with a transit leg;
--   T1 driving link speed computed from link timestamps and distance, and its spread per OSM way;
--   T3 whether a device's single-mode trip ends repeat exactly (a stored stay point) or vary (a fix);
--   T2 sub-path consistency across devices: between two anchor links, how many distinct interior link sequences occur.
\timing on
SET work_mem = '1GB';

\echo '=== T4: trip mode and mode_set'
SELECT travel_mode, count(*) trips, round(100.0 * count(*) / sum(count(*)) OVER (), 1) pct FROM base_trips GROUP BY 1 ORDER BY 2 DESC;
SELECT mode_set, count(*) trips, round(100.0 * count(*) / sum(count(*)) OVER (), 1) pct FROM base_trips GROUP BY 1 ORDER BY 2 DESC LIMIT 15;
SELECT round(100.0 * avg((EXISTS (SELECT 1 FROM base_trip_links l WHERE l.unique_trip_id = t.unique_trip_id
         AND l.travel_mode IN ('transit_bus','transit_subway','transit_rail')))::int), 1) pct_trips_with_transit_leg
FROM (SELECT unique_trip_id FROM base_trips TABLESAMPLE SYSTEM (5)) t;

\echo '=== T1: driving link speed from timestamps (links with duration > 0 and distance >= 50 m)'
CREATE TEMP TABLE dl AS
  SELECT l.osm_way_id, l.distance_m / extract(epoch FROM (l.end_time - l.start_time)) v_ts, l.speed_mps,
         extract(hour FROM l.start_time)::int h
  FROM base_trip_links l JOIN base_trips t USING (unique_trip_id)
  WHERE t.travel_mode = 'driving' AND l.travel_mode = 'driving' AND l.osm_way_id IS NOT NULL
    AND l.end_time > l.start_time AND l.distance_m >= 50;
SELECT count(*) links, round(avg((abs(v_ts - speed_mps) < 0.05)::int)::numeric, 3) share_ts_equals_field,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY v_ts)::numeric * 3.6, 1) median_kmh FROM dl;
\echo 'per way with >= 30 traversals: coefficient of variation of timestamp speed'
SELECT count(*) ways,
       round(percentile_cont(0.1) WITHIN GROUP (ORDER BY cv)::numeric, 3) cv_p10,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY cv)::numeric, 3) cv_p50,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY cv)::numeric, 3) cv_p90,
       round(avg((cv < 0.01)::int)::numeric, 3) share_cv_below_1pct
FROM (SELECT osm_way_id, stddev_samp(v_ts) / nullif(avg(v_ts), 0) cv FROM dl GROUP BY 1 HAVING count(*) >= 30) x;
\echo 'per way with >= 10 traversals in both 07-09h and 01-04h: median ratio of peak to night speed'
SELECT count(*) ways, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r)::numeric, 3) median_ratio,
       round(percentile_cont(0.1) WITHIN GROUP (ORDER BY r)::numeric, 3) p10, round(percentile_cont(0.9) WITHIN GROUP (ORDER BY r)::numeric, 3) p90
FROM (SELECT osm_way_id, avg(v_ts) FILTER (WHERE h BETWEEN 7 AND 8) / nullif(avg(v_ts) FILTER (WHERE h BETWEEN 1 AND 3), 0) r
      FROM dl GROUP BY 1
      HAVING count(*) FILTER (WHERE h BETWEEN 7 AND 8) >= 10 AND count(*) FILTER (WHERE h BETWEEN 1 AND 3) >= 10) x;

\echo '=== T3: repeat of single-mode trip ends per device'
CREATE TEMP TABLE te AS
  SELECT device_id, destination_lat la, destination_long lo FROM base_trips WHERE travel_mode IN ('driving','walking','cycling')
  UNION ALL SELECT device_id, origin_lat, origin_long FROM base_trips WHERE travel_mode IN ('driving','walking','cycling');
SELECT round(avg((n >= 2)::int)::numeric, 3) share_ends_whose_exact_coords_recur_for_device
FROM (SELECT count(*) OVER (PARTITION BY device_id, la, lo) n FROM te) x;
SELECT round(avg((n >= 2)::int)::numeric, 3) share_ends_recurring_within_about_11m
FROM (SELECT count(*) OVER (PARTITION BY device_id, round(la::numeric, 4), round(lo::numeric, 4)) n FROM te) x;

\echo '=== T2: sub-path consistency'
-- Link key: way id plus rounded start and end coordinates, so direction is kept.
CREATE TEMP TABLE lk0 AS
  SELECT l.unique_trip_id, t.device_id, substr(l.unique_trip_id, 5, 2) mon, extract(hour FROM t.start_time)::int h,
         l.link_seq, l.travel_mode lm, l.distance_m, l.origin_lat, l.origin_long, l.destination_lat, l.destination_long,
         l.osm_way_id || ':' || round(l.origin_lat::numeric, 4) || ',' || round(l.origin_long::numeric, 4) || '>'
           || round(l.destination_lat::numeric, 4) || ',' || round(l.destination_long::numeric, 4) k,
         l.link_seq - row_number() OVER (PARTITION BY l.unique_trip_id, l.travel_mode ORDER BY l.link_seq) leg
  FROM base_trip_links l JOIN base_trips t USING (unique_trip_id)
  WHERE l.osm_way_id IS NOT NULL AND l.origin_lat IS NOT NULL
    AND ((t.travel_mode = 'driving' AND l.travel_mode = 'driving') OR l.travel_mode = 'transit_walking');
-- A leg is a run of consecutive links of one mode. Legs with a gap between consecutive links (more than about 11 m)
-- are dropped.
CREATE TEMP TABLE lk AS
  SELECT *, abs(origin_lat - lag(destination_lat) OVER w) + abs(origin_long - lag(destination_long) OVER w) gap
  FROM lk0 WINDOW w AS (PARTITION BY unique_trip_id, lm, leg ORDER BY link_seq);
DROP TABLE lk0;
DELETE FROM lk USING (SELECT DISTINCT unique_trip_id, lm, leg FROM lk WHERE gap > 0.0001) g
  WHERE lk.unique_trip_id = g.unique_trip_id AND lk.lm = g.lm AND lk.leg = g.leg;
CREATE TEMP TABLE anchor AS
  SELECT lm, k FROM lk GROUP BY 1, 2 HAVING count(DISTINCT unique_trip_id) >= 20 AND count(DISTINCT device_id) >= 5;
CREATE INDEX ON anchor (lm, k); ANALYZE lk; ANALYZE anchor;
CREATE TEMP TABLE seq0 AS
  SELECT lk.unique_trip_id, lk.device_id, lk.mon, lk.h, lk.lm, lk.leg, lk.k, lk.distance_m, (a.k IS NOT NULL) is_anchor,
         row_number() OVER (PARTITION BY lk.unique_trip_id, lk.lm, lk.leg ORDER BY lk.link_seq) pos
  FROM lk LEFT JOIN anchor a USING (lm, k);
-- Prefix sums give each interior sequence a fingerprint without listing it: number of links, sum of link-key hashes,
-- and the position-weighted sum of hashes measured from the first anchor.
CREATE TEMP TABLE seq AS
  SELECT *, sum(distance_m) OVER w cum_m, sum(hashtext(k)::bigint) OVER w s1, sum(hashtext(k)::bigint * pos) OVER w s2
  FROM seq0 WINDOW w AS (PARTITION BY unique_trip_id, lm, leg ORDER BY pos);
DROP TABLE seq0;
CREATE INDEX ON seq (unique_trip_id, lm, leg, cum_m) WHERE is_anchor; ANALYZE seq;
-- For each anchor, and for each target distance (1.5, 3.5 and 8 km), pair it with the first later anchor at least that
-- far along the trip (and no more than 1.5 times farther). The interior fingerprint uses prefix sums up to the link
-- before the second anchor.
CREATE TEMP TABLE pr AS
  SELECT a.lm, a.k ka, b.k kb, t.tgt, a.unique_trip_id, a.device_id, a.mon, (a.h BETWEEN 7 AND 9 OR a.h BETWEEN 16 AND 18) peak,
         b.cum_m - a.cum_m dist_m,
         (b.pos - a.pos - 1) || ':' || ((b.s1 - hashtext(b.k)) - a.s1) || ':'
           || (((b.s2 - hashtext(b.k)::bigint * b.pos) - a.s2) - a.pos * ((b.s1 - hashtext(b.k)) - a.s1)) h
  FROM seq a CROSS JOIN (VALUES (1500), (3500), (8000)) t(tgt)
  CROSS JOIN LATERAL (SELECT * FROM seq b WHERE b.is_anchor AND b.unique_trip_id = a.unique_trip_id AND b.lm = a.lm AND b.leg = a.leg
                        AND b.cum_m >= a.cum_m + t.tgt ORDER BY b.cum_m LIMIT 1) b
  WHERE a.is_anchor AND b.cum_m <= a.cum_m + 1.5 * t.tgt;
\echo 'pairs kept: >= 5 trips from >= 3 devices; share with exactly one interior sequence, by distance bin'
CREATE TEMP TABLE pg AS
  SELECT lm, ka, kb, tgt, NULL::text grp, count(*) trips, count(DISTINCT device_id) devs, count(DISTINCT h) seqs,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY dist_m) d
  FROM pr GROUP BY lm, ka, kb, tgt HAVING count(*) >= 5 AND count(DISTINCT device_id) >= 3
  UNION ALL
  SELECT lm, ka, kb, tgt, 'month ' || mon, count(*), count(DISTINCT device_id), count(DISTINCT h), percentile_cont(0.5) WITHIN GROUP (ORDER BY dist_m)
  FROM pr GROUP BY lm, ka, kb, tgt, mon HAVING count(*) >= 5 AND count(DISTINCT device_id) >= 3
  UNION ALL
  SELECT lm, ka, kb, tgt, CASE WHEN peak THEN 'peak' ELSE 'off-peak' END, count(*), count(DISTINCT device_id), count(DISTINCT h), percentile_cont(0.5) WITHIN GROUP (ORDER BY dist_m)
  FROM pr GROUP BY lm, ka, kb, tgt, peak HAVING count(*) >= 5 AND count(DISTINCT device_id) >= 3;
SELECT lm, coalesce(grp, 'all') grp, CASE tgt WHEN 1500 THEN '1.5-2.3 km' WHEN 3500 THEN '3.5-5.3 km' ELSE '8-12 km' END bin,
       count(*) pairs, round(avg((seqs = 1)::int)::numeric, 3) share_one_sequence, round(avg(seqs)::numeric, 2) mean_sequences,
       round(avg(trips)::numeric, 1) mean_trips
FROM pg GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo 'coverage: legs, anchors, pair traversals'
SELECT lm, count(DISTINCT (unique_trip_id, leg)) legs_kept FROM lk GROUP BY 1;
SELECT lm, count(*) anchors FROM anchor GROUP BY 1;
SELECT lm, count(*) pair_traversals FROM pr GROUP BY 1;
