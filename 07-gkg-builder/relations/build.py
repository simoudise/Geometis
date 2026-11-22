"""GKG full build, Step 3: entities, relations and provenance for every geofence.

python -m relations.build [STEP ...]      (from 07-gkg-builder/, on the Mac mini)

Steps run in the order of STEPS; give step names to run a subset (each step deletes and rewrites its own output,
so a failed step can be rerun alone). Approved design (Evangelos, Nov 20):
- gkg.entity numbers every entity (urn + geofence) and records its UKO class; gkg.entity_type adds asserted extra
  types (each rule documented in RULES_EXTRA_TYPES and the data dictionary).
- gkg.edge holds one row per edge: relation code, subject and object entity numbers, provenance code and an
  optional value (meters). Symmetric relations are stored once, with subject number < object number. For a pair
  of inverse properties only the property named in RELATIONS is stored; the inverse follows from it.
- gkg.distance_measurement holds uko:DistanceMeasurement rows (straight-line and walking distance) from places,
  stops and intersections to landmark buildings and districts within 2 km.
- gkg.provenance records source, method, versions and the crash flag; every edge points to one row.
- uko:veryNear is not stored separately: it is uko:near with value_m <= 50.
- Edges whose subject or object fails the property's rdfs:domain or rdfs:range (UKO 15.7 class hierarchy plus
  asserted extra types) are removed by the enforce step and counted in gkg.edge_rejected.
Reads no trip table. Writes counts, never rows, to the log.
"""
import json, os, subprocess, sys, time, uuid, zipfile, re, csv
from pathlib import Path

import numpy as np
import pandas as pd
from gkg import config

DSN = os.environ.get("GEOMETIS_PG_DSN", config.PG_DSN)
ROOT = Path(__file__).resolve().parents[1]
ONTO = ROOT.parent / "01-ontologies"
PUBLIC = Path.home() / "geometis-data/gkg/public/2026-11-20"
PBF = Path.home() / "geometis-data/osrm/norcal.osm.pbf"
TIGER = Path.home() / "geometis-data/gkg/tiger/2024"
GTFS_CACHE = config.DATA_ROOT / "gtfs" / "mobilitydatabase"
TIMS_DIR = Path.home() / "Geometis-mini/tims-incoming"
GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
URN_NS = uuid.UUID("6f1c2a5e-3b7d-4e8a-9c41-0d2b7e5f9a10")
CODE_VERSION = os.environ.get("GKG_CODE_VERSION", "gkg-full")
ONTO_VERSION = "UKO 15.7.0 / REO 1.7.0 (release 2026-11-22)"

LANDMARK = ["Museum", "Theater", "ConcertHall", "OperaHouse", "CityHall", "Courthouse", "Library",
            "GovernmentBuilding", "Stadium", "Arena"]
VULNERABLE = ["School", "ElementarySchool", "MiddleSchool", "HighSchool", "PrivateSchool", "Preschool",
              "SeniorCenter", "SeniorFacility", "NursingHome", "AssistedLivingFacility",
              "Hospital", "GeneralHospital", "ChildrensHospital"]

class _Lazy:
    def __getattr__(self, k):
        import psycopg
        global conn
        conn = psycopg.connect(DSN, autocommit=True, options="-c statement_timeout=0 -c work_mem=256MB "
                               "-c maintenance_work_mem=2GB -c max_parallel_workers_per_gather=4")
        return getattr(conn, k)


conn = _Lazy()
X = lambda sql, a=None: conn.execute(sql, a) if a else conn.execute(sql)
Q = lambda sql, a=None: (conn.execute(sql, a) if a else conn.execute(sql)).fetchall()
LOG = []


def log(**kw):
    kw["t"] = time.strftime("%H:%M:%S")
    LOG.append(kw)
    print(json.dumps(kw, default=str), flush=True)


def urn(kind, *parts):
    return f"urn:urban-kg:{kind}:gkgfull:{uuid.uuid5(URN_NS, '|'.join([kind] + [str(p) for p in parts]))}"


def copy(table, cols, rows):
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            n = 0
            for r in rows:
                cp.write_row(r)
                n += 1
    return n


# --------------------------------------------------------------------------- relation catalogue
# (curie, crash_derived, symmetric, note). Domain and range come from the ontology in step "catalogue".
RELATIONS = [
    ("uko:adjacentSegment", False, False, "intersection node to each road segment that ends at it"),
    ("uko:connectsTo", False, False, "segment A's end node is segment B's start node (digitized direction)"),
    ("uko:touches", False, True, "road segments that share an end node"),
    ("uko:withinCensusTract", False, False, "point (or midpoint, or building centroid) in tract"),
    ("uko:within", False, False, "building in city block; place in building (place_building)"),
    ("uko:overlaps", False, True, "district polygon overlaps census tract polygon (shared area >= 1 percent)"),
    ("uko:adjacentTo", False, True, "census tracts whose boundaries share a line"),
    ("uko:near", False, True, "places, stops, intersections within 200 m (value_m = meters); veryNear is value_m <= 50"),
    ("uko:crosses", False, False, "road segment crosses rail segment; crosswalk to the road segment nearest its midpoint, within 7 m and 30 degrees of perpendicular"),
    ("uko:crossesOver", False, False, "road segments whose lines cross with no shared node; bridge over non-bridge, or non-tunnel over tunnel"),
    ("uko:intersectsRoad", False, True, "segments of differently named roads that meet at a shared node"),
    ("uko:hasJurisdiction", False, False, "feature to its city (TIGER place), else its county"),
    ("uko:inNeighborhood", False, False, "feature in a San Francisco neighborhood (SF Find and Analysis Neighborhoods)"),
    ("uko:adjacentNeighborhood", False, True, "neighborhoods of the same scheme sharing a boundary"),
    ("uko:inSupervisorDistrict", False, False, "feature in a San Francisco supervisor district (2022)"),
    ("uko:sharesWallWith", False, True, "buildings sharing at least 1 m of boundary"),
    ("uko:sharesBuildingWith", False, True, "places linked to the same building (gkg.place_building)"),
    ("uko:insideMall", False, False, "place in the same building as a ShoppingMall place"),
    ("uko:continuesAs", False, False, "named road changes name at a node with a turn of 30 degrees or less"),
    ("uko:branchesFrom", False, False, "ramp (subclass link) whose start node lies on a non-ramp motorway, trunk or primary segment"),
    ("uko:mergesInto", False, False, "ramp whose end node lies on a non-ramp motorway, trunk or primary segment"),
    ("uko:feedsInto", False, False, "lower-class road meets higher-class road at a shared node (class order of decision B3)"),
    ("uko:parallelTo", False, True, "segments within 30 m, 15 degrees, running together at least 50 m"),
    ("uko:alongsideOf", False, False, "sidewalk edge to nearest road segment within 25 m at most 20 degrees apart"),
    ("uko:onNorthSideOf", False, False, "alongsideOf pair, sidewalk north of the road line"),
    ("uko:onSouthSideOf", False, False, "alongsideOf pair, sidewalk south of the road line"),
    ("uko:onEastSideOf", False, False, "alongsideOf pair, sidewalk east of the road line"),
    ("uko:onWestSideOf", False, False, "alongsideOf pair, sidewalk west of the road line"),
    ("uko:servesStop", False, False, "route to each stop it serves on the reference service day"),
    ("uko:parentStation", False, False, "GTFS parent_station"),
    ("uko:atStop", False, False, "stop time to its stop"),
    ("uko:hasStopTime", False, False, "trip to its stop times"),
    ("uko:hasTrip", False, False, "route to its trips on the reference service day"),
    ("uko:hasServiceCalendar", False, False, "trip to its GTFS service_id calendar"),
    ("uko:hasServiceException", False, False, "calendar to its calendar_dates.txt exceptions"),
    ("uko:gtfsOperatedBy", False, False, "route to agency"),
    ("uko:hasTransferTo", False, False, "transfers.txt pairs; feeds without transfers.txt: stops of different routes within 200 m"),
    ("uko:fareProductOfAgency", False, False, "GTFS Fares v1 fare_attributes row to its agency"),
    ("uko:hasServiceArea", False, False, "route to the area within 400 m of its stops"),
    ("uko:anchorStation", False, False, "Priority Development Area to each transit station inside it"),
    ("uko:connectsToTransit", False, False, "road segment to the stop it serves (nearest walkable segment within 50 m)"),
    ("uko:nearTransitStop", False, False, "building within 400 m of a stop (value_m)"),
    ("uko:nearestTransitStop", False, False, "place to its nearest boardable stop (value_m)"),
    ("uko:hasTransitAccess", False, False, "building centroid inside a stop's 800 m walkshed"),
    ("uko:walkshedOrigin", False, False, "walkshed to its stop"),
    ("uko:operatedBySystem", False, False, "Bay Wheels station to the Bay Wheels system"),
    ("uko:hasAccessPoint", False, False, "intersection node or pedestrian node to the access point joining them"),
    ("uko:accessibleBy", False, False, "building to nearest street segment within 30 m"),
    ("uko:frontageOn", False, False, "building to nearest street segment within 30 m"),
    ("uko:providesAccessTo", False, False, "street segment to each building whose nearest street it is (within 30 m)"),
    ("uko:servesAsMainAccess", False, False, "nearest street segment to each place (no address field loaded; decision B3 fallback)"),
    ("uko:accessibleByBikeLane", False, False, "building to nearest cycleway edge within 50 m"),
    ("uko:accessibleBySidewalk", False, False, "building to nearest sidewalk edge within 50 m"),
    ("uko:hasParking", False, False, "building to parking facilities within 100 m"),
    ("uko:adjacentToCommonSpace", False, False, "building within 5 m of a park or other common space polygon"),
    ("uko:bordersCommonSpace", False, False, "road segment within 15 m of a common space boundary"),
    ("uko:bordersNaturalArea", False, False, "common space polygon touching or within 5 m of a natural area polygon"),
    ("uko:crossesThroughCommonSpace", False, False, "road segment crossing a common space polygon"),
    ("uko:hasTrailConnection", False, False, "common space to path edges (uko:Trail) touching or inside it"),
    ("uko:pathThroughCommonSpace", False, False, "pedestrian edge intersecting a common space polygon"),
    ("uko:providesRecreationFor", False, False, "common space to each census tract within an 800 m walk"),
    ("uko:partOfChain", False, False, "branded place to its brand organization"),
    ("uko:operatedByOrg", False, False, "branded place to its brand organization (decision B4)"),
    ("uko:inHighInjuryNetwork", True, False, "road segment with at least half its length within 10 m of the SF 2024 HIN"),
    ("uko:hinSegmentOf", True, False, "SF 2024 HIN feature to each road segment it overlaps"),
    ("uko:hasIntersectionRiskProfile", True, False, "intersection node with attached injury crashes to its risk profile"),
    ("uko:hasVulnerablePopulationNearby", False, False, "place, stop or intersection within 200 m of a school, senior or care facility, or hospital"),
    ("uko:nearVulnerablePopulation", False, False, "road segment within 200 m of such a facility"),
    ("uko:hasTruckRoutingConstraint", False, False, "segment to its truck restriction (Overture access_restrictions, mode hgv)"),
    ("uko:constrainsSegment", False, False, "truck restriction to the segment it applies to"),
    ("uko:hasTruckParkingFacility", False, False, "segment within 500 m of a truck parking facility"),
    ("uko:derivedFrom", False, False, "URN lineage (gkg.urn_lineage)"),
    ("uko:hasDataSource", False, False, "entity to the data source release it came from"),
    ("uko:hasDistanceMeasurement", False, False, "stored in gkg.distance_measurement, not gkg.edge: place, stop or intersection to landmark or district within 2 km"),
    ("reo:atIntersectionNode", True, False, "crash record to its attached intersection node (50 m)"),
    ("reo:hasCollisionCausationFactor", True, False, "crash record to its primary collision factor (exact SWITRS matches only)"),
    ("reo:incidentCollisionType", True, False, "crash record to its collision type"),
    ("reo:incidentLighting", True, False, "crash record to its lighting condition"),
    ("reo:incidentRoadSurface", True, False, "crash record to its road surface"),
    ("reo:incidentWeatherCondition", True, False, "crash record to its weather (WEATHER_1)"),
    # Added Nov 22 (REO 1.7.0, audit item O1). New relations go at the end so that existing relation codes stay fixed.
    ("reo:onRoadSegment", True, False, "crash record to the road segment stage 4 attached it to (value_m = snap distance)"),
    ("reo:hasKABCOSeverity", True, False, "crash record to its KABCO level through the SWITRS COLLISION_SEVERITY mapping rows (1 K, 2 A, 3 B, 4 C, 0 O)"),
]

