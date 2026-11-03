"""Knowledge Builder Stage 2: Census tracts and ACS demographics (v19 section 9.3, Stage 2).

Input: one stored geofence record. Every tract that intersects the core is loaded whole, not
clipped, with the share of its area that lies inside the core (geofence input spec, stage table).
ACS 5-year values come from the Census Bureau API; the release used is recorded with the build.
"""
import json

import geopandas as gpd
import requests
import shapely
from pyproj import Transformer
from shapely.ops import transform

from . import config
from .db import connect, copy_rows
from .geofence import fetch, tiger_zip

# ACS 5-year variables, named as in the Census Bureau's table-based summary files.
# Households by income bands: B19001_E002..E007 are below 35,000 dollars, B19001_E014..E017 are
# 100,000 dollars and above.
ACS_VARS = {
    "B01003_E001": "population",
    "B19013_E001": "median_household_income",
    "B25044_E001": "households_tenure_vehicles",
    "B25044_E003": "owner_no_vehicle",
    "B25044_E010": "renter_no_vehicle",
    "B19001_E001": "households_income",
}
LOW = [f"B19001_E{i:03d}" for i in range(2, 8)]
HIGH = [f"B19001_E{i:03d}" for i in range(14, 18)]
ACS_YEARS = [2024, 2023]  # the newest 5-year release first; the first one published is used
SF_URL = ("https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/"
          "acsdt5y{y}-{t}.dat")
# The Census Data API now requires a key; the summary files do not, so Stage 2 reads those.

_to_metric = Transformer.from_crs(config.STORE_CRS, config.METRIC_CRS, always_xy=True).transform


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else x  # the API uses large negative sentinels for missing values


def _table(year, table, state):
    """Tract rows of one ACS table for one state, cached as a small local file."""
    dest = config.DATA_ROOT / "acs" / f"acs5y{year}" / f"{table}-{state}.dat"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        prefix = f"1400000US{state}"
        with requests.get(SF_URL.format(y=year, t=table), stream=True, timeout=600) as r:
            if r.status_code != 200:
                return None
            r.encoding = "utf-8"
            lines = r.iter_lines(decode_unicode=True)
            head = next(lines)
            keep = [head] + [ln for ln in lines if ln.startswith(prefix)]
        tmp = dest.with_suffix(".part")
        tmp.write_text("\n".join(keep) + "\n")
        tmp.rename(dest)
    rows = dest.read_text().splitlines()
    head = rows[0].split("|")
    return {r.split("|")[0][9:]: dict(zip(head, r.split("|"))) for r in rows[1:]}


def fetch_acs(state, counties):
    tables = sorted({v.split("_")[0].lower() for v in list(ACS_VARS) + LOW + HIGH})
    for year in ACS_YEARS:
        got = [_table(year, t, state) for t in tables]
        if all(g is not None for g in got):
            merged = {}
            for g in got:
                for geoid, d in g.items():
                    if geoid[:5] in counties:
                        merged.setdefault(geoid, {}).update(d)
            return year, merged
    raise RuntimeError(f"no ACS 5-year summary file found for years {ACS_YEARS}")


def _hex(g):
    return shapely.to_wkb(shapely.set_srid(g, 4326), hex=True, include_srid=True)


def run(geofence_id):
    core, extent, rec = fetch(geofence_id)
    with connect() as conn:
        states, counties = conn.execute("SELECT states, counties FROM gkg.geofence WHERE geofence_id = %s",
                                        (geofence_id,)).fetchone()
    tracts = []
    for st in states:
        t = gpd.read_file(f"zip://{tiger_zip('tract', st)}").to_crs(config.STORE_CRS)
        tracts.append(t[t.intersects(core)])
    tracts = gpd.pd.concat(tracts)
    print(f"{len(tracts)} tracts intersect the core", flush=True)
    core_m = transform(_to_metric, core)
    shapely.prepare(core_m)
    tract_counties = sorted({g[:5] for g in tracts["GEOID"]})
    acs_year, acs = fetch_acs(states[0], set(tract_counties))
    print(f"ACS 5-year release ending {acs_year}: {len(acs)} tracts returned", flush=True)

    rows, missing = [], 0
    with connect() as conn:
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
            "VALUES (%s, 'stage2', %s, %s) RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION,
             json.dumps({"tiger": config.TIGER_VINTAGE, "acs5_end_year": acs_year}))).fetchone()[0]
        conn.execute("DELETE FROM gkg.census_tract WHERE geofence_id = %s", (geofence_id,))
        for geoid, geom in zip(tracts["GEOID"], tracts.geometry):
            g = shapely.make_valid(geom)
            gm = transform(_to_metric, g)
            share = gm.intersection(core_m).area / gm.area if gm.area > 0 else 0.0
            a = acs.get(geoid)
            if a is None:
                missing += 1
                vals = {k: None for k in ACS_VARS.values()}
                low = high = None
            else:
                vals = {name: _num(a[var]) for var, name in ACS_VARS.items()}
                low = sum(_num(a[v]) or 0 for v in LOW)
                high = sum(_num(a[v]) or 0 for v in HIGH)
            hh = vals["households_tenure_vehicles"]
            nov = None if hh in (None, 0) else ((vals["owner_no_vehicle"] or 0) + (vals["renter_no_vehicle"] or 0)) / hh
            if g.geom_type == "Polygon":
                g = shapely.MultiPolygon([g])
            rows.append((geofence_id, f"urn:urban-kg:CensusTract:census:{config.TIGER_VINTAGE}:{geoid}", geoid,
                         round(share, 6), vals["population"], vals["median_household_income"], nov,
                         vals["households_income"], low, high, acs_year, _hex(g), build_id))
        copy_rows(conn, "gkg.census_tract",
                  ["geofence_id", "urn", "geoid", "share_in_core", "population", "median_household_income",
                   "zero_vehicle_share", "households", "households_below_35k", "households_100k_plus",
                   "acs5_end_year", "geom", "build_id"], rows)
        stats = {"tracts": len(rows), "acs5_end_year": acs_year, "tracts_without_acs": missing}
        conn.execute("UPDATE gkg.build SET stats = %s WHERE build_id = %s", (json.dumps(stats), build_id))
        conn.commit()
    return build_id, stats
