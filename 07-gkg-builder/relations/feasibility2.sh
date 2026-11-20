#!/bin/bash
# GKG full build, Step 2, second sample job: families that need a source not yet loaded or a different method.
# Runs on the Mac mini through the job runner. Writes timings and counts only; drops its scratch schema.
set -o pipefail
P="/opt/homebrew/opt/postgresql@17/bin/psql -d geometis -X -A -F | -v ON_ERROR_STOP=1"
OUT=~/Geometis-mini/work/gkg-full/feas2; mkdir -p $OUT; cd $OUT
PBF=~/geometis-data/osrm/norcal.osm.pbf
$P -c "DROP SCHEMA IF EXISTS gkg_feas2 CASCADE; CREATE SCHEMA gkg_feas2"
for G in us-ca-contra-costa-5 us-ca-san-francisco; do
  BB=$($P -t -c "select concat_ws(' ', ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent)) from gkg.geofence where geofence_id='$G'")
  T=${G//-/_}
  for L in multipolygons lines points; do
    s=$(date +%s)
    /opt/homebrew/bin/ogr2ogr -f PostgreSQL PG:dbname=geometis "$PBF" $L -spat $BB -nln gkg_feas2.${L}_$T \
      -t_srs EPSG:3310 -lco GEOMETRY_NAME=geom -nlt PROMOTE_TO_MULTI -overwrite \
      --config OSM_USE_CUSTOM_INDEXING NO --config OGR_INTERLEAVED_READING YES 2>&1 | tail -2
    echo "osm_load $G $L seconds $(( $(date +%s) - s )) rows $($P -t -c "select count(*) from gkg_feas2.${L}_$T")"
  done
  $P -c "select '$G' g, count(*) filter (where leisure in ('park','garden','playground','recreation_ground','nature_reserve','dog_park')) parks,
          count(*) filter (where natural in ('wood','scrub','wetland','grassland','heath')) natural_areas,
          count(*) filter (where amenity='parking') parking,
          count(*) filter (where amenity='parking' and other_tags like '%\"hgv\"%') truck_parking,
          count(*) filter (where place in ('neighbourhood','quarter','suburb')) named_districts_poly from gkg_feas2.multipolygons_$T"
  $P -c "select '$G' g, count(*) filter (where place in ('neighbourhood','quarter','suburb')) named_district_points,
          string_agg(name, '; ') filter (where place in ('neighbourhood','quarter') and name ~* 'district|theat|shopping|downtown') district_names
          from gkg_feas2.points_$T"
  $P -c "select '$G' g, count(*) filter (where other_tags ~ '\"(hgv|maxweight|maxheight|maxlength)\"') truck_tags,
          count(*) filter (where other_tags ~ '\"cycleway(:left|:right|:both)?\"=>\"(lane|track)\"') bike_lane_tags,
          count(*) filter (where other_tags ~ '\"sidewalk\"=>\"(both|left|right|yes)\"') sidewalk_tags,
          count(*) filter (where other_tags ~ '\"layer\"') layer_tags from gkg_feas2.lines_$T where highway is not null"
  # Park-relation timing: roads within 15 m of a park boundary (bordersCommonSpace) and pedestrian edges in parks.
  s=$(date +%s)
  $P -c "create unlogged table gkg_feas2.park_$T as select osm_id, geom from gkg_feas2.multipolygons_$T
         where leisure in ('park','garden','playground','recreation_ground','nature_reserve','dog_park');
         create index on gkg_feas2.park_$T using gist(geom);
         select '$G' g, (select count(*) from gkg.road_segment r join gkg_feas2.park_$T p on r.geofence_id='$G' and
            ST_DWithin(ST_Transform(r.geom,3310), ST_Boundary(p.geom), 15)) borders_common_space,
           (select count(*) from gkg.pedestrian_edge e join gkg_feas2.park_$T p on e.geofence_id='$G' and
            ST_Intersects(ST_Transform(e.geom,3310), p.geom)) path_through_common_space"
  echo "park_relations $G seconds $(( $(date +%s) - s ))"
  # onSameBlock: polygonize street centerlines inside one 1 km tile at the core centroid; count building pairs per block.
  s=$(date +%s)
  $P -c "with c as (select ST_Transform(ST_Centroid(core),3310) p from gkg.geofence where geofence_id='$G'),
         tile as (select ST_Expand(p,500) t from c),
         streets as (select ST_Intersection(ST_Transform(r.geom,3310), t) g from gkg.road_segment r, tile
                     where r.geofence_id='$G' and r.road_classification not in ('service','track','motorway')
                     and ST_Intersects(ST_Transform(r.geom,3310), t)),
         blocks as (select (ST_Dump(ST_Polygonize(g))).geom b from streets),
         b2 as (select row_number() over () id, b from blocks),
         inb as (select b2.id, count(*) n from b2 join gkg.building bl on bl.geofence_id='$G'
                 and ST_Contains(b2.b, ST_PointOnSurface(ST_Transform(bl.geom,3310))) group by 1)
         select '$G' g, (select count(*) from b2) blocks_in_tile, sum(n) buildings_in_blocks, sum(n*(n-1)/2) building_pairs_same_block from inb"
  echo "on_same_block_tile $G seconds $(( $(date +%s) - s ))"
done
$P -c "select geofence_id, count(*) pairs from (select a.geofence_id from gkg.place_building a join gkg.place_building b
       on a.geofence_id=b.geofence_id and a.building_urn=b.building_urn and a.place_urn<b.place_urn) z group by 1"
# CCRS to TIMS join check for reo:incidentRoadSurface and reo:incidentWeatherCondition (counts only).
head -1 ~/geometis-data/ccrs/crashes_2024.csv | tr ',' '\n' | head -8
$P -c "select count(*) tims_2024, min(case_id), max(length(case_id)) from gkg.tims_crash where accident_year=2024"
~/geometis-venv/bin/python - <<'PY'
import duckdb
c = duckdb.connect()
cols = [r[0] for r in c.execute("describe select * from read_csv_auto('~/geometis-data/ccrs/crashes_2024.csv', sample_size=20000)").fetchall()]
idc = [x for x in cols if 'id' in x.lower()][:6]
print("ccrs id-like columns:", idc)
import subprocess
t = subprocess.run(["/opt/homebrew/opt/postgresql@17/bin/psql", "-d", "geometis", "-X", "-A", "-t", "-c",
                    "select case_id from gkg.tims_crash where accident_year=2024"], capture_output=True, text=True).stdout.split()
c.execute("create table t(case_id varchar)"); c.executemany("insert into t values (?)", [[x] for x in t])
for col in idc:
    n = c.execute(f'select count(*) from t where case_id in (select cast("{col}" as varchar) from read_csv_auto(\'~/geometis-data/ccrs/crashes_2024.csv\', sample_size=20000))').fetchone()[0]
    print("tims 2024 case ids matched by CCRS column", col, ":", n, "of", len(t))
PY
$P -c "DROP SCHEMA gkg_feas2 CASCADE"
df -h /System/Volumes/Data | tail -1
