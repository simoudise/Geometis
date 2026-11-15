"""Evangelos's 15 Test 1 templates (author "evangelos"), from the Sheet "Test 1 question templates (Evangelos)".

Each template keeps the wording of the Sheet's column C with its blanks filled; column G gives the method the
reference function follows. Every question also carries the plan's standard statements of network, snapping,
metric and projection (docs/test-plan-2026-11.md, "Reference answers"), as Claude's templates do.

Corrections Evangelos made on November 14, 2026 (change log), applied here without changing the Sheet:
- Row 3 is Constrained, not Network (the stored walkshed needs no route).
- Rows 11 and 12 count as definition NOT stated; rows 13, 14 and 15 count as definition stated.
Implementation decisions (change log):
- Row 2 names its area ("in {area}") because a list of tract IDs needs one geofence.
- Row 5 counts a crash as "after dark" when its lighting code is C, D or E (dark with street lights, dark
  without street lights, dark with street lights not working); code B (dusk or dawn) and '-' (not stated) are not
  after dark.
- Row 6 names the agency as a blank, because Diablo Valley College is served by County Connection, not Tri Delta
  Transit. Cal State East Bay Concord has no stop within 400 m and is not used.
- Row 9 states the place classes of each category in parentheses, because "retail shops" has no single class.
- Row 14 merges malls within 100 m of each other and accepts any name of the merged mall.
- Row 14 also drops a filling when the winning mall shares a name with another mall entry in the city (some malls
  appear twice, kilometers apart, so the 100 m merge cannot join them).
- Row 15 adds manufacturers in cities with fewer than six usable warehouses (Antioch, Pittsburg, Pleasant Hill).
- Rows 2 and 4 drop any filling whose answer list is empty.
Reference functions use reference.py (SciPy Dijkstra) and PostGIS, never loop.py's network tool.
"""
import numpy as np
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree
import reference as R
from templates_claude import q, pick, CITIES, CITY_LABEL, CC, SF, WALKDEF, ROADDEF, SNAP, STREET_SQL, city_label

LAMBERT = "Measure straight-line distances in California Albers (EPSG:3310)."
ALL_CITIES = CITIES[CC] + CITIES[SF]
GF_OF = {c: (CC if c in CITIES[CC] else SF) for c in ALL_CITIES}
AREA = {CC: "the five Contra Costa cities (Antioch, Concord, Pittsburg, Pleasant Hill and Walnut Creek)", SF: "San Francisco"}
DARK = ("C", "D", "E")

# ------------------------------------------------------------------ helpers

def pts(conn, sql, args):
    return q(conn, sql, args)

def xy_sql(alias="p"):
    return f"ST_X(ST_Transform({alias}.geom,3310)), ST_Y(ST_Transform({alias}.geom,3310))"

def unique_named(conn, gf, where, args=None, city=None):
    """Places matching a filter whose name occurs once in the geofence, inside the union core or, when a city is
    given, inside that city: [(name, x, y, urn)]."""
    a = {"g": gf, **(args or {})}
    inside = "in_core"
    if city:
        a["city"] = city
        inside = "ST_Within(geom, (select core from gkg.geofence where name=%(city)s))"
    return q(conn, f"""select name, x, y, urn from (
        select p.name, ST_X(ST_Transform(p.geom,3310)) x, ST_Y(ST_Transform(p.geom,3310)) y, p.urn, p.geom, p.in_core,
               count(*) over (partition by p.name) n, ({where}) ok
        from gkg.place p where p.geofence_id=%(g)s and p.name is not null and length(p.name) > 3) t
        where n = 1 and ok and {inside}""", a)

def multi_dist(N, nodes, limit=np.inf, mask=None):
    """Shortest distance from the nearest of several source nodes to every node."""
    nodes = np.unique(np.asarray(nodes, int))
    if len(nodes) == 0: return np.full(N.n, np.inf)
    g = N.matrix(np.ones(len(N.w), bool) if mask is None else mask)
    return dijkstra(g, directed=False, indices=nodes, min_only=True, limit=limit)

_pairs = {}
def pair_edges(N):
    """For each node pair, its edge indices sorted by length (built once per network)."""
    if id(N) not in _pairs:
        d = {}
        for k in np.argsort(N.w, kind="stable"):
            d.setdefault((min(N.a[k], N.b[k]), max(N.a[k], N.b[k])), []).append(int(k))
        _pairs[id(N)] = d
    return _pairs[id(N)]

def path_edge_idx(N, src, dst, mask):
    """Edge indices of one shortest path on the masked network, and its length."""
    g = N.matrix(mask)
    d, pred = dijkstra(g, directed=False, indices=src, return_predecessors=True)
    if not np.isfinite(d[dst]): return None, np.inf
    pairs = pair_edges(N)
    out, v = [], dst
    while v != src:
        u = pred[v]
        out.append(next(k for k in pairs[(min(u, v), max(u, v))] if mask[k])); v = u
    return out[::-1], float(d[dst])

def node_index(N, urns):
    return np.array([N.idx[u] for u in urns if u in N.idx], int)

# ------------------------------------------------------------------ row 1 (network, San Francisco)

