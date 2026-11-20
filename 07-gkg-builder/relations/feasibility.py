"""GKG full build, Step 2: timed samples per relation family (no graph is built).

python feasibility.py OUTDIR [SAMPLE_PCT]

Runs on the Mac mini. For each relation family and geofence it computes the relation for a random sample of source
entities (hashtext(urn) mod 100 < SAMPLE_PCT), inside an UNLOGGED scratch schema gkg_feas that is dropped at the end,
and records: sample sources, rows produced, seconds, and bytes per row (pg_total_relation_size of the sample
table, with its index). The full-build estimate scales rows and seconds by (all sources / sampled sources).
Walking distances to landmarks are timed with SciPy Dijkstra on the Test 2 walk graph (work/test2-export).
Writes OUTDIR/feasibility.json and prints a table. Reads no trip table; writes no query output to the repository.
"""
import json, os, sys, time, resource, hashlib
import numpy as np
import pandas as pd
import psycopg

OUT = sys.argv[1]
PCT = int(sys.argv[2]) if len(sys.argv) > 2 else 2
DSN = os.environ.get("GEOMETIS_PG_DSN", "dbname=geometis")
GEOFENCES = ["us-ca-contra-costa-5", "us-ca-san-francisco"]
PUBLIC = os.path.expanduser("~/geometis-data/gkg/public/2026-11-20")
EXPORT = os.path.expanduser("~/Geometis-mini/work/test2-export")

# Landmark classes approved on Nov 20 (decision B1 addition).
LANDMARK = ["Museum", "Theater", "ConcertHall", "OperaHouse", "CityHall", "Courthouse", "Library",
            "GovernmentBuilding", "Stadium", "Arena"]
# Overture categories that hold theaters, concert and opera halls but have no UKO class mapping yet (Step 3 adds
# them); counted here so that the size estimate is an upper bound.
LANDMARK_CATS = ["performing_arts_venue", "music_venue"]
VULNERABLE = ["School", "ElementarySchool", "MiddleSchool", "HighSchool", "PrivateSchool", "Preschool",
              "ChildCareCenter", "SeniorCenter", "SeniorFacility", "NursingHome", "AssistedLivingFacility",
              "Hospital", "GeneralHospital", "ChildrensHospital"]

conn = psycopg.connect(DSN, autocommit=True, options="-c statement_timeout=1800000")
X = lambda sql, a=None: conn.execute(sql, a or {})
Q = lambda sql, a=None: conn.execute(sql, a or {}).fetchall()
os.makedirs(OUT, exist_ok=True)
results = []


