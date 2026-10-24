-- =============================================================================
-- GeoMetis TLP — checks on the rebuilt April 2024 base trips
-- Run locally:  psql -d contracosta -f tlp_april_checks.sql > april_checks_out.txt 2>&1
--
-- Aggregates only: no device IDs, trip IDs or coordinates are returned.
-- Read-only except for TEMP tables, which disappear when psql exits.
-- Q5 scans all ~49 M segments; expect several minutes.
-- =============================================================================
\set ON_ERROR_STOP on
\pset footer off
\timing on
SET client_min_messages = warning;
SET work_mem = '512MB';

-- -----------------------------------------------------------------------------
-- Q1. The 151 vendor trip_ids stored under more than one day.
--     identical_start  : the same trip delivered in two daily files (double count)
--     sequential       : one trip split across two files (e.g. at midnight)
--     overlapping      : partial copies that overlap in time
-- -----------------------------------------------------------------------------
WITH m AS (
  SELECT original_trip_id,
         count(*)                         AS n_days,
         count(DISTINCT start_time)       AS n_starts,
         count(DISTINCT device_id)        AS n_devices,
         max(start_time)                  AS last_start,
         min(end_time)                    AS first_end,
         bool_or(end_time::date > start_time::date) AS any_crosses_midnight,
         max(start_time) - min(start_time) AS start_spread
  FROM base_trips
  GROUP BY original_trip_id
  HAVING count(*) > 1
)
SELECT count(*)                                                        AS trip_ids,
       count(*) FILTER (WHERE n_starts = 1)                            AS identical_start,
       count(*) FILTER (WHERE n_starts > 1 AND last_start >= first_end) AS sequential,
       count(*) FILTER (WHERE n_starts > 1 AND last_start <  first_end) AS overlapping,
       count(*) FILTER (WHERE any_crosses_midnight)                    AS any_crosses_midnight,
       count(*) FILTER (WHERE n_devices > 1)                           AS different_devices,
       max(n_days)                                                     AS max_days,
       max(start_spread)                                               AS max_start_spread
FROM m;

-- -----------------------------------------------------------------------------
-- Q2. Device persistence: are device IDs stable across days?
--     Note: counts only devices with at least one trip kept in the five cities.
-- -----------------------------------------------------------------------------
-- Q2a. Distribution of active days per device.
WITH d AS (
  SELECT device_id, count(*) AS trips, count(DISTINCT start_time::date) AS active_days,
         max(start_time::date) - min(start_time::date) + 1 AS span_days
  FROM base_trips GROUP BY device_id
)
SELECT active_days, count(*) AS devices, sum(trips) AS trips,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_devices,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY span_days) AS median_span_days
FROM d GROUP BY active_days ORDER BY active_days;

-- Q2b. Per day: active devices, devices never seen before, trips.
--      If IDs rotate daily, new_devices ≈ active_devices on every day.
WITH first_seen AS (
  SELECT device_id, min(start_time::date) AS first_day FROM base_trips GROUP BY device_id
)
SELECT b.start_time::date                         AS day,
       to_char(b.start_time::date, 'Dy')          AS dow,
       count(*)                                   AS trips,
       count(DISTINCT b.device_id)                AS active_devices,
       count(DISTINCT b.device_id) FILTER (WHERE f.first_day = b.start_time::date) AS new_devices,
       round(count(*)::numeric / count(DISTINCT b.device_id), 2)                  AS trips_per_device
FROM base_trips b JOIN first_seen f USING (device_id)
GROUP BY 1, 2 ORDER BY 1;

-- -----------------------------------------------------------------------------
-- Q3. Did the vendor's mode labelling change during the month?
--     April 1 labelled walks to and from the car 'driving_walking'; the April 30
--     sample labelled them 'driving'. Columns are segment counts per file day.
-- -----------------------------------------------------------------------------
SELECT left(unique_trip_id, 8)                                                          AS file_day,
       count(*)                                                                         AS segments,
       count(*) FILTER (WHERE travel_mode = 'driving_walking')                          AS driving_walking,
       count(*) FILTER (WHERE trip_event = 'start-end' AND travel_mode = 'driving')     AS start_end_driving,
       count(*) FILTER (WHERE trip_event = 'start-end' AND travel_mode = 'driving_walking') AS start_end_drv_walk,
       count(*) FILTER (WHERE trip_event = 'start-end' AND travel_mode = 'transit_walking') AS start_end_transit_walk,
       count(*) FILTER (WHERE travel_mode = 'transitwait')                              AS transitwait,
       count(*) FILTER (WHERE travel_mode LIKE 'transit\_%' AND travel_mode NOT IN ('transit_walking','transitwait')) AS transit_vehicle,
       count(*) FILTER (WHERE travel_mode = 'cycling')                                  AS cycling,
       count(*) FILTER (WHERE travel_mode = 'walking')                                  AS walking,
       count(*) FILTER (WHERE osm_way_id IS NULL)                                       AS no_osm_way
FROM base_trip_links
GROUP BY 1 ORDER BY 1;

