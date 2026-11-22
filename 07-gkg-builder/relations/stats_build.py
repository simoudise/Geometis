"""Place statistics (O4) and tract fingerprints (O5) for the San Francisco geofence, under UKO 15.8.

python -m relations.stats_build [STEP ...]      (from 07-gkg-builder/, on the Mac mini, through the job runner)

Source: the design note "GeoMetis ontology design note O4 O5 incidents (approved) 2026-11-22 11.50", approved by
Evangelos on November 22, 2026. Order of work as he set it: statistics from gkg.census_tract; LODES and ACS B08301;
the tract fingerprints. Incident counts wait for the audit chat's source check and are not in this module.

Storage. Every measured value is one entity in gkg.entity (class uko:PlaceStatistic or uko:FactorValue) and one row
in gkg.measured_value (number, unit, margin, period, procedure, source table and the other UKO 15.8 value
properties). Object relations go to gkg.edge with provenance, like every other relation. Fingerprints, reference
sets, distances and H3 grid cells are entities too. Public data only; reads no trip table.

Each step deletes and rewrites what it owns (entities by src, edges by relation), so a step can be rerun alone.
No step drops or renames an existing table.
"""
import csv, gzip, hashlib, io, json, math, sys, time, uuid, zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from relations import build as B
from relations.build import X, Q, log, copy, edges, reset, GEOFENCES, URN_NS

G = "us-ca-san-francisco"
SF_COUNTY = "06075"
SF_CITY = "urn:urban-kg:City:tiger2024:0667000"
DATA = B.config.DATA_ROOT
DL = DATA / "public" / "2026-11-22b"
LODES_YEAR = 2024
ACS_YEAR = 2024
URLS = {
    "lodes_wac": f"https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/ca_wac_S000_JT00_{LODES_YEAR}.csv.gz",
    "lodes_xwalk": "https://lehd.ces.census.gov/data/lodes/LODES8/ca/ca_xwalk.csv.gz",
    "blocks2020": "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_06_tabblock20.zip",  # statewide; the county PL file lacks POP20
}
TODAY = date.today().isoformat()
ACS_PERIOD = (f"{ACS_YEAR - 4}-01-01", f"{ACS_YEAR}-12-31")
LODES_PERIOD = (f"{LODES_YEAR}-04-01", f"{LODES_YEAR}-06-30")  # LODES reference quarter Q2 (see methodology)
TIGER_PERIOD = ("2024-01-01", "2024-01-01")
WALK_SPEED_KMH = 4.8   # 30 minutes at 4.8 km/h = 2,400 m; an assumption recorded in the methodology
FP_VERSION = "sf-tract-v1"
REFSET_VERSION = "sf-tracts-2026-11-22"
WEIGHTS_VERSION = "equal-factor-v1"

SOURCES = {  # data-source entities added by this module (the build's own eight stay)
    "acs5y2024": "ACS 5-year 2020-2024, table-based summary files (Census Bureau)",
    "lodes8-2024": f"LEHD LODES8 workplace area characteristics {LODES_YEAR}, all jobs (S000, JT00), with the LODES8 block crosswalk",
    "census2020-blocks": "2020 Census block populations (POP20) and internal points, TIGER/Line 2020 tabblock20 (California file, San Francisco County rows)",
    "tiger2024": "TIGER/Line 2024 census tracts and places (ALAND land area)",
    "gkg-derived": "Computed in the GKG from the sources it cites (network reach, fingerprint formulas)",
}
VARS = ["VAR_POPULATION", "VAR_LAND_AREA_KM2", "VAR_HOUSEHOLDS", "VAR_MEDIAN_HOUSEHOLD_INCOME", "VAR_HOUSEHOLDS_INCOME_BELOW_35K",
        "VAR_HOUSEHOLDS_INCOME_100K_PLUS", "VAR_ZERO_VEHICLE_HOUSEHOLD_SHARE", "VAR_JOB_COUNT", "VAR_WORKERS_16_PLUS",
        "VAR_COMMUTE_MODE_SHARE", "VAR_JOBS_REACHABLE"]
MODES = {  # ACS B08301 line -> UKO mode (line 001 is the total of workers 16 and over)
    "002": "MODE_CAR", "003": "MODE_CAR_ALONE", "004": "MODE_CARPOOL", "010": "MODE_TRANSIT", "016": "MODE_TAXI",
    "017": "MODE_MOTORCYCLE", "018": "MODE_BICYCLE", "019": "MODE_WALK", "020": "MODE_OTHER", "021": "MODE_WORK_FROM_HOME"}
PROCS = ["PROC_ACS_5YR", "PROC_ACS_DERIVED_SHARE", "PROC_SUM_OF_PARTS", "PROC_TIGER_LAND_AREA", "PROC_LODES_JOBS",
         "PROC_NETWORK_REACH", "PROC_FINGERPRINT_FORMULA"]
FACTORS = [f"FACTOR_{i:02d}" for i in range(1, 18)] + [f"GRADED_Q{i}" for i in range(1, 7)]
COMPONENTS = [  # (factor, component, unit, formula version, column)
    ("FACTOR_01", "orientation order phi", "0-1", "f1a-v1", "phi"),
    ("FACTOR_01", "circuity", "ratio", "f1b-v1", "circuity"),
    ("FACTOR_01", "share of intersections with four or more ways", "share 0-1", "f1c-v1", "share4"),
    ("FACTOR_01", "share of dead ends", "share 0-1", "f1c-v1", "share_dead"),
    ("FACTOR_01", "median block shape factor", "0-1", "f1d-median-v1", "block_shape"),
    ("FACTOR_03", "jobs reachable on foot within 30 minutes", "jobs", "f3-walk-v1", "jobs_walk30"),
    ("FACTOR_05", "share of residents within 400 m walk of a frequent stop", "share 0-1", "f5-v1", "frequent_share"),
    ("FACTOR_08", "median household income", "US dollars, inflation-adjusted to 2024", "f8a-v1", "median_income"),
    ("FACTOR_08", "share of households with no vehicle", "share 0-1", "f8b-v1", "zero_vehicle"),
]

