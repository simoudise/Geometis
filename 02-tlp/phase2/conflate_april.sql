-- TLP Phase 2, step 3: conflate every April 2024 vendor link to graph URNs with entry and exit fractions.
-- Runs on the Mac mini only. Writes the Tier 3 table tlp.link_conflation (trip ids stay on the Mac mini) and prints
-- aggregate coverage only.
--
-- Method "way". The crosswalk gives, for each OSM way, the URN pieces that carry it and the fraction range of each piece
-- (seg_from_frac to seg_to_frac). Those portions are merged into one line per way (tlp.way_line). A link's start and end
-- points are located on that line; the span between them is split across the portions it overlaps, and each overlap is
-- mapped back to fractions on its URN, in the direction of travel. Used when both link ends lie within 15 m of the line.
-- Method "fallback". Links with no way id, an unresolved way, a way that does not merge into one line, or an end more
-- than 15 m away go to the nearest piece of the layer that fits the mode (road for driving and bus, pedestrian or road for
-- walking and cycling, rail for subway and rail), if both ends lie within 30 m of it. One URN per link.
-- Method "none". Everything else (and transitwait links, which have no extent).
\timing on
SET work_mem = '512MB';
CREATE SCHEMA IF NOT EXISTS tlp;
DROP TABLE IF EXISTS tlp.way_portion, tlp.way_line, tlp.link_conflation;

CREATE TABLE tlp.way_portion AS
  SELECT x.osm_way_id, x.layer, x.segment_urn AS urn, x.seg_from_frac AS f0, x.seg_to_frac AS f1,
         ST_LineSubstring(g.geom, x.seg_from_frac, x.seg_to_frac) AS geom
  FROM gkg.osm_crosswalk x
  JOIN LATERAL (SELECT geom FROM gkg.road_segment r WHERE x.layer = 'vehicular' AND r.geofence_id = x.geofence_id AND r.urn = x.segment_urn
                UNION ALL SELECT geom FROM gkg.pedestrian_edge p WHERE x.layer = 'pedestrian' AND p.geofence_id = x.geofence_id AND p.urn = x.segment_urn
                UNION ALL SELECT geom FROM gkg.rail_segment t WHERE x.layer = 'rail' AND t.geofence_id = x.geofence_id AND t.urn = x.segment_urn) g ON true
  WHERE x.geofence_id = 'us-ca-contra-costa-5' AND x.seg_to_frac > x.seg_from_frac;

CREATE TABLE tlp.way_line AS
  SELECT osm_way_id, ST_LineMerge(ST_Union(geom)) AS geom FROM tlp.way_portion GROUP BY 1;
DELETE FROM tlp.way_line WHERE ST_GeometryType(geom) <> 'ST_LineString';
CREATE UNIQUE INDEX ON tlp.way_line (osm_way_id);

-- Position of each portion along its way line, and whether the portion runs the same way as the line.
ALTER TABLE tlp.way_portion ADD COLUMN a double precision, ADD COLUMN b double precision;
UPDATE tlp.way_portion p SET a = ST_LineLocatePoint(w.geom, ST_StartPoint(p.geom)),
                             b = ST_LineLocatePoint(w.geom, ST_EndPoint(p.geom))
  FROM tlp.way_line w WHERE w.osm_way_id = p.osm_way_id;
DELETE FROM tlp.way_portion WHERE a IS NULL OR a = b;
CREATE INDEX ON tlp.way_portion (osm_way_id);
ANALYZE tlp.way_portion; ANALYZE tlp.way_line;

CREATE TABLE tlp.link_conflation (
    unique_trip_id text NOT NULL, link_seq int NOT NULL, part smallint NOT NULL, layer text, urn text,
    entry_frac double precision, exit_frac double precision, method text NOT NULL, max_offset_m double precision);

-- Located link ends on the way line.
CREATE TEMP TABLE loc AS
  SELECT l.unique_trip_id, l.link_seq, l.osm_way_id,
         ST_LineLocatePoint(w.geom, o) lo_o, ST_LineLocatePoint(w.geom, d) lo_d,
         greatest(ST_Distance(o::geography, ST_ClosestPoint(w.geom, o)::geography),
                  ST_Distance(d::geography, ST_ClosestPoint(w.geom, d)::geography)) off_m
  FROM (SELECT unique_trip_id, link_seq, osm_way_id,
               ST_SetSRID(ST_MakePoint(origin_long, origin_lat), 4326) o,
               ST_SetSRID(ST_MakePoint(destination_long, destination_lat), 4326) d
        FROM base_trip_links
        WHERE unique_trip_id LIKE '202404%' AND osm_way_id IS NOT NULL AND coalesce(travel_mode, '') <> 'transitwait'
          AND origin_lat IS NOT NULL AND destination_lat IS NOT NULL) l
  JOIN tlp.way_line w USING (osm_way_id);