-- Q3b. Trip-level label per file day (shares of kept trips).
SELECT left(unique_trip_id, 8) AS file_day,
       count(*) AS trips,
       round(100.0 * avg((travel_mode = 'driving')::int), 1)                              AS pct_driving,
       round(100.0 * avg((travel_mode = 'multimodal (driving/driving_walking)')::int), 1) AS pct_drv_plus_walk,
       round(100.0 * avg((travel_mode = 'walking')::int), 1)                              AS pct_walking,
       round(100.0 * avg((mode_set LIKE '%transit\_bus%' OR mode_set LIKE '%transit\_subway%'
                          OR mode_set LIKE '%transit\_rail%')::int), 1)                   AS pct_transit_vehicle,
       round(100.0 * avg((travel_mode = 'transit_walking')::int), 1)                      AS pct_transit_walking_only,
       round(100.0 * avg((travel_mode = 'cycling')::int), 1)                              AS pct_cycling,
       round(100.0 * avg((trip_pair_type = 'inter')::int), 1)                             AS pct_inter
FROM base_trips GROUP BY 1 ORDER BY 1;

-- -----------------------------------------------------------------------------
-- Q4. Inter-city pairs: which city pairs, and did the mix shift mid-month?
--     (inter-city share drops from ~42% on Apr 5–12 to ~31% from Apr 15)
-- -----------------------------------------------------------------------------
SELECT start_city, end_city,
       count(*) FILTER (WHERE start_time < '2024-04-13') AS apr01_12,
       count(*) FILTER (WHERE start_time >= '2024-04-13') AS apr13_30,
       count(*) AS total
FROM base_trips
GROUP BY 1, 2 ORDER BY total DESC;

-- -----------------------------------------------------------------------------
-- Q5. Multimodal composition.
--     A leg begins at each 'start' or 'start-end' event, so short access and
--     egress walks (e.g. to a bus stop, or to a car) become legs of their own.
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS legs;
CREATE TEMP TABLE legs AS
WITH l AS (
  SELECT unique_trip_id, link_seq, travel_mode, trip_event, duration_sec, distance_m,
         sum((trip_event IN ('start', 'start-end'))::int)
           OVER (PARTITION BY unique_trip_id ORDER BY link_seq) AS leg_no
  FROM base_trip_links
)
SELECT unique_trip_id, leg_no,
       string_agg(DISTINCT travel_mode, '/')  AS leg_mode,     -- one mode per leg if labels are consistent
       count(*)                               AS segments,
       sum(distance_m)                        AS dist_m,
       sum(duration_sec)                      AS dur_s
FROM l GROUP BY unique_trip_id, leg_no;
CREATE INDEX ON legs (unique_trip_id, leg_no);
ANALYZE legs;

-- Q5a. Legs whose segments carry more than one mode label (labelling check).
SELECT count(*) AS legs, count(*) FILTER (WHERE leg_mode LIKE '%/%') AS mixed_mode_legs FROM legs;

-- Q5b. The 30 most common leg sequences.
WITH t AS (
  SELECT g.unique_trip_id,
         string_agg(g.leg_mode, ' > ' ORDER BY g.leg_no) AS sequence,
         count(*) AS n_legs
  FROM legs g GROUP BY g.unique_trip_id
)
SELECT t.sequence, t.n_legs,
       count(*)                                                         AS trips,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2)               AS pct,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY b.total_distance_m)::numeric / 1000, 2) AS median_km,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY b.elapsed_time_sec)::numeric / 60, 1)   AS median_min,
       round(100.0 * avg((b.trip_pair_type = 'inter')::int), 1)         AS pct_inter
FROM t JOIN base_trips b USING (unique_trip_id)
GROUP BY t.sequence, t.n_legs
ORDER BY trips DESC
LIMIT 30;

-- Q5c. Leg length, duration and speed by mode and position, multi-leg trips only.
--      position: first / middle / last leg of the trip.
--      Percentiles in each array: p10, p50, p90.
WITH p AS (
  SELECT g.*,
         CASE WHEN g.leg_no = min(g.leg_no) OVER w THEN 'first'
              WHEN g.leg_no = max(g.leg_no) OVER w THEN 'last'
              ELSE 'middle' END AS position,
         count(*) OVER w AS n_legs
  FROM legs g
  WINDOW w AS (PARTITION BY g.unique_trip_id)
)
SELECT leg_mode, position,
       count(*)                                                                         AS legs,
       percentile_cont(ARRAY[.1,.5,.9]) WITHIN GROUP (ORDER BY dist_m)                  AS dist_m,
       percentile_cont(ARRAY[.1,.5,.9]) WITHIN GROUP (ORDER BY dur_s / 60.0)            AS dur_min,
       percentile_cont(ARRAY[.1,.5,.9]) WITHIN GROUP (ORDER BY dist_m / NULLIF(dur_s, 0) * 3.6) AS speed_kmh
FROM p
WHERE n_legs > 1
GROUP BY leg_mode, position
HAVING count(*) >= 50
ORDER BY leg_mode, position;
