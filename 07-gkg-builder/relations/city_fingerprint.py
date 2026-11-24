"""City-level fingerprint of San Francisco (factor groups A and B of the Fingerprint Factor Specification, draft v0.1).

python -m relations.city_fingerprint [STEP ...]   (from 07-gkg-builder/, on the Mac mini, through the job runner)
Steps: downloads, cityfp, check.

Scope, as Evangelos approved it ("complete the San Francisco fingerprint", Nov 23 16:13; parameters "yes", Nov 23 19:11):
  Group A: factors 1 (parts a-d), 4, 5, 6, 8.   Group B: factors 3, 7, 9, 13, 17.
Not computed here: factor 2 and 11 (need OpenStreetMap tags), 10, 14, 15 (collected by hand), 12 (crash-derived; excluded
from every distance), 16 (no published San Francisco trip records). Factor 7's scaling residuals need a reference set of
cities and are not computed (one city only).

Approved parameters (Nov 23, 18:10 proposal, approved 19:11):
  F1(d)  block areas in four logarithmic bins (<1,000; 1,000-10,000; 10,000-100,000; >=100,000 m2); per bin the share of
         blocks and the median shape factor.
  F3     transit with r5py on the San Francisco feeds, Wednesday 2024-04-17, departures every minute 07:00-09:00, median
         travel time, walking 4.8 km/h; car with the OSRM car profile, free-flow.
  F4     mean and standard deviation over every H3 resolution-8 cell centred on San Francisco land, zero-job cells
         included; neighbours share an edge.
  F6     a run of connected segments flagged bridge (or tunnel) counts as one structure.
  F7     2020 Census urban areas intersected with the city's land, water excluded.
  F8     the city's own median household income (ACS 2020-2024 B19013, place 0667000).
  F9     Overture lodging categories hotel, motel, hostel, inn, bed and breakfast, guest house, resort; airports SFO and
         OAK; enplanements divided by the population of the San Francisco-Oakland-Fremont metro area (CBSA 41860).
  F13    the nearest NOAA station with at least 90 percent complete records for 2015-2024.
  F17    the latest May release of BLS OEWS for the San Francisco metro area.

Public data only. Reads no trip table. Values go to gkg.measured_value as uko:FactorValue rows of one uko:Fingerprint
(version sf-city-v1) of the City entity; tract-level jobs reachable by car and by transit go in as uko:PlaceStatistic rows.
Every proxy is named in the component text and in the job log.
"""
import csv, gzip, io, json, math, os, re, subprocess, sys, time, zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from relations import build as B
from relations import stats_build as S
from relations.build import X, Q, log, copy, edges, rid

G, SF_CITY = S.G, S.SF_CITY
DATA = B.config.DATA_ROOT
DL = DATA / "public" / "2026-11-23-cityfp"
FP_VERSION = "sf-city-v1"
TODAY = date.today().isoformat()
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
SERVICE_DAY = datetime(2024, 4, 17, 7, 0)
WINDOW = timedelta(hours=2)
WALK_KMH = 4.8
LIMIT_MIN = 30
LODGING = {"hotel", "motel", "hostel", "inn", "bed_and_breakfast", "guest_house", "resort"}
AIRPORTS = ["SFO", "OAK"]
CBSA = "41860"
OEWS_OCC = {"53-3054": "Taxi Drivers", "53-3053": "Shuttle Drivers and Chauffeurs"}
ACS_TABLES = ["b01003", "b19013", "b25044"]
PLACE_GEO, CBSA_SUFFIX = "1600000US0667000", "US" + CBSA
URLS = {
    # The Census Data API now requires a key, so place and metro rows come from the national table-based summary files.
    "acs_sf": "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-{t}.dat",
    "uac20": "https://www2.census.gov/geo/tiger/TIGER2024/UAC20/tl_2024_us_uac20.zip",
    "areawater": "https://www2.census.gov/geo/tiger/TIGER2024/AREAWATER/tl_2024_06075_areawater.zip",
    "faa_page": "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger",
    "ghcnd_stations": "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt",
    "ghcnd_station": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{id}.csv",
    "isd_history": "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv",
    "isd_year": "https://www.ncei.noaa.gov/data/global-hourly/access/{year}/{sid}.csv",
    # bls.gov refuses scripted file downloads (HTTP 403), so OEWS values come from the BLS public API (v1, no key).
    "bls_api": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
}
NEW_SOURCES = {
    "acs5y2024-api": "ACS 5-year 2020-2024 table-based summary files, national rows for place 0667000 and CBSA 41860",
    "tiger2024-uac20": "TIGER/Line 2024 2020 Census urban areas (UAC20)",
    "tiger2024-areawater": "TIGER/Line 2024 area hydrography, San Francisco County",
    "faa-enplanements": "FAA passenger boarding (enplanement) data, all airports, latest final calendar year",
    "noaa-ghcnd": "NOAA GHCN-Daily station record",
    "noaa-isd": "NOAA Integrated Surface Database hourly record",
    "bls-oews": "BLS Occupational Employment and Wage Statistics, latest May release, through the BLS public API",
    "osrm-car-norcal": "OSRM car profile on the Geofabrik Northern California extract (free-flow)",
    "r5py-gtfs-2024-04-17": "r5py (R5) on the San Francisco GTFS feeds of the transit stage and the regional OpenStreetMap cut",
}


def _get(url, dest=None, binary=True, timeout=600):
    import requests
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    if dest is None:
        return r.content if binary else r.text
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    import hashlib
    X("insert into gkg.download_manifest values (%(u)s,%(p)s,now(),%(b)s,%(h)s,%(n)s)",
      {"u": url, "p": str(dest), "b": dest.stat().st_size, "h": hashlib.sha256(r.content).hexdigest(), "n": dest.name})
    log(step="download", file=dest.name, bytes=dest.stat().st_size)
    return dest


def _cached(name, url):
    p = DL / name
    return p if p.exists() else _get(url, p)


# --------------------------------------------------------------------------- downloads