def prep():
    X("DROP SCHEMA IF EXISTS gkg_feas CASCADE")
    X("CREATE SCHEMA gkg_feas")
    t = time.time()
    # Projected copies (EPSG:3310) of every layer the families use, with GiST indexes.
    for name, sql in [
        ("seg", "select geofence_id g, urn, road_classification cls, name, from_node, to_node, length_m, is_bridge, "
                "ST_Transform(geom,3310) geom from gkg.road_segment"),
        ("node", "select geofence_id g, urn, node_kind, ST_Transform(geom,3310) geom from gkg.intersection_node"),
        ("ped", "select geofence_id g, urn, edge_class, subclass, ST_Transform(geom,3310) geom from gkg.pedestrian_edge"),
        ("place", "select geofence_id g, urn, uko_class, basic_category, brand, name, ST_Transform(geom,3310) geom from gkg.place"),
        ("stop", "select geofence_id g, urn, ST_Transform(geom,3310) geom from gkg.transit_stop "
                 "where coalesce(location_type,0) in (0,1)"),
        ("bld", "select geofence_id g, urn, ST_Transform(geom,3310) geom from gkg.building"),
        ("tract", "select geofence_id g, urn, ST_Transform(geom,3310) geom from gkg.census_tract"),
        ("rail", "select geofence_id g, urn, ST_Transform(geom,3310) geom from gkg.rail_segment"),
    ]:
        X(f"CREATE UNLOGGED TABLE gkg_feas.{name} AS {sql}")
        X(f"CREATE INDEX ON gkg_feas.{name} USING gist (geom)")
        X(f"CREATE INDEX ON gkg_feas.{name} (g)")
        X(f"ANALYZE gkg_feas.{name}")
    # Public polygons (EPSG:3310): districts = SF Find neighborhoods (117) + MTC PDAs in the six cities; SF 2024 HIN.
    import subprocess
    for f, tbl in (("sf_find_neighborhoods.geojson", "pub_sffind"), ("mtc_pda_pba2050plus.geojson", "pub_pda"),
                   ("sf_hin_2024.geojson", "pub_hin")):
        subprocess.run(["/opt/homebrew/bin/ogr2ogr", "-f", "PostgreSQL", "PG:dbname=geometis", os.path.join(PUBLIC, f),
                        "-nln", "gkg_feas." + tbl, "-t_srs", "EPSG:3310", "-lco", "GEOMETRY_NAME=geom",
                        "-nlt", "PROMOTE_TO_MULTI", "-overwrite"], check=True)
    X("""CREATE UNLOGGED TABLE gkg_feas.pub_district AS
         select 'sffind:'||name id, 'us-ca-san-francisco' g, geom from gkg_feas.pub_sffind
         union all select 'pda:'||coalesce(pda_name, joinkey), case when jurisdicti='San Francisco' then 'us-ca-san-francisco'
           else 'us-ca-contra-costa-5' end, geom from gkg_feas.pub_pda
         where jurisdicti in ('San Francisco','Antioch','Concord','Pittsburg','Pleasant Hill','Walnut Creek')""")
    X("CREATE INDEX ON gkg_feas.pub_district USING gist (geom)")
    X("CREATE INDEX ON gkg_feas.pub_hin USING gist (geom)")
    results.append({"family": "setup: projected copies and indexes", "geofence": "both",
                    "seconds_full": round(time.time() - t, 1)})


def sample_family(family, prop, g, src_sql, body_sql, full_src_sql):
    """src_sql selects sampled source rows (urn, geom); body_sql builds rows from table s; returns a dict."""
    X("DROP TABLE IF EXISTS gkg_feas.s, gkg_feas.r")
    X(f"CREATE UNLOGGED TABLE gkg_feas.s AS {src_sql}", {"g": g, "pct": PCT})
    n_s = Q("select count(*) from gkg_feas.s")[0][0]
    t = time.time()
    X(f"CREATE UNLOGGED TABLE gkg_feas.r AS {body_sql}", {"g": g, "pct": PCT})
    sec = time.time() - t
    X("CREATE INDEX ON gkg_feas.r (subj)")
    n_r = Q("select count(*) from gkg_feas.r")[0][0]
    size = Q("select pg_total_relation_size('gkg_feas.r')")[0][0]
    n_full = Q(full_src_sql, {"g": g})[0][0]
    scale = n_full / max(n_s, 1)
    d = {"family": family, "property": prop, "geofence": g, "sources_sampled": n_s, "sources_full": n_full,
         "rows_sample": n_r, "seconds_sample": round(sec, 2), "rows_full": int(n_r * scale),
         "seconds_full": round(sec * scale, 1), "bytes_per_row": round(size / max(n_r, 1)),
         "gb_full": round(size * scale / 1e9, 3)}
    results.append(d)
    print(json.dumps(d), flush=True)


S = "where g=%(g)s and abs(hashtext(urn)) %% 100 < %(pct)s"
POINTS = ("(select urn, geom from gkg_feas.place {w} union all select urn, geom from gkg_feas.stop {w} "
          "union all select urn, geom from gkg_feas.node {w})")
POINTS_ALL = ("select (select count(*) from gkg_feas.place where g=%(g)s)+(select count(*) from gkg_feas.stop where g=%(g)s)"
              "+(select count(*) from gkg_feas.node where g=%(g)s)")
TGT_POINTS = ("(select urn, geom from gkg_feas.place where g=%(g)s union all select urn, geom from gkg_feas.stop where g=%(g)s "
              "union all select urn, geom from gkg_feas.node where g=%(g)s)")
cls_list = lambda L: "(" + ",".join("'" + c + "'" for c in L) + ")"
LM_WHERE = f"(uko_class in {cls_list(LANDMARK)} or basic_category in {cls_list(LANDMARK_CATS)})"


