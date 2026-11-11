"""Knowledge Builder Stage 3, buildings part: Overture building footprints inside the extent, and the link from each
place to the footprint that contains it.

TLP Stage 2 attribution (v19 section 10.3.2) scores candidate places on "footprint containment", and the Phase 2 test
of candidate claim 2 needs footprints for two of its reference sets: trip ends inside a footprint that holds a single
place, and home anchors in residential buildings. Overture places are points, so footprints come from the Overture
buildings theme. Each building keeps its GERS id, Overture subtype and class (residential, commercial, education ...),
height and floor count. URNs are minted from the GERS id and the release, like other Overture-derived entities; they
are not yet in the URN registry (README open item).
"""
import json
import uuid

import duckdb

from . import config
from .db import connect
from .geofence import fetch

BUILDINGS_BASE = f"s3://overturemaps-us-west-2/release/{config.OVERTURE_RELEASE}/theme=buildings/type=building"
URN_NS = uuid.UUID("6f1c2a5e-3b7d-4e8a-9c41-0d2b7e5f9a10")

SCHEMA = """
CREATE TABLE IF NOT EXISTS gkg.building (
    geofence_id text NOT NULL, urn text NOT NULL, gers_id text NOT NULL, subtype text, class text,
    height double precision, num_floors integer, area_m2 double precision, in_core boolean NOT NULL,
    geom geometry(MultiPolygon, 4326) NOT NULL, build_id integer NOT NULL, PRIMARY KEY (geofence_id, urn));
CREATE INDEX IF NOT EXISTS building_geom ON gkg.building USING gist (geom);
CREATE TABLE IF NOT EXISTS gkg.place_building (
    geofence_id text NOT NULL, place_urn text NOT NULL, building_urn text NOT NULL, build_id integer NOT NULL,
    PRIMARY KEY (geofence_id, place_urn));
"""


def extract(geofence_id, extent):
    out = config.DATA_ROOT / "overture" / config.OVERTURE_RELEASE / geofence_id
    out.mkdir(parents=True, exist_ok=True)
    path = out / "building.parquet"
    if path.exists():
        return path
    xmin, ymin, xmax, ymax = extent.bounds
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    tmp = out / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con.execute(f"SET memory_limit='3GB'; SET threads=4; SET preserve_insertion_order=false; SET temp_directory='{tmp}'")
    con.execute(f"""COPY (
        SELECT id, subtype, class, height, num_floors, ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{BUILDINGS_BASE}/*', hive_partitioning=1)
        WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}
    ) TO '{path}.part' (FORMAT parquet)""")
    (out / "building.parquet.part").rename(path)
    return path


def run(geofence_id):
    core, extent, rec = fetch(geofence_id)
    path = extract(geofence_id, extent)
    print("overture buildings extract ready", flush=True)
    with connect() as conn:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
            "VALUES (%s, 'stage3-buildings', %s, %s) RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION, json.dumps({"overture": config.OVERTURE_RELEASE}))).fetchone()[0]
        conn.execute("DELETE FROM gkg.building WHERE geofence_id = %s", (geofence_id,))
        conn.execute("DELETE FROM gkg.place_building WHERE geofence_id = %s", (geofence_id,))
        conn.execute("CREATE TEMP TABLE _b (gers_id text, subtype text, class text, height double precision, "
                     "num_floors integer, wkb bytea) ON COMMIT DROP")
        con = duckdb.connect()
        res = con.execute(f"SELECT id, subtype, class, height, num_floors, wkb FROM read_parquet('{path}')")
        n = 0
        with conn.cursor().copy("COPY _b FROM STDIN") as cp:
            while True:
                rows = res.fetchmany(50000)
                if not rows:
                    break
                for r in rows:
                    cp.write_row([r[0], r[1], r[2], r[3], None if r[4] is None else int(r[4]), bytes(r[5])])
                    n += 1
        conn.execute(
            """INSERT INTO gkg.building
               SELECT %(g)s, 'urn:urban-kg:Building:overture:' || md5(%(ns)s || b.gers_id || '|' || %(rel)s)::uuid,
                      b.gers_id, b.subtype, b.class, b.height, b.num_floors,
                      ST_Area(gm::geography), ST_Intersects(gm, g.core), ST_Multi(gm), %(b)s
               FROM _b b CROSS JOIN LATERAL (SELECT ST_CollectionExtract(ST_MakeValid(ST_GeomFromWKB(b.wkb, 4326)), 3) gm) x
               JOIN gkg.geofence g ON g.geofence_id = %(g)s
               WHERE ST_Intersects(gm, g.extent) AND NOT ST_IsEmpty(gm)""",
            {"g": geofence_id, "ns": str(URN_NS) + "|", "rel": config.OVERTURE_RELEASE, "b": build_id})
        # A place belongs to the smallest footprint that contains it (nested footprints are rare but exist).
        conn.execute(
            """INSERT INTO gkg.place_building
               SELECT DISTINCT ON (p.urn) %(g)s, p.urn, b.urn, %(b)s
               FROM gkg.place p JOIN gkg.building b ON b.geofence_id = %(g)s AND ST_Contains(b.geom, p.geom)
               WHERE p.geofence_id = %(g)s ORDER BY p.urn, b.area_m2""", {"g": geofence_id, "b": build_id})
        q = lambda s: conn.execute(s, {"g": geofence_id}).fetchall()
        stats = {
            "source_rows": n,
            "buildings": q("SELECT count(*) FROM gkg.building WHERE geofence_id = %(g)s")[0][0],
            "buildings_in_core": q("SELECT count(*) FROM gkg.building WHERE geofence_id = %(g)s AND in_core")[0][0],
            "by_subtype": dict(q("SELECT coalesce(subtype, '(none)'), count(*) FROM gkg.building WHERE geofence_id = %(g)s "
                                 "GROUP BY 1 ORDER BY 2 DESC")),
            "places": q("SELECT count(*) FROM gkg.place WHERE geofence_id = %(g)s")[0][0],
            "places_in_a_building": q("SELECT count(*) FROM gkg.place_building WHERE geofence_id = %(g)s")[0][0],
            "buildings_by_place_count": dict(q(
                """SELECT CASE WHEN n >= 5 THEN '5+' ELSE n::text END, count(*) FROM (
                     SELECT b.urn, count(pb.place_urn) n FROM gkg.building b LEFT JOIN gkg.place_building pb
                       ON pb.geofence_id = b.geofence_id AND pb.building_urn = b.urn
                     WHERE b.geofence_id = %(g)s AND b.in_core GROUP BY 1) x GROUP BY 1 ORDER BY 1""")),
        }
        conn.execute("UPDATE gkg.build SET stats = %s, finished = now(), status = 'loaded' WHERE build_id = %s",
                     (json.dumps(stats), build_id))
        conn.commit()
    return build_id, stats
