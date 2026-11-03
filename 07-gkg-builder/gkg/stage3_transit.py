"""Knowledge Builder Stage 3, transit part: GTFS-static for the geofence (v19 section 9.3, Stage 3).

Source: the Mobility Database archive. For each feed whose bounding box touches the extent, the
loader picks the archived dataset whose service calendar covers the reference date (the month of the
client trips). When no archived dataset covers that date, the loader takes the nearest one and marks
the feed "nearest" with the gap in days, so that the build record shows the mismatch.

Output, for stops inside the extent: agencies, routes (with the UKO route class from route_type),
stops and stations, the stop times of trips that run on the reference date, the service calendar
rows for those trips, the road segment each stop sits on (uko:connectsToTransit), and one walkshed
per stop computed on the walkable network (vehicular segments other than motorways, plus the
pedestrian layer, joined at access points).

Mobility Database credentials come from MOBILITY_DB_TOKEN (a refresh token) in the environment.
"""
import datetime as dt
import io
import json
import os
import urllib.request
import uuid
import zipfile

import numpy as np
import pandas as pd
import shapely
from shapely.ops import transform
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from . import config
from .db import connect, copy_rows
from .geofence import fetch

MDB = "https://api.mobilitydatabase.org/v1"
URN_NS = uuid.UUID("6f1c2a5e-3b7d-4e8a-9c41-0d2b7e5f9a10")
# GTFS route_type to UKO route class (GTFS reference, routes.txt; extended types by their hundreds).
ROUTE_CLASS = {0: "LightRailRoute", 1: "SubwayRoute", 2: "RailRoute", 3: "BusRoute", 4: "FerryRoute",
               5: "LightRailRoute", 11: "BusRoute", 12: "RailRoute"}
EXT_CLASS = {1: "RailRoute", 2: "RailRoute", 4: "RailRoute", 7: "BusRoute", 9: "LightRailRoute",
             10: "LightRailRoute", 11: "BusRoute", 12: "FerryRoute"}

_to_m = Transformer.from_crs(config.STORE_CRS, config.METRIC_CRS, always_xy=True).transform


def route_class(rt):
    rt = int(rt)
    if rt in ROUTE_CLASS:
        return ROUTE_CLASS[rt]
    return EXT_CLASS.get(rt // 100, "TransitRoute")


def urn(kind, *parts):
    return f"urn:urban-kg:{kind}:gtfs:{uuid.uuid5(URN_NS, '|'.join([kind] + [str(p) for p in parts]))}"


# ---------------------------------------------------------------- Mobility Database access

class MobilityDatabase:
    def __init__(self):
        tok = os.environ.get("MOBILITY_DB_TOKEN")
        if not tok:
            raise RuntimeError("MOBILITY_DB_TOKEN is not set; source ~/.geometis-env first")
        req = urllib.request.Request(f"{MDB}/tokens", data=json.dumps({"refresh_token": tok}).encode(),
                                     headers={"Content-Type": "application/json"})
        self.access = json.load(urllib.request.urlopen(req, timeout=60))["access_token"]

    def get(self, path):
        req = urllib.request.Request(f"{MDB}{path}", headers={"Authorization": f"Bearer {self.access}"})
        return json.load(urllib.request.urlopen(req, timeout=120))

    def feeds_touching(self, bounds):
        xmin, ymin, xmax, ymax = bounds
        out, offset = [], 0
        while True:
            page = self.get(f"/gtfs_feeds?limit=100&offset={offset}&dataset_latitudes={ymin:.5f},{ymax:.5f}"
                            f"&dataset_longitudes={xmin:.5f},{xmax:.5f}&bounding_filter_method=partially_enclosed")
            out += page
            if len(page) < 100:
                return out
            offset += 100

    def datasets(self, feed_id, after, before):
        return self.get(f"/gtfs_feeds/{feed_id}/datasets?limit=500&downloaded_after={after}T00:00:00Z"
                        f"&downloaded_before={before}T00:00:00Z")


def download(url, dest):
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=600) as r:
            data = r.read()
        zipfile.ZipFile(io.BytesIO(data)).testzip()
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.rename(dest)
    return dest


# ---------------------------------------------------------------- GTFS reading