DDL = """
CREATE TABLE IF NOT EXISTS gkg.measured_value (eid bigint PRIMARY KEY, kind text NOT NULL, feature_eid bigint,
    variable text NOT NULL, value double precision, unit text, moe double precision, moe_level real,
    period_start date, period_end date, procedure text, source_table text, source_eid bigint, travel_mode text,
    threshold_min real, component text, formula_version text, standardized double precision, scaling_residual boolean,
    crash_derived boolean NOT NULL DEFAULT false, fingerprint_eid bigint);
CREATE INDEX IF NOT EXISTS measured_value_feature ON gkg.measured_value (feature_eid, variable);
CREATE TABLE IF NOT EXISTS gkg.census_block_2020 (geoid text PRIMARY KEY, tract text NOT NULL, pop20 integer,
    housing20 integer, lon double precision, lat double precision);
CREATE TABLE IF NOT EXISTS gkg.lodes_wac (year integer, geoid text, jobs integer, tract text, lon double precision,
    lat double precision, PRIMARY KEY (year, geoid));
CREATE TABLE IF NOT EXISTS gkg.fingerprint_distance (eid bigint PRIMARY KEY, from_fp bigint, to_fp bigint,
    value double precision, metric text, weights_version text, computed_on date);
CREATE TABLE IF NOT EXISTS gkg.download_manifest (url text, local_path text, downloaded timestamptz, bytes bigint,
    sha256 text, note text);
"""


def murn(kind, *parts):
    return f"urn:urban-kg:{kind}:gkgfull:{uuid.uuid5(URN_NS, '|'.join([kind] + [str(p) for p in parts]))}"


def ent(urn_, cls, src):
    return Q("insert into gkg.entity (urn, geofence_id, uko_class, src) values (%(u)s,%(g)s,%(c)s,%(s)s) "
             "on conflict (geofence_id, urn) do update set uko_class=excluded.uko_class returning eid",
             {"u": urn_, "g": G, "c": cls, "s": src})[0][0]


def eid(urn_):
    r = Q("select eid from gkg.entity where geofence_id=%(g)s and urn=%(u)s", {"g": G, "u": urn_})
    return r[0][0] if r else None


def ind(name):
    return eid("urn:urban-kg:" + name)


def src_eid(key):
    return eid(f"urn:urban-kg:DataSource:{key}")


def drop_src(*srcs):
    for s in srcs:
        X("delete from gkg.measured_value where eid in (select eid from gkg.entity where src=%(s)s)", {"s": s})
        X("delete from gkg.entity where src=%(s)s", {"s": s})


def add_values(kind, src, rows):
    """rows: dicts with urn, cls, feature, variable, value and optional fields. Returns the eids."""
    out = []
    for r in rows:
        e = ent(r["urn"], r["cls"], src)
        X("""insert into gkg.measured_value (eid, kind, feature_eid, variable, value, unit, moe, moe_level, period_start,
             period_end, procedure, source_table, source_eid, travel_mode, threshold_min, component, formula_version,
             standardized, scaling_residual, crash_derived, fingerprint_eid)
             values (%(e)s,%(k)s,%(f)s,%(v)s,%(val)s,%(unit)s,%(moe)s,%(lvl)s,%(p0)s,%(p1)s,%(proc)s,%(tab)s,%(s)s,%(mode)s,
                     %(thr)s,%(comp)s,%(fv)s,%(z)s,%(res)s,%(cd)s,%(fp)s)
             on conflict (eid) do update set value=excluded.value, moe=excluded.moe, standardized=excluded.standardized""",
          {"e": e, "k": kind, "f": r.get("feature"), "v": r["variable"], "val": r.get("value"), "unit": r.get("unit"),
           "moe": r.get("moe"), "lvl": r.get("moe_level"), "p0": r.get("p0"), "p1": r.get("p1"), "proc": r.get("proc"),
           "tab": r.get("table"), "s": r.get("source"), "mode": r.get("mode"), "thr": r.get("threshold"),
           "comp": r.get("component"), "fv": r.get("formula_version"), "z": r.get("z"), "res": r.get("residual"),
           "cd": bool(r.get("crash_derived", False)), "fp": r.get("fingerprint")})
        out.append(e)
    return out


def _download(key):
    url = URLS[key]
    DL.mkdir(parents=True, exist_ok=True)
    dest = DL / url.rsplit("/", 1)[1]
    if not dest.exists():
        import requests
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.rename(dest)
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        X("insert into gkg.download_manifest values (%(u)s,%(p)s,now(),%(b)s,%(h)s,%(n)s)",
          {"u": url, "p": str(dest), "b": dest.stat().st_size, "h": sha, "n": key})
        log(step="download", key=key, bytes=dest.stat().st_size, sha256=sha[:16])
    return dest


def _acs(table):
    """Tract rows of one ACS table for California, with estimate and margin columns (summary file)."""
    from gkg.stage2_demographics import _table
    t = _table(ACS_YEAR, table, "06")
    if t is None:
        raise SystemExit(f"ACS {ACS_YEAR} table {table} not found")
    return t