E1_CATS = {"grocery stores": ["GroceryStore"], "elementary schools": ["ElementarySchool"], "restaurants": ["Restaurant"]}
def e1_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    homes = q(conn, """select b.urn, ST_X(ST_Transform(ST_Centroid(b.geom),3310)), ST_Y(ST_Transform(ST_Centroid(b.geom),3310))
              from gkg.building b where b.geofence_id=%(g)s and b.class in ('house','detached') and b.in_core""", {"g": gf})
    cats = {c: np.array(q(conn, f"select {xy_sql()} from gkg.place p where p.geofence_id=%(g)s and p.uko_class = any(%(k)s)",
                         {"g": gf, "k": v}), float) for c, v in E1_CATS.items()}
    for j in rng.permutation(len(homes)):
        if len(out) >= k: break
        urn, x, y = homes[j]
        cat = list(E1_CATS)[len(out) % len(E1_CATS)]
        P = cats[cat]
        near = P[np.hypot(P[:, 0] - x, P[:, 1] - y) <= 1000]
        if len(near) == 0: continue
        d = W.dist(W.snap(x, y)[0])
        dd = np.array([d[W.snap(px, py)[0]] for px, py in near])
        if not np.all(np.isfinite(dd)): continue
        out.append({"slots": {"building": urn, "category": cat}, "answer": round(float(np.median(dd)))})
    return out

# ------------------------------------------------------------------ row 2 (network, either)

E2_TYPES = {"grocery store": ["GroceryStore"], "clinic": ["Clinic"], "pharmacy": ["Pharmacy"], "elementary school": ["ElementarySchool"]}
def e2_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    tracts = q(conn, """select geoid, ST_X(ST_Transform(ST_Centroid(geom),3310)), ST_Y(ST_Transform(ST_Centroid(geom),3310)),
               median_household_income, zero_vehicle_share from gkg.census_tract where geofence_id=%(g)s
               and median_household_income is not null and zero_vehicle_share is not null""", {"g": gf})
    tnode = np.array([W.snap(x, y)[0] for _, x, y, _, _ in tracts])
    dist_by_type = {}
    combos = [(inc, dist, t) for inc in (60000, 75000, 90000) for dist in (800, 1000) for t in E2_TYPES]
    for j in rng.permutation(len(combos)):
        if len(out) >= k: break
        inc, dmin, t = combos[j]
        if t not in dist_by_type:
            P = q(conn, f"select {xy_sql()} from gkg.place p where p.geofence_id=%(g)s and p.uko_class = any(%(k)s)", {"g": gf, "k": E2_TYPES[t]})
            dist_by_type[t] = multi_dist(W, [W.snap(x, y)[0] for x, y in P])
        d = dist_by_type[t][tnode]
        keep = [(tr[4], tr[0]) for tr, dd in zip(tracts, d) if tr[3] < inc and dd >= dmin]
        if not keep: continue                                   # empty answer list: drop the filling
        keep.sort(key=lambda r: (-r[0], r[1]))
        if len(keep) > 3 and abs(keep[2][0] - keep[3][0]) < 1e-9: continue   # tie at third place
        out.append({"slots": {"area": AREA[gf], "income": f"${inc:,}", "distance": f"{dmin:,} m".replace("1,000 m", "1 km"),
                              "place_type": t}, "answer": [g for _, g in keep[:3]]})
    return out

# ------------------------------------------------------------------ row 3 (constrained, San Francisco; definition not stated)

def sf_stations(conn):
    """BART and Caltrain stations inside San Francisco that have a stored 800 m walkshed."""
    return q(conn, """select s.name, w.urn from gkg.walkshed_area w join gkg.transit_stop s on s.urn=w.origin_urn and s.geofence_id=w.geofence_id
             join gkg.transit_agency a on a.geofence_id=s.geofence_id and a.feed_id=s.feed_id
             where s.geofence_id=%(g)s and s.location_type=1 and a.name in ('Bay Area Rapid Transit','Caltrain')
             and ST_Within(s.geom, (select core from gkg.geofence where name='San Francisco city'))""", {"g": SF})

def e3_sample(conn, gf, rng, k):
    out = []
    for name, wurn in pick(rng, sf_stations(conn), k):
        tot, fast = q(conn, f"""with w as (select ST_Transform(geom,3310) g from gkg.walkshed_area where geofence_id=%(g)s and urn=%(w)s)
            select sum(ST_Length(ST_Intersection(ST_Transform(s.geom,3310), w.g))),
                   sum(ST_Length(ST_Intersection(ST_Transform(s.geom,3310), w.g))) filter (where s.speed_limit_source='posted' and s.speed_limit_mph >= 30)
            from gkg.road_segment s, w where s.geofence_id=%(g)s and {STREET_SQL} and ST_Intersects(ST_Transform(s.geom,3310), w.g)""",
            {"g": gf, "w": wurn})[0]
        if tot: out.append({"slots": {"station": name}, "answer": round(100 * (fast or 0) / tot, 1)})
    return out

# ------------------------------------------------------------------ row 4 (network, either)

