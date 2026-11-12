-- TLP Phase 2: the sub-path consistency test (T2 of chat2_tests.sql) on the driving legs of "driving+driving_walking"
-- trips, the 38% of trips that end exactly on the network. Same method and thresholds as chat2_tests.sql; the walking
-- control is not repeated. Runs on the Mac mini only; prints aggregates only.
\timing on
SET work_mem = '1GB';
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
    AND t.mode_set = 'driving+driving_walking' AND l.travel_mode = 'driving';
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