DDL = """
CREATE TABLE IF NOT EXISTS gkg.entity (eid bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, urn text NOT NULL,
    geofence_id text NOT NULL, uko_class text NOT NULL, src text NOT NULL, UNIQUE (geofence_id, urn));
CREATE TABLE IF NOT EXISTS gkg.entity_type (eid bigint NOT NULL, uko_class text NOT NULL, rule text NOT NULL,
    PRIMARY KEY (eid, uko_class));
CREATE TABLE IF NOT EXISTS gkg.aux_entity (geofence_id text NOT NULL, urn text NOT NULL, uko_class text NOT NULL,
    kind text NOT NULL, name text, props jsonb, geom geometry(Geometry, 4326), PRIMARY KEY (geofence_id, urn));
CREATE INDEX IF NOT EXISTS aux_entity_kind ON gkg.aux_entity (kind);
CREATE TABLE IF NOT EXISTS gkg.relation_type (rid smallint PRIMARY KEY, curie text UNIQUE NOT NULL,
    domain_classes text[], range_classes text[], crash_derived boolean NOT NULL, is_symmetric boolean NOT NULL,
    inverse_curie text, method text);
CREATE TABLE IF NOT EXISTS gkg.provenance (pid smallint PRIMARY KEY, rid smallint NOT NULL, source text NOT NULL,
    method text NOT NULL, code_version text NOT NULL, ontology_version text NOT NULL, crash_derived boolean NOT NULL,
    built timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS gkg.edge (rid smallint NOT NULL, subj bigint NOT NULL, obj bigint NOT NULL,
    pid smallint NOT NULL, value_m real);
CREATE TABLE IF NOT EXISTS gkg.distance_measurement (subj bigint NOT NULL, target bigint NOT NULL,
    straight_m real NOT NULL, walk_m real, measured_to text NOT NULL, inside_target boolean NOT NULL,
    pid smallint NOT NULL);
CREATE TABLE IF NOT EXISTS gkg.edge_rejected (rid smallint, reason text, n bigint, example_subj_class text,
    example_obj_class text, checked timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS gkg.class_closure (uko_class text, ancestor text, PRIMARY KEY (uko_class, ancestor));
ALTER TABLE gkg.tims_crash ADD COLUMN IF NOT EXISTS weather_1 text, ADD COLUMN IF NOT EXISTS weather_2 text,
    ADD COLUMN IF NOT EXISTS road_surface text, ADD COLUMN IF NOT EXISTS road_cond_1 text;
"""

_pid = {}


def rid(curie):
    return Q("select rid from gkg.relation_type where curie=%(c)s", {"c": curie})[0][0]


def pid(curie, source, method, crash=None):
    key = (curie, source, method)
    if key not in _pid:
        r = rid(curie)
        cd = Q("select crash_derived from gkg.relation_type where rid=%(r)s", {"r": r})[0][0] if crash is None else crash
        n = Q("select coalesce(max(pid),0)+1 from gkg.provenance")[0][0]
        X("insert into gkg.provenance (pid, rid, source, method, code_version, ontology_version, crash_derived) "
          "values (%(p)s,%(r)s,%(s)s,%(m)s,%(c)s,%(o)s,%(cd)s)",
          {"p": n, "r": r, "s": source, "m": method, "c": CODE_VERSION, "o": ONTO_VERSION, "cd": cd})
        _pid[key] = n
    return _pid[key]


def reset(curie):
    """Delete a relation's edges and provenance rows before it is rebuilt."""
    r = rid(curie)
    X("delete from gkg.edge where rid=%(r)s", {"r": r})
    X("delete from gkg.provenance where rid=%(r)s", {"r": r})
    for k in [k for k in _pid if k[0] == curie]:
        del _pid[k]
    return r


def edges(curie, source, method, select_sql, args=None, symmetric=None):
    """Insert edges from a SELECT returning (subj eid, obj eid, value_m). Returns the row count."""
    r = rid(curie)
    p = pid(curie, source, method)
    sym = Q("select is_symmetric from gkg.relation_type where rid=%(r)s", {"r": r})[0][0] if symmetric is None else symmetric
    t = time.time()
    if sym:
        sql = (f"insert into gkg.edge (rid, subj, obj, pid, value_m) select distinct on (least(s,o), greatest(s,o)) "
               f"{r}, least(s,o), greatest(s,o), {p}, v from ({select_sql}) x(s,o,v) where s<>o")
    else:
        sql = f"insert into gkg.edge (rid, subj, obj, pid, value_m) select {r}, s, o, {p}, v from ({select_sql}) x(s,o,v)"
    n = (conn.execute(sql, args) if args else conn.execute(sql)).rowcount
    log(step="edges", relation=curie, source=source, rows=n, seconds=round(time.time() - t, 1))
    return n


# --------------------------------------------------------------------------- steps

def step_schema():
    for s in DDL.split(";"):
        if s.strip():
            X(s)
    X("drop index if exists gkg.edge_subj; drop index if exists gkg.edge_obj; drop index if exists gkg.dm_subj")


def catalogue_from_ontology(out_dir):
    """Write relation_type.tsv and class_closure.tsv from UKO 15.7 + REO 1.7.0 (run where rdflib is installed)."""
    import rdflib
    from rdflib.namespace import RDF, RDFS, OWL
    g = rdflib.Graph()
    for f in ["uko_ontology_v15_7.ttl", "reo_ontology_v1_7_0.ttl"]:
        g.parse(ONTO / f)
    nm = g.namespace_manager
    q = lambda x: x.n3(nm)

    def classes(node):
        if isinstance(node, rdflib.BNode):
            lst = g.value(node, OWL.unionOf)
            return [q(c) for c in rdflib.collection.Collection(g, lst)] if lst else []
        return [q(node)]

    def inherited(p, pred):
        v = list(g.objects(p, pred))
        if v:
            return v
        for parent in g.objects(p, RDFS.subPropertyOf):
            v = inherited(parent, pred)
            if v:
                return v
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "relation_type.tsv", "w") as fh:
        for i, (c, crash, sym, note) in enumerate(RELATIONS, 1):
            P = rdflib.URIRef(nm.expand_curie(c))
            if not list(g.triples((P, None, None))):
                raise SystemExit(f"{c} not in the ontology")
            dom = sum((classes(d) for d in inherited(P, RDFS.domain)), [])
            rng = sum((classes(d) for d in inherited(P, RDFS.range)), [])
            inv = [q(x) for x in g.objects(P, OWL.inverseOf)] + [q(x) for x in g.subjects(OWL.inverseOf, P)]
            fh.write("\t".join([str(i), c, ",".join(dom), ",".join(rng), str(crash), str(sym), inv[0] if inv else "", note]) + "\n")
    rows = set()
    for cl in set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class)):
        if not isinstance(cl, rdflib.URIRef):
            continue
        todo, seen = [cl], {cl}
        while todo:
            x = todo.pop()
            for p in list(g.objects(x, RDFS.subClassOf)) + list(g.objects(x, OWL.equivalentClass)):
                if isinstance(p, rdflib.URIRef) and p not in seen:
                    seen.add(p)
                    todo.append(p)
        for a in seen:
            rows.add((q(cl), q(a)))
    with open(out_dir / "class_closure.tsv", "w") as fh:
        for r in sorted(rows):
            fh.write("\t".join(r) + "\n")
    return len(rows)


CATALOGUE = Path(__file__).resolve().parent / "catalogue"


def step_catalogue():
    """Load relation_type and class_closure from the TSV files that catalogue_from_ontology wrote
    (python -m relations.build --catalogue, run beside the ontology files)."""
    X("truncate gkg.relation_type")
    rel = [l.rstrip("\n").split("\t") for l in open(CATALOGUE / "relation_type.tsv")]
    if [r[1] for r in rel] != [c for c, *_ in RELATIONS]:
        raise SystemExit("catalogue/relation_type.tsv is out of date: rerun --catalogue")
    for i, c, d, r, cd, sym, inv, note in rel:
        X("insert into gkg.relation_type values (%(i)s,%(c)s,%(d)s,%(r)s,%(cd)s,%(s)s,%(inv)s,%(m)s)",
          {"i": int(i), "c": c, "d": d.split(",") if d else [], "r": r.split(",") if r else [], "cd": cd == "True",
           "s": sym == "True", "inv": inv or None, "m": note})
    X("truncate gkg.class_closure")
    n = copy("gkg.class_closure", ["uko_class", "ancestor"], (l.rstrip("\n").split("\t") for l in open(CATALOGUE / "class_closure.tsv")))
    log(step="catalogue", relations=len(rel), closure_rows=n)


def _theater_rules():
    """Approved mapping (decision 5): performing_arts_venue -> Theater; within performing_arts_venue and
    music_venue, names with 'opera' -> OperaHouse and 'symphony|concert hall|philharmonic|music hall' ->
    ConcertHall; government places named 'city hall' -> CityHall."""
    return """case
      when p.basic_category in ('performing_arts_venue','music_venue') and p.name ~* 'opera' then 'uko:OperaHouse'
      when p.basic_category in ('performing_arts_venue','music_venue')
           and p.name ~* '(symphony|concert hall|philharmonic|music hall)' then 'uko:ConcertHall'
      when p.basic_category = 'performing_arts_venue' then 'uko:Theater'
      when (p.uko_class = 'GovernmentBuilding' or p.basic_category like 'government%%') and p.name ~* 'city hall'
           then 'uko:CityHall'
      else 'uko:' || coalesce(nullif(p.uko_class,''), 'PointOfInterest') end"""


def step_entities():
    """Register every existing entity with its UKO class."""
    X("truncate gkg.entity, gkg.entity_type restart identity")
    reg = [
        ("road_segment", "'uko:RoadSegment'"),
        ("intersection_node", "'uko:IntersectionNode'"),
        ("pedestrian_edge", "case when subclass='sidewalk' then 'uko:SidewalkSegment' when subclass='crosswalk' "
                            "then 'uko:Crosswalk' when edge_class='cycleway' then 'uko:Cycleway' "
                            "when edge_class='path' then 'uko:Trail' else 'uko:PedestrianNetworkEdge' end"),
        ("pedestrian_node", "'uko:PedestrianNetworkNode'"),
        ("access_point", "'uko:AccessPoint'"),
        ("rail_segment", "'uko:RailSegment'"),
        ("census_tract", "'uko:CensusTract'"),
        ("building", "'uko:Building'"),
        ("transit_stop", "'uko:' || coalesce(nullif(uko_class,''),'TransitStop')"),
        ("transit_route", "'uko:' || coalesce(nullif(uko_class,''),'TransitRoute')"),
        ("transit_agency", "'uko:TransitAgency'"),
        ("service_calendar", "'uko:ServiceCalendar'"),
        ("walkshed_area", "'uko:WalkShedArea'"),
    ]
    for t, cls in reg:
        n = conn.execute(f"insert into gkg.entity (urn, geofence_id, uko_class, src) select distinct on (geofence_id, urn) "
                         f"urn, geofence_id, {cls}, '{t}' from gkg.{t}").rowcount
        log(step="entities", table=t, rows=n)
    n = conn.execute(f"insert into gkg.entity (urn, geofence_id, uko_class, src) select distinct on (p.geofence_id, p.urn) "
                     f"p.urn, p.geofence_id, {_theater_rules()}, 'place' from gkg.place p").rowcount
    log(step="entities", table="place", rows=n)
    # Crash records attached in each geofence (reo:HistoricalIncidentRecord), crash-derived.
    n = conn.execute("insert into gkg.entity (urn, geofence_id, uko_class, src) select 'urn:route-event-kg:"
                     "HistoricalIncidentRecord:tims:'||case_id, geofence_id, 'reo:HistoricalIncidentRecord', 'tims_crash' "
                     "from (select distinct geofence_id, case_id from gkg.crash_attachment) a").rowcount
    log(step="entities", table="tims_crash (attached)", rows=n)
    # UKO 15.7 holds the subclass axioms the 15.6 build had to assert per entity; gkg.entity_type stays empty.
    X("truncate gkg.entity_type")


def _aux_register(kind):
    n = conn.execute("insert into gkg.entity (urn, geofence_id, uko_class, src) select urn, geofence_id, uko_class, "
                     "'aux:'||kind from gkg.aux_entity where kind=%(k)s on conflict (geofence_id, urn) do update set "
                     "uko_class=excluded.uko_class", {"k": kind}).rowcount
    log(step="aux", kind=kind, entities=n)


def _ogr(src, layer_sql_or_layer, table, where=None, spat=None, extra=None):
    cmd = ["/opt/homebrew/bin/ogr2ogr", "-f", "PostgreSQL", "PG:dbname=geometis", str(src)]
    if layer_sql_or_layer:
        cmd += [layer_sql_or_layer]
    cmd += ["-nln", table, "-t_srs", "EPSG:4326", "-lco", "GEOMETRY_NAME=geom", "-nlt", "PROMOTE_TO_MULTI",
            "-overwrite", "--config", "OSM_USE_CUSTOM_INDEXING", "NO", "--config", "OGR_INTERLEAVED_READING", "YES",
            "-ct_opt", "WARN_ABOUT_DIFFERENT_COORD_OP=NO"]
    if where:
        cmd += ["-where", where]
    if spat:
        cmd += ["-spat", *map(str, spat)]
    cmd += extra or []
    subprocess.run(cmd, check=True, capture_output=True)