E4_TYPES = {"police stations": "PoliceStation", "courthouses": "Courthouse"}
def e4_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    law = q(conn, f"select {xy_sql()} from gkg.place p where p.geofence_id=%(g)s and p.basic_category='attorney_or_law_firm'", {"g": gf})
    law_nodes = np.array([W.snap(x, y)[0] for x, y in law])
    combos = [(t, c, n) for t in E4_TYPES for c in CITIES[gf] for n in (1, 3, 5)]
    for j in rng.permutation(len(combos)):
        if len(out) >= k: break
        t, city, n = combos[j]
        civ = q(conn, f"""select p.name, {xy_sql()},
                  exists(select 1 from gkg.building b where b.geofence_id=p.geofence_id and b.class='parking'
                         and ST_DWithin(ST_Transform(b.geom,3310), ST_Transform(p.geom,3310), 100))
                  or exists(select 1 from gkg.place g where g.geofence_id=p.geofence_id and g.basic_category='parking_garage'
                         and ST_DWithin(ST_Transform(g.geom,3310), ST_Transform(p.geom,3310), 100))
              from gkg.place p where p.geofence_id=%(g)s and p.uko_class=%(t)s and p.name is not null
              and ST_Within(p.geom, (select core from gkg.geofence where name=%(c)s))""", {"g": gf, "t": E4_TYPES[t], "c": city})
        if not civ: continue
        names = []
        for name, x, y, parking in civ:
            if not parking: continue
            d = W.dist(W.snap(x, y)[0])
            if (d[law_nodes] <= 400).sum() >= n: names.append(name)
        if not names: continue                                  # empty answer list: drop the filling
        out.append({"slots": {"civic": t, "city": city_label(city), "n": n}, "answer": sorted(set(names))})
    return out

# ------------------------------------------------------------------ row 5 (network, either)

def e5_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    P = q(conn, f"""select p.name, {xy_sql()}, p.uko_class, p.basic_category, p.in_core from gkg.place p where p.geofence_id=%(g)s""", {"g": gf})
    xy = np.array([[r[1], r[2]] for r in P]); tree = cKDTree(xy)
    nightlife = np.array([r[3] in ("Bar", "Restaurant", "EntertainmentVenue") for r in P])
    name_n = {}
    for r in P: name_n[r[0]] = name_n.get(r[0], 0) + 1
    venues = []
    for i, r in enumerate(P):
        if not (r[5] and r[0] and len(r[0]) > 3 and name_n[r[0]] == 1 and (r[3] == "Bar" or r[4] == "music_venue")): continue
        nb = [j for j in tree.query_ball_point(xy[i], 200) if j != i and nightlife[j]]
        if len(nb) >= 10: venues.append((r[0], r[1], r[2]))
    nodes = q(conn, """with dark as (select a.node_urn, count(distinct c.case_id) n from gkg.tims_crash c
                  join gkg.crash_attachment a on a.case_id=c.case_id and a.geofence_id=%(g)s
                  where c.accident_year between 2021 and 2025 and c.lighting = any(%(d)s) and a.node_urn is not null group by 1),
              res as (select from_node u from gkg.road_segment where geofence_id=%(g)s and road_classification='residential'
                      union select to_node from gkg.road_segment where geofence_id=%(g)s and road_classification='residential')
              select n.urn, coalesce(dark.n,0) from gkg.intersection_node n join res on res.u=n.urn left join dark on dark.node_urn=n.urn
              where n.geofence_id=%(g)s and n.node_kind='intersection'""", {"g": gf, "d": list(DARK)})
    nix = node_index(W, [u for u, _ in nodes]); ncount = np.array([c for u, c in nodes if u in W.idx])
    for name, x, y in pick(rng, venues, k):
        kk = int(rng.integers(1, 4))
        d = W.dist(W.snap(x, y)[0])[nix]
        out.append({"slots": {"venue": name, "k": kk}, "answer": int(((d <= 400) & (ncount >= kk)).sum())})
    return out

# ------------------------------------------------------------------ row 6 (what-if, Contra Costa)

E6_COLLEGES = ["Los Medanos College", "Diablo Valley College"]
def e6_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    tracts = q(conn, """select ST_X(ST_Transform(ST_Centroid(geom),3310)), ST_Y(ST_Transform(ST_Centroid(geom),3310)), coalesce(population,0)
               from gkg.census_tract where geofence_id=%(g)s""", {"g": gf})
    tnode = np.array([W.snap(x, y)[0] for x, y, _ in tracts]); tpop = np.array([p for _, _, p in tracts])
    combos = []
    for col in E6_COLLEGES:
        rows = q(conn, """with c as (select geom from gkg.place where geofence_id=%(g)s and name=%(c)s and basic_category='college_university')
                 select distinct a.name, r.short_name, r.urn from gkg.transit_stop s join c on ST_DWithin(ST_Transform(s.geom,3310), ST_Transform(c.geom,3310), 400)
                 join gkg.transit_route r on r.geofence_id=s.geofence_id and r.urn = any(s.route_urns)
                 join gkg.transit_agency a on a.urn=r.agency_urn where s.geofence_id=%(g)s""", {"g": gf, "c": col})
        routes = {u: (ag, sn) for ag, sn, u in rows}
        for u in routes: combos.append((col, u, routes))
    stops_of = {}
    def covered(route_urns):
        sts = q(conn, """select distinct ST_X(ST_Transform(s.geom,3310)), ST_Y(ST_Transform(s.geom,3310)) from gkg.transit_stop s
                where s.geofence_id=%(g)s and s.route_urns && %(r)s""", {"g": gf, "r": list(route_urns)})
        d = multi_dist(W, [W.snap(x, y)[0] for x, y in sts], limit=800)
        return d[tnode] <= 800
    for j in rng.permutation(len(combos)):
        if len(out) >= k: break
        col, closed, routes = combos[j]
        before = covered(list(routes)); after = covered([u for u in routes if u != closed])
        ag, sn = routes[closed]
        out.append({"slots": {"agency": ag, "route": sn, "college": col}, "answer": int(round(tpop[before & ~after].sum()))})
    return out