def families(g):
    sp = f"select * from {POINTS.format(w=S)} x"
    for dist, prop in ((200, "uko:near"), (50, "uko:veryNear")):
        sample_family("Proximity", prop, g, sp,
                      f"select s.urn subj, t.urn obj, ST_Distance(s.geom,t.geom) d from gkg_feas.s s join {TGT_POINTS} t "
                      f"on ST_DWithin(s.geom,t.geom,{dist}) and s.urn<>t.urn", POINTS_ALL)
    sample_family("Proximity", "uko:nearTransitStop (400 m)", g, f"select urn, geom from gkg_feas.bld {S}",
                  "select s.urn subj, t.urn obj, ST_Distance(s.geom,t.geom) d from gkg_feas.s s join gkg_feas.stop t "
                  "on t.g=%(g)s and ST_DWithin(s.geom,t.geom,400)", "select count(*) from gkg_feas.bld where g=%(g)s")
    sample_family("Proximity", "uko:hasVulnerablePopulationNearby (200 m)", g, sp,
                  f"select s.urn subj, t.urn obj from gkg_feas.s s join gkg_feas.place t on t.g=%(g)s and t.uko_class in "
                  f"{cls_list(VULNERABLE)} and ST_DWithin(s.geom,t.geom,200) and s.urn<>t.urn", POINTS_ALL)
    sample_family("Proximity", "uko:nearVulnerablePopulation (200 m)", g, f"select urn, geom from gkg_feas.seg {S}",
                  f"select s.urn subj, t.urn obj from gkg_feas.s s join gkg_feas.place t on t.g=%(g)s and t.uko_class in "
                  f"{cls_list(VULNERABLE)} and ST_DWithin(s.geom,t.geom,200)", "select count(*) from gkg_feas.seg where g=%(g)s")
    sample_family("Access", "uko:accessibleBy / frontageOn / providesAccessTo (nearest street, 30 m)", g,
                  f"select urn, geom from gkg_feas.bld {S}",
                  "select s.urn subj, r.urn obj, r.d from gkg_feas.s s cross join lateral (select urn, ST_Distance(s.geom,geom) d "
                  "from gkg_feas.seg where g=%(g)s and cls not in ('motorway','track') order by geom <-> s.geom limit 1) r "
                  "where r.d<=30", "select count(*) from gkg_feas.bld where g=%(g)s")
    sample_family("Access", "uko:accessibleBySidewalk (50 m)", g, f"select urn, geom from gkg_feas.bld {S}",
                  "select s.urn subj, r.urn obj from gkg_feas.s s cross join lateral (select urn from gkg_feas.ped "
                  "where g=%(g)s and subclass='sidewalk' and ST_DWithin(s.geom,geom,50) order by geom <-> s.geom limit 1) r",
                  "select count(*) from gkg_feas.bld where g=%(g)s")
    sample_family("Access", "uko:alongsideOf (sidewalk to road, 25 m, 20 degrees)", g,
                  f"select urn, geom from gkg_feas.ped {S} and subclass='sidewalk'",
                  "select s.urn subj, r.urn obj from gkg_feas.s s cross join lateral (select urn from gkg_feas.seg "
                  "where g=%(g)s and ST_DWithin(s.geom,geom,25) and mod((degrees(ST_Azimuth(ST_StartPoint(s.geom),"
                  "ST_EndPoint(s.geom)))-degrees(ST_Azimuth(ST_StartPoint(geom),ST_EndPoint(geom)))+360)::numeric,180) "
                  "not between 20 and 160 "
                  "order by geom <-> s.geom limit 1) r",
                  "select count(*) from gkg_feas.ped where g=%(g)s and subclass='sidewalk'")
    sample_family("Containment", "uko:withinCensusTract (points)", g, sp,
                  "select s.urn subj, t.urn obj from gkg_feas.s s join gkg_feas.tract t on t.g=%(g)s and ST_Contains(t.geom,s.geom)",
                  POINTS_ALL)
    sample_family("Topology", "uko:sharesWallWith (buildings, shared edge >= 1 m)", g, f"select urn, geom from gkg_feas.bld {S}",
                  "select s.urn subj, t.urn obj from gkg_feas.s s join gkg_feas.bld t on t.g=%(g)s and s.urn<>t.urn and "
                  "ST_DWithin(s.geom,t.geom,0.5) and ST_Length(ST_Intersection(ST_Boundary(ST_Buffer(s.geom,0.3)),t.geom))>=1",
                  "select count(*) from gkg_feas.bld where g=%(g)s")
    sample_family("Topology", "uko:crossesOver/Under (road over road, no shared node)", g,
                  f"select urn, geom, from_node, to_node from gkg_feas.seg {S}",
                  "select s.urn subj, t.urn obj from gkg_feas.s s join gkg_feas.seg t on t.g=%(g)s and ST_Crosses(s.geom,t.geom) "
                  "and s.from_node not in (t.from_node,t.to_node) and s.to_node not in (t.from_node,t.to_node)",
                  "select count(*) from gkg_feas.seg where g=%(g)s")
    sample_family("Topology", "uko:parallelTo (30 m, 15 degrees, 50 m overlap)", g,
                  f"select urn, geom from gkg_feas.seg {S} and length_m>=50",
                  "select s.urn subj, t.urn obj from gkg_feas.s s join gkg_feas.seg t on t.g=%(g)s and s.urn<>t.urn and "
                  "t.length_m>=50 and ST_DWithin(s.geom,t.geom,30) and mod((degrees(ST_Azimuth(ST_StartPoint(s.geom),"
                  "ST_EndPoint(s.geom)))-degrees(ST_Azimuth(ST_StartPoint(t.geom),ST_EndPoint(t.geom)))+360)::numeric,180) "
                  "not between 15 and 165 and "
                  "ST_Length(ST_Intersection(ST_Buffer(s.geom,30,'endcap=flat'),t.geom))>=50",
                  "select count(*) from gkg_feas.seg where g=%(g)s and length_m>=50")
    lm = f"select urn, geom from gkg_feas.place where g=%(g)s and {LM_WHERE}"
    sample_family("Landmark and district distances", "uko:hasDistanceMeasurement to landmark buildings (2 km, straight line)", g, sp,
                  f"select s.urn subj, t.urn obj, ST_Distance(s.geom,t.geom) d from gkg_feas.s s join ({lm}) t "
                  "on ST_DWithin(s.geom,t.geom,2000) and s.urn<>t.urn", POINTS_ALL)
    sample_family("Landmark and district distances", "uko:hasDistanceMeasurement to districts (2 km to boundary, 0 inside)", g, sp,
                  "select s.urn subj, t.id obj, case when ST_Contains(t.geom,s.geom) then 0 else ST_Distance(s.geom,t.geom) end d "
                  "from gkg_feas.s s join gkg_feas.pub_district t on ST_DWithin(s.geom,t.geom,2000)", POINTS_ALL)
    if g == "us-ca-san-francisco":
        sample_family("Safety (crash-flagged)", "uko:inHighInjuryNetwork (SF 2024 HIN, 10 m, 50% of length)", g,
                      f"select urn, geom, length_m from gkg_feas.seg {S}",
                      "select s.urn subj, 'hin' obj from gkg_feas.s s where s.length_m>0 and ST_Length(ST_Intersection(s.geom,"
                      "(select ST_Union(ST_Buffer(geom,10)) from gkg_feas.pub_hin h where ST_DWithin(h.geom,s.geom,10))))"
                      ">=0.5*s.length_m", "select count(*) from gkg_feas.seg where g=%(g)s")