def step_downloads():
    """Every public file the city fingerprint needs, with a manifest row each."""
    DL.mkdir(parents=True, exist_ok=True)
    if not (DL / "acs_place_cbsa.json").exists():
        import requests
        rows = {}
        for t in ACS_TABLES:
            with requests.get(URLS["acs_sf"].format(t=t), stream=True, timeout=900, headers=UA) as r:
                r.raise_for_status()
                r.encoding = "utf-8"
                lines = r.iter_lines(decode_unicode=True)
                head = next(lines).split("|")
                for ln in lines:
                    geo = ln.split("|", 1)[0]
                    if geo == PLACE_GEO or (geo.startswith("310") and geo.endswith(CBSA_SUFFIX)):
                        rows.setdefault(geo, {}).update(dict(zip(head, ln.split("|"))))
            X("insert into gkg.download_manifest values (%(u)s,%(p)s,now(),null,null,%(n)s)",
              {"u": URLS["acs_sf"].format(t=t), "p": str(DL / "acs_place_cbsa.json"), "n": f"{t}: rows for place 0667000 and CBSA 41860 kept"})
        (DL / "acs_place_cbsa.json").write_text(json.dumps(rows, indent=1))
        log(step="downloads", acs_geos=sorted(rows))
    _cached("tl_2024_us_uac20.zip", URLS["uac20"])
    _cached("tl_2024_06075_areawater.zip", URLS["areawater"])
    # FAA: the newest final "all enplanements" Excel file linked from the passenger boarding page.
    if not list(DL.glob("faa_*all-enplanements*.xlsx")):
        page = _get(URLS["faa_page"], binary=False)
        links = sorted(set(re.findall(r'href="([^"]*all[-_]enplanements[^"]*)"', page, re.I)))
        log(step="downloads", faa_links=links[:12])
        cands = []
        for l in links:
            m = re.search(r"cy(\d{2,4})", l, re.I)
            if m and "prelim" not in l.lower():
                y = int(m.group(1)); y = y + 2000 if y < 100 else y
                cands.append((y, l))
        for y, l in sorted(cands, reverse=True):
            url = l if l.startswith("http") else "https://www.faa.gov" + l
            if not url.lower().endswith(".xlsx"):
                sub = _get(url, binary=False)
                x = re.findall(r'href="([^"]+\.xlsx)"', sub, re.I)
                if not x:
                    continue
                url = x[0] if x[0].startswith("http") else "https://www.faa.gov" + x[0]
            _get(url, DL / f"faa_cy{y}_all-enplanements.xlsx")
            break
    _cached("ghcnd-stations.txt", URLS["ghcnd_stations"])
    _cached("isd-history.csv", URLS["isd_history"])
    # OEWS mean hourly wage (data type 03) for the metro area; series OEU M 0041860 000000 occupation 03.
    if not (DL / "bls_oews_41860.json").exists():
        import requests
        ids = [f"OEUM00{CBSA}000000{o.replace('-', '')}03" for o in OEWS_OCC]
        r = requests.post(URLS["bls_api"], json={"seriesid": ids}, timeout=120)
        r.raise_for_status()
        (DL / "bls_oews_41860.json").write_text(r.text)
        X("insert into gkg.download_manifest values (%(u)s,%(p)s,now(),%(b)s,null,%(n)s)",
          {"u": URLS["bls_api"] + " " + ",".join(ids), "p": str(DL / "bls_oews_41860.json"), "b": len(r.content), "n": "BLS API v1"})
    log(step="downloads", files=sorted(p.name for p in DL.iterdir()))


# --------------------------------------------------------------------------- helpers

def _city_land():
    """City polygon (the geofence core) minus TIGER area water, in EPSG:4326 and as area in km2."""
    import geopandas as gpd
    from shapely import wkb
    core = wkb.loads(bytes(Q("select ST_AsBinary(core) from gkg.geofence where geofence_id=%(g)s", {"g": G})[0][0]))
    w = gpd.read_file(f"zip://{DL / 'tl_2024_06075_areawater.zip'}").to_crs(4326)
    land = core.difference(w.union_all())
    area = gpd.GeoSeries([land], crs=4326).to_crs(3310).area.iloc[0] / 1e6
    core_area = gpd.GeoSeries([core], crs=4326).to_crs(3310).area.iloc[0] / 1e6
    return core, land, area, core_area