# ------------------------------------------------------------------ row 7 (what-if, Contra Costa)

def e7_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    structs = q(conn, """select b.urn, ST_X(ST_Transform(ST_Centroid(b.geom),3310)), ST_Y(ST_Transform(ST_Centroid(b.geom),3310)),
                 (select g.name from gkg.geofence g where g.name = any(%(c)s) and ST_Within(ST_Centroid(b.geom), g.core))
               from gkg.building b where b.geofence_id=%(g)s and b.class='parking'
               union all select p.name, ST_X(ST_Transform(p.geom,3310)), ST_Y(ST_Transform(p.geom,3310)),
                 (select g.name from gkg.geofence g where g.name = any(%(c)s) and ST_Within(p.geom, g.core))
               from gkg.place p where p.geofence_id=%(g)s and p.basic_category='parking_garage'""", {"g": gf, "c": CITIES[gf]})
    structs = [s for s in structs if s[3]]
    snodes = np.array([W.snap(x, y)[0] for _, x, y, _ in structs])
    rest = {c: np.array([W.snap(x, y)[0] for x, y in q(conn, f"""select {xy_sql()} from gkg.place p where p.geofence_id=%(g)s
             and p.uko_class='Restaurant' and ST_Within(p.geom, (select core from gkg.geofence where name=%(c)s))""", {"g": gf, "c": c})], int)
            for c in CITIES[gf]}
    for j in pick(rng, list(range(len(structs))), k):
        ident, _, _, city = structs[j]
        before = multi_dist(W, snodes, limit=300)
        others = np.delete(snodes, j)
        after = multi_dist(W, others, limit=300) if len(others) else np.full(W.n, np.inf)
        r = rest[city]
        out.append({"slots": {"structure": ident, "city": city_label(city)},
                    "answer": int(((before[r] <= 300) & ~(after[r] <= 300)).sum())})
    return out

# ------------------------------------------------------------------ row 8 (what-if, Contra Costa)

import re
E8_NOT_ELEMENTARY = re.compile(r"(?i)\b(high|middle|intermediate|preschool|pre-school|district|unified)\b")   # mislabeled schools
E8_MEASURE = "straight"   # set by the all-schools check (gen_check_e8): 'straight' or 'drive'
def e8_answer(conn, gf, Rn, school_xy, dist, measure):
    if measure == "straight":
        urns = [r[0] for r in q(conn, """select urn from gkg.road_segment where geofence_id=%(g)s and road_classification='residential'
                 and ST_DWithin(ST_Transform(geom,3310), ST_SetSRID(ST_MakePoint(%(x)s,%(y)s),3310), %(d)s)""",
                {"g": gf, "x": school_xy[0], "y": school_xy[1], "d": dist})]
        cut = np.array([u in set(urns) for u in Rn.edge_urn])
    else:
        d = Rn.dist(Rn.snap(*school_xy)[0])
        near = np.minimum(d[Rn.a], d[Rn.b]) <= dist
        cut = near & (np.array(Rn.edge_cls) == "residential")
    if not cut.any(): return 0
    _, lab = connected_components(Rn.matrix(~cut), directed=False)
    deg = np.bincount(np.r_[Rn.a[~cut], Rn.b[~cut]], minlength=Rn.n)
    main_after = np.bincount(lab[deg > 0]).argmax()
    reach = (lab == main_after) & (deg > 0)
    return int((~reach[Rn.main]).sum())

def e8_sample(conn, gf, rng, k):
    Rn = R.net(conn, gf, "road"); out = []
    schools = [s for s in unique_named(conn, gf, "p.uko_class='ElementarySchool'") if not E8_NOT_ELEMENTARY.search(s[0])]
    for name, x, y, _ in pick(rng, schools, k):
        dist = int(rng.choice([100, 150, 250]))
        out.append({"slots": {"school": name, "distance": f"{dist} m"}, "answer": e8_answer(conn, gf, Rn, (x, y), dist, E8_MEASURE)})
    return out

def e8_check(conn):
    """All Contra Costa elementary schools at all three distances, both measures: share of zero answers."""
    Rn = R.net(conn, CC, "road"); res = {}
    for m in ("straight", "drive"):
        z = n = 0
        for nm, x, y, _ in unique_named(conn, CC, "p.uko_class='ElementarySchool'"):
            if E8_NOT_ELEMENTARY.search(nm): continue
            for dist in (100, 150, 250):
                a = e8_answer(conn, CC, Rn, (x, y), dist, m); n += 1; z += (a == 0)
        res[m] = (z, n)
    return res