def step_aux():
    """New entities from public data: neighborhoods, supervisor districts, PDAs, cities and counties, city blocks,
    common spaces, natural areas, parking, HIN features, brand organizations, data sources, Bay Wheels."""
    X("create schema if not exists gkg_load")
    X("delete from gkg.entity where src like 'aux:%'")
    X("truncate gkg.aux_entity")
    for f, t in [("sf_find_neighborhoods.geojson", "sffind"), ("sf_analysis_neighborhoods.geojson", "sfan"),
                 ("sf_supervisor_districts_2022.geojson", "sfsup"), ("mtc_pda_pba2050plus.geojson", "pda"),
                 ("sf_hin_2024.geojson", "hin")]:
        _ogr(PUBLIC / f, None, "gkg_load." + t)
    sf = "us-ca-san-francisco"
    X(f"""insert into gkg.aux_entity select '{sf}', 'urn:urban-kg:Neighborhood:datasf-pty2-tcw4:'||md5(name),
          'uko:Neighborhood', 'neighborhood', name, '{{"scheme":"SF Find Neighborhoods (pty2-tcw4)"}}', geom from gkg_load.sffind on conflict do nothing""")
    X(f"""insert into gkg.aux_entity select '{sf}', 'urn:urban-kg:Neighborhood:datasf-j2bu-swwd:'||md5(nhood),
          'uko:Neighborhood', 'neighborhood', nhood, '{{"scheme":"SF Analysis Neighborhoods (j2bu-swwd)"}}', geom from gkg_load.sfan on conflict do nothing""")
    X(f"""insert into gkg.aux_entity select '{sf}', 'urn:urban-kg:SupervisorDistrict:datasf-f2zs-jevy:'||sup_dist,
          'uko:SupervisorDistrict', 'supervisor_district', 'District '||sup_dist, '{{"scheme":"SF Supervisor Districts 2022"}}', geom from gkg_load.sfsup on conflict do nothing""")
    X("""insert into gkg.aux_entity select case when jurisdicti='San Francisco' then 'us-ca-san-francisco' else 'us-ca-contra-costa-5' end,
          'urn:urban-kg:PriorityDevelopmentArea:mtc-pba2050plus:'||md5(coalesce(joinkey,pda_name)), 'uko:PriorityDevelopmentArea',
          'pda', pda_name, jsonb_build_object('jurisdiction', jurisdicti), geom from gkg_load.pda
          where jurisdicti in ('San Francisco','Antioch','Concord','Pittsburg','Pleasant Hill','Walnut Creek') on conflict do nothing""")
    X(f"""insert into gkg.aux_entity select '{sf}', 'urn:urban-kg:HighInjuryNetwork:datasf-enwt-3u8m:'||objectid, 'uko:HighInjuryNetwork',
          'hin_feature', full_street_name, jsonb_build_object('crash_derived', true, 'network', 'SF Vision Zero HIN 2024'), geom
          from gkg_load.hin on conflict do nothing""")
    X(f"""insert into gkg.aux_entity values ('{sf}', 'urn:urban-kg:HighInjuryNetwork:datasf-enwt-3u8m:network', 'uko:HighInjuryNetwork',
          'hin_network', 'San Francisco Vision Zero High Injury Network 2024', '{{"crash_derived": true}}', null)""")
    # Cities and counties (TIGER 2024) intersecting each geofence extent.
    _ogr(f"/vsizip/{TIGER}/tl_2024_06_place.zip", None, "gkg_load.place06")
    _ogr(f"/vsizip/{TIGER}/tl_2024_us_county.zip", None, "gkg_load.county", where="STATEFP='06'")
    for g in GEOFENCES:
        X("""insert into gkg.aux_entity select %(g)s, 'urn:urban-kg:City:tiger2024:'||p.geoid, 'uko:City', 'city', p.name,
             jsonb_build_object('geoid', p.geoid), p.geom from gkg_load.place06 p join gkg.geofence f on f.geofence_id=%(g)s
             and ST_Intersects(p.geom, f.extent) and p.lsad in ('25','57') on conflict do nothing""", {"g": g})
        X("""insert into gkg.aux_entity select %(g)s, 'urn:urban-kg:County:tiger2024:'||c.geoid, 'uko:County', 'county', c.name,
             jsonb_build_object('geoid', c.geoid), c.geom from gkg_load.county c join gkg.geofence f on f.geofence_id=%(g)s
             and ST_Intersects(c.geom, f.extent) on conflict do nothing""", {"g": g})
    # OSM polygons: common spaces, natural areas, parking.
    for g in GEOFENCES:
        bb = Q("select ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent) from gkg.geofence where geofence_id=%(g)s", {"g": g})[0]
        t = "osm_" + g.replace("-", "_")
        _ogr(PBF, "multipolygons", f"gkg_load.{t}", spat=bb,
             where="leisure IS NOT NULL OR \"natural\" IS NOT NULL OR amenity='parking' OR landuse IN ('recreation_ground','village_green')")
        X(f"""insert into gkg.aux_entity select %(g)s, 'urn:urban-kg:CommonSpace:osm:'||coalesce(osm_id, osm_way_id), case
              when leisure='dog_park' then 'uko:DogPark' when leisure='garden' then 'uko:Garden'
              when leisure='playground' then 'uko:Playground' when leisure='nature_reserve' then 'uko:NaturalArea'
              else 'uko:Park' end, 'common_space', o.name, jsonb_build_object('leisure', leisure), o.geom
              from gkg_load.{t} o join gkg.geofence f on f.geofence_id=%(g)s and ST_Intersects(o.geom, f.extent)
              where leisure in ('park','garden','playground','recreation_ground','nature_reserve','dog_park')
                 or landuse in ('recreation_ground','village_green')
              on conflict do nothing""", {"g": g})
        X(f"""insert into gkg.aux_entity select %(g)s, 'urn:urban-kg:NaturalArea:osm:'||coalesce(osm_id, osm_way_id), 'uko:NaturalArea',
              'natural_area', o.name, jsonb_build_object('natural', "natural"), o.geom
              from gkg_load.{t} o join gkg.geofence f on f.geofence_id=%(g)s and ST_Intersects(o.geom, f.extent)
              where "natural" in ('wood','scrub','wetland','grassland','heath') and coalesce(leisure,'')=''
              on conflict do nothing""", {"g": g})
        X(f"""insert into gkg.aux_entity select %(g)s, 'urn:urban-kg:ParkingFacility:osm:'||coalesce(osm_id, osm_way_id),
              case when other_tags ~ '"hgv"=>"(yes|designated)"' then 'uko:TruckParkingFacility' else 'uko:ParkingLot' end,
              'parking', o.name, null, o.geom
              from gkg_load.{t} o join gkg.geofence f on f.geofence_id=%(g)s and ST_Intersects(o.geom, f.extent)
              where amenity='parking' on conflict do nothing""", {"g": g})
    # Brand organizations (one per brand name and geofence), data sources, Bay Wheels.
    X("""insert into gkg.aux_entity select distinct on (geofence_id, lower(brand)) geofence_id,
         'urn:urban-kg:Organization:overture-brand:'||md5(lower(brand)), 'uko:Organization', 'organization', brand, null, null
         from gkg.place where brand is not null and brand<>'' order by geofence_id, lower(brand), brand""")
    srcs = {"overture": "Overture Maps 2026-10-21.0", "gtfs": "GTFS feeds (Mobility Database archive)",
            "acs": "Census ACS 5-year / TIGER 2024", "tims": "TIMS SWITRS (SafeTREC), downloaded 2026-11-10",
            "osm": "OpenStreetMap norcal.osm.pbf (2026-10-21)", "datasf": "DataSF (2026-11-20 download)",
            "mtc": "MTC Priority Development Areas, Plan Bay Area 2050+", "gbfs": "Bay Wheels GBFS 2.3 (2026-11-20)"}
    for g in GEOFENCES:
        for k, v in srcs.items():
            X("insert into gkg.aux_entity values (%(g)s, %(u)s, 'uko:DataSource', 'data_source', %(n)s, null, null)",
              {"g": g, "u": f"urn:urban-kg:DataSource:{k}", "n": v})
    st = json.load(open(PUBLIC / "gbfs/station_information.json"))["data"]["stations"]
    sysinfo = json.load(open(PUBLIC / "gbfs/system_information.json"))["data"]
    X("""insert into gkg.aux_entity values ('us-ca-san-francisco', 'urn:urban-kg:SharedMobilitySystem:gbfs:'||%(i)s,
         'uko:SharedMobilitySystem', 'gbfs_system', %(n)s, null, null)""", {"i": sysinfo.get("system_id", "bay"), "n": sysinfo.get("name", "Bay Wheels")})
    rows = [("us-ca-san-francisco", urn("SharedMobilityStation", "baywheels", s["station_id"]), "uko:SharedMobilityStation",
             "gbfs_station", s.get("name"), json.dumps({"station_id": s["station_id"], "capacity": s.get("capacity")}),
             f"SRID=4326;POINT({s['lon']} {s['lat']})") for s in st]
    X("create temp table _gb (like gkg.aux_entity)")
    copy("_gb", ["geofence_id", "urn", "uko_class", "kind", "name", "props", "geom"], rows)
    X("""insert into gkg.aux_entity select b.* from _gb b join gkg.geofence f on f.geofence_id=b.geofence_id
         and ST_Intersects(b.geom, f.extent)""")
    X("drop table _gb")
    for k in ["neighborhood", "supervisor_district", "pda", "hin_feature", "hin_network", "city", "county", "common_space",
              "natural_area", "parking", "organization", "data_source", "gbfs_system", "gbfs_station"]:
        _aux_register(k)
    X("create index if not exists aux_entity_geom on gkg.aux_entity using gist (geom)")


def step_blocks():
    """uko:CityBlock entities: faces of the street network (non-service, non-track, non-motorway roads)."""
    X("delete from gkg.entity where src='aux:city_block'")
    X("delete from gkg.aux_entity where kind='city_block'")
    for g in GEOFENCES:
        t = time.time()
        X("""insert into gkg.aux_entity select %(g)s, 'urn:urban-kg:CityBlock:gkgfull:'||md5(%(g)s||ST_AsText(ST_SnapToGrid(ST_PointOnSurface(b),1e-6))),
             'uko:CityBlock', 'city_block', null, jsonb_build_object('area_m2', round(ST_Area(b::geography))), b
             from (select (ST_Dump(ST_Polygonize(u))).geom b from (select ST_Union(geom) u from gkg.road_segment
                   where geofence_id=%(g)s and coalesce(road_classification,'') not in ('service','track','motorway','unknown')
                     and coalesce(subclass,'')<>'link' and not coalesce(is_tunnel,false) and not coalesce(is_bridge,false)) un) z
             where ST_Area(b::geography) between 200 and 2000000
             on conflict do nothing""", {"g": g})
        log(step="blocks", geofence=g, seconds=round(time.time() - t, 1),
            blocks=Q("select count(*) from gkg.aux_entity where kind='city_block' and geofence_id=%(g)s", {"g": g})[0][0])
    _aux_register("city_block")


def step_work():
    """Projected (EPSG:3310) work copies of every layer, keyed by entity number."""
    X("drop schema if exists gkg_work cascade")
    X("create schema gkg_work")
    W = [
        ("seg", "road_segment", "s.road_classification cls, s.subclass, s.name, s.from_node, s.to_node, s.length_m, "
                "coalesce(s.is_bridge,false) is_bridge, coalesce(s.is_tunnel,false) is_tunnel, s.access_restrictions"),
        ("node", "intersection_node", "s.node_kind"),
        ("ped", "pedestrian_edge", "s.edge_class, s.subclass, s.from_node, s.to_node, s.length_m"),
        ("pnode", "pedestrian_node", "1 one"),
        ("place", "place", "s.uko_class pclass, s.basic_category, s.brand, s.name"),
        ("stop", "transit_stop", "s.location_type, s.feed_id, s.stop_id, s.parent_urn, s.route_urns"),
        ("bld", "building", "1 one"),
        ("tract", "census_tract", "1 one"),
        ("rail", "rail_segment", "1 one"),
        ("shed", "walkshed_area", "s.origin_urn"),
    ]
    for name, table, cols in W:
        X(f"""create unlogged table gkg_work.{name} as select e.eid, e.urn, e.uko_class, s.geofence_id g, {cols},
              ST_Transform(s.geom, 3310) geom from gkg.{table} s join gkg.entity e on e.geofence_id=s.geofence_id and e.urn=s.urn
              where s.geom is not null""")
        X(f"create index on gkg_work.{name} using gist (geom)")
        X(f"create index on gkg_work.{name} (g)")
        X(f"analyze gkg_work.{name}")
    X("""create unlogged table gkg_work.aux as select e.eid, a.urn, a.uko_class, a.kind, a.name, a.props, a.geofence_id g,
         ST_Transform(a.geom, 3310) geom from gkg.aux_entity a join gkg.entity e on e.geofence_id=a.geofence_id and e.urn=a.urn
         where a.geom is not null""")
    X("create index on gkg_work.aux using gist (geom)")
    X("create index on gkg_work.aux (kind, g)")
    X("analyze gkg_work.aux")
    # Points used by proximity and containment families: places, stops, intersections.
    X("""create unlogged table gkg_work.pts as select eid, g, geom, 'place' t from gkg_work.place
         union all select eid, g, geom, 'stop' from gkg_work.stop union all select eid, g, geom, 'node' from gkg_work.node""")
    X("create index on gkg_work.pts using gist (geom)")
    X("analyze gkg_work.pts")
    X("create unlogged table gkg_work.bldc as select eid, g, ST_PointOnSurface(geom) geom from gkg_work.bld")
    X("create index on gkg_work.bldc using gist (geom)")
    X("create unlogged table gkg_work.segmid as select eid, g, ST_LineInterpolatePoint(ST_LineMerge(geom), 0.5) geom "
      "from gkg_work.seg where GeometryType(ST_LineMerge(geom))='LINESTRING'")
    X("create index on gkg_work.segmid using gist (geom)")
    X("analyze gkg_work.bldc; analyze gkg_work.segmid")
    log(step="work", layers=len(W) + 4)