def _xlsx_rows(path):
    """Rows of the first worksheet of an .xlsx file, read with the standard library (openpyxl is not installed)."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheet = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
        out = []
        for row in ET.fromstring(z.read(sheet)).iter("{%s}row" % ns["m"]):
            vals = {}
            for c in row.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", c.get("r")).group(1)
                col = 0
                for ch in ref:
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else None
                vals[col - 1] = val
            out.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
    return out


def _acs_rows():
    d = json.loads((DL / "acs_place_cbsa.json").read_text())
    place = d[PLACE_GEO]
    cbsa = [v for k, v in d.items() if k.startswith("310") and k.endswith(CBSA_SUFFIX)][0]
    return place, cbsa


def _xwalk_blocks():
    """All California LODES blocks with jobs, with their internal points (LODES8 crosswalk)."""
    xw = pd.read_csv(S._download("lodes_xwalk"), dtype=str, usecols=["tabblk2020", "trct", "blklatdd", "blklondd"])
    wac = pd.read_csv(S._download("lodes_wac"), dtype={"w_geocode": str}, usecols=["w_geocode", "C000"])
    b = wac.merge(xw, left_on="w_geocode", right_on="tabblk2020", how="inner")
    b["lat"], b["lon"] = b.blklatdd.astype(float), b.blklondd.astype(float)
    return b[b.C000 > 0][["w_geocode", "trct", "C000", "lat", "lon"]]


def _tract_origins():
    """Population-weighted centroid of each San Francisco tract (2020 block populations), as in the tract fingerprint."""
    blk = pd.DataFrame(Q("select tract, pop20, lon, lat from gkg.census_block_2020 where tract like %(p)s and pop20>0",
                         {"p": S.SF_COUNTY + "%"}), columns=["tract", "pop20", "lon", "lat"])
    cen = blk.groupby("tract").apply(lambda g: pd.Series({"lon": np.average(g.lon, weights=g.pop20),
                                                         "lat": np.average(g.lat, weights=g.pop20)}))
    pop = dict(Q("select geoid, population from gkg.census_tract where geofence_id=%(g)s and geoid like %(p)s",
                 {"g": G, "p": S.SF_COUNTY + "%"}))
    cen["population"] = [pop.get(t) for t in cen.index]
    return cen


def _cells(b, res=10):
    """Job blocks aggregated to H3 cells (job-weighted point per cell); keeps routing requests small.
    Resolution 10 cells average about 0.015 km2, so the snapping error is under about 100 m."""
    import h3
    b = b.assign(cell=[h3.latlng_to_cell(a, o, res) for a, o in zip(b.lat, b.lon)])
    g = b.groupby("cell").apply(lambda x: pd.Series({"jobs": x.C000.sum(), "lat": np.average(x.lat, weights=x.C000),
                                                    "lon": np.average(x.lon, weights=x.C000)}))
    return g.reset_index()


def _haversine_km(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))


# --------------------------------------------------------------------------- factor 3: car (OSRM) and transit (r5py)

def _car_reach(orig, dest):
    """Jobs reachable within 30 minutes by car from each origin: OSRM table service, car profile, free-flow."""
    import requests
    osrm = Path.home() / "geometis-data" / "osrm" / "car" / "norcal.osrm"
    port = 5055
    proc = subprocess.Popen(["/opt/homebrew/bin/osrm-routed", "--algorithm", "mld", "--port", str(port),
                             "--max-table-size", "1100", str(osrm)], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                requests.get(f"http://127.0.0.1:{port}/nearest/v1/driving/-122.42,37.77", timeout=2)
                break
            except Exception:
                time.sleep(1)
        out = np.zeros(len(orig))
        d_xy = dest[["lon", "lat"]].values
        for i0 in range(0, len(orig), 20):
            o = orig.iloc[i0:i0 + 20]
            for j0 in range(0, len(dest), 1000):
                dd = d_xy[j0:j0 + 1000]
                coords = ";".join(f"{x:.6f},{y:.6f}" for x, y in np.r_[o[["lon", "lat"]].values, dd])
                src = ";".join(str(k) for k in range(len(o)))
                dst = ";".join(str(k) for k in range(len(o), len(o) + len(dd)))
                r = requests.get(f"http://127.0.0.1:{port}/table/v1/driving/{coords}?sources={src}&destinations={dst}"
                                 "&annotations=duration", timeout=300).json()
                if r.get("code") != "Ok":
                    raise SystemExit(f"OSRM table failed: {r.get('code')} {r.get('message')}")
                dur = np.array([[np.nan if v is None else v for v in row] for row in r["durations"]], dtype=float)
                ok = dur <= LIMIT_MIN * 60
                out[i0:i0 + len(o)] += (ok * dest.jobs.values[j0:j0 + 1000]).sum(axis=1)
        return out
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def _sanitize_gtfs(src, out_dir):
    """Copy of a GTFS zip that R5's loader accepts: optional tables with no rows are left out, blank transfer_type
    values become 0 (recommended transfer point, the GTFS default), and trips with a time of 72:00:00 or later are
    removed (R5's limit; only long-distance trains have them). Returns the path and a list of the changes."""
    out = out_dir / src.name
    changes = []
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        names = zin.namelist()
        drop_trips = set()
        if "stop_times.txt" in names:
            st = pd.read_csv(zin.open("stop_times.txt"), dtype=str, keep_default_na=False)
            for c in ("arrival_time", "departure_time"):
                h = pd.to_numeric(st[c].str.split(":").str[0], errors="coerce")
                drop_trips |= set(st.trip_id[h >= 72])
            if drop_trips:
                changes.append(f"removed {len(drop_trips)} trips with times of 72 h or more")
        for n in names:
            data = zin.read(n)
            base = n.rsplit("/", 1)[-1]
            if base.endswith(".txt") and base not in ("agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
                                                       "calendar.txt", "calendar_dates.txt"):
                if len([l for l in data.decode("utf-8-sig", "replace").splitlines() if l.strip()]) <= 1:
                    changes.append(f"left out empty {base}")
                    continue
            if base == "transfers.txt":
                t = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
                if "transfer_type" in t:
                    nb = int((t.transfer_type.str.strip() == "").sum())
                    if nb:
                        t.loc[t.transfer_type.str.strip() == "", "transfer_type"] = "0"
                        changes.append(f"set {nb} blank transfer_type values to 0")
                        data = t.to_csv(index=False).encode()
            if base in ("trips.txt", "stop_times.txt", "frequencies.txt") and drop_trips:
                t = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
                if "trip_id" in t:
                    data = t[~t.trip_id.isin(drop_trips)].to_csv(index=False).encode()
            zout.writestr(n, data)
    return out, changes


def _transit_reach(orig, dest, osm, feeds):
    """Jobs reachable within 30 minutes by transit (with walking access and egress): r5py, median over departures
    every minute from 07:00 to 09:00 on 2024-04-17."""
    import r5py, geopandas as gpd
    from shapely.geometry import Point
    work = Path.home() / "Geometis-mini" / "work" / "gkg-full" / "r5-gtfs"
    work.mkdir(parents=True, exist_ok=True)
    clean, dropped = [], []
    for f in feeds:
        c, ch = _sanitize_gtfs(f, work)
        clean.append(c)
        if ch:
            log(step="cityfp", gtfs=f.name, changes=ch)
            dropped.append(f"{f.name} cleaned: " + "; ".join(ch))
    import com.conveyal.gtfs  # available once r5py has started the JVM
    feeds = []
    for c in clean:
        try:
            com.conveyal.gtfs.GTFSFeed.writableTempFileFromGtfs(str(c)).close()
            feeds.append(c)
        except Exception as e:
            dropped.append(f"{c.name} REJECTED by R5's GTFS loader: {str(e)[:120]}")
            log(step="cityfp", r5_dropped_feed=dropped[-1])
    while True:
        try:
            net = r5py.TransportNetwork(str(osm), [str(f) for f in feeds])
            break
        except r5py.util.exceptions.GtfsFileError as e:
            bad = [f for f in feeds if f.name in str(e)]
            if not bad:
                raise
            feeds.remove(bad[0])
            dropped.append(f"{bad[0].name} REJECTED: {str(e).splitlines()[1][:120] if len(str(e).splitlines()) > 1 else str(e)[:120]}")
            log(step="cityfp", r5_dropped_feed=dropped[-1])
    o = gpd.GeoDataFrame({"id": list(orig.index)}, geometry=[Point(x, y) for x, y in zip(orig.lon, orig.lat)], crs=4326)
    d = gpd.GeoDataFrame({"id": list(dest.index)}, geometry=[Point(x, y) for x, y in zip(dest.lon, dest.lat)], crs=4326)
    kw = dict(origins=o, destinations=d, departure=SERVICE_DAY, departure_time_window=WINDOW, percentiles=[50],
              transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK], max_time=timedelta(minutes=LIMIT_MIN),
              speed_walking=WALK_KMH)
    try:
        tt = r5py.TravelTimeMatrix(net, **kw)
    except TypeError:
        tt = r5py.TravelTimeMatrixComputer(net, **kw).compute_travel_times()
    col = [c for c in tt.columns if c.startswith("travel_time")][0]
    tt = tt[tt[col].notna() & (tt[col] <= LIMIT_MIN)]
    jobs = dest.jobs.to_dict()
    reach = tt.assign(j=tt["to_id"].map(jobs)).groupby("from_id").j.sum()
    return np.array([float(reach.get(i, 0.0)) for i in orig.index]), getattr(r5py, "__version__", "?"), dropped


# --------------------------------------------------------------------------- factor 13 helpers