# ------------------------------------------------------------------ row 9 (what-if, San Francisco)

E9_STREETS = ["Market Street", "Van Ness Avenue", "Mission Street", "Geary Boulevard", "Valencia Street", "3rd Street"]
E9_CATS = {"restaurants": ["Restaurant"], "retail shops": ["RetailEstablishment", "SpecialtyStore", "ClothingStore"], "cafes": ["Cafe", "CoffeeShop"]}
E9_CAT_TEXT = {"restaurants": "restaurants (place class Restaurant)", "retail shops": "retail shops (place class RetailEstablishment, SpecialtyStore or ClothingStore)",
               "cafes": "cafes (place class Cafe or CoffeeShop)"}
E9_ORIGIN_CLASSES = ["Hospital", "Museum", "TrainStation", "Stadium", "University", "CollegeUniversity", "Park", "Library"]

def street_urns(conn, street):
    return [r[0] for r in q(conn, """select urn from gkg.road_segment where geofence_id=%(g)s and name=%(n)s
             and ST_Intersects(geom, (select core from gkg.geofence where name='San Francisco city'))""", {"g": SF, "n": street})]

def e9_sample(conn, gf, rng, k):
    Rn = R.net(conn, gf, "road"); out = []
    origins = unique_named(conn, gf, "p.uko_class = any(%(oc)s)", {"oc": E9_ORIGIN_CLASSES})
    combos = [(s, c) for s in E9_STREETS for c in E9_CATS]
    for j in rng.permutation(len(combos)):
        if len(out) >= k: break
        street, cat = combos[j]
        urns = street_urns(conn, street)
        if not urns: continue
        far = q(conn, """select o.urn from gkg.place o where o.geofence_id=%(g)s and o.urn = any(%(u)s)
                and not exists(select 1 from gkg.road_segment s where s.geofence_id=%(g)s and s.urn = any(%(s)s)
                               and ST_DWithin(ST_Transform(s.geom,3310), ST_Transform(o.geom,3310), 3000))""",
                {"g": gf, "u": [o[3] for o in origins], "s": urns})
        far = set(r[0] for r in far)
        cand = [o for o in origins if o[3] in far]
        if not cand: continue
        oname, ox, oy, _ = cand[int(rng.integers(len(cand)))]
        places = q(conn, f"""select distinct {xy_sql()} from gkg.place p where p.geofence_id=%(g)s and p.uko_class = any(%(k)s)
                  and exists(select 1 from gkg.road_segment s where s.geofence_id=%(g)s and s.urn = any(%(s)s)
                             and ST_DWithin(ST_Transform(s.geom,3310), ST_Transform(p.geom,3310), 100))""",
                   {"g": gf, "k": E9_CATS[cat], "s": urns})
        if not places: continue
        src = Rn.snap(ox, oy)[0]
        before = Rn.dist(src); after = Rn.dist(src, remove_urns=urns)
        pn = np.array([Rn.snap(x, y)[0] for x, y in places])
        grow = (after[pn] - before[pn] > 200)
        out.append({"slots": {"street": street, "category": E9_CAT_TEXT[cat], "origin": oname}, "answer": int(grow.sum())})
    return out

# ------------------------------------------------------------------ row 10 (what-if, San Francisco)

def e10_sample(conn, gf, rng, k):
    import shapely, shapely.wkt
    Rn = R.net(conn, gf, "road"); out = []
    allm = np.ones(len(Rn.w), bool)
    cand = q(conn, """select name, x, y from (select p.name, ST_X(ST_Transform(p.geom,3310)) x, ST_Y(ST_Transform(p.geom,3310)) y, p.in_core,
                 p.uko_class, count(*) over (partition by p.name) n from gkg.place p where p.geofence_id=%(g)s and p.name is not null
                 and length(p.name) > 3) t where n = 1 and in_core
                 and uko_class in ('Restaurant','School','ElementarySchool','Park','Hotel','GroceryStore','Bank','Library','Museum')""", {"g": gf})
    cxy = np.array([[x, y] for _, x, y in cand]); cpts = shapely.points(cxy[:, 0], cxy[:, 1])
    for street in [E9_STREETS[i] for i in rng.permutation(len(E9_STREETS))]:
        if len(out) >= k: break
        urns = street_urns(conn, street)
        if not urns: continue
        us = set(urns); closed = np.array([u in us for u in Rn.edge_urn])
        sline = shapely.wkt.loads(q(conn, """select ST_AsText(ST_Union(ST_Transform(geom,3310))) from gkg.road_segment
                 where geofence_id=%(g)s and urn = any(%(s)s)""", {"g": gf, "s": urns})[0][0])
        dd = shapely.distance(sline, cpts)
        ps = [cand[i] for i in np.where((dd >= 100) & (dd <= 800))[0]]
        for _ in range(60):
            if len(ps) < 2: break
            a, b = pick(rng, ps, 2)
            if not shapely.LineString([(a[1], a[2]), (b[1], b[2])]).intersects(sline): continue
            sa, sb = Rn.snap(a[1], a[2])[0], Rn.snap(b[1], b[2])[0]
            old, _ = path_edge_idx(Rn, sa, sb, allm)
            if not old or not any(closed[e] for e in old): continue
            new, dn = path_edge_idx(Rn, sa, sb, allm & ~closed)
            if new is None: continue
            only = set(Rn.edge_urn[e] for e in new) - set(Rn.edge_urn[e] for e in old)
            if not only: continue
            nodes = set()
            for e in new:
                if Rn.edge_urn[e] in only: nodes |= {Rn.urn[Rn.a[e]], Rn.urn[Rn.b[e]]}
            n = q(conn, """select count(distinct c.case_id) from gkg.tims_crash c join gkg.crash_attachment a on a.case_id=c.case_id and a.geofence_id=%(g)s
                  where c.accident_year between 2021 and 2025 and (a.segment_urn = any(%(s)s) or a.node_urn = any(%(n)s))""",
                  {"g": gf, "s": list(only), "n": list(nodes)})[0][0]
            out.append({"slots": {"street": street, "origin": a[0], "destination": b[0]}, "answer": int(n)})
            break
    return out