def read(zf, name, usecols=None):
    names = {n.split("/")[-1]: n for n in zf.namelist()}
    if name not in names:
        return None
    with zf.open(names[name]) as f:
        df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    if usecols:
        for c in usecols:
            if c not in df.columns:
                df[c] = ""
        df = df[usecols]
    return df


def calendar_span(zf):
    """First and last service date in calendar.txt and calendar_dates.txt (added service only)."""
    days = []
    cal = read(zf, "calendar.txt", ["start_date", "end_date"])
    if cal is not None and len(cal):
        days += list(cal["start_date"]) + list(cal["end_date"])
    cd = read(zf, "calendar_dates.txt", ["date", "exception_type"])
    if cd is not None and len(cd):
        days += list(cd.loc[cd["exception_type"] == "1", "date"])
    days = sorted(d for d in days if len(d) == 8)
    return (days[0], days[-1]) if days else (None, None)


def active_services(zf, day):
    """Service ids that run on day (YYYYMMDD), following calendar.txt and calendar_dates.txt."""
    wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
        dt.datetime.strptime(day, "%Y%m%d").weekday()]
    on = set()
    cal = read(zf, "calendar.txt")
    if cal is not None and len(cal):
        m = (cal["start_date"] <= day) & (cal["end_date"] >= day) & (cal[wd] == "1")
        on |= set(cal.loc[m, "service_id"])
    cd = read(zf, "calendar_dates.txt", ["service_id", "date", "exception_type"])
    if cd is not None and len(cd):
        cd = cd[cd["date"] == day]
        on |= set(cd.loc[cd["exception_type"] == "1", "service_id"])
        on -= set(cd.loc[cd["exception_type"] == "2", "service_id"])
    return on


def pick_dataset(mdb, feed, ref_day, cache):
    """The archived dataset that covers ref_day, else the nearest one by service dates."""
    ref = dt.date(int(ref_day[:4]), int(ref_day[4:6]), int(ref_day[6:]))
    after = (ref - dt.timedelta(days=400)).isoformat()
    before = (ref + dt.timedelta(days=400)).isoformat()
    ds = sorted(mdb.datasets(feed["id"], after, before), key=lambda x: x["downloaded_at"])
    if not ds:
        return None
    # Datasets downloaded on or before the reference date first, newest first; then later ones, oldest first.
    early = [d for d in ds if d["downloaded_at"][:10] <= ref.isoformat()][::-1]
    late = [d for d in ds if d["downloaded_at"][:10] > ref.isoformat()]
    best, best_gap = None, None
    for d in early[:3] + late[:3]:
        path = download(d["hosted_url"], cache / feed["id"] / f"{d['id']}.zip")
        with zipfile.ZipFile(path) as zf:
            lo, hi = calendar_span(zf)
            covers = lo is not None and lo <= ref_day <= hi and bool(active_services(zf, ref_day))
        if covers:
            return dict(dataset=d, path=path, span=(lo, hi), match="covers", gap_days=0)
        if lo is None:
            continue
        lo_d, hi_d = (dt.datetime.strptime(x, "%Y%m%d").date() for x in (lo, hi))
        gap = (lo_d - ref).days if lo_d > ref else (ref - hi_d).days
        if best_gap is None or gap < best_gap:
            best, best_gap = dict(dataset=d, path=path, span=(lo, hi), match="nearest", gap_days=gap), gap
    return best


# ---------------------------------------------------------------- walkable network

