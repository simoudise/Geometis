"""Stage 5, speed limits: one speed limit in mph for every vehicular segment, with the source of the value.

v19 Stage 5 asks for speed analytics from modeled defaults only, because the trip corpus's segment timing is
allocated, not measured (F19). This step supplies the posted-speed layer those defaults start from.

Order of sources, first match wins:
  1. posted     Overture's unconditional maximum speed (Stage 1 column speed_limit_value), converted to mph.
                Overture builds this field from OpenStreetMap maxspeed tags. A check on 6 November 2026 matched
                OSM maxspeed through the crosswalk and found no segment where OSM had a value and Overture did
                not, so OSM is not a separate source here.
  2. statutory  California Vehicle Code prima facie limits: 25 mph on residential and living streets
                (22352(a)(2), business or residence district) and 15 mph in alleys (22352(a)(1)(C)).
                The residence-district test is not checked segment by segment; the class stands in for it.
  3. class_median  The median posted value of the same road class inside the same geofence, when at least
                MIN_POSTED segments of that class carry a posted value.
  4. none       No value. Service roads other than alleys, and classes with too few posted values, stay here.
"""
import json

from . import config
from .db import connect

MIN_POSTED = 30
KMH_PER_MPH = 1.609344


def run(geofence_id):
    sql = """
    ALTER TABLE gkg.road_segment ADD COLUMN IF NOT EXISTS speed_limit_mph double precision,
                                 ADD COLUMN IF NOT EXISTS speed_limit_source text;
    UPDATE gkg.road_segment SET speed_limit_mph = NULL, speed_limit_source = NULL WHERE geofence_id = %(g)s;

    UPDATE gkg.road_segment SET speed_limit_source = 'posted',
           speed_limit_mph = CASE WHEN speed_limit_unit = 'km/h' THEN round((speed_limit_value / %(k)s)::numeric, 1)
                                  ELSE speed_limit_value END
     WHERE geofence_id = %(g)s AND speed_limit_value IS NOT NULL;

    UPDATE gkg.road_segment SET speed_limit_source = 'statutory',
           speed_limit_mph = CASE WHEN subclass = 'alley' THEN 15 ELSE 25 END
     WHERE geofence_id = %(g)s AND speed_limit_source IS NULL
       AND (road_classification IN ('residential', 'living_street') OR subclass = 'alley');

    WITH med AS (
        SELECT road_classification cls, percentile_disc(0.5) WITHIN GROUP (ORDER BY speed_limit_mph) mph
          FROM gkg.road_segment
         WHERE geofence_id = %(g)s AND speed_limit_source = 'posted' AND road_classification <> 'service'
         GROUP BY 1 HAVING count(*) >= %(n)s)
    UPDATE gkg.road_segment r SET speed_limit_source = 'class_median', speed_limit_mph = med.mph
      FROM med WHERE r.geofence_id = %(g)s AND r.speed_limit_source IS NULL AND r.road_classification = med.cls;

    UPDATE gkg.road_segment SET speed_limit_source = 'none'
     WHERE geofence_id = %(g)s AND speed_limit_source IS NULL;
    """
    with connect() as conn:
        # psycopg sends parameterized SQL one statement at a time.
        for stmt in (x.strip() for x in sql.split(";")):
            if stmt:
                conn.execute(stmt, {"g": geofence_id, "k": KMH_PER_MPH, "n": MIN_POSTED} if "%(" in stmt else None)
        rows = conn.execute(
            "SELECT coalesce(road_classification, ''), speed_limit_source, count(*), round(sum(length_m)::numeric / 1000, 1), "
            "percentile_disc(0.5) WITHIN GROUP (ORDER BY speed_limit_mph) "
            "FROM gkg.road_segment WHERE geofence_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (geofence_id,)).fetchall()
        total = conn.execute(
            "SELECT speed_limit_source, round((sum(length_m) / sum(sum(length_m)) OVER ())::numeric, 3) "
            "FROM gkg.road_segment WHERE geofence_id = %s GROUP BY 1 ORDER BY 1", (geofence_id,)).fetchall()
        out = {"min_posted_for_class_median": MIN_POSTED,
               "share_of_length_by_source": {s: float(v) for s, v in total},
               "by_class": [{"class": c, "source": s, "segments": n, "km": float(km),
                             "median_mph": None if m is None else float(m)} for c, s, n, km, m in rows]}
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions, stats, finished, status) "
            "VALUES (%s, 'stage5-speed', %s, %s, %s, now(), 'loaded') RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION, json.dumps({"overture": config.OVERTURE_RELEASE}),
             json.dumps(out))).fetchone()[0]
        conn.commit()
    return build_id, out
