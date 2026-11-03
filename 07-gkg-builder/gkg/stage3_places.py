"""Knowledge Builder Stage 3, places part: Overture places inside the extent (v19 section 9.3, Stage 3).

Each place keeps its Overture GERS id as an attribute, its taxonomy, confidence and operating
status, and a UKO class assigned by rule: a place gets the UKO class whose name, written in
snake case, equals the place's Overture basic category or one of its taxonomy levels (most specific
first). Places that no rule maps stay unclassified for the LLM-assisted classifier that v19 names;
that classifier is not built yet. Foursquare OS Places and the GTFS part of Stage 3 come later.
"""
import json
import re
import uuid
from pathlib import Path

import duckdb
import shapely

from . import config
from .db import connect, copy_rows
from .geofence import fetch

PLACES_BASE = f"s3://overturemaps-us-west-2/release/{config.OVERTURE_RELEASE}/theme=places/type=place"
URN_NS = uuid.UUID("6f1c2a5e-3b7d-4e8a-9c41-0d2b7e5f9a10")
UKO_TTL = Path(__file__).resolve().parents[2] / "01-ontologies" / "uko_ontology_v15_5.ttl"


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def uko_classes(ttl_path):
    """UKO class local names, keyed by their snake-case form, with their direct parents."""
    s = Path(ttl_path).read_text()
    out = {}
    for c, body in re.findall(r"uko:(\w+)\s+(?:a|rdf:type)\s+owl:Class\s*;(.*?)\.\s*\n", s, re.S):
        out[snake(c)] = (c, re.findall(r"rdfs:subClassOf\s+uko:(\w+)", body))
    return out


CROSSWALK = Path(__file__).resolve().parents[1] / "mappings" / "overture_to_uko_v1.json"


def classify(basic, hierarchy, classes, xw):
    """Exact name match first (most specific level first), then the reviewed crosswalk."""
    hierarchy = hierarchy or []
    for cand in [basic] + list(reversed(hierarchy)):
        if cand and cand in classes:
            return classes[cand][0], f"name:{cand}"
    if len(hierarchy) > 1 and hierarchy[1] in xw["level2"]:
        c = xw["level2"][hierarchy[1]]
        return (c, f"crosswalk-level2:{hierarchy[1]}") if c else (None, f"excluded:{hierarchy[1]}")
    if hierarchy and hierarchy[0] in xw["top"]:
        c = xw["top"][hierarchy[0]]
        return (c, f"crosswalk-top:{hierarchy[0]}") if c else (None, f"excluded:{hierarchy[0]}")
    return None, None


def extract(geofence_id, extent):
    out = config.DATA_ROOT / "overture" / config.OVERTURE_RELEASE / geofence_id
    out.mkdir(parents=True, exist_ok=True)
    path = out / "place.parquet"
    if path.exists():
        return path
    xmin, ymin, xmax, ymax = extent.bounds
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    con.execute(f"SET memory_limit='3GB'; SET threads=4; SET preserve_insertion_order=false; "
                f"SET temp_directory='{out}'")
    con.execute(f"""COPY (
        SELECT id, names."primary" AS name, basic_category, taxonomy."primary" AS taxonomy_primary,
               taxonomy.hierarchy AS hierarchy, confidence, operating_status,
               brand.names."primary" AS brand, ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{PLACES_BASE}/*', hive_partitioning=1)
        WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}
    ) TO '{path}.part' (FORMAT parquet)""")
    Path(f"{path}.part").rename(path)
    return path


def run(geofence_id, ttl_path=UKO_TTL):
    core, extent, rec = fetch(geofence_id)
    path = extract(geofence_id, extent)
    classes = uko_classes(ttl_path)
    xw = json.loads(CROSSWALK.read_text())
    bad = [c for c in list(xw["level2"].values()) + list(xw["top"].values()) if c and snake(c) not in classes]
    if bad:
        raise ValueError(f"crosswalk names classes that UKO lacks: {bad}")
    con = duckdb.connect()
    res = con.execute(f"SELECT * FROM read_parquet('{path}')")
    cols = [d[0] for d in res.description]
    rows_in = [dict(zip(cols, r)) for r in res.fetchall()]
    shapely.prepare(extent)
    shapely.prepare(core)
    rows, mapped, by_class, unmapped = [], 0, {}, {}
    with connect() as conn:
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
            "VALUES (%s, 'stage3-places', %s, %s) RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION, json.dumps({"overture": config.OVERTURE_RELEASE,
                                                               "uko": "15.5.0"}))).fetchone()[0]
        conn.execute("DELETE FROM gkg.place WHERE geofence_id = %s", (geofence_id,))
        for p in rows_in:
            g = shapely.from_wkb(bytes(p["wkb"]))
            if g.geom_type != "Point":
                g = g.representative_point()
            if not extent.intersects(g):
                continue
            hierarchy = list(p["hierarchy"]) if p["hierarchy"] is not None else []
            cls, via = classify(p["basic_category"], hierarchy, classes, xw)
            if cls:
                mapped += 1
                by_class[cls] = by_class.get(cls, 0) + 1
            elif not (via or "").startswith("excluded"):
                key = p["basic_category"] or "(none)"
                unmapped[key] = unmapped.get(key, 0) + 1
            urn = f"urn:urban-kg:PointOfInterest:overture:{uuid.uuid5(URN_NS, 'place|' + p['id'])}"
            rows.append((geofence_id, urn, p["id"], p["name"], p["basic_category"], p["taxonomy_primary"],
                         json.dumps(hierarchy), p["confidence"], p["operating_status"], p["brand"], cls, via,
                         ("name" if via.startswith("name") else "crosswalk") if cls else None, bool(core.intersects(g)),
                         shapely.to_wkb(shapely.set_srid(g, 4326), hex=True, include_srid=True), build_id))
        copy_rows(conn, "gkg.place",
                  ["geofence_id", "urn", "gers_id", "name", "basic_category", "taxonomy_primary", "taxonomy_hierarchy",
                   "confidence", "operating_status", "brand", "uko_class", "uko_class_via", "classified_by",
                   "in_core", "geom", "build_id"], rows)
        top_unmapped = sorted(unmapped.items(), key=lambda kv: -kv[1])[:25]
        excluded = sum(1 for r in rows if r[11] and r[11].startswith("excluded"))
        stats = {"places": len(rows), "mapped_by_rule": mapped, "excluded_on_purpose": excluded,
                 "mapped_share": round(mapped / max(1, len(rows)), 4),
                 "classes_used": len(by_class), "top_classes": sorted(by_class.items(), key=lambda kv: -kv[1])[:20],
                 "top_unmapped_categories": top_unmapped}
        conn.execute("UPDATE gkg.build SET stats = %s, finished = now(), status = 'loaded' WHERE build_id = %s",
                     (json.dumps(stats), build_id))
        conn.commit()
    return build_id, stats
