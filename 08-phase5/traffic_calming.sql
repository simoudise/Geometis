-- Phase 5: SFMTA traffic calming devices installed 2018-2022, placed on San Francisco road segments, with injury crashes
-- 36 months before and after installation, grouped by measure. Input table p5.tc loaded by ogr2ogr from SFMTA's layer.
-- Aggregates only (public crash data).
\timing on
CREATE TEMP TABLE d AS
  SELECT objectid_1 id, tc_measure measure, streetname, install_yr::int yr,
         coalesce(nullif(regexp_replace(install_mo, '[^0-9]', '', 'g'), '')::int,
                  CASE upper(left(install_mo, 3)) WHEN 'JAN' THEN 1 WHEN 'FEB' THEN 2 WHEN 'MAR' THEN 3 WHEN 'APR' THEN 4
                    WHEN 'MAY' THEN 5 WHEN 'JUN' THEN 6 WHEN 'JUL' THEN 7 WHEN 'AUG' THEN 8 WHEN 'SEP' THEN 9 WHEN 'OCT' THEN 10
                    WHEN 'NOV' THEN 11 WHEN 'DEC' THEN 12 END) mo,
         ST_LineInterpolatePoint(ST_LineMerge(wkb_geometry), 0.5) p
  FROM p5.tc WHERE install_yr ~ '^20(18|19|20|21|22)$' AND coalesce(current_st, '') = 'Complete';
\echo '--- devices 2018-2022 marked Complete, and how many have an install month'
SELECT count(*), count(mo) with_month FROM d;
CREATE TEMP TABLE ds AS
  SELECT d.*, s.urn, s.dist FROM d
  CROSS JOIN LATERAL (SELECT r.urn, ST_Distance(r.geom::geography, d.p::geography) dist FROM gkg.road_segment r
                      WHERE r.geofence_id = 'us-ca-san-francisco' AND r.geom && ST_Expand(d.p, 0.001)
                        AND gkg.road_key(regexp_replace(coalesce(r.name, ''), '^[Tt]he ', '')) = gkg.road_key(regexp_replace(d.streetname, '^[Tt]he ', ''))
                      ORDER BY r.geom <-> d.p LIMIT 1) s
  WHERE d.mo IS NOT NULL AND s.dist <= 50;
\echo '--- devices placed on a segment of the named street within 50 m'
SELECT count(*), count(DISTINCT urn) segments FROM ds;
-- One row per treated segment: the earliest installation and the set of measures.
CREATE TEMP TABLE seg AS
  SELECT urn, min(make_date(yr, mo, 1)) c, string_agg(DISTINCT measure, '; ') measures,
         CASE WHEN bool_or(measure ILIKE '%cushion%') THEN 'speed cushion' WHEN bool_or(measure ILIKE '%hump%') THEN 'speed hump'
              ELSE 'raised crosswalk or speed table' END grp
  FROM ds GROUP BY urn;
CREATE TEMP TABLE city AS SELECT c.collision_date FROM gkg.crash_attachment a JOIN gkg.tims_crash c USING (case_id)
  WHERE a.geofence_id = 'us-ca-san-francisco';
\echo '--- injury crashes on treated segments (segment crashes only, not intersection crashes), 36 months before and after'
SELECT grp, count(*) segments, sum(b) before, sum(af) after, round(sum(e)) expected_after_city_trend,
       round((sum(af) / nullif(sum(e), 0))::numeric, 3) ratio_to_trend
FROM (SELECT s.grp, s.c,
        (SELECT count(*) FROM gkg.crash_attachment a JOIN gkg.tims_crash x USING (case_id)
          WHERE a.geofence_id = 'us-ca-san-francisco' AND a.segment_urn = s.urn AND a.node_urn IS NULL
            AND x.collision_date >= s.c - interval '36 months' AND x.collision_date < s.c) b,
        (SELECT count(*) FROM gkg.crash_attachment a JOIN gkg.tims_crash x USING (case_id)
          WHERE a.geofence_id = 'us-ca-san-francisco' AND a.segment_urn = s.urn AND a.node_urn IS NULL
            AND x.collision_date >= s.c + interval '1 month' AND x.collision_date < s.c + interval '37 months') af,
        (SELECT count(*) FROM gkg.crash_attachment a JOIN gkg.tims_crash x USING (case_id)
          WHERE a.geofence_id = 'us-ca-san-francisco' AND a.segment_urn = s.urn AND a.node_urn IS NULL
            AND x.collision_date >= s.c - interval '36 months' AND x.collision_date < s.c)
        * (SELECT count(*) FROM city WHERE collision_date >= s.c + interval '1 month' AND collision_date < s.c + interval '37 months')::float
        / (SELECT count(*) FROM city WHERE collision_date >= s.c - interval '36 months' AND collision_date < s.c) e
      FROM seg s) q
GROUP BY ROLLUP (grp) ORDER BY grp NULLS LAST;
