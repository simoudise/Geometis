-- TLP Phase 2, step 2: entry and exit positions of vendor links on the graph, on a 1 per cent sample of April 2024
-- trips (chosen by a hash of the trip id). Runs on the Mac mini; returns aggregates only.
--
-- Method. For each OSM way in the sample, the crosswalk gives the graph pieces (road, pedestrian or rail URNs) that
-- carry it. Their geometries are merged into one line per way. Each vendor link's start and end coordinates are
-- projected onto that line: the projection distance says how far the vendor's point lies from the graph, and the
-- distance along the line between the two projections is the link's span on the graph, compared with the vendor's
-- distance_m. A way whose pieces do not merge into a single line (a loop or a gap) is counted and skipped.
\timing on
SET work_mem = '256MB';
CREATE TEMP TABLE s AS
  SELECT l.unique_trip_id, l.link_seq, coalesce(l.travel_mode, '(none)') mode, l.distance_m, l.osm_way_id,
         ST_SetSRID(ST_MakePoint(l.origin_long, l.origin_lat), 4326) o,
         ST_SetSRID(ST_MakePoint(l.destination_long, l.destination_lat), 4326) d
  FROM base_trip_links l
  WHERE l.unique_trip_id LIKE '202404%' AND l.osm_way_id IS NOT NULL
    AND abs(hashtext(l.unique_trip_id)) % 100 = 0;
CREATE TEMP TABLE w AS
  SELECT x.osm_way_id, ST_LineMerge(ST_Union(g.geom)) geom, count(*) pieces
  FROM (SELECT DISTINCT osm_way_id FROM s) q
  JOIN gkg.osm_crosswalk x USING (osm_way_id)
  JOIN LATERAL (SELECT geom FROM gkg.road_segment r WHERE x.layer = 'vehicular' AND r.geofence_id = x.geofence_id AND r.urn = x.segment_urn
                UNION ALL SELECT geom FROM gkg.pedestrian_edge p WHERE x.layer = 'pedestrian' AND p.geofence_id = x.geofence_id AND p.urn = x.segment_urn
                UNION ALL SELECT geom FROM gkg.rail_segment t WHERE x.layer = 'rail' AND t.geofence_id = x.geofence_id AND t.urn = x.segment_urn) g ON true
  WHERE x.geofence_id = 'us-ca-contra-costa-5'
  GROUP BY 1;
CREATE INDEX ON w (osm_way_id); ANALYZE w;
\echo '--- Ways in the sample: share whose graph pieces merge into one line'
SELECT count(*) ways, round(avg((ST_GeometryType(geom) = 'ST_LineString')::int)::numeric, 3) single_line FROM w;
CREATE TEMP TABLE p AS
  SELECT s.mode, s.distance_m,
         ST_Distance(s.o::geography, ST_ClosestPoint(w.geom, s.o)::geography) o_off_m,
         ST_Distance(s.d::geography, ST_ClosestPoint(w.geom, s.d)::geography) d_off_m,
         abs(ST_LineLocatePoint(w.geom, s.d) - ST_LineLocatePoint(w.geom, s.o)) * ST_Length(w.geom::geography) span_m
  FROM s JOIN w USING (osm_way_id)
  WHERE ST_GeometryType(w.geom) = 'ST_LineString' AND s.o IS NOT NULL AND s.d IS NOT NULL;
\echo '--- Links in the sample, by mode: distance of the vendor points from the graph, and span against vendor distance'
SELECT mode, count(*) links,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY greatest(o_off_m, d_off_m))::numeric, 1) median_max_offset_m,
  round(avg((greatest(o_off_m, d_off_m) <= 15)::int)::numeric, 3) both_ends_within_15m,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY span_m / nullif(distance_m, 0))::numeric, 3) median_span_ratio,
  round(avg((abs(span_m - distance_m) <= greatest(10, 0.1 * distance_m))::int)::numeric, 3) span_within_10pct_or_10m
FROM p GROUP BY 1 HAVING count(*) >= 50 ORDER BY 2 DESC;