def counts_only():
    """Families whose size is set by a join on stored tables: counted in full, no geometry."""
    t = time.time()
    rows = Q("""select g, count(*) from (select a.geofence_id g from gkg.seg_intersects a join gkg.seg_intersects b
                on a.geofence_id=b.geofence_id and a.node_urn=b.node_urn and a.segment_urn<b.segment_urn) z group by 1""")
    for g, n in rows:
        results.append({"family": "Road network", "property": "continuesAs/feedsInto/branchesFrom/mergesInto candidates "
                        "(segment pairs at a shared node; the rules keep a subset)", "geofence": g, "rows_full": n,
                        "seconds_full": round(time.time() - t, 1)})
    for g, n, tr in Q("select geofence_id, count(*), count(distinct trip_id) from gkg.transit_stop_time group by 1"):
        results.append({"family": "Transit", "property": "uko:hasStopTime / atStop (stop times) and TransitTrip entities",
                        "geofence": g, "rows_full": n, "trips": tr})
    for g, n in Q("select geofence_id, count(*) from gkg.place where brand is not null group by 1"):
        results.append({"family": "Commercial", "property": "uko:partOfChain / operatedByOrg (branded places)",
                        "geofence": g, "rows_full": n})
    for g, n in Q("select geofence_id, count(*) from gkg.road_segment where access_restrictions is not null group by 1"):
        results.append({"family": "Freight", "property": "uko:constrainsSegment candidates (segments with access "
                        "restrictions; truck-relevant subset smaller)", "geofence": g, "rows_full": n})