def _ghcnd(core):
    """Days per year (2015-2024) with snowfall >= 1 cm, precipitation >= 10 mm and maximum temperature >= 35 C, from the
    GHCN-Daily station nearest the city with at least 90 percent of days reporting PRCP and TMAX."""
    from shapely.geometry import Point
    st = []
    for line in (DL / "ghcnd-stations.txt").read_text().splitlines():
        sid, lat, lon = line[0:11], float(line[12:20]), float(line[21:30])
        if abs(lat - 37.76) < 0.6 and abs(lon + 122.44) < 0.7:
            st.append((sid, lat, lon, line[41:71].strip()))
    import geopandas as gpd
    cg = gpd.GeoSeries([core], crs=4326).to_crs(3310).iloc[0]
    st = sorted(st, key=lambda s: gpd.GeoSeries([Point(s[2], s[1])], crs=4326).to_crs(3310).iloc[0].distance(cg))
    days = pd.date_range("2015-01-01", "2024-12-31", freq="D")
    tried = []
    for sid, lat, lon, name in st[:40]:
        dist = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(3310).iloc[0].distance(cg)
        if dist > 50000:
            break
        try:
            f = _cached(f"ghcnd_{sid}.csv", URLS["ghcnd_station"].format(id=sid))
        except Exception as e:
            tried.append((sid, name, round(dist), "download failed")); continue
        df = pd.read_csv(f, usecols=lambda c: c in ("DATE", "PRCP", "SNOW", "TMAX"), low_memory=False)
        df["DATE"] = pd.to_datetime(df.DATE)
        df = df[(df.DATE >= days[0]) & (df.DATE <= days[-1])].drop_duplicates("DATE")
        comp = {e: (df[e].notna().sum() / len(days) if e in df else 0.0) for e in ("PRCP", "TMAX", "SNOW")}
        tried.append((sid, name, round(dist), {k: round(v, 3) for k, v in comp.items()}))
        if comp["PRCP"] >= 0.9 and comp["TMAX"] >= 0.9:
            # GHCN-Daily units: PRCP tenths of mm, TMAX tenths of degrees C, SNOW mm.
            pr = (df.PRCP >= 100).sum() / 10
            hot = (df.TMAX >= 350).sum() / 10
            snow = (df.SNOW >= 10).sum() / 10 if comp["SNOW"] >= 0.9 else None
            check = {"tmax_max_C": float(df.TMAX.max()) / 10, "prcp_max_mm": float(df.PRCP.max()) / 10}
            return dict(station=sid, name=name, distance_m=round(dist), completeness=comp, heavy_rain_days=pr,
                        hot_days=hot, snow_days=snow, unit_check=check, tried=tried)
    return dict(station=None, tried=tried)


def _isd_fog(core):
    """Hours per year (2015-2024) with visibility below 1 km, from the ISD station nearest the city whose valid
    visibility reports cover at least 90 percent of hours."""
    from shapely.geometry import Point
    import geopandas as gpd
    h = pd.read_csv(DL / "isd-history.csv", dtype=str)
    h = h[h.LAT.notna() & h.LON.notna()]
    h["lat"], h["lon"] = h.LAT.astype(float), h.LON.astype(float)
    h = h[(h.lat.sub(37.76).abs() < 0.6) & (h.lon.add(122.44).abs() < 0.7) & (h.BEGIN <= "20150101") & (h.END >= "20241231")]
    cg = gpd.GeoSeries([core], crs=4326).to_crs(3310).iloc[0]
    h["dist"] = [gpd.GeoSeries([Point(x, y)], crs=4326).to_crs(3310).iloc[0].distance(cg) for x, y in zip(h.lon, h.lat)]
    h = h.sort_values("dist")
    hours = 10 * 365 * 24 + 3 * 24
    tried = []
    for _, r in h.head(6).iterrows():
        if r.dist > 50000:
            break
        sid, name = f"{r.USAF}{r.WBAN}", str(r.get("STATION NAME", ""))
        vis, ok = [], True
        for y in range(2015, 2025):
            try:
                f = _cached(f"isd_{sid}_{y}.csv", URLS["isd_year"].format(year=y, sid=sid))
            except Exception:
                ok = False
                break
            d = pd.read_csv(f, usecols=["DATE", "VIS"], dtype=str)
            v = d.VIS.str.split(",", expand=True)
            d = d.assign(m=pd.to_numeric(v[0], errors="coerce"), q=v[1])
            d = d[(d.m < 999999) & (~d.q.isin(["2", "3", "6", "7"]))]
            vis.append(d.assign(hour=d.DATE.str[:13]).groupby("hour").m.min())
        if not ok:
            tried.append((sid, name, round(r.dist), "missing years"))
            continue
        v = pd.concat(vis)
        cover = len(v) / hours
        tried.append((sid, name, round(r.dist), round(cover, 3)))
        if cover >= 0.9:
            return dict(station=sid, name=name, distance_m=round(r.dist), coverage=cover,
                        fog_hours=float((v < 1000).sum()) / 10, tried=tried)
    return dict(station=None, tried=tried)


# --------------------------------------------------------------------------- the fingerprint