def step_stored():
    """Relations the builder already stored, moved into the edge table under their UKO names."""
    for c in ["uko:adjacentSegment", "uko:connectsTo", "uko:touches", "uko:connectsToTransit", "uko:hasAccessPoint",
              "uko:parentStation", "uko:servesStop", "uko:gtfsOperatedBy", "uko:walkshedOrigin", "uko:derivedFrom",
              "uko:within"]:
        reset(c)
    j = "join gkg.entity {a} on {a}.geofence_id={g} and {a}.urn={u}"
    edges("uko:adjacentSegment", "Overture 2026-10-21.0", "segment end nodes (gkg.seg_intersects)",
          "select n.eid, s.eid, null::real from gkg.seg_intersects x " + j.format(a="s", g="x.geofence_id", u="x.segment_urn")
          + " " + j.format(a="n", g="x.geofence_id", u="x.node_urn"))
    edges("uko:connectsTo", "Overture 2026-10-21.0", "end node of A is start node of B (gkg.seg_connects_to)",
          "select a.eid, b.eid, null::real from gkg.seg_connects_to x " + j.format(a="a", g="x.geofence_id", u="x.from_segment")
          + " " + j.format(a="b", g="x.geofence_id", u="x.to_segment"))
    edges("uko:touches", "Overture 2026-10-21.0", "segments sharing an end node (gkg.seg_adjacent)",
          "select a.eid, b.eid, null::real from gkg.seg_adjacent x " + j.format(a="a", g="x.geofence_id", u="x.segment_a")
          + " " + j.format(a="b", g="x.geofence_id", u="x.segment_b"))
    edges("uko:connectsToTransit", "Overture 2026-10-21.0; GTFS", "nearest walkable segment within 50 m of each stop (gkg.stop_road)",
          "select a.eid, b.eid, x.distance_m::real from gkg.stop_road x " + j.format(a="a", g="x.geofence_id", u="x.segment_urn")
          + " " + j.format(a="b", g="x.geofence_id", u="x.stop_urn"))
    for col in ["intersection_node", "pedestrian_node"]:
        edges("uko:hasAccessPoint", "Overture 2026-10-21.0", f"access point joining road and pedestrian layers ({col})",
              f"select a.eid, b.eid, null::real from gkg.access_point x " + j.format(a="a", g="x.geofence_id", u=f"x.{col}")
              + " " + j.format(a="b", g="x.geofence_id", u="x.urn"))
    edges("uko:parentStation", "GTFS", "stops.txt parent_station",
          "select a.eid, b.eid, null::real from gkg.transit_stop x " + j.format(a="a", g="x.geofence_id", u="x.urn")
          + " " + j.format(a="b", g="x.geofence_id", u="x.parent_urn"))
    edges("uko:servesStop", "GTFS", "route of a stop time at the stop (transit_stop.route_urns)",
          "select b.eid, a.eid, null::real from gkg.transit_stop x cross join unnest(x.route_urns) r(u) "
          + j.format(a="a", g="x.geofence_id", u="x.urn") + " " + j.format(a="b", g="x.geofence_id", u="r.u"))
    edges("uko:gtfsOperatedBy", "GTFS", "routes.txt agency_id",
          "select a.eid, b.eid, null::real from gkg.transit_route x " + j.format(a="a", g="x.geofence_id", u="x.urn")
          + " " + j.format(a="b", g="x.geofence_id", u="x.agency_urn"))
    edges("uko:walkshedOrigin", "GTFS; Overture 2026-10-21.0", "network walkshed per stop (800 m)",
          "select a.eid, b.eid, null::real from gkg.walkshed_area x " + j.format(a="a", g="x.geofence_id", u="x.urn")
          + " " + j.format(a="b", g="x.geofence_id", u="x.origin_urn"))
    edges("uko:derivedFrom", "Overture releases", "URN lineage (gkg.urn_lineage)",
          "select a.eid, b.eid, null::real from gkg.urn_lineage x join gkg.entity a on a.urn=x.new_urn join gkg.entity b "
          "on b.urn=x.old_urn and b.geofence_id=a.geofence_id")
    edges("uko:within", "Overture 2026-10-21.0", "place linked to building (gkg.place_building)",
          "select a.eid, b.eid, null::real from gkg.place_building x " + j.format(a="a", g="x.geofence_id", u="x.place_urn")
          + " " + j.format(a="b", g="x.geofence_id", u="x.building_urn"))
    edges("uko:within", "Overture 2026-10-21.0; derived city blocks", "building point on surface inside city block",
          "select b.eid, k.eid, null::real from gkg_work.bldc b join gkg_work.aux k on k.kind='city_block' and k.g=b.g "
          "and ST_Contains(k.geom, b.geom)")


def step_containment():
    for c in ["uko:withinCensusTract", "uko:hasJurisdiction", "uko:inNeighborhood", "uko:inSupervisorDistrict",
              "uko:overlaps", "uko:adjacentTo", "uko:adjacentNeighborhood"]:
        reset(c)
    layers = [("pts", "places, stops and intersections (point)"), ("bldc", "buildings (point on surface)"),
              ("segmid", "road segments (midpoint)")]
    for lay, what in layers[:2]:
        edges("uko:withinCensusTract", "Census TIGER 2024; Overture; GTFS", f"{what} inside tract",
              f"select p.eid, t.eid, null::real from gkg_work.{lay} p join gkg_work.tract t on t.g=p.g and ST_Contains(t.geom, p.geom)")
    edges("uko:withinCensusTract", "Census TIGER 2024; Overture", "segment midpoint in tract (gkg.segment_within_tract)",
          "select a.eid, b.eid, null::real from gkg.segment_within_tract x join gkg.entity a on a.geofence_id=x.geofence_id "
          "and a.urn=x.segment_urn join gkg.entity b on b.geofence_id=x.geofence_id and b.urn=x.tract_urn")
    for lay, what in layers:
        edges("uko:hasJurisdiction", "TIGER 2024 places and counties", f"{what}: city that contains it, else county",
              f"""select * from (select p.eid, coalesce(
                    (select c.eid from gkg_work.aux c where c.kind='city' and c.g=p.g and ST_Contains(c.geom, p.geom) limit 1),
                    (select c.eid from gkg_work.aux c where c.kind='county' and c.g=p.g and ST_Contains(c.geom, p.geom) limit 1)) o,
                  null::real v from gkg_work.{lay} p) z where o is not null""")
        for kind, c, src in [("neighborhood", "uko:inNeighborhood", "DataSF SF Find and Analysis Neighborhoods"),
                             ("supervisor_district", "uko:inSupervisorDistrict", "DataSF Supervisor Districts 2022")]:
            edges(c, src, f"{what} inside polygon",
                  f"select p.eid, a.eid, null::real from gkg_work.{lay} p join gkg_work.aux a on a.kind='{kind}' and a.g=p.g "
                  f"and ST_Contains(a.geom, p.geom)")
    edges("uko:overlaps", "DataSF; MTC; TIGER 2024", "district polygon and tract share at least 1 percent of the smaller area",
          """select a.eid, t.eid, null::real from gkg_work.aux a join gkg_work.tract t on t.g=a.g and ST_Intersects(a.geom, t.geom)
             where a.kind in ('neighborhood','supervisor_district','pda') and
             ST_Area(ST_Intersection(ST_MakeValid(a.geom), ST_MakeValid(t.geom))) >= 0.01*least(ST_Area(a.geom), ST_Area(t.geom))""")
    edges("uko:adjacentTo", "Census TIGER 2024", "tracts whose boundaries share a line",
          """select a.eid, b.eid, null::real from gkg_work.tract a join gkg_work.tract b on a.g=b.g and a.eid<b.eid
             and ST_Touches(a.geom, b.geom) and ST_Dimension(ST_Intersection(a.geom, b.geom)) >= 1""")
    edges("uko:adjacentNeighborhood", "DataSF", "neighborhoods of the same scheme sharing a boundary (within 1 m)",
          """select a.eid, b.eid, null::real from gkg_work.aux a join gkg_work.aux b on a.kind='neighborhood' and b.kind='neighborhood'
             and a.g=b.g and a.eid<b.eid and a.props->>'scheme'=b.props->>'scheme' and ST_DWithin(a.geom, b.geom, 1)
             and not ST_Overlaps(a.geom, b.geom)""")


def step_proximity():
    for c in ["uko:near", "uko:nearTransitStop", "uko:hasVulnerablePopulationNearby", "uko:nearVulnerablePopulation",
              "uko:nearestTransitStop"]:
        reset(c)
    for g in GEOFENCES:
        edges("uko:near", "Overture 2026-10-21.0; GTFS", "places, stops, intersections within 200 m (EPSG:3310); veryNear = value_m <= 50",
              "select a.eid, b.eid, ST_Distance(a.geom, b.geom)::real from gkg_work.pts a join gkg_work.pts b "
              "on b.g=a.g and a.eid<b.eid and ST_DWithin(a.geom, b.geom, 200) where a.g=%(g)s", {"g": g}, symmetric=False)
    edges("uko:nearTransitStop", "Overture; GTFS", "building within 400 m of a boardable stop",
          "select b.eid, s.eid, ST_Distance(b.geom, s.geom)::real from gkg_work.bld b join gkg_work.stop s on s.g=b.g "
          "and coalesce(s.location_type,0) in (0,1) and ST_DWithin(b.geom, s.geom, 400)")
    vul = "(" + ",".join(f"'{v}'" for v in VULNERABLE) + ")"
    edges("uko:hasVulnerablePopulationNearby", "Overture places", "within 200 m of a school, senior or care facility, or hospital",
          f"select a.eid, v.eid, ST_Distance(a.geom, v.geom)::real from gkg_work.pts a join gkg_work.place v on v.g=a.g "
          f"and v.pclass in {vul} and a.eid<>v.eid and ST_DWithin(a.geom, v.geom, 200)")
    edges("uko:nearVulnerablePopulation", "Overture", "road segment within 200 m of such a facility",
          f"select s.eid, v.eid, ST_Distance(s.geom, v.geom)::real from gkg_work.seg s join gkg_work.place v on v.g=s.g "
          f"and v.pclass in {vul} and ST_DWithin(s.geom, v.geom, 200)")
    edges("uko:nearestTransitStop", "Overture; GTFS", "nearest boardable stop to each place (straight line)",
          "select p.eid, r.eid, r.d::real from gkg_work.place p cross join lateral (select s.eid, ST_Distance(p.geom, s.geom) d "
          "from gkg_work.stop s where s.g=p.g and coalesce(s.location_type,0) in (0,1) order by s.geom <-> p.geom limit 1) r")