# ------------------------------------------------------------------ row 11 (constrained, either; definition not stated)

def e11_sample(conn, gf, rng, k):
    out = []
    for city in pick(rng, CITIES[gf], k):
        n = q(conn, """select count(distinct c.case_id) from gkg.tims_crash c join gkg.crash_attachment a on a.case_id=c.case_id and a.geofence_id=%(g)s
              join gkg.road_segment s on s.urn=a.segment_urn and s.geofence_id=%(g)s
              where c.accident_year between 2021 and 2025 and c.pedestrian and s.road_classification in ('trunk','primary','secondary')
              and coalesce(s.subclass,'') <> 'link' and ST_Within(c.geom, (select core from gkg.geofence where name=%(c)s))""", {"g": gf, "c": city})[0][0]
        out.append({"slots": {"city": city_label(city)}, "answer": int(n)})
    return out

# ------------------------------------------------------------------ row 12 (constrained, either; definition not stated)

def e12_sample(conn, gf, rng, k):
    out = []
    for city in pick(rng, CITIES[gf], k):
        rows = q(conn, """with c as (select ST_Transform(core,3310) g from gkg.geofence where name=%(c)s)
                 select t.geoid, t.zero_vehicle_share from gkg.census_tract t, c where t.geofence_id=%(g)s and t.zero_vehicle_share is not null
                 and ST_Area(ST_Intersection(ST_Transform(t.geom,3310), c.g)) > 0.5 * ST_Area(ST_Transform(t.geom,3310))
                 order by 2 desc, 1""", {"g": gf, "c": city})
        if not rows or (len(rows) > 1 and abs(rows[0][1] - rows[1][1]) < 1e-9): continue
        out.append({"slots": {"city": city_label(city)}, "answer": rows[0][0]})
    return out

# ------------------------------------------------------------------ row 13 (constrained, San Francisco; definition stated)

def e13_sample(conn, gf, rng, k):
    out = []
    for name, wurn in pick(rng, sf_stations(conn), k):
        tot, ok = q(conn, f"""with w as (select ST_Transform(geom,3310) g from gkg.walkshed_area where geofence_id=%(g)s and urn=%(w)s),
                 s as (select s.*, ST_Length(ST_Intersection(ST_Transform(s.geom,3310), w.g)) len from gkg.road_segment s, w
                       where s.geofence_id=%(g)s and {STREET_SQL} and ST_Intersects(ST_Transform(s.geom,3310), w.g))
            select sum(len), sum(len) filter (where speed_limit_source='posted' and speed_limit_mph <= 25
                   and exists(select 1 from gkg.pedestrian_edge e where e.geofence_id=%(g)s and e.subclass='sidewalk'
                              and ST_DWithin(ST_Transform(e.geom,3310), ST_Transform(s.geom,3310), 20))) from s""", {"g": gf, "w": wurn})[0]
        if tot: out.append({"slots": {"station": name}, "answer": round(100 * (ok or 0) / tot, 1)})
    return out

# ------------------------------------------------------------------ row 14 (constrained, either; definition stated)

def malls(conn, gf, city):
    """Shopping malls in a city, merged when within 100 m of each other (single linkage): [(names, x, y)]."""
    rows = q(conn, f"""select p.name, {xy_sql()} from gkg.place p where p.geofence_id=%(g)s and p.uko_class='ShoppingMall'
             and p.name is not null and ST_Within(p.geom, (select core from gkg.geofence where name=%(c)s))""", {"g": gf, "c": city})
    if not rows: return []
    xy = np.array([[x, y] for _, x, y in rows]); parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i, j in cKDTree(xy).query_pairs(100): parent[find(i)] = find(j)
    groups = {}
    for i in range(len(rows)): groups.setdefault(find(i), []).append(i)
    return [(sorted(set(rows[i][0] for i in g)), float(xy[g, 0].mean()), float(xy[g, 1].mean())) for g in groups.values()]

MALL_WORDS = ("shoppingcenter", "shoppingmall", "mall", "centre", "center", "ctr", "galleria")
def mall_key(name):
    import re
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    for w in MALL_WORDS: k = k.replace(w, "")
    return k