def _n(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else x


def _rss(ms):
    ms = [m for m in ms if m is not None]
    return math.sqrt(sum(m * m for m in ms)) if ms else None


def _share_moe(num, den, m_num, m_den):
    """Census Bureau formula for the margin of a proportion; falls back to the ratio formula when negative."""
    if not den or num is None or m_num is None or m_den is None:
        return None
    p = num / den
    rad = m_num ** 2 - p ** 2 * m_den ** 2
    if rad < 0:
        rad = m_num ** 2 + p ** 2 * m_den ** 2
    return math.sqrt(rad) / den


# --------------------------------------------------------------------------- steps

def step_schema():
    for s in DDL.split(";"):
        if s.strip():
            X(s)


def step_individuals():
    """Entities for the vocabulary individuals and the new data sources, so that edges can point at them."""
    for name in VARS:
        ent("urn:urban-kg:" + name, "uko:PlaceVariable", "uko_individual")
    for name in MODES.values():
        ent("urn:urban-kg:" + name, "uko:TravelMode", "uko_individual")
    ent("urn:urban-kg:MODE_WALK", "uko:TravelMode", "uko_individual")
    for name in PROCS:
        ent("urn:urban-kg:" + name, "uko:EstimationProcedure", "uko_individual")
    for name in FACTORS:
        ent("urn:urban-kg:" + name, "uko:FingerprintFactor", "uko_individual")
    for k, v in SOURCES.items():
        X("insert into gkg.aux_entity values (%(g)s, %(u)s, 'uko:DataSource', 'data_source', %(n)s, null, null) "
          "on conflict (geofence_id, urn) do update set name=excluded.name", {"g": G, "u": f"urn:urban-kg:DataSource:{k}", "n": v})
        ent(f"urn:urban-kg:DataSource:{k}", "uko:DataSource", "aux:data_source")
    log(step="individuals", vars=len(VARS), modes=len(MODES), procs=len(PROCS), factors=len(FACTORS), sources=len(SOURCES))


def step_tracts():
    """Statistics from gkg.census_tract (ACS 2020-2024) with margins from the cached summary files, land area from
    TIGER 2024, and San Francisco city totals summed from its tracts."""
    import geopandas as gpd
    drop_src("stat:tract")
    acs = {}
    for t in ["b01003", "b19013", "b19001", "b25044"]:
        for geoid, d in _acs(t).items():
            acs.setdefault(geoid, {}).update(d)
    tiger = gpd.read_file(f"zip://{DATA}/tiger/2024/tl_2024_06_tract.zip", ignore_geometry=True)[["GEOID", "ALAND"]]
    aland = dict(zip(tiger.GEOID, tiger.ALAND))
    tracts = Q("""select t.geoid, e.eid, t.population, t.median_household_income, t.zero_vehicle_share, t.households,
                  t.households_below_35k, t.households_100k_plus, t.acs5_end_year from gkg.census_tract t
                  join gkg.entity e on e.geofence_id=t.geofence_id and e.urn=t.urn where t.geofence_id=%(g)s""", {"g": G})
    if any(r[8] != ACS_YEAR for r in tracts):
        raise SystemExit("gkg.census_tract is not ACS 2020-2024")
    s_acs, s_tig = src_eid("acs5y2024"), src_eid("tiger2024")
    rows = []
    city = {k: [] for k in ["pop", "hh", "lo", "hi", "nov", "hhv", "land"]}
    for geoid, feid, pop, med, zvs, hh, lo, hi, _ in tracts:
        a = acs.get(geoid, {})
        m = lambda v: _n(a.get(v))
        nov, hhv = (m("B25044_E003") or 0) + (m("B25044_E010") or 0), m("B25044_E001")
        nov_moe = _rss([m("B25044_M003"), m("B25044_M010")])
        lo_moe = _rss([m(f"B19001_M{i:03d}") for i in range(2, 8)])
        hi_moe = _rss([m(f"B19001_M{i:03d}") for i in range(14, 18)])
        base = dict(feature=feid, p0=ACS_PERIOD[0], p1=ACS_PERIOD[1], moe_level=0.90, source=s_acs, cls="uko:PlaceStatistic")
        U = lambda var: murn("PlaceStatistic", G, geoid, var, ACS_YEAR)
        rows += [
            dict(base, urn=U("pop"), variable="VAR_POPULATION", value=pop, unit="persons", moe=m("B01003_M001"), proc="PROC_ACS_5YR", table="B01003"),
            dict(base, urn=U("hh"), variable="VAR_HOUSEHOLDS", value=hh, unit="households", moe=m("B19001_M001"), proc="PROC_ACS_5YR", table="B19001"),
            dict(base, urn=U("med"), variable="VAR_MEDIAN_HOUSEHOLD_INCOME", value=med, unit="US dollars, inflation-adjusted to 2024", moe=m("B19013_M001"), proc="PROC_ACS_5YR", table="B19013"),
            dict(base, urn=U("lo"), variable="VAR_HOUSEHOLDS_INCOME_BELOW_35K", value=lo, unit="households", moe=lo_moe, proc="PROC_SUM_OF_PARTS", table="B19001 lines 002-007"),
            dict(base, urn=U("hi"), variable="VAR_HOUSEHOLDS_INCOME_100K_PLUS", value=hi, unit="households", moe=hi_moe, proc="PROC_SUM_OF_PARTS", table="B19001 lines 014-017"),
            dict(base, urn=U("zvs"), variable="VAR_ZERO_VEHICLE_HOUSEHOLD_SHARE", value=zvs, unit="share 0-1", moe=_share_moe(nov, hhv, nov_moe, m("B25044_M001")), proc="PROC_ACS_DERIVED_SHARE", table="B25044 lines 003+010 / 001"),
            dict(feature=feid, urn=U("land"), cls="uko:PlaceStatistic", variable="VAR_LAND_AREA_KM2", value=(aland.get(geoid) or 0) / 1e6 if geoid in aland else None,
                 unit="square kilometers", p0=TIGER_PERIOD[0], p1=TIGER_PERIOD[1], proc="PROC_TIGER_LAND_AREA", table="tl_2024_06_tract ALAND", source=s_tig),
        ]
        if geoid.startswith(SF_COUNTY):
            for k, v, mm in [("pop", pop, m("B01003_M001")), ("hh", hh, m("B19001_M001")), ("lo", lo, lo_moe), ("hi", hi, hi_moe),
                             ("nov", nov, nov_moe), ("hhv", hhv, m("B25044_M001"))]:
                city[k].append((v or 0, mm))
            city["land"].append(aland.get(geoid, 0) / 1e6)
    # San Francisco city (= county): totals from its tracts; land area from the TIGER place file.
    place = gpd.read_file(f"zip://{DATA}/tiger/2024/tl_2024_06_place.zip", ignore_geometry=True)
    sf_land = float(place.loc[place.GEOID == "0667000", "ALAND"].iloc[0]) / 1e6
    ceid = eid(SF_CITY)
    tot = lambda k: (sum(v for v, _ in city[k]), _rss([mm for _, mm in city[k]]))
    cb = dict(feature=ceid, p0=ACS_PERIOD[0], p1=ACS_PERIOD[1], moe_level=0.90, source=s_acs, cls="uko:PlaceStatistic", proc="PROC_SUM_OF_PARTS")
    CU = lambda var: murn("PlaceStatistic", G, "0667000", var, ACS_YEAR)
    nov_t, hhv_t = tot("nov"), tot("hhv")
    rows += [
        dict(cb, urn=CU("pop"), variable="VAR_POPULATION", value=tot("pop")[0], moe=tot("pop")[1], unit="persons", table="B01003, summed over tracts"),
        dict(cb, urn=CU("hh"), variable="VAR_HOUSEHOLDS", value=tot("hh")[0], moe=tot("hh")[1], unit="households", table="B19001, summed over tracts"),
        dict(cb, urn=CU("lo"), variable="VAR_HOUSEHOLDS_INCOME_BELOW_35K", value=tot("lo")[0], moe=tot("lo")[1], unit="households", table="B19001 lines 002-007, summed over tracts"),
        dict(cb, urn=CU("hi"), variable="VAR_HOUSEHOLDS_INCOME_100K_PLUS", value=tot("hi")[0], moe=tot("hi")[1], unit="households", table="B19001 lines 014-017, summed over tracts"),
        dict(cb, urn=CU("zvs"), variable="VAR_ZERO_VEHICLE_HOUSEHOLD_SHARE", value=nov_t[0] / hhv_t[0], moe=_share_moe(nov_t[0], hhv_t[0], nov_t[1], hhv_t[1]),
             unit="share 0-1", proc="PROC_ACS_DERIVED_SHARE", table="B25044, summed over tracts"),
        dict(feature=ceid, urn=CU("land"), cls="uko:PlaceStatistic", variable="VAR_LAND_AREA_KM2", value=sf_land, unit="square kilometers",
             p0=TIGER_PERIOD[0], p1=TIGER_PERIOD[1], proc="PROC_TIGER_LAND_AREA", table="tl_2024_06_place ALAND (GEOID 0667000)", source=s_tig),
    ]
    rows = [r for r in rows if r.get("value") is not None]
    add_values("place_statistic", "stat:tract", rows)
    log(step="tracts", tracts=len(tracts), sf_tracts=len(city["land"]), statistics=len(rows),
        sf_population=round(tot("pop")[0]), sf_land_km2=round(sf_land, 1))


def step_downloads():
    for k in URLS:
        _download(k)


def step_lodes():
    """LODES jobs by block -> tracts (all geofence tracts), San Francisco city, and H3 resolution-8 cells inside the
    city. Block internal points come from the LODES8 crosswalk."""
    import h3
    drop_src("stat:lodes", "stat:grid_cell")
    X("delete from gkg.aux_entity where kind='grid_cell' and geofence_id=%(g)s", {"g": G})
    tracts = {r[0]: r[1] for r in Q("select t.geoid, e.eid from gkg.census_tract t join gkg.entity e on e.geofence_id=t.geofence_id "
                                    "and e.urn=t.urn where t.geofence_id=%(g)s", {"g": G})}
    counties = {g[:5] for g in tracts}
    xw = pd.read_csv(_download("lodes_xwalk"), dtype=str, usecols=["tabblk2020", "trct", "blklatdd", "blklondd"])
    xw = xw[xw.trct.str[:5].isin(counties)]
    wac = pd.read_csv(_download("lodes_wac"), dtype={"w_geocode": str}, usecols=["w_geocode", "C000"])
    wac = wac.merge(xw, left_on="w_geocode", right_on="tabblk2020", how="left")
    wac = wac[wac.trct.notna()]
    X("delete from gkg.lodes_wac where year=%(y)s", {"y": LODES_YEAR})
    copy("gkg.lodes_wac", ["year", "geoid", "jobs", "tract", "lon", "lat"],
         ((LODES_YEAR, r.w_geocode, int(r.C000), r.trct, float(r.blklondd), float(r.blklatdd)) for r in wac.itertuples()))
    s_l = src_eid("lodes8-2024")
    base = dict(cls="uko:PlaceStatistic", variable="VAR_JOB_COUNT", unit="jobs", p0=LODES_PERIOD[0], p1=LODES_PERIOD[1],
                proc="PROC_LODES_JOBS", table=f"ca_wac_S000_JT00_{LODES_YEAR} C000", source=s_l)
    by_tract = wac.groupby("trct").C000.sum()
    rows = [dict(base, urn=murn("PlaceStatistic", G, g, "jobs", LODES_YEAR), feature=e, value=float(by_tract.get(g, 0)))
            for g, e in tracts.items()]
    sf = wac[wac.trct.str.startswith(SF_COUNTY)]
    rows.append(dict(base, urn=murn("PlaceStatistic", G, "0667000", "jobs", LODES_YEAR), feature=eid(SF_CITY), value=float(sf.C000.sum()),
                     table=f"ca_wac_S000_JT00_{LODES_YEAR} C000, summed over the city's blocks"))
    add_values("place_statistic", "stat:lodes", rows)
    # H3 resolution 8 cells: every cell of the city that holds at least one job.
    sf = sf.assign(cell=[h3.latlng_to_cell(float(a), float(o), 8) for a, o in zip(sf.blklatdd, sf.blklondd)])
    cells = sf.groupby("cell").C000.sum()
    grows = []
    for cell, jobs in cells.items():
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
        wkt = "POLYGON((" + ",".join(f"{x} {y}" for x, y in ring + ring[:1]) + "))"
        u = f"urn:urban-kg:GridCell:h3:{cell}"
        X("insert into gkg.aux_entity values (%(g)s,%(u)s,'uko:GridCell','grid_cell',%(c)s,%(p)s,ST_GeomFromText(%(w)s,4326))",
          {"g": G, "u": u, "c": cell, "p": json.dumps({"gridSystem": "H3", "gridResolution": 8, "gridIndex": cell}), "w": wkt})
        ge = ent(u, "uko:GridCell", "stat:grid_cell")
        grows.append(dict(base, urn=murn("PlaceStatistic", G, "h3", cell, LODES_YEAR), feature=ge, value=float(jobs),
                          table=f"ca_wac_S000_JT00_{LODES_YEAR} C000, summed over blocks whose internal point lies in the cell"))
    add_values("place_statistic", "stat:lodes", grows)
    log(step="lodes", blocks=len(wac), tract_stats=len(rows) - 1, sf_jobs=int(sf.C000.sum()), h3_cells=len(grows))


def step_commute():
    """ACS B08301 (means of transportation to work): workers 16 and over and the share of each mode, per tract
    and for the city, with margins (proportion formula)."""
    drop_src("stat:commute")
    acs = _acs("b08301")
    tracts = {r[0]: r[1] for r in Q("select t.geoid, e.eid from gkg.census_tract t join gkg.entity e on e.geofence_id=t.geofence_id "
                                    "and e.urn=t.urn where t.geofence_id=%(g)s", {"g": G})}
    s_acs = src_eid("acs5y2024")
    base = dict(cls="uko:PlaceStatistic", p0=ACS_PERIOD[0], p1=ACS_PERIOD[1], moe_level=0.90, source=s_acs)
    rows, city = [], {}
    for geoid, feid in tracts.items():
        a = acs.get(geoid)
        if not a:
            continue
        tot, mtot = _n(a["B08301_E001"]), _n(a["B08301_M001"])
        rows.append(dict(base, urn=murn("PlaceStatistic", G, geoid, "workers", ACS_YEAR), feature=feid, variable="VAR_WORKERS_16_PLUS",
                         value=tot, moe=mtot, unit="workers", proc="PROC_ACS_5YR", table="B08301 line 001"))
        if geoid.startswith(SF_COUNTY):
            city.setdefault("001", []).append((tot or 0, mtot))
        for line, mode in MODES.items():
            e, mm = _n(a[f"B08301_E{line}"]), _n(a[f"B08301_M{line}"])
            if geoid.startswith(SF_COUNTY):
                city.setdefault(line, []).append((e or 0, mm))
            if tot:
                rows.append(dict(base, urn=murn("PlaceStatistic", G, geoid, "share", mode, ACS_YEAR), feature=feid,
                                 variable="VAR_COMMUTE_MODE_SHARE", mode=mode, value=(e or 0) / tot,
                                 moe=_share_moe(e or 0, tot, mm, mtot), unit="share 0-1", proc="PROC_ACS_DERIVED_SHARE",
                                 table=f"B08301 line {line} / line 001"))
    ceid = eid(SF_CITY)
    T = lambda line: (sum(v for v, _ in city[line]), _rss([m for _, m in city[line]]))
    tot = T("001")
    rows.append(dict(base, urn=murn("PlaceStatistic", G, "0667000", "workers", ACS_YEAR), feature=ceid, variable="VAR_WORKERS_16_PLUS",
                     value=tot[0], moe=tot[1], unit="workers", proc="PROC_SUM_OF_PARTS", table="B08301 line 001, summed over tracts"))
    for line, mode in MODES.items():
        e = T(line)
        rows.append(dict(base, urn=murn("PlaceStatistic", G, "0667000", "share", mode, ACS_YEAR), feature=ceid, variable="VAR_COMMUTE_MODE_SHARE",
                         mode=mode, value=e[0] / tot[0], moe=_share_moe(e[0], tot[0], e[1], tot[1]), unit="share 0-1",
                         proc="PROC_ACS_DERIVED_SHARE", table=f"B08301 line {line} / line 001, summed over tracts"))
    add_values("place_statistic", "stat:commute", rows)
    log(step="commute", statistics=len(rows), sf_transit_share=round(T("010")[0] / tot[0], 3), sf_wfh_share=round(T("021")[0] / tot[0], 3))


def step_blocks():
    """2020 Census block populations and internal points for San Francisco County."""
    import geopandas as gpd
    b = gpd.read_file(f"zip://{_download('blocks2020')}", ignore_geometry=True, where="COUNTYFP20 = '075'")
    cols = {c.upper(): c for c in b.columns}
    need = ["GEOID20", "POP20", "HOUSING20", "INTPTLAT20", "INTPTLON20"]
    if any(n not in cols for n in need):
        raise SystemExit(f"block file lacks {[n for n in need if n not in cols]}: {list(b.columns)}")
    X("delete from gkg.census_block_2020 where tract like %(p)s", {"p": SF_COUNTY + "%"})
    copy("gkg.census_block_2020", ["geoid", "tract", "pop20", "housing20", "lon", "lat"],
         ((r[cols["GEOID20"]], r[cols["GEOID20"]][:11], int(r[cols["POP20"]]), int(r[cols["HOUSING20"]]),
           float(r[cols["INTPTLON20"]]), float(r[cols["INTPTLAT20"]])) for _, r in b.iterrows()))
    log(step="blocks", blocks=len(b), pop20=int(b[cols["POP20"]].astype(int).sum()))


def _factor_inputs():
    """Per San Francisco tract: the nine fingerprint components (factors 1, 3, 5 and 8)."""
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    tr = pd.DataFrame(Q("""select t.geoid, e.eid, t.population, t.median_household_income, t.zero_vehicle_share
                          from gkg.census_tract t join gkg.entity e on e.geofence_id=t.geofence_id and e.urn=t.urn
                          where t.geofence_id=%(g)s and t.geoid like %(p)s order by t.geoid""", {"g": G, "p": SF_COUNTY + "%"}),
                      columns=["geoid", "eid", "population", "median_income", "zero_vehicle"]).set_index("geoid")
    # Factor 1 (a)-(b): vehicular segments by midpoint; bearings and lengths on the ellipsoid.
    seg = pd.DataFrame(Q("""select t.geoid, degrees(ST_Azimuth(ST_StartPoint(l)::geography, ST_EndPoint(l)::geography)),
                                   ST_Length(l::geography), ST_Distance(ST_StartPoint(l)::geography, ST_EndPoint(l)::geography)
                            from (select ST_LineMerge(geom) l from gkg.road_segment where geofence_id=%(g)s
                                  and coalesce(road_classification,'') not in ('track','unknown')
                                  and coalesce(subclass,'') not in ('parking_aisle','driveway')) s
                            join gkg.census_tract t on t.geofence_id=%(g)s and t.geoid like %(p)s
                              and ST_Contains(t.geom, ST_LineInterpolatePoint(s.l, 0.5))
                            where GeometryType(s.l)='LINESTRING'""", {"g": G, "p": SF_COUNTY + "%"}),
                       columns=["geoid", "az", "len", "straight"]).dropna()
    def phi(g):
        az = np.r_[g.az.values, (g.az.values + 180) % 360]
        w = np.r_[g.len.values, g.len.values]
        bins = np.floor(((az + 5) % 360) / 10).astype(int)  # 36 bins of 10 degrees centered on 0, 10, 20 ...
        p = np.bincount(bins, weights=w, minlength=36)
        p = p[p > 0] / p.sum()
        H = -(p * np.log(p)).sum()
        return 1 - ((H - 1.386) / (3.584 - 1.386)) ** 2
    f1 = seg.groupby("geoid").apply(lambda g: pd.Series({"phi": phi(g), "circuity": g.len.sum() / max(g.straight.sum(), 1e-9)}))
    tr = tr.join(f1)
    # Factor 1 (c): node degrees.
    nd = pd.DataFrame(Q("""select t.geoid, count(*) filter (where n.degree<>2), count(*) filter (where n.degree>=4),
                                  count(*) filter (where n.degree=1)
                           from gkg.intersection_node n join gkg.census_tract t on t.geofence_id=%(g)s and t.geoid like %(p)s
                             and ST_Contains(t.geom, n.geom) where n.geofence_id=%(g)s group by 1""", {"g": G, "p": SF_COUNTY + "%"}),
                      columns=["geoid", "nodes", "n4", "dead"]).set_index("geoid")
    tr["share4"] = nd.n4 / nd.nodes.where(nd.nodes > 0)
    tr["share_dead"] = nd.dead / nd.nodes.where(nd.nodes > 0)
    # Factor 1 (d): block shape factor = area / area of the circle on the block's longest internal distance.
    bs = pd.DataFrame(Q("""select t.geoid, percentile_cont(0.5) within group (order by
                                  ST_Area(b.g) / (pi() * power(ST_MaxDistance(b.g, b.g) / 2, 2)))
                           from (select ST_Transform(geom, 3310) g, geom from gkg.aux_entity where kind='city_block' and geofence_id=%(g)s) b
                           join gkg.census_tract t on t.geofence_id=%(g)s and t.geoid like %(p)s and ST_Contains(t.geom, ST_PointOnSurface(b.geom))
                           group by 1""", {"g": G, "p": SF_COUNTY + "%"}), columns=["geoid", "block_shape"]).set_index("geoid")
    tr = tr.join(bs)
    # Walking network and block points.
    m, xy, _ = B._walk_graph(G)
    tree = cKDTree(xy)
    from pyproj import Transformer
    to3310 = Transformer.from_crs(4326, 3310, always_xy=True).transform
    blk = pd.DataFrame(Q("select geoid, tract, pop20, lon, lat from gkg.census_block_2020 where tract like %(p)s", {"p": SF_COUNTY + "%"}),
                       columns=["geoid", "tract", "pop20", "lon", "lat"])
    bx, by = to3310(blk.lon.values, blk.lat.values)
    blk["off"], blk["node"] = tree.query(np.c_[bx, by], k=1)
    jobs = pd.DataFrame(Q("select jobs, lon, lat from gkg.lodes_wac where year=%(y)s", {"y": LODES_YEAR}), columns=["jobs", "lon", "lat"])
    jx, jy = to3310(jobs.lon.values, jobs.lat.values)
    jobs["off"], jobs["node"] = tree.query(np.c_[jx, jy], k=1)
    jobs = jobs[jobs.off <= 200]  # blocks more than 200 m from the walking network are outside the geofence's network
    # Factor 3: jobs within a 30-minute walk of the tract's population-weighted centroid (2020 block populations).
    limit = WALK_SPEED_KMH * 1000 / 60 * 30
    cen = blk[blk.pop20 > 0].groupby("tract").apply(lambda g: pd.Series({
        "x": np.average(to3310(g.lon.values, g.lat.values)[0], weights=g.pop20),
        "y": np.average(to3310(g.lon.values, g.lat.values)[1], weights=g.pop20)}))
    coff, cnode = tree.query(cen[["x", "y"]].values, k=1)
    D = dijkstra(m, directed=False, indices=cnode, limit=limit)
    jw = []
    for i in range(len(cen)):
        reach = D[i, jobs.node.values] + coff[i] + jobs.off.values <= limit
        jw.append(float(jobs.jobs.values[reach].sum()))
    tr["jobs_walk30"] = pd.Series(jw, index=cen.index)
    # Factor 5: share of residents within a 400 m walk of a stop with at least four departures in every hour 07-19.
    st = pd.DataFrame(Q("""select s.stop_urn, split_part(s.departure_time,':',1)::int h, count(*) from gkg.transit_stop_time s
                          where s.geofence_id=%(g)s and s.departure_time ~ '^[0-9]+:'
                            and split_part(s.departure_time,':',1)::int between 7 and 18 group by 1,2""", {"g": G}),
                      columns=["stop", "h", "n"])
    ok = st[st.n >= 4].groupby("stop").h.nunique()
    freq = list(ok[ok == 12].index)
    sxy = Q("select ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.transit_stop where geofence_id=%(g)s and urn = any(%(u)s)",
            {"g": G, "u": freq})
    _, snode = tree.query(np.array(sxy), k=1)
    Ds = dijkstra(m, directed=False, indices=np.unique(snode), limit=400, min_only=True)
    blk["near"] = (Ds[blk.node.values] + blk.off.values) <= 400
    fs = blk.groupby("tract").apply(lambda g: g.pop20[g.near].sum() / g.pop20.sum() if g.pop20.sum() > 0 else np.nan)
    tr["frequent_share"] = fs
    info = {"frequent_stops": len(freq), "service_day": Q("select min(service_day) from gkg.transit_stop_time where geofence_id=%(g)s", {"g": G})[0][0],
            "walk_limit_m": limit}
    return tr, info


def step_fingerprints():
    """Tract fingerprints for San Francisco (factors 1, 3, 5 and 8), the reference set, the jobs-reachable
    statistic, and the pairwise distances between reference-set tracts."""
    for c in ["uko:fingerprintOf", "uko:usesReferenceSet", "uko:hasReferenceMember", "uko:hasFactorValue", "uko:valueOfFactor",
              "uko:distanceFrom", "uko:distanceTo", "uko:factorSetUsed"]:
        reset(c)
    drop_src("fp:fingerprint", "fp:factor_value", "fp:reference_set", "fp:distance", "stat:reach")
    t0 = time.time()
    tr, info = _factor_inputs()
    cols = [c[4] for c in COMPONENTS]
    ref = tr[(tr.population.fillna(0) > 0) & tr[cols].notna().all(axis=1)]
    mu, sd = ref[cols].mean(), ref[cols].std(ddof=1)
    z = (tr[cols] - mu) / sd
    s_d = src_eid("gkg-derived")
    # Reference set and fingerprints.
    rs_u = murn("ReferenceSet", G, REFSET_VERSION)
    rs = ent(rs_u, "uko:ReferenceSet", "fp:reference_set")
    X("insert into gkg.aux_entity values (%(g)s,%(u)s,'uko:ReferenceSet','reference_set',%(n)s,%(p)s,null) on conflict (geofence_id, urn) do update set props=excluded.props",
      {"g": G, "u": rs_u, "n": "San Francisco tracts with population and all nine components",
       "p": json.dumps({"referenceSetVersion": REFSET_VERSION, "members": len(ref), "mean": mu.round(6).to_dict(), "sd": sd.round(6).to_dict()})})
    fps, fv_rows = {}, []
    for geoid, r in tr.iterrows():
        u = murn("Fingerprint", G, geoid, FP_VERSION)
        fps[geoid] = ent(u, "uko:Fingerprint", "fp:fingerprint")
        X("insert into gkg.aux_entity values (%(g)s,%(u)s,'uko:Fingerprint','fingerprint',%(n)s,%(p)s,null) on conflict (geofence_id, urn) do update set props=excluded.props",
          {"g": G, "u": u, "n": f"tract {geoid}", "p": json.dumps({"fingerprintVersion": FP_VERSION, "computedOn": TODAY, "tract": geoid,
                                                                    "inReferenceSet": geoid in ref.index})})
        for fac, comp, unit, fver, col in COMPONENTS:
            v = r[col]
            if pd.isna(v):
                continue
            fv_rows.append(dict(urn=murn("FactorValue", G, geoid, FP_VERSION, fac, comp), cls="uko:FactorValue", feature=r.eid,
                                variable=fac, value=float(v), unit=unit, component=comp, formula_version=fver,
                                z=None if geoid not in ref.index else float(z.loc[geoid, col]), residual=False,
                                proc="PROC_FINGERPRINT_FORMULA", source=s_d, p0=TODAY, p1=TODAY, fingerprint=fps[geoid]))
    add_values("factor_value", "fp:factor_value", fv_rows)
    # Jobs reachable on foot as a place statistic too (O4, competency question F3).
    s_l = src_eid("lodes8-2024")
    add_values("place_statistic", "stat:reach", [
        dict(urn=murn("PlaceStatistic", G, geoid, "jobs-walk-30", LODES_YEAR), cls="uko:PlaceStatistic", feature=r.eid,
             variable="VAR_JOBS_REACHABLE", mode="MODE_WALK", threshold=30, value=float(r.jobs_walk30), unit="jobs",
             proc="PROC_NETWORK_REACH", source=s_l, p0=LODES_PERIOD[0], p1=LODES_PERIOD[1],
             table=f"ca_wac_S000_JT00_{LODES_YEAR} C000; walking network at {WALK_SPEED_KMH} km/h from the population-weighted centroid")
        for geoid, r in tr.iterrows() if pd.notna(r.jobs_walk30)])
    # Distances: weighted Euclidean over standardized components; each factor weighs 1, split equally over its components.
    w = np.array([1 / sum(1 for c in COMPONENTS if c[0] == f) for f, *_ in COMPONENTS])
    Z = z.loc[ref.index, cols].values
    ids = list(ref.index)
    drows = []
    for i in range(len(ids)):
        d = np.sqrt(((Z[i] - Z[i + 1:]) ** 2 * w).sum(axis=1))
        for j, dv in zip(range(i + 1, len(ids)), d):
            drows.append((ids[i], ids[j], float(dv)))
    metric = ("weighted Euclidean on standardized components (z against the reference set); each factor weighs 1, "
              "split equally over its components; factors 1, 3, 5, 8")
    X("create temp table _d (urn text, a text, b text, d double precision)")
    copy("_d", ["urn", "a", "b", "d"], ((murn("FingerprintDistance", G, a, b, FP_VERSION, WEIGHTS_VERSION), a, b, d) for a, b, d in drows))
    X("insert into gkg.entity (urn, geofence_id, uko_class, src) select urn, %(g)s, 'uko:FingerprintDistance', 'fp:distance' from _d "
      "on conflict (geofence_id, urn) do nothing", {"g": G})
    X("""insert into gkg.aux_entity select %(g)s, urn, 'uko:FingerprintDistance', 'fingerprint_distance', a||' - '||b,
         jsonb_build_object('distanceValue', d, 'distanceMetric', %(m)s::text, 'weightsVersion', %(w)s::text, 'computedOn', %(t)s::text), null from _d
         on conflict (geofence_id, urn) do update set props=excluded.props""", {"g": G, "m": metric, "w": WEIGHTS_VERSION, "t": TODAY})
    X("create table if not exists gkg.fingerprint_distance (eid bigint primary key, from_fp bigint, to_fp bigint, value double precision, "
      "metric text, weights_version text, computed_on date)")
    X("delete from gkg.fingerprint_distance where eid in (select eid from gkg.entity where src='fp:distance')")
    fpmap = {g: e for g, e in fps.items()}
    X("create temp table _fp (geoid text, eid bigint)")
    copy("_fp", ["geoid", "eid"], fpmap.items())
    X("""insert into gkg.fingerprint_distance select e.eid, a.eid, b.eid, d.d, %(m)s::text, %(w)s::text, %(t)s::date from _d d
         join gkg.entity e on e.geofence_id=%(g)s and e.urn=d.urn join _fp a on a.geoid=d.a join _fp b on b.geoid=d.b""",
      {"g": G, "m": metric, "w": WEIGHTS_VERSION, "t": TODAY})
    # Edges.
    src, meth = "GKG fingerprint step (relations/stats_build.py)", f"fingerprint {FP_VERSION}, reference set {REFSET_VERSION}"
    edges("uko:fingerprintOf", src, meth, """select e.eid, t.eid, null::real from _fp f join gkg.entity e on e.eid=f.eid
             join gkg.census_tract c on c.geofence_id='us-ca-san-francisco' and c.geoid=f.geoid
             join gkg.entity t on t.geofence_id=c.geofence_id and t.urn=c.urn""")
    edges("uko:usesReferenceSet", src, meth, f"select eid, {rs}, null::real from _fp")
    X("create temp table _ref (geoid text)")
    copy("_ref", ["geoid"], ((g,) for g in ref.index))
    edges("uko:hasReferenceMember", src, meth, f"""select {rs}, t.eid, null::real from _ref r join gkg.census_tract c
             on c.geofence_id='us-ca-san-francisco' and c.geoid=r.geoid join gkg.entity t on t.geofence_id=c.geofence_id and t.urn=c.urn""")
    edges("uko:hasFactorValue", src, meth, "select fingerprint_eid, eid, null::real from gkg.measured_value where kind='factor_value'")
    edges("uko:valueOfFactor", src, meth, """select v.eid, f.eid, null::real from gkg.measured_value v join gkg.entity f
             on f.geofence_id='us-ca-san-francisco' and f.urn='urn:urban-kg:'||v.variable where v.kind='factor_value'""")
    edges("uko:distanceFrom", src, meth, "select eid, from_fp, null::real from gkg.fingerprint_distance")
    edges("uko:distanceTo", src, meth, "select eid, to_fp, null::real from gkg.fingerprint_distance")
    edges("uko:factorSetUsed", src, meth, """select d.eid, f.eid, null::real from gkg.fingerprint_distance d cross join
             (values ('FACTOR_01'),('FACTOR_03'),('FACTOR_05'),('FACTOR_08')) v(n) join gkg.entity f
             on f.geofence_id='us-ca-san-francisco' and f.urn='urn:urban-kg:'||v.n""")
    for t in ["_d", "_fp", "_ref"]:
        X(f"drop table {t}")
    log(step="fingerprints", tracts=len(tr), reference_members=len(ref), factor_values=len(fv_rows), distances=len(drows),
        seconds=round(time.time() - t0, 1), **{k: (str(v) if not isinstance(v, (int, float)) else v) for k, v in info.items()},
        medians={c: round(float(ref[c].median()), 4) for c in cols})


def step_statedges():
    """Edges of every place statistic and factor value: area, variable, source, procedure, mode."""
    for c in ["uko:hasPlaceStatistic", "sosa:observedProperty", "uko:valueSource", "sosa:usedProcedure", "uko:travelMode"]:
        reset(c)
    src, meth = "GKG place statistics (relations/stats_build.py)", "measured values in gkg.measured_value"
    edges("uko:hasPlaceStatistic", src, meth, "select feature_eid, eid, null::real from gkg.measured_value where kind='place_statistic'")
    edges("sosa:observedProperty", src, meth, """select v.eid, i.eid, null::real from gkg.measured_value v join gkg.entity i
             on i.geofence_id='us-ca-san-francisco' and i.urn='urn:urban-kg:'||v.variable where v.kind='place_statistic'""")
    edges("uko:valueSource", src, meth, "select eid, source_eid, null::real from gkg.measured_value where source_eid is not null")
    edges("sosa:usedProcedure", src, meth, """select v.eid, i.eid, null::real from gkg.measured_value v join gkg.entity i
             on i.geofence_id='us-ca-san-francisco' and i.urn='urn:urban-kg:'||v.procedure""")
    edges("uko:travelMode", src, meth, """select v.eid, i.eid, null::real from gkg.measured_value v join gkg.entity i
             on i.geofence_id='us-ca-san-francisco' and i.urn='urn:urban-kg:'||v.travel_mode where v.travel_mode is not null""")


def step_check():
    """Counts and checks of the loaded values (printed to the job log; aggregates only)."""
    r = {}
    r["by_kind_variable"] = Q("select kind, variable, count(*), count(moe) from gkg.measured_value group by 1,2 order by 1,2")
    r["values_without_entity"] = Q("select count(*) from gkg.measured_value v where not exists (select 1 from gkg.entity e where e.eid=v.eid)")[0][0]
    r["statistics_without_area_edge"] = Q("""select count(*) from gkg.measured_value v where kind='place_statistic' and not exists
        (select 1 from gkg.edge x where x.rid=(select rid from gkg.relation_type where curie='uko:hasPlaceStatistic') and x.obj=v.eid)""")[0][0]
    r["shares_out_of_range"] = Q("select count(*) from gkg.measured_value where unit='share 0-1' and (value<0 or value>1)")[0][0]
    r["mode_shares_not_summing"] = Q("""select count(*) from (select feature_eid, sum(value) s from gkg.measured_value where variable='VAR_COMMUTE_MODE_SHARE'
        and travel_mode not in ('MODE_CAR_ALONE','MODE_CARPOOL') group by 1) x where abs(s-1) > 0.001""")[0][0]
    r["sf_population_vs_acs_county"] = Q("""select round(value), round(moe) from gkg.measured_value v join gkg.entity e on e.eid=v.feature_eid
        where e.urn=%(c)s and v.variable='VAR_POPULATION'""", {"c": SF_CITY})
    r["lodes_jobs_sf_city"] = Q("""select round(value) from gkg.measured_value v join gkg.entity e on e.eid=v.feature_eid
        where e.urn=%(c)s and v.variable='VAR_JOB_COUNT'""", {"c": SF_CITY})
    r["distances"] = Q("select count(*), round(min(value)::numeric,3), round(avg(value)::numeric,3), round(max(value)::numeric,3) from gkg.fingerprint_distance")
    r["standardized_mean_abs"] = Q("""select component, round(avg(standardized)::numeric,4), round(stddev_samp(standardized)::numeric,4), count(standardized)
        from gkg.measured_value where kind='factor_value' group by 1 order by 1""")
    print(json.dumps(r, default=str, indent=1))


STEPS = [("schema", step_schema), ("individuals", step_individuals), ("tracts", step_tracts), ("downloads", step_downloads),
         ("lodes", step_lodes), ("commute", step_commute), ("blocks", step_blocks), ("fingerprints", step_fingerprints),
         ("statedges", step_statedges), ("check", step_check)]

if __name__ == "__main__":
    want = sys.argv[1:] or [s for s, _ in STEPS]
    for name, fn in STEPS:
        if name in want:
            t = time.time()
            log(step=name, status="start")
            fn()
            log(step=name, status="done", seconds=round(time.time() - t, 1))