def step_topology():
    for c in ["uko:crosses", "uko:crossesOver", "uko:intersectsRoad", "uko:sharesWallWith", "uko:sharesBuildingWith",
              "uko:insideMall", "uko:parallelTo"]:
        reset(c)
    edges("uko:crosses", "Overture 2026-10-21.0", "road segment crosses rail segment",
          "select s.eid, r.eid, null::real from gkg_work.seg s join gkg_work.rail r on r.g=s.g and ST_Crosses(s.geom, r.geom)")
    edges("uko:crosses", "Overture 2026-10-21.0", "crosswalk edge to the road segment nearest its midpoint: within 7 m and within 30 degrees of perpendicular",
          "select p.eid, r.eid, r.d::real from gkg_work.ped p cross join lateral (select s.eid, ST_Distance(s.geom, "
          "ST_LineInterpolatePoint(ST_LineMerge(p.geom), 0.5)) d, abs(mod((degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(p.geom)), "
          "ST_EndPoint(ST_LineMerge(p.geom)))) - degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(s.geom)), ST_EndPoint(ST_LineMerge(s.geom)))) "
          "+ 360)::numeric, 180) - 90) off_perp from gkg_work.seg s where s.g=p.g and s.cls not in ('motorway','track') "
          "order by s.geom <-> ST_LineInterpolatePoint(ST_LineMerge(p.geom), 0.5) limit 1) r "
          "where p.subclass='crosswalk' and GeometryType(ST_LineMerge(p.geom))='LINESTRING' and r.d <= 7 and r.off_perp <= 30")
    edges("uko:crossesOver", "Overture 2026-10-21.0", "lines cross, no shared node; bridge over non-bridge or non-tunnel over tunnel",
          """select case when a.is_bridge or b.is_tunnel then a.eid else b.eid end, case when a.is_bridge or b.is_tunnel then b.eid else a.eid end,
             null::real from gkg_work.seg a join gkg_work.seg b on b.g=a.g and a.eid<b.eid and ST_Crosses(a.geom, b.geom)
             and a.from_node not in (b.from_node, b.to_node) and a.to_node not in (b.from_node, b.to_node)
             where (a.is_bridge <> b.is_bridge) or (a.is_tunnel <> b.is_tunnel)""")
    edges("uko:intersectsRoad", "Overture 2026-10-21.0", "differently named roads meeting at a shared node (from uko:touches)",
          """select x.subj, x.obj, null::real from gkg.edge x join gkg_work.seg a on a.eid=x.subj join gkg_work.seg b on b.eid=x.obj
             where x.rid=(select rid from gkg.relation_type where curie='uko:touches')
               and coalesce(a.name,'')<>'' and coalesce(b.name,'')<>'' and gkg.road_key(a.name)<>gkg.road_key(b.name)""")
    edges("uko:sharesWallWith", "Overture buildings", "boundaries share at least 1 m",
          """select a.eid, b.eid, null::real from gkg_work.bld a join gkg_work.bld b on b.g=a.g and a.eid<b.eid and ST_DWithin(a.geom, b.geom, 0.5)
             where ST_Length(ST_Intersection(ST_Boundary(ST_Buffer(a.geom, 0.3)), b.geom)) >= 1""")
    edges("uko:sharesBuildingWith", "Overture places and buildings", "places linked to the same building",
          """select a.eid, b.eid, null::real from gkg.place_building x join gkg.place_building y on y.geofence_id=x.geofence_id
             and y.building_urn=x.building_urn and x.place_urn<y.place_urn
             join gkg.entity a on a.geofence_id=x.geofence_id and a.urn=x.place_urn join gkg.entity b on b.geofence_id=y.geofence_id and b.urn=y.place_urn""")
    edges("uko:insideMall", "Overture places and buildings", "place in the same building as a ShoppingMall place",
          """select a.eid, m.eid, null::real from gkg.place_building x join gkg.place_building y on y.geofence_id=x.geofence_id and y.building_urn=x.building_urn
             join gkg.place mp on mp.geofence_id=y.geofence_id and mp.urn=y.place_urn and mp.uko_class='ShoppingMall'
             join gkg.entity a on a.geofence_id=x.geofence_id and a.urn=x.place_urn join gkg.entity m on m.geofence_id=y.geofence_id and m.urn=y.place_urn
             where x.place_urn<>y.place_urn""")
    edges("uko:parallelTo", "Overture 2026-10-21.0", "within 30 m, at most 15 degrees apart, overlapping at least 50 m",
          """select a.eid, b.eid, null::real from gkg_work.seg a join gkg_work.seg b on b.g=a.g and a.eid<b.eid and a.length_m>=50 and b.length_m>=50
             and ST_DWithin(a.geom, b.geom, 30)
             where mod((degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(a.geom)), ST_EndPoint(ST_LineMerge(a.geom))))
                       - degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(b.geom)), ST_EndPoint(ST_LineMerge(b.geom)))) + 360)::numeric, 180)
                   not between 15 and 165
               and ST_Length(ST_Intersection(ST_Buffer(a.geom, 30, 'endcap=flat'), b.geom)) >= 50""")


def step_roadnet():
    for c in ["uko:continuesAs", "uko:branchesFrom", "uko:mergesInto", "uko:feedsInto"]:
        reset(c)
    # Bearing of each segment at each of its ends, pointing away from the node.
    X("drop table if exists gkg_work.ends")
    X("""create unlogged table gkg_work.ends as
         select eid, g, cls, subclass, name, from_node node, 'start' pos,
                degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(geom)), ST_LineInterpolatePoint(ST_LineMerge(geom), least(1, 15/greatest(length_m,15))))) az
         from gkg_work.seg where GeometryType(ST_LineMerge(geom))='LINESTRING'
         union all
         select eid, g, cls, subclass, name, to_node, 'end',
                degrees(ST_Azimuth(ST_EndPoint(ST_LineMerge(geom)), ST_LineInterpolatePoint(ST_LineMerge(geom), greatest(0, 1-15/greatest(length_m,15)))))
         from gkg_work.seg where GeometryType(ST_LineMerge(geom))='LINESTRING'""")
    X("create index on gkg_work.ends (g, node)")
    edges("uko:continuesAs", "Overture 2026-10-21.0", "name changes at a node where the line runs on within 30 degrees (decision B3)",
          """select a.eid, b.eid, null::real from gkg_work.ends a join gkg_work.ends b on b.g=a.g and b.node=a.node and b.eid<>a.eid
             where a.pos='end' and b.pos='start' and coalesce(a.name,'')<>'' and coalesce(b.name,'')<>''
               and gkg.road_key(a.name)<>gkg.road_key(b.name)
               and abs(mod((a.az - b.az + 540)::numeric, 360) - 180) >= 150""")
    hi = "('motorway','trunk','primary')"
    edges("uko:branchesFrom", "Overture 2026-10-21.0", "ramp start node on a non-ramp motorway, trunk or primary segment",
          f"""select distinct a.eid, b.eid, null::real from gkg_work.ends a join gkg_work.ends b on b.g=a.g and b.node=a.node and b.eid<>a.eid
              where a.subclass='link' and a.pos='start' and coalesce(b.subclass,'')<>'link' and b.cls in {hi}""")
    edges("uko:mergesInto", "Overture 2026-10-21.0", "ramp end node on a non-ramp motorway, trunk or primary segment",
          f"""select distinct a.eid, b.eid, null::real from gkg_work.ends a join gkg_work.ends b on b.g=a.g and b.node=a.node and b.eid<>a.eid
              where a.subclass='link' and a.pos='end' and coalesce(b.subclass,'')<>'link' and b.cls in {hi}""")
    order = "array['service','residential','unclassified','tertiary','secondary','primary','trunk','motorway']"
    edges("uko:feedsInto", "Overture 2026-10-21.0", "lower class meets higher class at a shared node (decision B3 order)",
          f"""select distinct a.eid, b.eid, null::real from gkg_work.ends a join gkg_work.ends b on b.g=a.g and b.node=a.node and b.eid<>a.eid
              where array_position({order}, case when a.cls='unclassified' then 'residential' else a.cls end)
                  < array_position({order}, case when b.cls='unclassified' then 'residential' else b.cls end)""")


def step_access():
    for c in ["uko:accessibleBy", "uko:frontageOn", "uko:providesAccessTo", "uko:servesAsMainAccess", "uko:accessibleByBikeLane",
              "uko:accessibleBySidewalk", "uko:hasParking", "uko:alongsideOf", "uko:onNorthSideOf", "uko:onSouthSideOf",
              "uko:onEastSideOf", "uko:onWestSideOf"]:
        reset(c)
    street = "s.cls not in ('motorway','track','service') and coalesce(s.subclass,'')<>'link'"
    X("drop table if exists gkg_work.bnear")
    X(f"""create unlogged table gkg_work.bnear as select b.eid b, r.eid s, r.d from gkg_work.bld b cross join lateral
          (select s.eid, ST_Distance(b.geom, s.geom) d from gkg_work.seg s where s.g=b.g and {street}
           order by s.geom <-> b.geom limit 1) r where r.d <= 30""")
    for c in ["uko:accessibleBy", "uko:frontageOn"]:
        edges(c, "Overture 2026-10-21.0", "nearest street segment within 30 m of the building (decision B1)",
              "select b, s, d::real from gkg_work.bnear")
    edges("uko:providesAccessTo", "Overture 2026-10-21.0", "street segment to buildings whose nearest street it is (30 m)",
          "select s, b, d::real from gkg_work.bnear")
    edges("uko:servesAsMainAccess", "Overture 2026-10-21.0", "nearest street segment to each place (no address field loaded)",
          f"select r.eid, p.eid, r.d::real from gkg_work.place p cross join lateral (select s.eid, ST_Distance(p.geom, s.geom) d "
          f"from gkg_work.seg s where s.g=p.g and {street} order by s.geom <-> p.geom limit 1) r where r.d <= 100")
    for c, cond in [("uko:accessibleByBikeLane", "e.edge_class='cycleway'"), ("uko:accessibleBySidewalk", "e.subclass='sidewalk'")]:
        edges(c, "Overture 2026-10-21.0", f"nearest edge with {cond} within 50 m",
              f"select b.eid, r.eid, r.d::real from gkg_work.bld b cross join lateral (select e.eid, ST_Distance(b.geom, e.geom) d "
              f"from gkg_work.ped e where e.g=b.g and {cond} and ST_DWithin(b.geom, e.geom, 50) order by e.geom <-> b.geom limit 1) r")
    edges("uko:hasParking", "OpenStreetMap amenity=parking", "parking polygons within 100 m of the building",
          "select b.eid, p.eid, ST_Distance(b.geom, p.geom)::real from gkg_work.bld b join gkg_work.aux p on p.kind='parking' "
          "and p.g=b.g and ST_DWithin(b.geom, p.geom, 100)")
    X("drop table if exists gkg_work.along")
    X("""create unlogged table gkg_work.along as select e.eid sw, r.eid rd, r.side from gkg_work.ped e cross join lateral
         (select s.eid, case when abs(ST_Y(ST_Centroid(e.geom)) - ST_Y(ST_ClosestPoint(s.geom, ST_Centroid(e.geom))))
                               >= abs(ST_X(ST_Centroid(e.geom)) - ST_X(ST_ClosestPoint(s.geom, ST_Centroid(e.geom))))
                  then case when ST_Y(ST_Centroid(e.geom)) > ST_Y(ST_ClosestPoint(s.geom, ST_Centroid(e.geom))) then 'N' else 'S' end
                  else case when ST_X(ST_Centroid(e.geom)) > ST_X(ST_ClosestPoint(s.geom, ST_Centroid(e.geom))) then 'E' else 'W' end end side
          from gkg_work.seg s where s.g=e.g and s.cls not in ('motorway','service','track') and ST_DWithin(e.geom, s.geom, 25)
            and mod((degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(e.geom)), ST_EndPoint(ST_LineMerge(e.geom))))
                    - degrees(ST_Azimuth(ST_StartPoint(ST_LineMerge(s.geom)), ST_EndPoint(ST_LineMerge(s.geom)))) + 360)::numeric, 180)
                not between 20 and 160
          order by s.geom <-> e.geom limit 1) r where e.subclass='sidewalk'""")
    edges("uko:alongsideOf", "Overture 2026-10-21.0", "nearest road within 25 m and 20 degrees of each sidewalk edge",
          "select sw, rd, null::real from gkg_work.along")
    for side, c in [("N", "uko:onNorthSideOf"), ("S", "uko:onSouthSideOf"), ("E", "uko:onEastSideOf"), ("W", "uko:onWestSideOf")]:
        edges(c, "Overture 2026-10-21.0", "alongsideOf pair; side from the larger of the north-south and east-west offsets",
              f"select sw, rd, null::real from gkg_work.along where side='{side}'")


def step_commons():
    for c in ["uko:adjacentToCommonSpace", "uko:bordersCommonSpace", "uko:bordersNaturalArea", "uko:crossesThroughCommonSpace",
              "uko:hasTrailConnection", "uko:pathThroughCommonSpace"]:
        reset(c)
    cs = "c.kind='common_space'"
    edges("uko:adjacentToCommonSpace", "Overture buildings; OpenStreetMap", "building within 5 m of a common space",
          f"select b.eid, c.eid, ST_Distance(b.geom, c.geom)::real from gkg_work.bld b join gkg_work.aux c on {cs} and c.g=b.g and ST_DWithin(b.geom, c.geom, 5)")
    edges("uko:bordersCommonSpace", "Overture; OpenStreetMap", "road segment within 15 m of a common space boundary",
          f"select s.eid, c.eid, null::real from gkg_work.seg s join gkg_work.aux c on {cs} and c.g=s.g and ST_DWithin(s.geom, ST_Boundary(c.geom), 15)")
    edges("uko:bordersNaturalArea", "OpenStreetMap", "common space within 5 m of a natural area",
          f"select c.eid, n.eid, null::real from gkg_work.aux c join gkg_work.aux n on n.kind='natural_area' and n.g=c.g and {cs} and ST_DWithin(c.geom, n.geom, 5)")
    edges("uko:crossesThroughCommonSpace", "Overture; OpenStreetMap", "road segment crosses a common space polygon",
          f"select s.eid, c.eid, null::real from gkg_work.seg s join gkg_work.aux c on {cs} and c.g=s.g and ST_Crosses(s.geom, c.geom)")
    edges("uko:hasTrailConnection", "Overture; OpenStreetMap", "path edges (uko:Trail) touching or inside a common space",
          f"select c.eid, e.eid, null::real from gkg_work.aux c join gkg_work.ped e on e.g=c.g and e.edge_class='path' and {cs} and ST_Intersects(c.geom, e.geom)")
    edges("uko:pathThroughCommonSpace", "Overture; OpenStreetMap", "pedestrian edge intersecting a common space",
          f"select e.eid, c.eid, null::real from gkg_work.ped e join gkg_work.aux c on {cs} and c.g=e.g and ST_Intersects(c.geom, e.geom)")