def walk_graph(conn, geofence_id):
    """Nodes and undirected edges of the walkable network, in metric coordinates."""
    rows = conn.execute(
        "SELECT from_node, to_node, length_m FROM gkg.road_segment WHERE geofence_id = %s "
        "AND coalesce(road_classification, '') NOT IN ('motorway') "
        "UNION ALL SELECT from_node, to_node, length_m FROM gkg.pedestrian_edge WHERE geofence_id = %s "
        "UNION ALL SELECT intersection_node, pedestrian_node, 0 FROM gkg.access_point WHERE geofence_id = %s",
        (geofence_id, geofence_id, geofence_id)).fetchall()
    pts = conn.execute(
        "SELECT urn, ST_X(geom), ST_Y(geom) FROM gkg.intersection_node WHERE geofence_id = %s "
        "UNION ALL SELECT urn, ST_X(geom), ST_Y(geom) FROM gkg.pedestrian_node WHERE geofence_id = %s",
        (geofence_id, geofence_id)).fetchall()
    idx = {u: i for i, (u, _, _) in enumerate(pts)}
    x, y = _to_m(np.array([p[1] for p in pts]), np.array([p[2] for p in pts]))
    # Nodes with an incident motorway segment only stay in the index but get no walkable edge.
    a = np.array([idx[r[0]] for r in rows if r[0] in idx and r[1] in idx])
    b = np.array([idx[r[1]] for r in rows if r[0] in idx and r[1] in idx])
    w = np.array([max(float(r[2]), 0.01) for r in rows if r[0] in idx and r[1] in idx])
    n = len(pts)
    g = coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    deg = np.diff(g.indptr)
    return g, np.c_[x, y], deg


def walksheds(conn, geofence_id, stops_xy):
    """Network reach of each stop within the threshold, with exponential distance decay."""
    g, xy, deg = walk_graph(conn, geofence_id)
    walkable = np.where(deg > 0)[0]
    tree = cKDTree(xy[walkable])
    snap_d, snap_i = tree.query(stops_xy, k=1)
    src = walkable[snap_i]
    thr, beta = config.WALKSHED_THRESHOLD_M, config.WALKSHED_BETA
    out = []
    for k in range(0, len(src), 200):
        chunk = src[k:k + 200]
        dist = dijkstra(g, directed=False, indices=chunk, limit=thr)
        for j, s in enumerate(chunk):
            d = dist[j] + snap_d[k + j]
            reach = np.where(d <= thr)[0]
            if snap_d[k + j] > config.WALKSHED_MAX_SNAP_M or len(reach) < 2:
                out.append(None)
                continue
            p = xy[reach]
            hull = shapely.concave_hull(shapely.multipoints(p), ratio=0.3)
            out.append(dict(snap_m=float(snap_d[k + j]), nodes=int(len(reach)),
                            decay_weighted_nodes=float(np.exp(-beta * d[reach]).sum()),
                            area_m2=float(hull.area), hull=hull))
    return out


# ---------------------------------------------------------------- main