INSERT INTO tlp.link_conflation
  SELECT unique_trip_id, link_seq,
         row_number() OVER (PARTITION BY unique_trip_id, link_seq ORDER BY CASE WHEN fwd THEN x0 ELSE -x0 END)::smallint,
         layer, urn,
         CASE WHEN fwd THEN fx0 ELSE fx1 END, CASE WHEN fwd THEN fx1 ELSE fx0 END, 'way', off_m
  FROM (
    SELECT q.*, p.layer, p.urn, x0, x1,
           -- position t along the portion in the line's direction, then the URN fraction
           p.f0 + (CASE WHEN p.b > p.a THEN (x0 - least(p.a, p.b)) / abs(p.b - p.a)
                        ELSE 1 - (x0 - least(p.a, p.b)) / abs(p.b - p.a) END) * (p.f1 - p.f0) fx0,
           p.f0 + (CASE WHEN p.b > p.a THEN (x1 - least(p.a, p.b)) / abs(p.b - p.a)
                        ELSE 1 - (x1 - least(p.a, p.b)) / abs(p.b - p.a) END) * (p.f1 - p.f0) fx1
    FROM (SELECT *, lo_d >= lo_o fwd, least(lo_o, lo_d) s0, greatest(lo_o, lo_d) s1 FROM loc WHERE off_m <= 15) q
    JOIN tlp.way_portion p ON p.osm_way_id = q.osm_way_id AND greatest(p.a, p.b) > q.s0 AND least(p.a, p.b) < q.s1
    CROSS JOIN LATERAL (SELECT greatest(least(p.a, p.b), q.s0) x0, least(greatest(p.a, p.b), q.s1) x1) c
  ) z;

-- Fallback for every other link with an extent.
CREATE TEMP TABLE fb AS
  SELECT l.unique_trip_id, l.link_seq, l.travel_mode,
         ST_SetSRID(ST_MakePoint(l.origin_long, l.origin_lat), 4326) o,
         ST_SetSRID(ST_MakePoint(l.destination_long, l.destination_lat), 4326) d
  FROM base_trip_links l
  WHERE l.unique_trip_id LIKE '202404%' AND coalesce(l.travel_mode, '') <> 'transitwait'
    AND l.origin_lat IS NOT NULL AND l.destination_lat IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM tlp.link_conflation c WHERE c.unique_trip_id = l.unique_trip_id AND c.link_seq = l.link_seq);
CREATE TEMP TABLE cand AS
  SELECT 'vehicular' layer, urn, geom FROM gkg.road_segment WHERE geofence_id = 'us-ca-contra-costa-5'
  UNION ALL SELECT 'pedestrian', urn, geom FROM gkg.pedestrian_edge WHERE geofence_id = 'us-ca-contra-costa-5'
  UNION ALL SELECT 'rail', urn, geom FROM gkg.rail_segment WHERE geofence_id = 'us-ca-contra-costa-5';
CREATE INDEX ON cand USING gist (geom); ANALYZE cand;
INSERT INTO tlp.link_conflation
  SELECT f.unique_trip_id, f.link_seq, 1, c.layer, c.urn, ST_LineLocatePoint(c.geom, f.o), ST_LineLocatePoint(c.geom, f.d),
         'fallback', greatest(ST_Distance(f.o::geography, c.geom::geography), ST_Distance(f.d::geography, c.geom::geography))
  FROM fb f
  CROSS JOIN LATERAL (
    SELECT * FROM cand c
    WHERE c.layer = ANY (CASE WHEN f.travel_mode IN ('transit_subway', 'transit_rail') THEN ARRAY['rail']
                              WHEN f.travel_mode IN ('walking', 'cycling', 'transit_walking') THEN ARRAY['pedestrian', 'vehicular']
                              ELSE ARRAY['vehicular'] END)
    ORDER BY c.geom <-> ST_LineInterpolatePoint(ST_MakeLine(f.o, f.d), 0.5) LIMIT 1) c
  WHERE ST_DWithin(f.o::geography, c.geom::geography, 30) AND ST_DWithin(f.d::geography, c.geom::geography, 30);
CREATE INDEX ON tlp.link_conflation (unique_trip_id, link_seq);
ANALYZE tlp.link_conflation;

\echo '--- Coverage of April 2024 links by mode (aggregates only)'
SELECT coalesce(l.travel_mode, '(none)') mode, count(*) links, round(sum(l.distance_m) / 1000) km,
       round(avg((m.method = 'way')::int)::numeric, 3) by_way,
       round(avg((m.method = 'fallback')::int)::numeric, 3) by_fallback,
       round(avg((m.method IS NULL)::int)::numeric, 3) unmatched,
       round((sum(l.distance_m) FILTER (WHERE m.method IS NOT NULL) / nullif(sum(l.distance_m), 0))::numeric, 3) distance_matched,
       round(avg(m.parts)::numeric, 2) urns_per_matched_link
FROM base_trip_links l
LEFT JOIN (SELECT unique_trip_id, link_seq, min(method) method, count(*) parts FROM tlp.link_conflation GROUP BY 1, 2) m
  USING (unique_trip_id, link_seq)
WHERE l.unique_trip_id LIKE '202404%'
GROUP BY 1 ORDER BY 2 DESC;
\echo '--- Fraction sanity: share of parts with fractions inside [0, 1]'
SELECT method, count(*) parts, round(avg((entry_frac BETWEEN -1e-9 AND 1 + 1e-9 AND exit_frac BETWEEN -1e-9 AND 1 + 1e-9)::int)::numeric, 4) in_range
FROM tlp.link_conflation GROUP BY 1;