def step_commercial_safety_freight():
    for c in ["uko:partOfChain", "uko:operatedByOrg", "uko:inHighInjuryNetwork", "uko:hinSegmentOf", "uko:hasIntersectionRiskProfile",
              "uko:hasTruckRoutingConstraint", "uko:constrainsSegment", "uko:hasTruckParkingFacility", "uko:hasDataSource"]:
        reset(c)
    for c in ["uko:partOfChain", "uko:operatedByOrg"]:
        edges(c, "Overture places (brand)", "branded place to its brand organization",
              """select p.eid, o.eid, null::real from gkg_work.place p join gkg.entity o on o.geofence_id=p.g
                 and o.urn='urn:urban-kg:Organization:overture-brand:'||md5(lower(p.brand)) where p.brand<>''""")
    X("drop table if exists gkg_work.hinbuf")
    X("""create unlogged table gkg_work.hinbuf as select ST_Subdivide(ST_Union(ST_Buffer(geom, 10)), 64) geom
         from gkg_work.aux where kind='hin_feature'""")
    X("create index on gkg_work.hinbuf using gist (geom)")
    edges("uko:inHighInjuryNetwork", "DataSF enwt-3u8m (2024 HIN, injuries 2020-2024)", "at least half the segment within 10 m of HIN lines",
          """select s.eid, n.eid, null::real from (select s.eid, s.length_m, sum(ST_Length(ST_Intersection(s.geom, h.geom))) inside
             from gkg_work.seg s join gkg_work.hinbuf h on ST_Intersects(s.geom, h.geom) where s.g='us-ca-san-francisco' and s.length_m>0
             group by s.eid, s.length_m) s join gkg.entity n on n.geofence_id='us-ca-san-francisco'
             and n.urn='urn:urban-kg:HighInjuryNetwork:datasf-enwt-3u8m:network' where s.inside >= 0.5*s.length_m""")
    edges("uko:hinSegmentOf", "DataSF enwt-3u8m (2024 HIN)", "HIN feature to road segments with at least 10 m inside its 10 m buffer",
          """select h.eid, s.eid, null::real from gkg_work.aux h join gkg_work.seg s on h.kind='hin_feature' and s.g=h.g and ST_DWithin(h.geom, s.geom, 10)
             where ST_Length(ST_Intersection(s.geom, ST_Buffer(h.geom, 10))) >= 10""")
    # Risk profiles: one per intersection node with attached crashes.
    X("delete from gkg.entity where src='aux:risk_profile'")
    X("delete from gkg.aux_entity where kind='risk_profile'")
    X("""insert into gkg.aux_entity select a.geofence_id, 'urn:urban-kg:IntersectionRiskProfile:tims:'||md5(a.node_urn), 'uko:IntersectionRiskProfile',
         'risk_profile', null, jsonb_build_object('crashes_2021_2025', count(*) filter (where c.accident_year between 2021 and 2025),
         'crashes_all', count(*), 'crash_derived', true), null
         from gkg.crash_attachment a join gkg.tims_crash c using (case_id) where a.node_urn is not null group by a.geofence_id, a.node_urn""")
    _aux_register("risk_profile")
    edges("uko:hasIntersectionRiskProfile", "TIMS (crash_attachment)", "intersection node to its crash profile",
          """select n.eid, p.eid, null::real from (select distinct geofence_id, node_urn from gkg.crash_attachment where node_urn is not null) a
             join gkg.entity n on n.geofence_id=a.geofence_id and n.urn=a.node_urn
             join gkg.entity p on p.geofence_id=a.geofence_id and p.urn='urn:urban-kg:IntersectionRiskProfile:tims:'||md5(a.node_urn)""")
    # Truck restrictions from Overture access_restrictions (mode hgv), one constraint entity per segment and rule.
    X("delete from gkg.entity where src='aux:truck_constraint'")
    X("delete from gkg.aux_entity where kind='truck_constraint'")
    X("""insert into gkg.aux_entity select s.geofence_id, 'urn:urban-kg:TruckRoutingConstraint:overture:'||md5(s.urn||r.ord),
         case when r.rule->>'access_type'='designated' then 'uko:TruckRouteDesignation' else 'uko:RegulatoryRoutingConstraint' end,
         'truck_constraint', r.rule->>'access_type', jsonb_build_object('rule', r.rule, 'segment', s.urn), null
         from gkg.road_segment s cross join lateral jsonb_array_elements(s.access_restrictions) with ordinality r(rule, ord)
         where jsonb_typeof(s.access_restrictions)='array' and (r.rule->'when'->'mode') @> '["hgv"]'""")
    _aux_register("truck_constraint")
    edges("uko:hasTruckRoutingConstraint", "Overture 2026-10-21.0 access_restrictions", "segment to its hgv access rule",
          """select s.eid, c.eid, null::real from gkg.aux_entity a join gkg.entity c on c.geofence_id=a.geofence_id and c.urn=a.urn
             join gkg.entity s on s.geofence_id=a.geofence_id and s.urn=a.props->>'segment' where a.kind='truck_constraint'""")
    edges("uko:constrainsSegment", "Overture 2026-10-21.0 access_restrictions", "hgv access rule to its segment",
          """select c.eid, s.eid, null::real from gkg.aux_entity a join gkg.entity c on c.geofence_id=a.geofence_id and c.urn=a.urn
             join gkg.entity s on s.geofence_id=a.geofence_id and s.urn=a.props->>'segment' where a.kind='truck_constraint'""")
    edges("uko:hasTruckParkingFacility", "Overture; OpenStreetMap", "segment within 500 m of a truck parking facility",
          """select s.eid, p.eid, ST_Distance(s.geom, p.geom)::real from gkg_work.aux p join gkg_work.seg s on s.g=p.g
             and ST_DWithin(s.geom, p.geom, 500) where p.kind='parking' and p.uko_class='uko:TruckParkingFacility'""")
    srcmap = [("road_segment|intersection_node|pedestrian_edge|pedestrian_node|access_point|rail_segment|building|place|aux:city_block|aux:organization|aux:truck_constraint", "overture"),
              ("transit_stop|transit_route|transit_agency|service_calendar|walkshed_area|aux:trip|aux:stop_time|aux:service_exception|aux:fare_product|aux:service_area", "gtfs"),
              ("census_tract|aux:city|aux:county", "acs"), ("tims_crash|aux:risk_profile", "tims"),
              ("aux:common_space|aux:natural_area|aux:parking", "osm"),
              ("aux:neighborhood|aux:supervisor_district|aux:hin_feature|aux:hin_network", "datasf"), ("aux:pda", "mtc"),
              ("aux:gbfs_system|aux:gbfs_station", "gbfs")]
    for pat, k in srcmap:
        edges("uko:hasDataSource", "build records (gkg.build.source_versions)", f"entity to its {k} source release",
              f"""select e.eid, d.eid, null::real from gkg.entity e join gkg.entity d on d.geofence_id=e.geofence_id
                  and d.urn='urn:urban-kg:DataSource:{k}' where e.src ~ '^({pat})$'""")


def step_tims():
    """Load WEATHER_1/2, ROAD_SURFACE, ROAD_COND_1 from the TIMS files (decision 6) and build the REO crash links."""
    rows = []
    for f in sorted(TIMS_DIR.glob("*/Crashes*.csv")):
        with open(f, newline="", encoding="utf-8-sig", errors="replace") as fh:
            for r in csv.DictReader(fh):
                rows.append((r["CASE_ID"], r.get("WEATHER_1"), r.get("WEATHER_2"), r.get("ROAD_SURFACE"), r.get("ROAD_COND_1")))
    X("create temp table _w (case_id text, w1 text, w2 text, rs text, rc text)")
    copy("_w", ["case_id", "w1", "w2", "rs", "rc"], rows)
    n = conn.execute("update gkg.tims_crash c set weather_1=w.w1, weather_2=w.w2, road_surface=w.rs, road_cond_1=w.rc from "
                     "(select distinct on (case_id) * from _w) w where w.case_id=c.case_id").rowcount
    X("drop table _w")
    log(step="tims", rows_read=len(rows), crashes_updated=n)
    for c in ["reo:atIntersectionNode", "reo:hasCollisionCausationFactor", "reo:incidentCollisionType", "reo:incidentLighting",
              "reo:incidentRoadSurface", "reo:incidentWeatherCondition", "reo:onRoadSegment", "reo:hasKABCOSeverity"]:
        reset(c)
    X("delete from gkg.entity where src='reo_individual'")
    maps = {  # SWITRS codes -> REO 1.7.0 individuals; codes without an exact REO match get no edge
        "collision_type": ("reo:incidentCollisionType", {"A": "HEAD_ON", "B": "SIDESWIPE", "C": "REAR_END", "D": "BROADSIDE",
                           "F": "OVERTURNED", "G": "VEHICLE_PEDESTRIAN", "H": "COLLISION_TYPE_OTHER", "E": "COLLISION_TYPE_OTHER"}),
        "lighting": ("reo:incidentLighting", {"A": "LIGHTING_DAYLIGHT", "B": "LIGHTING_DUSK_DAWN", "C": "LIGHTING_DARK_STREET_LIGHTS",
                     "D": "LIGHTING_DARK_NO_LIGHTS", "-": "LIGHTING_NOT_STATED"}),
        "road_surface": ("reo:incidentRoadSurface", {"A": "SURFACE_DRY", "B": "SURFACE_WET", "C": "SURFACE_SNOWY_ICY", "D": "SURFACE_SLIPPERY",
                         "-": "SURFACE_NOT_STATED"}),
        "weather_1": ("reo:incidentWeatherCondition", {"A": "WEATHER_CLEAR", "B": "WEATHER_CLOUDY", "C": "WEATHER_RAINING", "D": "WEATHER_SNOWING",
                      "E": "WEATHER_FOG", "G": "WEATHER_WINDY", "-": "WEATHER_NOT_STATED"}),
        "trim(pcf_category)": ("reo:hasCollisionCausationFactor", {"01": "PCF_DUIInjury", "03": "PCF_UnsafeSpeed", "04": "PCF_FollowingTooClosely",
                               "07": "PCF_UnsafeTurnLaneChange", "21": "PCF_UnsafeStartBacking", "00": "PCF_Unknown"}),
    }
    rng = {"reo:incidentCollisionType": "reo:CollisionType", "reo:incidentLighting": "reo:LightingCondition",
           "reo:incidentRoadSurface": "reo:RoadSurfaceCondition", "reo:incidentWeatherCondition": "reo:WeatherCondition",
           "reo:hasCollisionCausationFactor": "reo:CollisionCausationFactor"}
    for col, (c, m) in maps.items():
        for g in GEOFENCES:
            for ind in sorted(set(m.values())):
                X("insert into gkg.entity (urn, geofence_id, uko_class, src) values (%(u)s, %(g)s, %(c)s, 'reo_individual') on conflict do nothing",
                  {"u": "urn:route-event-kg:" + ind, "g": g, "c": rng[c]})
        vals = ",".join(f"('{k}','urn:route-event-kg:{v}')" for k, v in m.items())
        edges(c, "TIMS SWITRS (downloaded 2026-11-10)", f"SWITRS {col} code to REO individual (exact matches only)",
              f"""select r.eid, i.eid, null::real from gkg.crash_attachment a join gkg.tims_crash t using (case_id)
                  join (values {vals}) m(code, u) on m.code = {('t.' + col) if not col.startswith('trim') else 'trim(t.pcf_category)'}
                  join gkg.entity r on r.geofence_id=a.geofence_id and r.urn='urn:route-event-kg:HistoricalIncidentRecord:tims:'||a.case_id
                  join gkg.entity i on i.geofence_id=a.geofence_id and i.urn=m.u""")
    edges("reo:atIntersectionNode", "TIMS SWITRS; Overture", "crash attached to intersection node within 50 m (stage 4)",
          """select r.eid, n.eid, a.node_snap_m::real from gkg.crash_attachment a
             join gkg.entity r on r.geofence_id=a.geofence_id and r.urn='urn:route-event-kg:HistoricalIncidentRecord:tims:'||a.case_id
             join gkg.entity n on n.geofence_id=a.geofence_id and n.urn=a.node_urn""")
    # REO 1.7.0 (audit item O1): crash to road segment, and KABCO severity. Both crash-derived.
    edges("reo:onRoadSegment", "TIMS SWITRS; Overture", "crash attached to road segment (stage 4 snap; value_m = snap distance)",
          """select r.eid, s.eid, a.segment_snap_m::real from gkg.crash_attachment a
             join gkg.entity r on r.geofence_id=a.geofence_id and r.urn='urn:route-event-kg:HistoricalIncidentRecord:tims:'||a.case_id
             join gkg.entity s on s.geofence_id=a.geofence_id and s.urn=a.segment_urn""")
    for g in GEOFENCES:
        for k in "KABCO":
            X("insert into gkg.entity (urn, geofence_id, uko_class, src) values (%(u)s, %(g)s, 'reo:KABCOSeverity', 'reo_individual') "
              "on conflict do nothing", {"u": "urn:route-event-kg:KABCO_" + k, "g": g})
    edges("reo:hasKABCOSeverity", "TIMS SWITRS", "SWITRS COLLISION_SEVERITY to KABCO through reo:SeverityCodeMapping rows SEVMAP_SWITRS_CA_*",
          """select r.eid, i.eid, null::real from gkg.crash_attachment a join gkg.tims_crash t using (case_id)
             join (values (1,'K'),(2,'A'),(3,'B'),(4,'C'),(0,'O')) m(code, k) on m.code = t.severity
             join gkg.entity r on r.geofence_id=a.geofence_id and r.urn='urn:route-event-kg:HistoricalIncidentRecord:tims:'||a.case_id
             join gkg.entity i on i.geofence_id=a.geofence_id and i.urn='urn:route-event-kg:KABCO_'||m.k""")


