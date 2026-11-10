-- TLP Phase 2, step 1: crosswalk coverage of the April 2024 vendor links (job 080). Aggregates only.
-- Run on the Mac mini: psql -d geometis -f crosswalk_coverage.sql
\timing on
CREATE TEMP TABLE xw AS
  SELECT osm_way_id, bool_or(layer='vehicular') veh, bool_or(layer='pedestrian') ped, count(DISTINCT segment_urn) n_urn,
         max(osm_version) v
  FROM gkg.osm_crosswalk WHERE geofence_id = 'us-ca-contra-costa-5' GROUP BY 1;
CREATE INDEX ON xw (osm_way_id); ANALYZE xw;
CREATE TEMP TABLE l AS
  SELECT l.unique_trip_id, coalesce(l.travel_mode,'(none)') mode, l.distance_m, l.osm_way_id, l.osm_way_version,
         x.osm_way_id IS NOT NULL hit, x.veh, x.ped, x.v xv
  FROM base_trip_links l LEFT JOIN xw x USING (osm_way_id)
  WHERE l.unique_trip_id LIKE '202404%';
\echo '--- Links and distance by mode: share with a way id, share resolved through the crosswalk'
SELECT mode, count(*) links, round(sum(distance_m)/1000) km,
  round(avg((osm_way_id IS NOT NULL)::int)::numeric,3) has_way,
  round(avg(hit::int)::numeric,3) link_share_resolved,
  round((sum(distance_m) FILTER (WHERE hit) / nullif(sum(distance_m) FILTER (WHERE osm_way_id IS NOT NULL),0))::numeric,3) dist_share_resolved_of_way_links,
  round(avg((hit AND veh)::int)::numeric,3) to_vehicular, round(avg((hit AND ped AND NOT veh)::int)::numeric,3) to_pedestrian_only
FROM l GROUP BY 1 ORDER BY 2 DESC;
\echo '--- Version agreement where resolved (vendor 2024 way version vs version in the 2026 crosswalk)'
SELECT round(avg((osm_way_version = xv)::int)::numeric,3) same_version, round(avg((osm_way_version < xv)::int)::numeric,3) vendor_older,
       round(avg((osm_way_version > xv)::int)::numeric,3) vendor_newer FROM l WHERE hit AND osm_way_version IS NOT NULL AND xv IS NOT NULL;
\echo '--- Trips: share whose way-bearing links all resolve, by trip mode'
SELECT t.travel_mode, count(*) trips, round(avg(all_hit::int)::numeric,3) all_resolved, round(avg(share)::numeric,3) mean_dist_share
FROM (SELECT unique_trip_id, bool_and(hit) all_hit,
             sum(distance_m) FILTER (WHERE hit)/nullif(sum(distance_m),0) share
      FROM l WHERE osm_way_id IS NOT NULL GROUP BY 1) s JOIN base_trips t USING (unique_trip_id)
GROUP BY 1 HAVING count(*) >= 100 ORDER BY 2 DESC LIMIT 12;
\echo '--- Unresolved way ids: how many distinct, and how much distance they carry'
SELECT count(DISTINCT osm_way_id) distinct_unresolved_ways, round(sum(distance_m)/1000) km FROM l WHERE osm_way_id IS NOT NULL AND NOT hit;
