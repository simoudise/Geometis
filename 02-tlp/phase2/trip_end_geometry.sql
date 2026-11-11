-- TLP Phase 2: where April 2024 trip destinations lie (job 095). 5 per cent sample; aggregates only.
CREATE TEMP TABLE e AS
  SELECT t.travel_mode, ST_SetSRID(ST_MakePoint(t.destination_long, t.destination_lat), 4326) p
  FROM base_trips t WHERE t.unique_trip_id LIKE '202404%' AND abs(hashtext(t.unique_trip_id)) % 20 = 0;
SELECT CASE WHEN travel_mode LIKE 'multimodal%' THEN 'multimodal' ELSE travel_mode END mode, count(*) n,
  round(avg((EXISTS (SELECT 1 FROM gkg.building b WHERE b.geofence_id='us-ca-contra-costa-5' AND ST_Contains(b.geom, e.p)))::int)::numeric,3) inside_footprint,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY r.d)::numeric,1) median_m_to_network,
  round(avg((r.d < 1)::int)::numeric,3) within_1m_of_network,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pl.d)::numeric,1) median_m_to_nearest_place
FROM e
CROSS JOIN LATERAL (SELECT min(ST_Distance(e.p::geography, x.geom::geography)) d FROM (
   (SELECT geom FROM gkg.road_segment WHERE geofence_id='us-ca-contra-costa-5' ORDER BY geom <-> e.p LIMIT 3)
   UNION ALL (SELECT geom FROM gkg.pedestrian_edge WHERE geofence_id='us-ca-contra-costa-5' ORDER BY geom <-> e.p LIMIT 3)) x) r
CROSS JOIN LATERAL (SELECT ST_Distance(e.p::geography, geom::geography) d FROM gkg.place WHERE geofence_id='us-ca-contra-costa-5' ORDER BY geom <-> e.p LIMIT 1) pl
GROUP BY 1 ORDER BY 2 DESC;