def step_transit():
    """Trips, stop times, service exceptions, transfers, fares and service areas from the GTFS datasets the
    transit stage used (gkg.build.source_versions), restricted to the stored reference service day."""
    for c in ["uko:hasTrip", "uko:hasStopTime", "uko:atStop", "uko:hasServiceCalendar", "uko:hasServiceException",
              "uko:hasTransferTo", "uko:fareProductOfAgency", "uko:hasServiceArea", "uko:anchorStation", "uko:hasTransitAccess",
              "uko:operatedBySystem"]:
        reset(c)
    for k in ["trip", "stop_time", "service_exception", "fare_product", "service_area"]:
        X("delete from gkg.entity where src=%(s)s", {"s": "aux:" + k})
        X("delete from gkg.aux_entity where kind=%(k)s", {"k": k})
    sys.path.insert(0, str(ROOT))
    from gkg.stage3_transit import read as gread
    T = lambda kind, *p: f"urn:urban-kg:{kind}:gtfs:{uuid.uuid5(URN_NS, '|'.join([kind] + [str(x) for x in p]))}"
    for g in GEOFENCES:
        sv = Q("select source_versions from gkg.build where geofence_id=%(g)s and stage='stage3-transit' order by build_id desc limit 1", {"g": g})[0][0]
        feeds = [f for f in sv.get("feeds", []) if f.get("dataset") and f.get("status") == "loaded"]
        trips, stimes, exc, xfer, fares = [], [], [], [], []
        st_rows = Q("select feed_id, trip_id, stop_urn, route_urn, stop_sequence from gkg.transit_stop_time where geofence_id=%(g)s", {"g": g})
        trip_set = {(r[0], r[1]): r[3] for r in st_rows}
        for f in feeds:
            path = GTFS_CACHE / f["feed"] / f"{f['dataset']}.zip"
            if not path.exists():
                log(step="transit", warning="dataset zip missing", feed=f["feed"])
                continue
            with zipfile.ZipFile(path) as zf:
                tr = gread(zf, "trips.txt", ["route_id", "service_id", "trip_id"])
                for _, t in tr.iterrows():
                    if (f["feed"], t["trip_id"]) in trip_set:
                        trips.append((g, T("TransitTrip", f["feed"], t["trip_id"]), f["feed"], t["trip_id"],
                                      T("TransitRoute", f["feed"], t["route_id"]), T("ServiceCalendar", f["feed"], t["service_id"]), t["service_id"]))
                cd = gread(zf, "calendar_dates.txt", ["service_id", "date", "exception_type"])
                if cd is not None:
                    used = {t[6] for t in trips if t[2] == f["feed"]}
                    for _, c in cd[cd["service_id"].isin(used)].iterrows():
                        exc.append((g, T("ServiceException", f["feed"], c["service_id"], c["date"]), T("ServiceCalendar", f["feed"], c["service_id"]),
                                    c["date"], c["exception_type"]))
                tf = gread(zf, "transfers.txt", ["from_stop_id", "to_stop_id", "transfer_type", "min_transfer_time"])
                if tf is not None:
                    for _, x in tf.iterrows():
                        if x["from_stop_id"] and x["to_stop_id"] and x["from_stop_id"] != x["to_stop_id"]:
                            xfer.append((T("TransitStop", f["feed"], x["from_stop_id"]), T("TransitStop", f["feed"], x["to_stop_id"]), f["feed"]))
                fa = gread(zf, "fare_attributes.txt", ["fare_id", "price", "currency_type", "agency_id"])
                ag = gread(zf, "agency.txt", ["agency_id", "agency_name"])
                if fa is not None and ag is not None and len(ag):
                    for _, x in fa.iterrows():
                        a_id = x["agency_id"] or ag.iloc[0]["agency_id"] or ag.iloc[0]["agency_name"]
                        fares.append((g, T("FareProduct", f["feed"], x["fare_id"]), x["fare_id"], x["price"], x["currency_type"],
                                      T("TransitAgency", f["feed"], a_id)))
        for (fid, tid, su, ru, seq) in st_rows:
            stimes.append((g, T("StopTime", fid, tid, seq, su), T("TransitTrip", fid, tid), su))
        X("create temp table _a (geofence_id text, urn text, uko_class text, kind text, name text, props jsonb)")
        copy("_a", ["geofence_id", "urn", "uko_class", "kind", "name", "props"],
             [(g, t[1], "uko:TransitTrip", "trip", t[3], json.dumps({"route": t[4], "calendar": t[5]})) for t in trips]
             + [(g, s[1], "uko:StopTime", "stop_time", None, json.dumps({"trip": s[2], "stop": s[3]})) for s in stimes]
             + [(g, e[1], "uko:ServiceException", "service_exception", e[3], json.dumps({"calendar": e[2], "exception_type": e[4]})) for e in exc]
             + [(g, x[1], "uko:FareProduct", "fare_product", x[2], json.dumps({"price": x[3], "currency": x[4], "agency": x[5], "gtfs_fares_version": "v1"})) for x in fares])
        X("insert into gkg.aux_entity (geofence_id, urn, uko_class, kind, name, props) select distinct on (geofence_id, urn) * from _a on conflict do nothing")
        X("drop table _a")
        X("create temp table _x (a text, b text, feed text)")
        copy("_x", ["a", "b", "feed"], xfer)
        X("create table if not exists gkg_work.xfer (geofence_id text, a text, b text, feed text)")
        X("delete from gkg_work.xfer where geofence_id=%(g)s", {"g": g})
        X("insert into gkg_work.xfer select %(g)s, a, b, feed from _x", {"g": g})
        X("drop table _x")
        log(step="transit", geofence=g, feeds=len(feeds), trips=len(trips), stop_times=len(stimes), exceptions=len(exc),
            transfers_listed=len(xfer), fare_products=len(fares))
    # Service areas: 400 m around each route's stops.
    X("""insert into gkg.aux_entity select r.geofence_id, 'urn:urban-kg:ServiceArea:gkgfull:'||md5(r.urn), 'uko:ServiceArea', 'service_area',
         r.short_name, jsonb_build_object('route', r.urn, 'buffer_m', 400),
         ST_Transform(ST_Union(ST_Buffer(ST_Transform(s.geom, 3310), 400)), 4326)
         from gkg.transit_route r join gkg.transit_stop s on s.geofence_id=r.geofence_id and r.urn = any(s.route_urns)
         group by r.geofence_id, r.urn, r.short_name""")
    for k in ["trip", "stop_time", "service_exception", "fare_product", "service_area"]:
        _aux_register(k)
    a = "join gkg.entity {x} on {x}.geofence_id=a.geofence_id and {x}.urn={u}"
    edges("uko:hasTrip", "GTFS trips.txt", "route to trips running on the reference day",
          "select r.eid, t.eid, null::real from gkg.aux_entity a " + a.format(x="t", u="a.urn") + " " + a.format(x="r", u="a.props->>'route'") + " where a.kind='trip'")
    edges("uko:hasServiceCalendar", "GTFS trips.txt", "trip to its service_id calendar",
          "select t.eid, c.eid, null::real from gkg.aux_entity a " + a.format(x="t", u="a.urn") + " " + a.format(x="c", u="a.props->>'calendar'") + " where a.kind='trip'")
    edges("uko:hasStopTime", "GTFS stop_times.txt", "trip to its stop times",
          "select t.eid, s.eid, null::real from gkg.aux_entity a " + a.format(x="s", u="a.urn") + " " + a.format(x="t", u="a.props->>'trip'") + " where a.kind='stop_time'")
    edges("uko:atStop", "GTFS stop_times.txt", "stop time to its stop",
          "select s.eid, p.eid, null::real from gkg.aux_entity a " + a.format(x="s", u="a.urn") + " " + a.format(x="p", u="a.props->>'stop'") + " where a.kind='stop_time'")
    edges("uko:hasServiceException", "GTFS calendar_dates.txt", "calendar to its exception dates",
          "select c.eid, e.eid, null::real from gkg.aux_entity a " + a.format(x="e", u="a.urn") + " " + a.format(x="c", u="a.props->>'calendar'") + " where a.kind='service_exception'")
    edges("uko:fareProductOfAgency", "GTFS fare_attributes.txt (Fares v1)", "fare product to its agency",
          "select f.eid, g.eid, null::real from gkg.aux_entity a " + a.format(x="f", u="a.urn") + " " + a.format(x="g", u="a.props->>'agency'") + " where a.kind='fare_product'")
    edges("uko:hasServiceArea", "GTFS; derived", "route to the area within 400 m of its stops",
          "select r.eid, s.eid, null::real from gkg.aux_entity a " + a.format(x="s", u="a.urn") + " " + a.format(x="r", u="a.props->>'route'") + " where a.kind='service_area'")
    edges("uko:hasTransferTo", "GTFS transfers.txt", "listed transfer pairs",
          "select a1.eid, b1.eid, null::real from gkg_work.xfer a join gkg.entity a1 on a1.geofence_id=a.geofence_id and a1.urn=a.a "
          "join gkg.entity b1 on b1.geofence_id=a.geofence_id and b1.urn=a.b")
    edges("uko:hasTransferTo", "GTFS; derived", "feeds without transfers.txt: stops of different routes within 200 m (decision B5)",
          """select a.eid, b.eid, ST_Distance(a.geom, b.geom)::real from gkg_work.stop a join gkg_work.stop b on b.g=a.g and a.eid<>b.eid
             and ST_DWithin(a.geom, b.geom, 200) and not (a.route_urns && b.route_urns)
             where coalesce(a.location_type,0)=0 and coalesce(b.location_type,0)=0
               and a.feed_id not in (select distinct feed from gkg_work.xfer) and b.feed_id not in (select distinct feed from gkg_work.xfer)""")
    edges("uko:anchorStation", "MTC PDAs; GTFS", "transit station (location_type 1, or a rail stop) inside the PDA",
          """select p.eid, s.eid, null::real from gkg_work.aux p join gkg_work.stop s on s.g=p.g and ST_Contains(p.geom, s.geom)
             where p.kind='pda' and s.uko_class='uko:TransitStation'""")
    edges("uko:hasTransitAccess", "GTFS; Overture", "building point on surface inside a stop's 800 m walkshed",
          """select b.eid, s.eid, null::real from gkg_work.shed w join gkg_work.bldc b on b.g=w.g and ST_Contains(w.geom, b.geom)
             join gkg.entity s on s.geofence_id=w.g and s.urn=w.origin_urn""")
    edges("uko:operatedBySystem", "Bay Wheels GBFS 2.3", "station to system",
          """select s.eid, y.eid, null::real from gkg.entity s join gkg.entity y on y.geofence_id=s.geofence_id and y.uko_class='uko:SharedMobilitySystem'
             where s.uko_class='uko:SharedMobilityStation'""")


def _walk_graph(g):
    """Walking network (road segments except motorways, pedestrian edges, access points) in EPSG:3310."""
    from scipy.sparse import coo_matrix
    rows = Q("""select from_node, to_node, length_m from gkg.road_segment where geofence_id=%(g)s and coalesce(road_classification,'')<>'motorway'
                union all select from_node, to_node, length_m from gkg.pedestrian_edge where geofence_id=%(g)s
                union all select intersection_node, pedestrian_node, 0 from gkg.access_point where geofence_id=%(g)s""", {"g": g})
    pts = Q("""select e.eid, n.urn, ST_X(ST_Transform(n.geom,3310)), ST_Y(ST_Transform(n.geom,3310)) from gkg.intersection_node n
               join gkg.entity e on e.geofence_id=n.geofence_id and e.urn=n.urn where n.geofence_id=%(g)s
               union all select null, urn, ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.pedestrian_node where geofence_id=%(g)s""", {"g": g})
    idx = {p[1]: i for i, p in enumerate(pts)}
    keep = [(idx[a], idx[b], max(float(w or 0), 0.01)) for a, b, w in rows if a in idx and b in idx]
    a, b, w = (np.array(v) for v in zip(*keep))
    n = len(pts)
    m = coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    xy = np.array([[p[2], p[3]] for p in pts])
    node_eid = np.array([p[0] if p[0] is not None else -1 for p in pts], dtype=np.int64)
    return m, xy, node_eid


NODES_NEAR = """select ST_X(n.geom), ST_Y(n.geom) from gkg_work.node n join gkg_work.aux x on x.eid=%({a})s and n.g=%(g)s
    and ST_DWithin(x.geom, n.geom, 20)
    union all select ST_X(n.geom), ST_Y(n.geom) from gkg_work.pnode n join gkg_work.aux x on x.eid=%({a})s and n.g=%(g)s
    and ST_DWithin(x.geom, n.geom, 20)"""