def e14_sample(conn, gf, rng, k):
    W = R.net(conn, gf, "walk"); out = []
    danger = np.array(q(conn, """with c as (select a.node_urn, count(distinct a.case_id) n from gkg.crash_attachment a
                  join gkg.tims_crash c on c.case_id=a.case_id where a.geofence_id=%(g)s and a.node_urn is not null
                  and c.accident_year between 2021 and 2025 group by 1 having count(distinct a.case_id) >= 3)
              select ST_X(ST_Transform(n.geom,3310)), ST_Y(ST_Transform(n.geom,3310)) from gkg.intersection_node n
              join c on c.node_urn=n.urn where n.geofence_id=%(g)s""", {"g": gf}), float).reshape(-1, 2)
    dtree = cKDTree(danger) if len(danger) else None
    stops = q(conn, f"""select {xy_sql('s')}, coalesce(s.departures_on_service_day,0) from gkg.transit_stop s
              where s.geofence_id=%(g)s and coalesce(s.location_type,0)=0""", {"g": gf})
    snode = np.array([W.snap(x, y)[0] for x, y, _ in stops]); sdep = np.array([d for _, _, d in stops])
    combos = [(c, kk) for c in CITIES[gf] for kk in (0, 1, 2)]
    for j in rng.permutation(len(combos)):
        if len(out) >= k: break
        city, kk = combos[j]
        ms = malls(conn, gf, city)
        scored = []
        for names, x, y in ms:
            nd = len(dtree.query_ball_point([x, y], 200)) if dtree is not None else 0
            if nd > kk: continue
            d = W.dist(W.snap(x, y)[0])[snode]
            scored.append((int(sdep[d <= 400].sum()), names))
        if not scored: continue
        scored.sort(key=lambda r: -r[0])
        if len(scored) > 1 and scored[0][0] == scored[1][0]: continue      # tie
        # Some malls appear twice far apart (one entry mislocated, e.g. "Sun Valley Mall" 5 km from "Sunvalley
        # Shopping Center"); the 100 m merge cannot join them. Drop the filling when the winner shares a name key
        # with another mall in the city, because the answer would then depend on which entry is right.
        win = {mall_key(n) for n in scored[0][1]}
        others = [n for names, _, _ in ms if set(names) != set(scored[0][1]) for n in names]
        if any(mall_key(n) in win for n in others): continue
        out.append({"slots": {"city": city_label(city), "k": kk}, "answer": scored[0][1]})
    return out

# ------------------------------------------------------------------ row 15 (constrained, Contra Costa; definition stated)

def e15_places(conn, gf):
    """Warehouses and transportation-and-storage businesses; manufacturers added in cities with fewer than six."""
    base = "p.uko_class='Warehouse' or p.basic_category='b2b_transportation_and_storage_service'"
    rows, counts = [], {}
    for city in CITIES[gf]:
        w = unique_named(conn, gf, base, city=city)
        counts[city] = len(w)
        if len(w) < 6:
            w = w + unique_named(conn, gf, "p.basic_category='manufacturer'", city=city)
        rows += w
    return rows, counts

def e15_sample(conn, gf, rng, k):
    Rn = R.net(conn, gf, "road"); out = []
    cls = np.array(Rn.edge_cls)
    grade = dict(q(conn, "select urn, max_abs_grade from gkg.road_segment where geofence_id=%(g)s", {"g": gf}))
    sub = dict(q(conn, "select urn, coalesce(subclass,'') from gkg.road_segment where geofence_id=%(g)s", {"g": gf}))
    g = np.array([grade.get(u) if grade.get(u) is not None else np.inf for u in Rn.edge_urn])
    truck = np.isin(cls, ["trunk", "primary", "secondary", "motorway"]) & (g <= 0.06)
    _, lab = connected_components(Rn.matrix(truck), directed=False)
    deg = np.bincount(np.r_[Rn.a[truck], Rn.b[truck]], minlength=Rn.n)
    main = np.where((lab == np.bincount(lab[deg > 0]).argmax()) & (deg > 0))[0]
    tree = cKDTree(Rn.xy[main])
    ramp = truck & (cls == "motorway") & np.array([sub.get(u) == "link" for u in Rn.edge_urn])
    ramp_nodes = np.intersect1d(np.unique(np.r_[Rn.a[ramp], Rn.b[ramp]]), main)
    d_ramp = multi_dist(Rn, ramp_nodes, mask=truck)
    places, _ = e15_places(conn, gf)
    for name, x, y, _ in pick(rng, places, k):
        _, i = tree.query([x, y]); v = float(d_ramp[main[i]])
        if np.isfinite(v) and v >= 50: out.append({"slots": {"warehouse": name}, "answer": round(v)})   # skip trivial starts on a ramp
    return out

# ------------------------------------------------------------------ template table

# Fillings per geofence where the default (3 and 3) does not fit: one question per city.
PER = {"eC11": {CC: 5, SF: 1}, "eC12": {CC: 5, SF: 1}}