def run(geofence_id, ref_day=None):
    ref_day = ref_day or config.TRANSIT_REFERENCE_DATE
    core, extent, rec = fetch(geofence_id)
    shapely.prepare(extent)
    shapely.prepare(core)
    cache = config.DATA_ROOT / "gtfs" / "mobilitydatabase"
    mdb = MobilityDatabase()
    feeds = mdb.feeds_touching(extent.bounds)
    print(f"{len(feeds)} feeds touch the extent bounding box", flush=True)

    agencies, routes, stops, stop_times, cal_rows, feed_log = [], [], [], [], [], []
    picks = {}
    for f in feeds:
        try:
            picks[f["id"]] = pick_dataset(mdb, f, ref_day, cache)
        except Exception as e:  # one broken archive must not stop the build
            feed_log.append(dict(feed=f["id"], provider=f.get("provider"), status="error", error=str(e)[:200]))
            picks[f["id"]] = "error"
    # A deprecated feed and the feed it redirects to describe the same service: keep only the member of each
    # redirect group whose dataset lies closest to the reference date.
    group = {f["id"]: f["id"] for f in feeds}

    def root(x):
        while group.setdefault(x, x) != x:
            x = group[x]
        return x
    for f in feeds:
        for r in f.get("redirects") or []:
            group[root(f["id"])] = root(r["target_id"])
    best = {}
    for f in feeds:
        p = picks[f["id"]]
        if isinstance(p, dict):
            key = (p["gap_days"], 0 if p["match"] == "covers" else 1, -int(p["dataset"]["downloaded_at"][:10].replace("-", "")))
            g = root(f["id"])
            if g not in best or key < best[g][0]:
                best[g] = (key, f["id"])
    keep = {v[1] for v in best.values()}
    for f in feeds:
        pick = picks[f["id"]]
        if pick == "error":
            continue
        if pick is None:
            feed_log.append(dict(feed=f["id"], provider=f.get("provider"), status="no dataset in archive"))
            continue
        if f["id"] not in keep:
            feed_log.append(dict(feed=f["id"], provider=f.get("provider"), dataset=pick["dataset"]["id"],
                                 match=pick["match"], gap_days=pick["gap_days"],
                                 status=f"superseded by {best[root(f['id'])][1]} (same redirect group)"))
            continue
        with zipfile.ZipFile(pick["path"]) as zf:
            st = read(zf, "stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type",
                                        "parent_station", "wheelchair_boarding"])
            st = st[(st["stop_lat"] != "") & (st["stop_lon"] != "")]
            pts = shapely.points(st["stop_lon"].astype(float).values, st["stop_lat"].astype(float).values)
            inside = shapely.intersects(extent, pts)
            entry = dict(feed=f["id"], provider=f.get("provider"), dataset=pick["dataset"]["id"],
                         downloaded=pick["dataset"]["downloaded_at"][:10], service_span=list(pick["span"]),
                         match=pick["match"], gap_days=pick["gap_days"], stops_inside=int(inside.sum()))
            if not inside.any():
                entry["status"] = "no stops inside the extent"
                feed_log.append(entry)
                continue
            entry["status"] = "loaded"
            feed_log.append(entry)
            st = st[inside].copy()
            st["geom"] = pts[inside]
            day = ref_day if pick["match"] == "covers" else None
            services = active_services(zf, day) if day else None
            tr = read(zf, "trips.txt", ["route_id", "service_id", "trip_id", "direction_id", "shape_id"])
            if services is None:
                # Nearest dataset: use the weekday in its own calendar that falls closest to the reference weekday.
                lo, hi = pick["span"]
                target = dt.datetime.strptime(ref_day, "%Y%m%d").weekday()
                d0 = dt.datetime.strptime(lo if pick["span"][0] > ref_day else hi, "%Y%m%d").date()
                step = 1 if pick["span"][0] > ref_day else -1
                for _ in range(21):
                    if d0.weekday() == target and active_services(zf, d0.strftime("%Y%m%d")):
                        break
                    d0 += dt.timedelta(days=step)
                day = d0.strftime("%Y%m%d")
                services = active_services(zf, day)
            entry["service_day_used"] = day
            tr = tr[tr["service_id"].isin(services)]
            sot = read(zf, "stop_times.txt", ["trip_id", "arrival_time", "departure_time", "stop_id",
                                              "stop_sequence"])
            sot = sot[sot["trip_id"].isin(set(tr["trip_id"]))]
            # Platforms count for their parent station as well.
            parent = dict(zip(st["stop_id"], st["parent_station"]))
            sot_in = sot[sot["stop_id"].isin(set(st["stop_id"]))].merge(tr[["trip_id", "route_id"]], on="trip_id")
            rt = read(zf, "routes.txt", ["route_id", "agency_id", "route_short_name", "route_long_name",
                                         "route_type"])
            ag = read(zf, "agency.txt", ["agency_id", "agency_name", "agency_url", "agency_timezone"])
            fid = f["id"]
            ag_urn = {}
            used_routes = set(sot_in["route_id"])
            used_ag = set(rt.loc[rt["route_id"].isin(used_routes), "agency_id"])
            for _, a in ag.iterrows():
                u = urn("TransitAgency", fid, a["agency_id"] or a["agency_name"])
                ag_urn[a["agency_id"]] = u
                if a["agency_id"] in used_ag or len(ag) == 1:
                    agencies.append((geofence_id, u, fid, a["agency_id"], a["agency_name"], a["agency_url"], build_ph))
            default_ag = next(iter(ag_urn.values())) if ag_urn else None
            trips_per_route = tr[tr["route_id"].isin(used_routes)].groupby("route_id").size().to_dict()
            for _, r in rt[rt["route_id"].isin(used_routes)].iterrows():
                cls = route_class(r["route_type"] or 3)
                routes.append((geofence_id, urn("TransitRoute", fid, r["route_id"]), fid, r["route_id"],
                               r["route_short_name"], r["route_long_name"], int(r["route_type"] or 3), cls,
                               ag_urn.get(r["agency_id"], default_ag), int(trips_per_route.get(r["route_id"], 0)),
                               day, build_ph))
            dep = sot_in.groupby("stop_id").size().to_dict()
            rts = sot_in.groupby("stop_id")["route_id"].apply(lambda s: sorted(set(s))).to_dict()
            rtype = dict(zip(rt["route_id"], rt["route_type"]))
            for _, s in st.iterrows():
                kids = [k for k, p in parent.items() if p == s["stop_id"]]
                n_dep = dep.get(s["stop_id"], 0) + sum(dep.get(k, 0) for k in kids)
                r_ids = sorted(set(rts.get(s["stop_id"], [])).union(*[rts.get(k, []) for k in kids]))
                lt = s["location_type"] or "0"
                types = {int(rtype.get(r) or 3) for r in r_ids}
                if lt == "1":
                    cls = "TransitStation"
                elif lt == "2":
                    cls = "StationEntrance"
                elif lt == "4":
                    cls = "BoardingArea"
                elif s["parent_station"]:
                    cls = "StopLocation"
                elif types == {3}:
                    cls = "BusStop"
                else:
                    cls = "TransitStop"
                stops.append(dict(urn=urn("TransitStop", fid, s["stop_id"]), feed=fid, stop_id=s["stop_id"],
                                  name=s["stop_name"], cls=cls, location_type=int(lt) if lt.isdigit() else 0,
                                  parent=urn("TransitStop", fid, s["parent_station"]) if s["parent_station"] else None,
                                  departures=int(n_dep), routes=[urn("TransitRoute", fid, r) for r in r_ids],
                                  wheelchair=s["wheelchair_boarding"] or None, geom=s["geom"],
                                  in_core=bool(core.intersects(s["geom"]))))
            for _, t in sot_in.iterrows():
                stop_times.append((geofence_id, urn("TransitStop", fid, t["stop_id"]),
                                   urn("TransitRoute", fid, t["route_id"]), fid, t["trip_id"], t["arrival_time"],
                                   t["departure_time"], int(t["stop_sequence"] or 0), day, build_ph))
            for sid in sorted(services):
                cal_rows.append((geofence_id, urn("ServiceCalendar", fid, sid), fid, sid, day, build_ph))
        print(f"{f['id']} {f.get('provider')}: {entry}", flush=True)

    print(f"{len(stops)} stops inside the extent; computing walksheds", flush=True)
    with connect() as conn:
        build_id = conn.execute(
            "INSERT INTO gkg.build (geofence_id, stage, builder_version, source_versions) "
            "VALUES (%s, 'stage3-transit', %s, %s) RETURNING build_id",
            (geofence_id, config.BUILDER_VERSION,
             json.dumps({"gtfs": "Mobility Database archive", "reference_date": ref_day,
                         "feeds": feed_log}))).fetchone()[0]
        xy = np.c_[_to_m(np.array([s["geom"].x for s in stops]), np.array([s["geom"].y for s in stops]))] \
            if stops else np.zeros((0, 2))
        sheds = walksheds(conn, geofence_id, xy) if stops else []
        to_store = Transformer.from_crs(config.METRIC_CRS, config.STORE_CRS, always_xy=True).transform
        for table in ["transit_agency", "transit_route", "transit_stop", "transit_stop_time", "service_calendar",
                      "walkshed_area", "stop_road"]:
            conn.execute(f"DELETE FROM gkg.{table} WHERE geofence_id = %s", (geofence_id,))

        def fix(rows):
            return [tuple(build_id if v is build_ph else v for v in r) for r in rows]

        seen = set()
        agencies_u = [r for r in fix(agencies) if not (r[1] in seen or seen.add(r[1]))]
        copy_rows(conn, "gkg.transit_agency", ["geofence_id", "urn", "feed_id", "agency_id", "name", "url",
                                               "build_id"], agencies_u)
        copy_rows(conn, "gkg.transit_route", ["geofence_id", "urn", "feed_id", "route_id", "short_name",
                                              "long_name", "route_type", "uko_class", "agency_urn",
                                              "trips_on_service_day", "service_day", "build_id"], fix(routes))
        copy_rows(conn, "gkg.transit_stop",
                  ["geofence_id", "urn", "feed_id", "stop_id", "name", "uko_class", "location_type",
                   "parent_urn", "departures_on_service_day", "route_urns", "wheelchair_boarding", "in_core",
                   "geom", "build_id"],
                  [(geofence_id, s["urn"], s["feed"], s["stop_id"], s["name"], s["cls"], s["location_type"],
                    s["parent"], s["departures"], s["routes"], s["wheelchair"], s["in_core"],
                    shapely.to_wkb(shapely.set_srid(s["geom"], 4326), hex=True, include_srid=True), build_id)
                   for s in stops])
        copy_rows(conn, "gkg.transit_stop_time", ["geofence_id", "stop_urn", "route_urn", "feed_id", "trip_id",
                                                  "arrival_time", "departure_time", "stop_sequence",
                                                  "service_day", "build_id"], fix(stop_times))
        copy_rows(conn, "gkg.service_calendar", ["geofence_id", "urn", "feed_id", "service_id", "service_day",
                                                 "build_id"], fix(cal_rows))
        shed_rows, no_shed = [], 0
        for s, w in zip(stops, sheds):
            if w is None:
                no_shed += 1
                continue
            hull = w["hull"]
            if hull.geom_type != "Polygon":
                hull = shapely.convex_hull(hull)
            hull = transform(to_store, hull)
            if hull.geom_type != "Polygon":
                no_shed += 1
                continue
            shed_rows.append((geofence_id, "urn:urban-kg:WalkShedArea:" + s["urn"].split(":")[-1], s["urn"],
                              config.WALKSHED_THRESHOLD_M, "exponential", config.WALKSHED_BETA, w["snap_m"],
                              w["nodes"], w["decay_weighted_nodes"], w["area_m2"],
                              shapely.to_wkb(shapely.set_srid(hull, 4326), hex=True, include_srid=True), build_id))
        copy_rows(conn, "gkg.walkshed_area", ["geofence_id", "urn", "origin_urn", "distance_threshold_m",
                                              "decay_method", "beta", "snap_m", "nodes_reached",
                                              "decay_weighted_nodes", "area_m2", "geom", "build_id"], shed_rows)
        # uko:connectsToTransit: each stop to the nearest walkable road segment within 50 m.
        conn.execute("""
            INSERT INTO gkg.stop_road (geofence_id, segment_urn, stop_urn, distance_m, build_id)
            SELECT s.geofence_id, r.urn, s.urn, r.d, %s FROM gkg.transit_stop s
            CROSS JOIN LATERAL (
                SELECT urn, ST_Distance(s.geom::geography, geom::geography) AS d FROM gkg.road_segment
                WHERE geofence_id = s.geofence_id AND coalesce(road_classification, '') <> 'motorway'
                ORDER BY geom <-> s.geom LIMIT 1) r
            WHERE s.geofence_id = %s AND r.d <= 50""", (build_id, geofence_id))
        n_road = conn.execute("SELECT count(*) FROM gkg.stop_road WHERE geofence_id = %s",
                              (geofence_id,)).fetchone()[0]
        boardable = [s for s in stops if s["location_type"] in (0, 1) and not s["parent"]]
        stats = {"reference_date": ref_day, "feeds_loaded": sum(1 for f in feed_log if f.get("status") == "loaded"),
                 "feeds_nearest": [f["feed"] for f in feed_log if f.get("status") == "loaded" and
                                   f.get("match") == "nearest"],
                 "agencies": len(agencies_u), "routes": len(routes), "stops": len(stops),
                 "stops_in_core": sum(s["in_core"] for s in stops),
                 "boardable_stops_without_service": sum(1 for s in boardable if s["departures"] == 0),
                 "stop_times": len(stop_times), "walksheds": len(shed_rows), "stops_without_walkshed": no_shed,
                 "stops_on_road": n_road,
                 "by_class": pd.Series([s["cls"] for s in stops]).value_counts().to_dict() if stops else {}}
        conn.execute("UPDATE gkg.build SET stats = %s, finished = now(), status = 'loaded' WHERE build_id = %s",
                     (json.dumps(stats), build_id))
        conn.commit()
    return build_id, stats, feed_log


build_ph = object()  # placeholder replaced by the build id once the build row exists