def step_distances():
    """uko:DistanceMeasurement rows: places, stops and intersections to landmark buildings and districts within
    2 km; straight line (EPSG:3310) and walking distance (Dijkstra on the walking network, 2 km limit)."""
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    r = rid("uko:hasDistanceMeasurement") if Q("select 1 from gkg.relation_type where curie='uko:hasDistanceMeasurement'") else None
    X("truncate gkg.distance_measurement")
    if r:
        X("delete from gkg.provenance where rid=%(r)s", {"r": r})
    p_lm = pid("uko:hasDistanceMeasurement", "Overture places; GTFS; walking network", "to landmark building within 2 km: straight line and walking distance (point)")
    p_ds = pid("uko:hasDistanceMeasurement", "DataSF SF Find; MTC PDAs; walking network", "to district within 2 km: distance to boundary, 0 inside; walking distance to nearest node in or within 20 m of it")
    lmc = "(" + ",".join(f"'uko:{c}'" for c in LANDMARK) + ")"
    for g in GEOFENCES:
        t0 = time.time()
        m, xy, node_eid = _walk_graph(g)
        tree = cKDTree(xy)
        # Targets.
        lm = Q(f"select p.eid, ST_X(p.geom), ST_Y(p.geom) from gkg_work.place p where p.g=%(g)s and p.uko_class in {lmc}", {"g": g})
        ds = Q("select eid from gkg_work.aux where g=%(g)s and kind in ('neighborhood','pda') and coalesce(props->>'scheme','') not like 'SF Analysis%%'", {"g": g})
        # Sources with their snap node and offset.
        src = Q("select eid, ST_X(geom), ST_Y(geom) from gkg_work.pts where g=%(g)s", {"g": g})
        s_eid = np.array([s[0] for s in src], dtype=np.int64)
        s_xy = np.array([[s[1], s[2]] for s in src])
        s_off, s_node = tree.query(s_xy, k=1)
        pos = pd.Series(np.arange(len(s_eid)), index=s_eid)
        out = 0
        # Landmarks: straight-line pairs from SQL, walking from Dijkstra per batch of targets.
        lm_eid = np.array([x[0] for x in lm], dtype=np.int64)
        lm_off, lm_node = tree.query(np.array([[x[1], x[2]] for x in lm]), k=1) if lm else (np.array([]), np.array([], int))
        pairs = pd.DataFrame(Q(f"""select a.eid, t.eid, ST_Distance(a.geom, t.geom) from gkg_work.pts a join gkg_work.place t on t.g=a.g
                                   and t.uko_class in {lmc} and a.eid<>t.eid and ST_DWithin(a.geom, t.geom, 2000) where a.g=%(g)s""", {"g": g}),
                             columns=["s", "t", "d"])
        lm_pos = pd.Series(np.arange(len(lm_eid)), index=lm_eid)
        walk = np.full(len(pairs), np.nan, dtype=np.float32)
        if len(pairs):
            tp = lm_pos[pairs.t.values].values
            sp = pos[pairs.s.values].values
            for b0 in range(0, len(lm_eid), 256):
                sel = np.where((tp >= b0) & (tp < b0 + 256))[0]
                if not len(sel):
                    continue
                D = dijkstra(m, directed=False, indices=lm_node[b0:b0 + 256], limit=2000).astype(np.float32)
                v = D[tp[sel] - b0, s_node[sp[sel]]] + s_off[sp[sel]] + lm_off[tp[sel]]
                walk[sel] = np.where(np.isfinite(v), v, np.nan)
        rows = ((int(a), int(b), float(d), None if np.isnan(w) else float(w), "point", False, p_lm)
                for a, b, d, w in zip(pairs.s.values, pairs.t.values, pairs.d.values, walk))
        out += copy("gkg.distance_measurement", ["subj", "target", "straight_m", "walk_m", "measured_to", "inside_target", "pid"], rows)
        # Districts: straight-line distance to boundary from SQL; walking by multi-source Dijkstra per district.
        for (deid,) in ds:
            dp = pd.DataFrame(Q("""select a.eid, case when ST_Contains(d.geom, a.geom) then 0 else ST_Distance(a.geom, d.geom) end,
                                          ST_Contains(d.geom, a.geom) from gkg_work.pts a join gkg_work.aux d on d.eid=%(d)s
                                   and ST_DWithin(a.geom, d.geom, 2000) where a.g=%(g)s""", {"d": deid, "g": g}), columns=["s", "d", "inside"])
            if not len(dp):
                continue
            inn = Q(NODES_NEAR.format(a="d"), {"d": deid, "g": g})
            sp = pos[dp.s.values].values
            if inn:
                _, srcn = tree.query(np.array(inn), k=1)
                D = dijkstra(m, directed=False, indices=np.unique(srcn), limit=2000, min_only=True).astype(np.float32)
                v = D[s_node[sp]] + s_off[sp]
                v = np.where(dp.inside.values, 0.0, v)
            else:
                v = np.full(len(dp), np.nan)
            rows = ((int(a), int(deid), float(d), None if not np.isfinite(w) else float(w), "boundary", bool(i), p_ds)
                    for a, d, i, w in zip(dp.s.values, dp.d.values, dp.inside.values, v))
            out += copy("gkg.distance_measurement", ["subj", "target", "straight_m", "walk_m", "measured_to", "inside_target", "pid"], rows)
        log(step="distances", geofence=g, landmarks=len(lm), districts=len(ds), rows=out, seconds=round(time.time() - t0, 1))


def step_recreation():
    """uko:providesRecreationFor: common space to every census tract with a walking-network node within an
    800 m walk of it (decision B7)."""
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    reset("uko:providesRecreationFor")
    p = pid("uko:providesRecreationFor", "OpenStreetMap; Census TIGER 2024; walking network",
            "tracts with a network node within an 800 m walk of the common space (nodes within 20 m of it are sources)")
    total = 0
    for g in GEOFENCES:
        m, xy, _ = _walk_graph(g)
        tree = cKDTree(xy)
        tr = Q("""select t.eid, ST_X(n.geom), ST_Y(n.geom) from (select ST_Transform(geom,3310) geom from gkg.intersection_node where geofence_id=%(g)s) n
                  join gkg_work.tract t on t.g=%(g)s and ST_Contains(t.geom, n.geom)""", {"g": g})
        _, tnode = tree.query(np.array([[r[1], r[2]] for r in tr]), k=1)
        node_tract = pd.Series([r[0] for r in tr], index=tnode).groupby(level=0).first()
        parks = Q("select eid from gkg_work.aux where g=%(g)s and kind='common_space'", {"g": g})
        out = []
        for (pe,) in parks:
            inn = Q(NODES_NEAR.format(a="d"), {"d": pe, "g": g})
            if not inn:
                continue
            _, srcn = tree.query(np.array(inn), k=1)
            D = dijkstra(m, directed=False, indices=np.unique(srcn), limit=800, min_only=True)
            reached = np.where(np.isfinite(D))[0]
            tracts = set(node_tract.reindex(reached).dropna().astype(np.int64).tolist())
            out += [(1, pe, t) for t in tracts]
        r = rid("uko:providesRecreationFor")
        total += copy("gkg.edge", ["rid", "subj", "obj", "pid"], [(r, a, b, p) for _, a, b in out])
        log(step="recreation", geofence=g, parks=len(parks), edges=len(out))


def step_enforce():
    """Remove edges whose subject or object fails the property's domain or range; count them."""
    X("truncate gkg.edge_rejected")
    X("drop table if exists gkg_work.ok")
    X("""create unlogged table gkg_work.ok as select e.eid, c.ancestor cls from gkg.entity e join gkg.class_closure c on c.uko_class=e.uko_class
         union select t.eid, c.ancestor from gkg.entity_type t join gkg.class_closure c on c.uko_class=t.uko_class""")
    X("create index on gkg_work.ok (eid, cls)")
    X("analyze gkg_work.ok")
    for r, curie, dom, rng in Q("select rid, curie, domain_classes, range_classes from gkg.relation_type order by rid"):
        for side, classes in (("subj", dom), ("obj", rng)):
            if not classes or "owl:Thing" in classes:
                continue
            ex = Q(f"""select es.uko_class, eo.uko_class, count(*) over () from gkg.edge x join gkg.entity es on es.eid=x.subj
                       join gkg.entity eo on eo.eid=x.obj where x.rid=%(r)s and not exists
                       (select 1 from gkg_work.ok k where k.eid=x.{side} and k.cls = any(%(c)s)) limit 1""", {"r": r, "c": classes})
            if not ex:
                continue
            n = conn.execute(f"""delete from gkg.edge x where x.rid=%(r)s and not exists
                                 (select 1 from gkg_work.ok k where k.eid=x.{side} and k.cls = any(%(c)s))""", {"r": r, "c": classes}).rowcount
            X("insert into gkg.edge_rejected (rid, reason, n, example_subj_class, example_obj_class) values (%(r)s,%(w)s,%(n)s,%(a)s,%(b)s)",
              {"r": r, "w": ("domain" if side == "subj" else "range") + " not in " + ",".join(classes), "n": n, "a": ex[0][0], "b": ex[0][1]})
            log(step="enforce", relation=curie, side=side, removed=n, example=[ex[0][0], ex[0][1]])
    # Distance measurements: subject must be a SpatialEntity (always true here); recorded for completeness.


def step_index():
    X("create index if not exists edge_subj on gkg.edge (subj, rid)")
    X("create index if not exists edge_obj on gkg.edge (obj, rid)")
    X("create index if not exists edge_rid on gkg.edge (rid)")
    X("create index if not exists dm_subj on gkg.distance_measurement (subj)")
    X("create index if not exists dm_target on gkg.distance_measurement (target)")
    X("create index if not exists entity_urn on gkg.entity (urn)")
    X("analyze gkg.edge; analyze gkg.distance_measurement; analyze gkg.entity")
    X("analyze gkg.edge")
    log(step="index", edge_gb=Q("select round(pg_total_relation_size('gkg.edge')/1e9,2)")[0][0],
        dm_gb=Q("select round(pg_total_relation_size('gkg.distance_measurement')/1e9,2)")[0][0],
        entity_gb=Q("select round(pg_total_relation_size('gkg.entity')/1e9,2)")[0][0])


def step_retype():
    """Clear the per-entity type assertions that UKO 15.7 made unnecessary (subclass axioms now in the ontology)."""
    n = Q("select count(*) from gkg.entity_type")[0][0]
    X("truncate gkg.entity_type")
    log(step="retype", removed_assertions=n)


def step_views():
    """Read views: named edges, veryNear, and the export that crash-prediction work must use."""
    X("""create or replace view gkg.edge_named as select t.curie relation, s.urn subject_urn, s.uko_class subject_class,
         o.urn object_urn, o.uko_class object_class, s.geofence_id, x.value_m, p.source, p.method, p.code_version,
         p.ontology_version, t.crash_derived from gkg.edge x join gkg.relation_type t using (rid) join gkg.provenance p using (pid)
         join gkg.entity s on s.eid=x.subj join gkg.entity o on o.eid=x.obj""")
    X("""create or replace view gkg.rel_very_near as select x.subj, x.obj, x.value_m, x.pid from gkg.edge x
         where x.rid=(select rid from gkg.relation_type where curie='uko:near') and x.value_m <= 50""")
    X("""create or replace view gkg.edge_for_crash_prediction as select x.* from gkg.edge x join gkg.relation_type t using (rid)
         join gkg.entity s on s.eid=x.subj join gkg.entity o on o.eid=x.obj
         where not t.crash_derived and s.src not in ('tims_crash','aux:risk_profile','aux:hin_feature','aux:hin_network')
           and o.src not in ('tims_crash','aux:risk_profile','aux:hin_feature','aux:hin_network')""")
    log(step="views", views=3)


def step_cleanup():
    X("drop schema if exists gkg_work cascade")
    X("drop schema if exists gkg_load cascade")


STEPS = [("schema", step_schema), ("catalogue", step_catalogue), ("entities", step_entities), ("aux", step_aux),
         ("blocks", step_blocks), ("work", step_work), ("stored", step_stored), ("containment", step_containment),
         ("proximity", step_proximity), ("topology", step_topology), ("roadnet", step_roadnet), ("access", step_access),
         ("commons", step_commons), ("other", step_commercial_safety_freight), ("tims", step_tims), ("transit", step_transit),
         ("distances", step_distances), ("recreation", step_recreation), ("retype", step_retype), ("index", step_index), ("enforce", step_enforce),
         ("views", step_views), ("cleanup", step_cleanup)]

if __name__ == "__main__":
    if sys.argv[1:] == ["--catalogue"]:
        print(catalogue_from_ontology(CATALOGUE), "closure rows")
        raise SystemExit
    want = sys.argv[1:] or [s for s, _ in STEPS]
    t0 = time.time()
    for name, fn in STEPS:
        if name in want:
            t = time.time()
            log(step=name, status="start")
            fn()
            log(step=name, status="done", seconds=round(time.time() - t, 1))
    log(step="all", seconds=round(time.time() - t0, 1),
        free_disk=subprocess.run(["df", "-h", "/System/Volumes/Data"], capture_output=True, text=True).stdout.splitlines()[-1])