TRUCKDEF = ("Count as a truck route any trunk, primary or secondary road or freeway, ramps included, whose steepest grade is 6 percent or less.")
T = [
 # id, category, stated_definition, kind, text, sampler, geofences, sidewalk_dependent
 ("eN1", "network", None, "meters", "Starting from the single-family home {building} (a building tagged as a house or detached house), what is the median walking distance along the walking network to the {category} within 1 km of it in a straight line? " + WALKDEF + " " + SNAP + " Start from the center of the building's footprint. " + LAMBERT, e1_sample, [SF], False),
 ("eN2", "network", None, "names", "Among census tracts in {area} with a median household income below {income}, which 3 have the highest share of households without a car, counting only tracts whose center is at least {distance} along the walking network from the nearest {place_type}? List their census tract IDs (GEOIDs). " + WALKDEF + " " + SNAP + " A tract's center is the centroid of its polygon. If fewer than 3 tracts qualify, list all that do.", e2_sample, [CC, SF], False),
 ("eC3", "constrained", False, "number", "What share of the street length inside the 800 m walkshed of the {station} station carries a posted speed limit of 30 mph or more? Give the share as a percentage. Use the station's stored 800 m walkshed. Give the percentage to one decimal.", e3_sample, [SF], False),
 ("eN4", "network", None, "names", "Which {civic} in {city} have a parking structure within 100 m (a building tagged as parking, or a parking garage) and at least {n} law offices within a 400 m walk along the walking network? List their names. " + WALKDEF + " " + SNAP + " " + LAMBERT, e4_sample, [CC, SF], False),
 ("eN5", "network", None, "buffer_count", "Treat everything within a 400 m walk (along the walking network) of {venue} as its entertainment district. How many intersections inside that district had at least {k} injury crashes after dark between 2021 and 2025, counting only intersections where at least one street is residential? " + WALKDEF + " " + SNAP, e5_sample, [CC, SF], False),
 ("eW6", "what-if", None, "buffer_count", "If {agency} route {route} stopped running, how many people would no longer live within an 800 m walk (along the walking network) of a bus stop served by a route that also stops within 400 m of {college}? Count a census tract's whole population when the tract's center lies within the walk. " + WALKDEF + " " + SNAP + " A tract's center is the centroid of its polygon. " + LAMBERT, e6_sample, [CC], False),
 ("eW7", "what-if", None, "buffer_count", "If the parking structure {structure} closed, how many restaurants in {city} would no longer have any mapped parking structure or garage within a 300 m walk along the walking network? " + WALKDEF + " " + SNAP + " Measure from the center of a parking building's footprint.", e7_sample, [CC], False),
 ("eW8", "what-if", None, "count", "If every residential street segment within {distance} of {school} were closed to cars but stayed open to walking, how many intersections would no longer be reachable by car from the rest of the road network? " + ROADDEF + " Count intersection nodes that were on the main connected part of the road network before the closure and are not on it after. " + LAMBERT, e8_sample, [CC], False),
 ("eW9", "what-if", None, "buffer_count", "If {street} in San Francisco were closed to private cars along its whole length (still open to transit and walking), how many {category} within 100 m of {street} would see the shortest drive to them from {origin} grow by more than 200 m? " + ROADDEF + " " + SNAP + " " + LAMBERT, e9_sample, [SF], False),
 ("eW10", "what-if", None, "count", "If {street} in San Francisco were closed to private cars, the shortest drive from {origin} to {destination} would use other streets. How many injury crashes between 2021 and 2025 were recorded on the road segments the new route uses that the old route did not? " + ROADDEF + " " + SNAP + " Count each crash once, including crashes matched to the intersections at the ends of those segments.", e10_sample, [SF], False),
 ("eC11", "constrained", False, "count", "How many injury crashes involving a pedestrian happened on arterial roads inside {city} in the last five complete years?", e11_sample, [CC, SF], False),
 ("eC12", "constrained", False, "name", "Which census tract in {city} has the highest share of households without a car, among tracts that lie mostly inside the city? Give its census tract ID (GEOID).", e12_sample, [CC, SF], False),
 ("eC13", "constrained", True, "number", "Count a street segment as walkable if it has a mapped sidewalk within 20 m and a posted speed limit of 25 mph or less. What share of the street length inside the 800 m walkshed of {station} is walkable? Use the station's stored 800 m walkshed. Give the share as a percentage to one decimal. " + LAMBERT, e13_sample, [SF], True),
 ("eC14", "constrained", True, "name", "Count a mall's access as transit-rich by the number of weekday transit departures at stops within a 400 m walk along the walking network. Count an intersection as dangerous if it recorded at least 3 injury crashes between 2021 and 2025. Among the shopping malls in {city} with at most {k} dangerous intersections within 200 m, which has the most weekday transit departures within a 400 m walk? " + WALKDEF + " " + SNAP + " " + LAMBERT, e14_sample, [CC, SF], False),
 ("eC15", "constrained", True, "meters", TRUCKDEF + " Along truck routes only, how many meters is the shortest drive from {warehouse} to the nearest freeway ramp? Start at the truck-route node nearest to the warehouse, ignore one-way rules, and treat a freeway ramp as any motorway segment of subclass link. " + LAMBERT, e15_sample, [CC], False),
]