def walking(g):
    """Time Dijkstra (2 km limit) from a sample of landmark targets on the Test 2 walk graph."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    d = os.path.join(EXPORT, g)
    rd = lambda k, c=None: pd.read_parquet(os.path.join(d, f"{k}.parquet"), columns=c)
    seg, node, ped, pnode = (rd("segment", ["urn", "length_m", "road_classification"]), rd("node", ["urn", "x", "y"]),
                             rd("ped_edge", ["urn", "length_m"]), rd("ped_node", ["urn", "x", "y"]))
    e = rd("edges")
    def ends(rel):
        z = e[e.rel == rel].sort_values(["src", "dst"]).groupby("src").dst.agg(list)
        z = z[z.map(len) == 2]
        return pd.DataFrame({"urn": z.index, "a": z.map(lambda v: v[0]).values, "b": z.map(lambda v: v[1]).values})
    se = ends("segment_node").merge(seg, on="urn")
    se = se[se.road_classification.fillna("") != "motorway"]
    pe = ends("pededge_pednode").merge(ped, on="urn")
    ap = e[e.rel == "node_pednode"]
    nodes = pd.concat([node[["urn", "x", "y"]], pnode[["urn", "x", "y"]]], ignore_index=True)
    idx = pd.Series(np.arange(len(nodes)), index=nodes.urn)
    a = np.r_[idx[se.a].values, idx[pe.a].values, idx[ap.src].values]
    b = np.r_[idx[se.b].values, idx[pe.b].values, idx[ap.dst].values]
    w = np.r_[se.length_m.values, pe.length_m.values, np.zeros(len(ap))].clip(0.01)
    n = len(nodes)
    m = coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    tg = Q(f"select ST_X(geom), ST_Y(geom) from gkg_feas.place where g=%(g)s and {LM_WHERE} "
           "union all select ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)) from gkg_feas.pub_district "
           "where g=%(g)s", {"g": g})
    n_t = len(tg)
    if n_t == 0:
        return
    rng = np.random.default_rng(20261120)
    pick = rng.choice(n_t, size=min(40, n_t), replace=False)
    _, tn = cKDTree(nodes[["x", "y"]].values).query(np.array(tg)[pick], k=1)
    t = time.time()
    D = dijkstra(m, directed=False, indices=tn, limit=2000)
    sec = time.time() - t
    reached = int(np.isfinite(D).sum())
    results.append({"family": "Landmark and district distances", "property": "network walking distance (Dijkstra, 2 km)",
                    "geofence": g, "targets_full": n_t, "targets_sampled": len(pick), "seconds_sample": round(sec, 2),
                    "seconds_full": round(sec * n_t / len(pick), 1), "walk_nodes": n,
                    "node_distances_full": int(reached * n_t / len(pick)),
                    "note": "distances to graph nodes; each place, stop or intersection then takes its snap node's value"})
    print(json.dumps(results[-1]), flush=True)


t0 = time.time()
prep()
for g in GEOFENCES:
    families(g)
    walking(g)
counts_only()
X("DROP SCHEMA gkg_feas CASCADE")
meta = {"sample_pct": PCT, "total_seconds": round(time.time() - t0, 1),
        "python_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1),
        "pg_settings": dict(Q("select name, setting||coalesce(unit,'') from pg_settings where name in "
                              "('shared_buffers','work_mem','maintenance_work_mem','max_parallel_workers_per_gather')"))}
json.dump({"meta": meta, "results": results}, open(os.path.join(OUT, "feasibility.json"), "w"), indent=1)
print(json.dumps(meta))