def step_cityfp():
    import h3, geopandas as gpd
    from shapely import wkb
    from shapely.geometry import Point, shape
    from scipy.sparse.csgraph import dijkstra, connected_components
    from scipy.sparse import coo_matrix
    from scipy.spatial import cKDTree
    t0 = time.time()
    info, comps = {}, []   # comps: (factor, component, value, unit, formula version, source key, proxy note or None)
    core, land, land_km2, core_km2 = _city_land()
    info["core_km2"], info["land_km2"] = round(core_km2, 2), round(land_km2, 2)
    place, cbsa = _acs_rows()
    pop = float(place["B01003_E001"])
    info["acs_place_geo"], info["acs_cbsa_geo"] = place["GEO_ID"], cbsa["GEO_ID"]

    # ---- Factor 1, city level, over the vehicular network of the core.
    seg = pd.DataFrame(Q("""select degrees(ST_Azimuth(ST_StartPoint(l)::geography, ST_EndPoint(l)::geography)),
                                   ST_Length(l::geography), ST_Distance(ST_StartPoint(l)::geography, ST_EndPoint(l)::geography)
                            from (select ST_LineMerge(geom) l from gkg.road_segment where geofence_id=%(g)s and in_core
                                  and coalesce(road_classification,'') not in ('track','unknown')
                                  and coalesce(subclass,'') not in ('parking_aisle','driveway')) s
                            where GeometryType(l)='LINESTRING'""", {"g": G}), columns=["az", "len", "straight"]).dropna()
    az = np.r_[seg.az.values, (seg.az.values + 180) % 360]
    w = np.r_[seg.len.values, seg.len.values]
    p = np.bincount(np.floor(((az + 5) % 360) / 10).astype(int), weights=w, minlength=36)
    p = p[p > 0] / p.sum()
    H = -(p * np.log(p)).sum()
    comps += [("FACTOR_01", "orientation order phi (city)", 1 - ((H - 1.386) / (3.584 - 1.386)) ** 2, "0-1", "f1a-v1", "overture", None),
              ("FACTOR_01", "circuity (city)", seg.len.sum() / seg.straight.sum(), "ratio", "f1b-v1", "overture", None)]
    nd = Q("""select count(*) filter (where degree<>2), count(*) filter (where degree>=4), count(*) filter (where degree=1)
              from gkg.intersection_node where geofence_id=%(g)s and in_core""", {"g": G})[0]
    comps += [("FACTOR_01", "share of intersections with four or more ways (city)", nd[1] / nd[0], "share 0-1", "f1c-v1", "overture", None),
              ("FACTOR_01", "share of dead ends (city)", nd[2] / nd[0], "share 0-1", "f1c-v1", "overture", None)]
    bl = pd.DataFrame(Q("""select ST_Area(b.g), ST_Area(b.g) / (pi() * power(ST_MaxDistance(b.g, b.g) / 2, 2))
                           from (select ST_Transform(a.geom, 3310) g from gkg.aux_entity a join gkg.geofence f on f.geofence_id=a.geofence_id
                                 where a.kind='city_block' and a.geofence_id=%(g)s and ST_Contains(f.core, ST_PointOnSurface(a.geom))) b""",
                        {"g": G}), columns=["area", "shape"])
    edges_ = [0, 1000, 10000, 100000, np.inf]
    labels = ["under 1,000 m2", "1,000 to 10,000 m2", "10,000 to 100,000 m2", "100,000 m2 and above"]
    bl["bin"] = pd.cut(bl.area, edges_, right=False, labels=labels)
    for lab in labels:
        sub = bl[bl.bin == lab]
        note = "the block layer keeps faces of 200 m2 to 2 km2 only" if lab in (labels[0], labels[3]) else None
        comps.append(("FACTOR_01", f"share of blocks, area {lab}", len(sub) / len(bl), "share 0-1", "f1d-hist-v1", "overture", note))
        comps.append(("FACTOR_01", f"median block shape factor, area {lab}", float(sub["shape"].median()) if len(sub) else None,
                      "0-1", "f1d-hist-v1", "overture", note))
    info["f1"] = {"segments": len(seg), "nodes_non2": nd[0], "blocks": len(bl)}

    # ---- Factor 4: polycentricity on H3 resolution 8 (a proxy: job density only, no mobility flows).
    b = _xwalk_blocks()
    sfb = b[b.trct.str.startswith(S.SF_COUNTY)]
    cells_land = set(h3.geo_to_cells(land.__geo_interface__ if land.geom_type == "Polygon" else land.__geo_interface__, 8))
    sfb = sfb.assign(cell=[h3.latlng_to_cell(a, o, 8) for a, o in zip(sfb.lat, sfb.lon)])
    jobs_cell = sfb.groupby("cell").C000.sum()
    lost = int(jobs_cell[~jobs_cell.index.isin(cells_land)].sum())
    cells = sorted(cells_land)
    area = np.array([h3.cell_area(c, unit="km^2") for c in cells])
    jobs = np.array([float(jobs_cell.get(c, 0)) for c in cells])
    dens = jobs / area
    thr = dens.mean() + dens.std(ddof=0)
    hi = [i for i in range(len(cells)) if dens[i] > thr]
    pos = {cells[i]: k for k, i in enumerate(hi)}
    rows, cols_ = [], []
    for k, i in enumerate(hi):
        for nb in h3.grid_disk(cells[i], 1):
            if nb in pos and nb != cells[i]:
                rows.append(k); cols_.append(pos[nb])
    ncomp, lab = connected_components(coo_matrix((np.ones(len(rows)), (rows, cols_)), shape=(len(hi), len(hi))), directed=False) if hi else (0, [])
    total = jobs.sum()
    centres = []
    for c in range(ncomp):
        idx = [hi[k] for k in range(len(hi)) if lab[k] == c]
        jc = jobs[idx].sum()
        if jc >= 0.01 * total:
            ll = np.array([h3.cell_to_latlng(cells[i]) for i in idx])
            centres.append((jc, np.average(ll[:, 0], weights=jobs[idx] + 1e-9), np.average(ll[:, 1], weights=jobs[idx] + 1e-9), len(idx)))
    centres.sort(reverse=True)
    if len(centres) > 1:
        dd = [_haversine_km(a[1], a[2], c[1], c[2]) for i, a in enumerate(centres) for c in centres[i + 1:]]
        mdist = float(np.mean(dd)) / math.sqrt(land_km2)
    else:
        mdist = None
    proxy4 = "proxy: job density only (Bassolas et al. 2019 use mobility flows); thresholds 1 SD and 1 percent are proposals"
    comps += [("FACTOR_04", "number of employment centres", float(len(centres)), "count", "f4-v1", "lodes8-2024", proxy4),
              ("FACTOR_04", "share of jobs in the largest centre", centres[0][0] / total if centres else None, "share 0-1", "f4-v1", "lodes8-2024", proxy4),
              ("FACTOR_04", "mean distance between centres / sqrt(land area)", mdist, "ratio", "f4-v1", "lodes8-2024", proxy4)]
    info["f4"] = {"cells_on_land": len(cells), "jobs_in_cells": int(total), "jobs_in_cells_centred_on_water": lost,
                  "density_mean": round(float(dens.mean()), 1), "density_sd": round(float(dens.std(ddof=0)), 1),
                  "centres": [(int(c[0]), round(c[1], 4), round(c[2], 4), c[3]) for c in centres]}

    # ---- Factor 5, city level: block populations scaled to ACS tract totals.
    m, xy, _ = B._walk_graph(G)
    tree = cKDTree(xy)
    from pyproj import Transformer
    to3310 = Transformer.from_crs(4326, 3310, always_xy=True).transform
    blk = pd.DataFrame(Q("select geoid, tract, pop20, lon, lat from gkg.census_block_2020 where tract like %(p)s", {"p": S.SF_COUNTY + "%"}),
                       columns=["geoid", "tract", "pop20", "lon", "lat"])
    tpop = dict(Q("select geoid, population from gkg.census_tract where geofence_id=%(g)s and geoid like %(p)s", {"g": G, "p": S.SF_COUNTY + "%"}))
    s20 = blk.groupby("tract").pop20.sum()
    blk["pop"] = [r.pop20 * (tpop.get(r.tract) or 0) / s20[r.tract] if s20[r.tract] > 0 else 0 for r in blk.itertuples()]
    bx, by = to3310(blk.lon.values, blk.lat.values)
    blk["off"], blk["node"] = tree.query(np.c_[bx, by], k=1)
    st = pd.DataFrame(Q("""select s.stop_urn, split_part(s.departure_time,':',1)::int h, count(*) from gkg.transit_stop_time s
                          where s.geofence_id=%(g)s and s.departure_time ~ '^[0-9]+:'
                            and split_part(s.departure_time,':',1)::int between 7 and 18 group by 1,2""", {"g": G}), columns=["stop", "h", "n"])
    ok = st[st.n >= 4].groupby("stop").h.nunique()
    freq = list(ok[ok == 12].index)
    sxy = Q("select ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.transit_stop where geofence_id=%(g)s and urn = any(%(u)s)",
            {"g": G, "u": freq})
    _, snode = tree.query(np.array(sxy), k=1)
    Ds = dijkstra(m, directed=False, indices=np.unique(snode), limit=400, min_only=True)
    near = (Ds[blk.node.values] + blk.off.values) <= 400
    comps.append(("FACTOR_05", "share of residents within 400 m walk of a frequent stop (city)", float(blk["pop"][near].sum() / blk["pop"].sum()),
                  "share 0-1", "f5-city-v1", "gkg-derived",
                  "service day is the transit stage's stored weekday per feed (mostly Wed 2024-04-17), not the second Tuesday"))
    info["f5"] = {"frequent_stops": len(freq), "residents_scaled": round(float(blk["pop"].sum()))}

    # ---- Factor 6: topography and structures on the vehicular network of the core.
    r6 = Q("""select sum(length_m), sum(length_m) filter (where not coalesce(is_bridge,false) and not coalesce(is_tunnel,false) and grade is not null),
                     sum(length_m) filter (where not coalesce(is_bridge,false) and not coalesce(is_tunnel,false) and abs(grade) > 0.05),
                     sum(length_m) filter (where not coalesce(is_bridge,false) and not coalesce(is_tunnel,false) and abs(grade) > 0.08)
              from gkg.road_segment where geofence_id=%(g)s and in_core and coalesce(road_classification,'') not in ('track','unknown')
                and coalesce(subclass,'') not in ('parking_aisle','driveway')""", {"g": G})[0]
    total_km = float(r6[0]) / 1000
    structs = {}
    for flag in ("is_bridge", "is_tunnel"):
        e = Q(f"""select from_node, to_node from gkg.road_segment where geofence_id=%(g)s and in_core and coalesce({flag},false)
                  and coalesce(road_classification,'') not in ('track','unknown') and coalesce(subclass,'') not in ('parking_aisle','driveway')""", {"g": G})
        nodes = {n: i for i, n in enumerate(sorted({x for r in e for x in r}))}
        if e:
            mm = coo_matrix((np.ones(len(e)), ([nodes[a] for a, _ in e], [nodes[b_] for _, b_ in e])), shape=(len(nodes), len(nodes)))
            structs[flag] = (connected_components(mm, directed=False)[0], len(e))
        else:
            structs[flag] = (0, 0)
    proxy6 = "grade from the DEM at segment ends (v19 Stage 1); bridge and tunnel segments left out of the grade shares"
    comps += [("FACTOR_06", "share of vehicular length with grade above 5 percent", float(r6[2]) / float(r6[1]), "share 0-1", "f6-v1", "gkg-derived", proxy6),
              ("FACTOR_06", "share of vehicular length with grade above 8 percent", float(r6[3]) / float(r6[1]), "share 0-1", "f6-v1", "gkg-derived", proxy6),
              ("FACTOR_06", "bridges per 100 km of vehicular network", structs["is_bridge"][0] / total_km * 100, "count per 100 km", "f6-v1", "overture",
               "a structure is a connected run of bridge-flagged segments (Overture road flags)"),
              ("FACTOR_06", "tunnels per 100 km of vehicular network", structs["is_tunnel"][0] / total_km * 100, "count per 100 km", "f6-v1", "overture",
               "a structure is a connected run of tunnel-flagged segments (Overture road flags)")]
    info["f6"] = {"vehicular_km": round(total_km, 1), "graded_km": round(float(r6[1]) / 1000, 1),
                  "bridges": structs["is_bridge"], "tunnels": structs["is_tunnel"]}

    # ---- Factor 8, city level.
    lo_hi = Q("""select households_below_35k, households_100k_plus from gkg.census_tract where geofence_id=%(g)s and geoid like %(p)s
                 and households_below_35k is not null and households_100k_plus is not null""", {"g": G, "p": S.SF_COUNTY + "%"})
    lo = np.array([float(r[0]) for r in lo_hi]); hi_ = np.array([float(r[1]) for r in lo_hi])
    dissim = 0.5 * np.abs(lo / lo.sum() - hi_ / hi_.sum()).sum()
    zv = (float(place["B25044_E003"]) + float(place["B25044_E010"])) / float(place["B25044_E001"])
    comps += [("FACTOR_08", "median household income (city, ACS B19013 place)", float(place["B19013_E001"]), "US dollars, inflation-adjusted to 2024",
               "f8a-city-v1", "acs5y2024-api", None),
              ("FACTOR_08", "share of households with no vehicle (city, ACS B25044 place)", zv, "share 0-1", "f8b-city-v1", "acs5y2024-api", None),
              ("FACTOR_08", "income dissimilarity index, households below $35,000 vs $100,000 and above, across tracts", float(dissim),
               "index 0-1", "f8c-v1", "acs5y2024", "income bands are a proposal in the specification; the Reardon rank-order index is the alternative")]
    info["f8"] = {"tracts_in_index": len(lo_hi)}

    # ---- Factor 7.
    ua = gpd.read_file(f"zip://{DL / 'tl_2024_us_uac20.zip'}", bbox=(-123.2, 37.4, -122.0, 38.0)).to_crs(4326)
    urb = gpd.GeoSeries([land.intersection(ua.union_all())], crs=4326).to_crs(3310).area.iloc[0] / 1e6
    comps += [("FACTOR_07", "population (ACS 2020-2024, place)", pop, "persons", "f7-v1", "acs5y2024-api", None),
              ("FACTOR_07", "urbanized land area (2020 urban areas within city land)", urb, "km2", "f7-v1", "tiger2024-uac20",
               "scaling residual not computed: one city, no reference set")]
    info["f7"] = {"urban_areas_in_bbox": list(ua.NAME20) if "NAME20" in ua else len(ua), "city_land_km2": round(land_km2, 2)}

    # ---- Factor 9.
    lodg = Q("""select taxonomy_primary, count(*) from gkg.place p join gkg.geofence f on f.geofence_id=p.geofence_id
                where p.geofence_id=%(g)s and ST_Contains(f.core, p.geom) and taxonomy_primary = any(%(c)s) group by 1""",
             {"g": G, "c": sorted(LODGING)})
    n_lodg = sum(r[1] for r in lodg)
    comps.append(("FACTOR_09", "lodging places per 1,000 residents", n_lodg / pop * 1000, "count per 1,000", "f9a-v1", "overture",
                  "places, not rooms; Overture categories hotel, motel, hostel, inn, bed_and_breakfast, guest_house, resort"))
    info["f9_lodging"] = dict(lodg)
    fx = sorted(DL.glob("faa_cy*_all-enplanements.xlsx"))
    if fx:
        fa = pd.DataFrame(_xlsx_rows(fx[-1]))
        hdr = next(i for i in range(15) if any(str(v).strip().lower() == "locid" for v in fa.iloc[i]))
        fa.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in fa.iloc[hdr]]
        fa = fa.iloc[hdr + 1:]
        ecol = [c for c in fa.columns if re.match(r"CY\s*\d+\s*Enplanements", c, re.I)][0]
        ap = fa[fa.Locid.astype(str).str.strip().isin(AIRPORTS)]
        enp = {r.Locid.strip(): float(str(r[ecol]).replace(",", "")) for _, r in ap.iterrows()}
        comps.append(("FACTOR_09", "annual airport enplanements per metro resident (SFO and OAK)", sum(enp.values()) / float(cbsa["B01003_E001"]),
                      "ratio", "f9b-v1", "faa-enplanements", f"{fx[-1].name}, column {ecol}; airports within 40 km taken as SFO and OAK"))
        info["f9_enplanements"] = enp
        info["f9_metro_population"] = float(cbsa["B01003_E001"])

    # ---- Factor 3: tract values by car, transit and walking; city value = resident-weighted mean.
    orig = _tract_origins()
    dest_all = _cells(b, 10)
    dkm = _haversine_km(37.76, -122.44, dest_all.lat.values, dest_all.lon.values)
    dest_car = dest_all[dkm <= 70].reset_index(drop=True)
    cache = Path.home() / "Geometis-mini" / "work" / "gkg-full" / f"cityfp-car-cache-{len(orig)}-{len(dest_car)}.json"
    if cache.exists():
        car = np.array(json.loads(cache.read_text()))
    else:
        car = _car_reach(orig, dest_car)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(car.tolist()))
    log(step="cityfp", car_done=True, car_destinations=len(dest_car))
    osm = Path.home() / "geometis-data" / "gkg" / "r5" / "sf.osm.pbf"
    bbox = (-122.6501, 37.4460, -121.8962, 38.0999)
    dest_tr = dest_all[(dest_all.lon > bbox[0]) & (dest_all.lon < bbox[2]) & (dest_all.lat > bbox[1]) & (dest_all.lat < bbox[3])].reset_index(drop=True)
    sv = Q("select source_versions from gkg.build where geofence_id=%(g)s and stage='stage3-transit' order by build_id desc limit 1", {"g": G})[0][0]
    feeds, nosvc = [], []
    for f in sv.get("feeds", []):
        if f.get("status") != "loaded" or not f.get("dataset"):
            continue
        span = f.get("service_span") or ["0", "0"]
        path = B.GTFS_CACHE / f["feed"] / f"{f['dataset']}.zip"
        if not (span[0] <= "20240417" <= span[1]):
            # A feed with no service on the day adds no departures, so leaving it out does not change any travel time.
            nosvc.append(f"{f['feed']} {f.get('provider', '')} ({span[0]}-{span[1]})")
        elif path.exists():
            feeds.append(path)
    transit, r5v, r5_dropped = _transit_reach(orig, dest_tr, osm, feeds)
    walk = dict(Q("""select c.geoid, v.value from gkg.measured_value v join gkg.entity e on e.eid=v.feature_eid
                     join gkg.census_tract c on c.geofence_id=e.geofence_id and c.urn=e.urn
                     where v.variable='VAR_JOBS_REACHABLE' and v.travel_mode='MODE_WALK'"""))
    orig["car"], orig["transit"] = car, transit
    orig["walk"] = [walk.get(t) for t in orig.index]
    wts = orig.population.fillna(0)
    for mode, col, note in (("car", "car", "free-flow car times overstate peak access; jobs anywhere in California within reach"),
                            ("transit", "transit", "network and jobs limited to the regional OSM cut; feeds without service on 2024-04-17: " + "; ".join(nosvc)
                             + ("; " + "; ".join(r5_dropped) if r5_dropped else "")),
                            ("walking", "walk", "tract walking values of Nov 22 (graph walk, San Francisco jobs only)")):
        sel = orig[col].notna() & (wts > 0)
        comps.append(("FACTOR_03", f"jobs reachable within 30 minutes by {mode} (resident-weighted mean of tracts)",
                      float(np.average(orig[col][sel], weights=wts[sel])), "jobs", f"f3-{col}-city-v1",
                      {"car": "osrm-car-norcal", "transit": "r5py-gtfs-2024-04-17", "walk": "lodes8-2024"}[col], note))
    info["f3"] = {"origins": len(orig), "car_destinations_h3r10": len(dest_car), "transit_destinations_h3r10": len(dest_tr),
                  "feeds": [p.name for p in feeds], "feeds_without_service_on_day": nosvc, "r5py": r5v, "r5_dropped": r5_dropped,
                  "tract_median_car": float(np.median(car)), "tract_median_transit": float(np.median(transit))}

    # ---- Factor 13.
    gh = _ghcnd(core)
    info["f13_ghcnd"] = gh
    if gh.get("station"):
        note = f"GHCN-Daily {gh['station']} {gh['name']}, {gh['distance_m']} m from the city"
        comps += [("FACTOR_13", "days per year with precipitation of 10 mm or more", gh["heavy_rain_days"], "days per year", "f13-v1", "noaa-ghcnd", note),
                  ("FACTOR_13", "days per year with maximum temperature of 35 C or more", gh["hot_days"], "days per year", "f13-v1", "noaa-ghcnd", note),
                  ("FACTOR_13", "days per year with snowfall of 1 cm or more", gh["snow_days"], "days per year", "f13-v1", "noaa-ghcnd",
                   note + ("" if gh["snow_days"] is not None else "; SNOW reported on fewer than 90 percent of days, value missing"))]
    isd = _isd_fog(core)
    info["f13_isd"] = isd
    if isd.get("station"):
        comps.append(("FACTOR_13", "hours per year with visibility below 1 km", isd["fog_hours"], "hours per year", "f13-v1", "noaa-isd",
                      f"proxy for fog; ISD {isd['station']} {isd['name']}, {isd['distance_m']} m from the city"))

    # ---- Factor 17 (BLS API; the latest annual value is the May release of that year).
    bj = json.loads((DL / "bls_oews_41860.json").read_text())
    info["f17"] = {"messages": bj.get("message")}
    for ser in bj.get("Results", {}).get("series", []):
        occ = ser["seriesID"][-8:-2]
        occ = occ[:2] + "-" + occ[2:]
        latest = [x for x in ser.get("data", []) if x.get("latest") == "true"]
        val = float(latest[0]["value"]) if latest and latest[0]["value"] not in ("-", "") else None
        note = (f"May {latest[0]['year']} release; employed drivers only, gig ride-hail drivers not counted" if latest
                else "no estimate published for this metro area")
        comps.append(("FACTOR_17", f"mean hourly wage, SOC {occ} {OEWS_OCC.get(occ, '')}", val, "US dollars per hour", "f17-v1", "bls-oews", note))
        info["f17"][occ] = latest[0] if latest else None

    # ---- Store: data sources, the fingerprint, its factor values, tract reach statistics, and their edges.
    for k, v in NEW_SOURCES.items():
        X("insert into gkg.aux_entity values (%(g)s, %(u)s, 'uko:DataSource', 'data_source', %(n)s, null, null) "
          "on conflict (geofence_id, urn) do update set name=excluded.name", {"g": G, "u": f"urn:urban-kg:DataSource:{k}", "n": v})
        S.ent(f"urn:urban-kg:DataSource:{k}", "uko:DataSource", "aux:data_source")
    if not S.src_eid("overture"):
        S.ent("urn:urban-kg:DataSource:overture", "uko:DataSource", "aux:data_source")
    for c in ("uko:fingerprintOf", "uko:hasFactorValue", "uko:valueOfFactor"):
        X("""delete from gkg.edge x using gkg.entity e where x.rid=%(r)s and (x.subj=e.eid or x.obj=e.eid)
             and e.src in ('fp:city_fingerprint','fp:city_factor_value')""", {"r": rid(c)})
    S.drop_src("fp:city_fingerprint", "fp:city_factor_value", "stat:reach_city")
    city = S.eid(SF_CITY)
    fpu = S.murn("Fingerprint", G, "0667000", FP_VERSION)
    fp = S.ent(fpu, "uko:Fingerprint", "fp:city_fingerprint")
    X("insert into gkg.aux_entity values (%(g)s,%(u)s,'uko:Fingerprint','fingerprint',%(n)s,%(p)s,null) on conflict (geofence_id, urn) "
      "do update set props=excluded.props", {"g": G, "u": fpu, "n": "San Francisco city",
                                              "p": json.dumps({"fingerprintVersion": FP_VERSION, "computedOn": TODAY, "area": "City 0667000"})})
    rows = []
    for fac, comp, val, unit, fver, skey, note in comps:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            log(step="cityfp", missing=f"{fac} {comp}", note=note)
            continue
        rows.append(dict(urn=S.murn("FactorValue", G, "0667000", FP_VERSION, fac, comp), cls="uko:FactorValue", feature=city,
                         variable=fac, value=float(val), unit=unit, component=comp + (f" [{note}]" if note else ""),
                         formula_version=fver, residual=False, proc="PROC_FINGERPRINT_FORMULA",
                         source=S.src_eid(skey), p0=TODAY, p1=TODAY, fingerprint=fp))
    S.add_values("factor_value", "fp:city_factor_value", rows)
    tr = dict(Q("select c.geoid, e.eid from gkg.census_tract c join gkg.entity e on e.geofence_id=c.geofence_id and e.urn=c.urn "
                "where c.geofence_id=%(g)s", {"g": G}))
    srows = []
    for t, r in orig.iterrows():
        for mode, col, skey in (("MODE_CAR", "car", "osrm-car-norcal"), ("MODE_TRANSIT", "transit", "r5py-gtfs-2024-04-17")):
            srows.append(dict(urn=S.murn("PlaceStatistic", G, t, f"jobs-{col}-30", S.LODES_YEAR), cls="uko:PlaceStatistic", feature=tr.get(t),
                              variable="VAR_JOBS_REACHABLE", mode=mode, threshold=30, value=float(r[col]), unit="jobs",
                              proc="PROC_NETWORK_REACH", source=S.src_eid(skey), p0=S.LODES_PERIOD[0], p1=S.LODES_PERIOD[1],
                              table=f"LODES8 {S.LODES_YEAR} C000 on H3 r10 cells; from the tract's population-weighted centroid"))
    S.add_values("place_statistic", "stat:reach_city", srows)
    src, meth = "GKG city fingerprint (relations/city_fingerprint.py)", f"fingerprint {FP_VERSION}"
    edges("uko:fingerprintOf", src, meth, f"select {fp}, {city}, null::real")
    edges("uko:hasFactorValue", src, meth, f"select {fp}, eid, null::real from gkg.measured_value where fingerprint_eid={fp}")
    edges("uko:valueOfFactor", src, meth, f"""select v.eid, f.eid, null::real from gkg.measured_value v join gkg.entity f
             on f.geofence_id='{G}' and f.urn='urn:urban-kg:'||v.variable where v.fingerprint_eid={fp}""")
    out = Path.home() / "Geometis-mini" / "work" / "gkg-full" / f"city-fingerprint-{TODAY}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"components": [dict(zip(["factor", "component", "value", "unit", "formula", "source", "note"], c)) for c in comps],
                               "info": info}, default=str, indent=1))
    log(step="cityfp", values=len(rows), reach_stats=len(srows), seconds=round(time.time() - t0, 1), summary=str(out))


def step_check():
    r = Q("""select v.variable, v.component, round(v.value::numeric, 4), v.unit from gkg.measured_value v join gkg.entity e on e.eid=v.eid
             where e.src='fp:city_factor_value' order by 1, 2""")
    for x in r:
        print(" | ".join(str(c) for c in x))
    print(Q("select travel_mode, count(*), round(min(value)), round(percentile_cont(0.5) within group (order by value)), round(max(value)) "
            "from gkg.measured_value v join gkg.entity e on e.eid=v.eid where e.src='stat:reach_city' group by 1"))
    print(Q("""select rt.curie, count(*) from gkg.edge x join gkg.relation_type rt on rt.rid=x.rid join gkg.entity e on e.eid in (x.subj, x.obj)
               where e.src in ('fp:city_fingerprint','fp:city_factor_value') group by 1"""))


STEPS = [("downloads", step_downloads), ("cityfp", step_cityfp), ("check", step_check)]

if __name__ == "__main__":
    want = sys.argv[1:] or [s for s, _ in STEPS]
    for name, fn in STEPS:
        if name in want:
            t = time.time()
            log(step=name, status="start")
            fn()
            log(step=name, status="done", seconds=round(time.time() - t, 1))
