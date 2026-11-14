"""Claude's Test 1 templates: 15 non-lookup (5 network, 5 what-if, 5 constrained) and 10 lookup.

Each template has a sampler that draws fillings from the graph and a reference function that computes the
answer with reference.py (SciPy) or PostGIS, never with loop.py's network tool. Evangelos's 15 templates are
implemented separately in templates_evangelos.py from his Sheet.

Answer kinds and tolerances (docs/test-plan-2026-11.md): 'meters' and 'number' within 5 percent;
'buffer_count' within 5 percent or 1, whichever is larger; 'count' exact; 'name' exact (case-insensitive);
'names' F1 >= 0.8; 'yesno' exact.
"""
import numpy as np
import reference as R

CC, SF = "us-ca-contra-costa-5", "us-ca-san-francisco"
CITIES = {CC: ["Antioch", "Concord", "Pittsburg", "Pleasant Hill", "Walnut Creek"], SF: ["San Francisco city"]}
CITY_LABEL = {"San Francisco city": "San Francisco"}

WALKDEF = ("Use the walking network: every road segment except freeways (road class motorway), plus the mapped "
           "pedestrian ways and their links to intersections, all usable in both directions.")
ROADDEF = "Use the road network: every road segment, usable in both directions (ignore one-way rules)."
SNAP = ("Attach each place, stop or station to the nearest node of that network by straight-line distance, "
        "among nodes connected to the main part of the network, and measure route length in meters.")
STREETDEF = ("Count as streets the road classes trunk, primary, secondary, tertiary, residential, unclassified and "
             "living_street, excluding ramps (subclass link).")
FORM = {"meters": "Give the answer in meters.", "number": "Give the answer as a number.",
        "count": "Give the answer as a whole number.", "buffer_count": "Give the answer as a whole number.",
        "name": "Give the answer as one name.", "yesno": "Answer yes or no."}

def q(conn, sql, args=None):
    with conn.cursor() as cur:
        cur.execute(sql, args or {})
        rows = cur.fetchall()
    conn.rollback()
    return rows

def city_label(c): return CITY_LABEL.get(c, c)

def bart_stations(conn, gf):
    return q(conn, """select s.name, ST_X(ST_Transform(s.geom,3310)), ST_Y(ST_Transform(s.geom,3310)), s.urn
        from gkg.transit_stop s join gkg.transit_agency a on a.geofence_id=s.geofence_id and a.feed_id=s.feed_id
        where s.geofence_id=%(g)s and a.name='Bay Area Rapid Transit' and s.location_type=1 and s.name is not null and s.in_core""", {"g": gf})

_places_cache = {}
def unique_places(conn, gf, classes=None, city=None):
    """Places whose name occurs once in the geofence (so the name identifies them)."""
    if gf not in _places_cache:
        _places_cache[gf] = q(conn, """select name, x, y, uko_class, urn from (
            select p.name, ST_X(ST_Transform(p.geom,3310)) x, ST_Y(ST_Transform(p.geom,3310)) y, p.uko_class, p.urn, p.in_core,
                   count(*) over (partition by p.name) n
            from gkg.place p where p.geofence_id=%(g)s and p.name is not null and length(p.name) > 3) t where n = 1 and in_core""", {"g": gf})
    rows = _places_cache[gf]
    if classes:
        rows = [r for r in rows if r[3] in classes]
    if city:
        inside = set(r[0] for r in q(conn, """select p.urn from gkg.place p where p.geofence_id=%(g)s
            and ST_Within(p.geom, (select core from gkg.geofence where name=%(c)s))""", {"g": gf, "c": city}))
        rows = [r for r in rows if r[4] in inside]
    return [r[:4] for r in rows]

def pick(rng, rows, k):
    if not rows: return []
    ix = rng.choice(len(rows), size=min(k, len(rows)), replace=False)
    return [rows[i] for i in ix]

# ------------------------------------------------------------------ network

def n1_sample(conn, gf, rng, k):
    """Walk from a BART station to the nearest grocery store."""
    W = R.net(conn, gf, "walk")
    groc = q(conn, "select ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.place where geofence_id=%(g)s and uko_class='GroceryStore'", {"g": gf})
    gnodes = np.array([W.snap(x, y)[0] for x, y in groc])
    out = []
    for name, x, y, _ in pick(rng, bart_stations(conn, gf), k):
        s, _ = W.snap(x, y); d = W.dist(s)
        out.append({"slots": {"station": name}, "answer": round(float(d[gnodes].min()))})
    return out

def n2_sample(conn, gf, rng, k):
    """Road route between two uniquely named places in one city, at least 1 km apart."""
    Rn = R.net(conn, gf, "road"); out = []
    by_city = {c: unique_places(conn, gf, ["Restaurant", "School", "ElementarySchool", "Park", "Hotel", "GroceryStore", "Bank"], c) for c in CITIES[gf]}
    for _ in range(200):
        if len(out) >= k: break
        city = CITIES[gf][int(rng.integers(len(CITIES[gf])))]; ps = by_city[city]
        if len(ps) < 2: continue
        a, b = pick(rng, ps, 2)
        if np.hypot(a[1] - b[1], a[2] - b[2]) < 1000: continue
        sa, _ = Rn.snap(a[1], a[2]); sb, _ = Rn.snap(b[1], b[2])
        out.append({"slots": {"A": a[0], "B": b[0], "city": city_label(city)}, "answer": round(Rn.dist(sa, sb))})
    return out

N3_CATS = {"Restaurant": "restaurants", "Cafe": "cafes", "GroceryStore": "grocery stores", "Bar": "bars"}
def n3_sample(conn, gf, rng, k):
    """Places of one category within 400 m walk of a BART station."""
    W = R.net(conn, gf, "walk"); out = []
    for name, x, y, _ in pick(rng, bart_stations(conn, gf), k):
        cat = list(N3_CATS)[int(rng.integers(len(N3_CATS)))]
        pts = q(conn, "select ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.place where geofence_id=%(g)s and uko_class=%(c)s", {"g": gf, "c": cat})
        s, _ = W.snap(x, y); d = W.dist(s)
        n = sum(1 for px, py in pts if d[W.snap(px, py)[0]] <= 400)
        out.append({"slots": {"station": name, "category": N3_CATS[cat]}, "answer": n})
    return out

def n4_sample(conn, gf, rng, k):
    """Elementary school nearest by road to a uniquely named place."""
    Rn = R.net(conn, gf, "road")
    schools = unique_places(conn, gf, ["ElementarySchool"])
    snodes = np.array([Rn.snap(x, y)[0] for _, x, y, _ in schools]); out = []
    for name, x, y, _ in pick(rng, unique_places(conn, gf, ["GroceryStore", "Park", "Hotel", "Restaurant"]), k):
        d = Rn.dist(Rn.snap(x, y)[0])[snodes]
        order = np.argsort(d)
        if d[order[1]] - d[order[0]] < 50: continue  # skip near-ties
        out.append({"slots": {"place": name}, "answer": schools[order[0]][0]})
    return out

def n5_sample(conn, gf, rng, k):
    """Ratio of walking distance to straight-line distance between a BART station and a place 0.5-2 km away."""
    W = R.net(conn, gf, "walk"); out = []
    ps = unique_places(conn, gf, ["Restaurant", "School", "ElementarySchool", "Park", "Hotel", "GroceryStore"])
    for name, x, y, _ in pick(rng, bart_stations(conn, gf), k):
        cand = [p for p in ps if 500 <= np.hypot(p[1] - x, p[2] - y) <= 2000]
        if not cand: continue
        p = cand[int(rng.integers(len(cand)))]
        wd = W.dist(W.snap(x, y)[0], W.snap(p[1], p[2])[0])
        out.append({"slots": {"station": name, "place": p[0]}, "answer": round(wd / np.hypot(p[1] - x, p[2] - y), 3)})
    return out

# ------------------------------------------------------------------ what-if

def _place_pairs(conn, gf, rng, Rn, min_m, max_m, tries=200):
    ps = unique_places(conn, gf, ["Restaurant", "School", "ElementarySchool", "Park", "Hotel", "GroceryStore", "Bank"])
    for _ in range(tries):
        a, b = pick(rng, ps, 2)
        if min_m <= np.hypot(a[1] - b[1], a[2] - b[2]) <= max_m:
            yield a, b, Rn.snap(a[1], a[2])[0], Rn.snap(b[1], b[2])[0]

def w1_sample(conn, gf, rng, k):
    """Close one road segment on the shortest route; extra meters."""
    Rn = R.net(conn, gf, "road"); out = []
    for a, b, sa, sb in _place_pairs(conn, gf, rng, Rn, 1500, 6000):
        if len(out) >= k: break
        base = Rn.dist(sa, sb); pe = Rn.path_edges(sa, sb)
        if not pe: continue
        e = pe[int(rng.integers(len(pe)))]
        after = Rn.dist(sa, sb, remove_urns=[Rn.edge_urn[e]])
        if not np.isfinite(after) or after - base < 20: continue
        out.append({"slots": {"A": a[0], "B": b[0], "segment": Rn.edge_urn[e], "segname": Rn.edge_name[e] or "an unnamed road"},
                    "answer": round(after - base)})
    return out

def w2_sample(conn, gf, rng, k):
    """Close every freeway; extra meters on the road route."""
    Rn = R.net(conn, gf, "road"); out = []
    for a, b, sa, sb in _place_pairs(conn, gf, rng, Rn, 4000, 15000):
        if len(out) >= k: break
        base = Rn.dist(sa, sb); after = Rn.dist(sa, sb, avoid_cls=["motorway"])
        if np.isfinite(after) and after - base >= 50:
            out.append({"slots": {"A": a[0], "B": b[0]}, "answer": round(after - base)})
    return out

def w3_sample(conn, gf, rng, k):
    """Close every segment of one named street inside a city; extra meters on the walk from a BART station."""
    W = R.net(conn, gf, "walk"); out = []
    stations = bart_stations(conn, gf)
    ps = unique_places(conn, gf, ["Restaurant", "School", "ElementarySchool", "Park", "Hotel", "GroceryStore", "Cafe"])
    for _ in range(200):
        if len(out) >= k: break
        st = stations[int(rng.integers(len(stations)))]
        cand = [p for p in ps if 600 <= np.hypot(p[1] - st[1], p[2] - st[2]) <= 2500]
        if not cand: continue
        p = cand[int(rng.integers(len(cand)))]
        s, t = W.snap(st[1], st[2])[0], W.snap(p[1], p[2])[0]
        names = [W.edge_name[e] for e in W.path_edges(s, t) if W.edge_name[e]]
        if not names: continue
        street = names[int(rng.integers(len(names)))]
        city = q(conn, """select g.name from gkg.geofence g where g.name = any(%(c)s)
                 and ST_Within((select geom from gkg.transit_stop where urn=%(u)s and geofence_id=%(gf)s), g.core)""",
                 {"c": CITIES[gf], "u": st[3], "gf": gf})
        if not city: continue
        city = city[0][0]
        urns = [r[0] for r in q(conn, """select urn from gkg.road_segment where geofence_id=%(g)s and name=%(n)s
                 and ST_Intersects(geom, (select core from gkg.geofence where name=%(c)s))""", {"g": gf, "n": street, "c": city})]
        base = W.dist(s, t); after = W.dist(s, t, remove_urns=urns)
        if np.isfinite(after) and after - base >= 20:
            out.append({"slots": {"station": st[0], "place": p[0], "street": street, "city": city_label(city)}, "answer": round(after - base)})
    return out

def w4_sample(conn, gf, rng, k):
    """Close one segment between two intersections; can you still drive between them? Half no (a cut segment)."""
    import networkx as nx
    Rn = R.net(conn, gf, "road")
    G = nx.Graph(); G.add_edges_from((int(a), int(b), {"k": i}) for i, (a, b) in enumerate(zip(Rn.a, Rn.b)))
    main = set(int(v) for v in Rn.main)
    H = G.subgraph(main).copy()
    bridges = list(nx.bridges(H))
    cuts = []
    for j in rng.permutation(len(bridges))[:300]:
        u, v = bridges[j]
        data = H[u][v]; H.remove_edge(u, v)
        cu = nx.node_connected_component(H, u)
        small = cu if len(cu) <= len(main) / 2 else nx.node_connected_component(H, v)
        H.add_edge(u, v, **data)
        if 5 <= len(small) <= 2000: cuts.append((u, v, small))
        if len(cuts) >= 20: break
    out = []
    for i in range(k):
        if i % 2 == 0 and cuts:
            u, v, small = cuts[int(rng.integers(len(cuts)))]
            inside = small - {u, v} or small
            x = sorted(inside)[int(rng.integers(len(inside)))]
            y = int(Rn.main[int(rng.integers(len(Rn.main)))])
            while y in small: y = int(Rn.main[int(rng.integers(len(Rn.main)))])
            e = G[u][v]["k"]; ans = "no"
        else:
            x, y = (int(z) for z in rng.choice(Rn.main, 2, replace=False))
            pe = Rn.path_edges(x, y)
            if not pe: continue
            e = pe[int(rng.integers(len(pe)))]
            ans = "yes" if np.isfinite(Rn.dist(x, y, remove_urns=[Rn.edge_urn[e]])) else "no"
        out.append({"slots": {"X": Rn.urn[x], "Y": Rn.urn[y], "segment": Rn.edge_urn[e]}, "answer": ans})
    return out

def w5_sample(conn, gf, rng, k):
    """Close all primary and secondary roads; extra meters on a road route within one city."""
    Rn = R.net(conn, gf, "road"); out = []
    for a, b, sa, sb in _place_pairs(conn, gf, rng, Rn, 1500, 5000):
        if len(out) >= k: break
        base = Rn.dist(sa, sb); after = Rn.dist(sa, sb, avoid_cls=["primary", "secondary"])
        if np.isfinite(after) and after - base >= 50:
            out.append({"slots": {"A": a[0], "B": b[0]}, "answer": round(after - base)})
    return out

# ------------------------------------------------------------------ constrained

STREET_SQL = ("road_classification in ('trunk','primary','secondary','tertiary','residential','unclassified','living_street') "
              "and coalesce(subclass,'') <> 'link'")

def c1_sample(conn, gf, rng, k):
    out = []
    for city in CITIES[gf]:
        L = q(conn, f"""select sum(ST_Length(ST_Transform(ST_Intersection(s.geom, g.core),3310))) from gkg.road_segment s, gkg.geofence g
                 where s.geofence_id=%(gf)s and g.name=%(c)s and ST_Intersects(s.geom, g.core) and {STREET_SQL}""", {"gf": gf, "c": city})[0][0]
        out.append({"slots": {"city": city_label(city)}, "answer": round(L)})
    return pick(rng, out, k)

def c2_sample(conn, gf, rng, k):
    out = []
    for name, x, y, _ in pick(rng, unique_places(conn, gf, ["ElementarySchool"]), k):
        n = q(conn, f"""select count(*) from gkg.road_segment s where s.geofence_id=%(gf)s and {STREET_SQL}
                 and speed_limit_source='posted' and speed_limit_mph > 25
                 and ST_DWithin(ST_Transform(s.geom,3310), ST_SetSRID(ST_MakePoint(%(x)s,%(y)s),3310), 500)""", {"gf": gf, "x": x, "y": y})[0][0]
        out.append({"slots": {"school": name}, "answer": n})
    return out

def c3_sample(conn, gf, rng, k):
    out = []
    for name, x, y, _ in pick(rng, bart_stations(conn, gf), k):
        n = q(conn, """select count(*) from gkg.tims_crash c join gkg.crash_attachment a on a.case_id=c.case_id and a.geofence_id=%(gf)s
                 join gkg.intersection_node n on n.urn=a.node_urn and n.geofence_id=%(gf)s
                 where c.accident_year between 2021 and 2025 and c.severity in (1,2)
                 and ST_DWithin(ST_Transform(n.geom,3310), ST_SetSRID(ST_MakePoint(%(x)s,%(y)s),3310), 300)""", {"gf": gf, "x": x, "y": y})[0][0]
        out.append({"slots": {"station": name}, "answer": n})
    return out

def c4_sample(conn, gf, rng, k):
    out = []
    for city in CITIES[gf]:
        n = q(conn, """select count(*) from gkg.road_segment s, gkg.geofence g where s.geofence_id=%(gf)s and g.name=%(c)s
                 and ST_Intersects(s.geom, g.core) and road_classification in ('trunk','primary','secondary')
                 and coalesce(subclass,'') <> 'link' and coalesce(speed_limit_source,'') <> 'posted'""", {"gf": gf, "c": city})[0][0]
        out.append({"slots": {"city": city_label(city)}, "answer": n})
    return pick(rng, out, k)

def c5_sample(conn, gf, rng, k):
    out = []
    for name, x, y, _ in pick(rng, bart_stations(conn, gf), k):
        tot, res = q(conn, f"""with b as (select ST_Buffer(ST_SetSRID(ST_MakePoint(%(x)s,%(y)s),3310), 400) g)
                 select sum(ST_Length(ST_Intersection(ST_Transform(s.geom,3310), b.g))),
                        sum(ST_Length(ST_Intersection(ST_Transform(s.geom,3310), b.g))) filter (where road_classification='residential')
                 from gkg.road_segment s, b where s.geofence_id=%(gf)s and {STREET_SQL}
                 and ST_Intersects(ST_Transform(s.geom,3310), b.g)""", {"gf": gf, "x": x, "y": y})[0]
        if tot: out.append({"slots": {"station": name}, "answer": round(100 * (res or 0) / tot, 1)})
    return out

# ------------------------------------------------------------------ lookups

LOOKUP_CATS = {"GroceryStore": "grocery stores", "Restaurant": "restaurants", "School": "schools", "Park": "parks",
               "Bank": "banks", "GasStation": "gas stations", "Hotel": "hotels", "Cafe": "cafes"}

def l1_sample(conn, gf, rng, k):
    out = []
    for _ in range(k):
        city = CITIES[gf][int(rng.integers(len(CITIES[gf])))]; cat = list(LOOKUP_CATS)[int(rng.integers(len(LOOKUP_CATS)))]
        n = q(conn, "select count(*) from gkg.place p where p.geofence_id=%(g)s and p.uko_class=%(c)s and ST_Within(p.geom,(select core from gkg.geofence where name=%(city)s))",
              {"g": gf, "c": cat, "city": city})[0][0]
        out.append({"slots": {"category": LOOKUP_CATS[cat], "city": city_label(city)}, "answer": n})
    return out

def l2_sample(conn, gf, rng, k):
    out = []
    for name, *_ in pick(rng, unique_places(conn, gf, ["Park", "School", "Hotel", "GroceryStore"]), k):
        pop = q(conn, "select t.population from gkg.census_tract t, gkg.place p where t.geofence_id=%(g)s and p.geofence_id=%(g)s and p.name=%(n)s and ST_Within(p.geom, t.geom)", {"g": gf, "n": name})
        if pop and pop[0][0] is not None: out.append({"slots": {"place": name}, "answer": int(pop[0][0])})
    return out

def l3_sample(conn, gf, rng, k):
    out = []
    for city in pick(rng, CITIES[gf], k):
        n = q(conn, "select count(*) from gkg.transit_stop s where s.geofence_id=%(g)s and s.uko_class='BusStop' and ST_Within(s.geom,(select core from gkg.geofence where name=%(c)s))", {"g": gf, "c": city})[0][0]
        out.append({"slots": {"city": city_label(city)}, "answer": n})
    return out

def l4_sample(conn, gf, rng, k):
    out = []
    for _ in range(k):
        city = CITIES[gf][int(rng.integers(len(CITIES[gf])))]; yr = int(rng.integers(2016, 2026))
        n = q(conn, "select count(*) from gkg.tims_crash c where c.accident_year=%(y)s and ST_Within(c.geom,(select core from gkg.geofence where name=%(c)s))", {"y": yr, "c": city})[0][0]
        out.append({"slots": {"year": yr, "city": city_label(city)}, "answer": n})
    return out

def l5_sample(conn, gf, rng, k):
    out = []
    for name, *_ in pick(rng, unique_places(conn, gf, ["Park", "School", "Hotel", "GroceryStore"]), k):
        v = q(conn, "select t.median_household_income from gkg.census_tract t, gkg.place p where t.geofence_id=%(g)s and p.geofence_id=%(g)s and p.name=%(n)s and ST_Within(p.geom, t.geom)", {"g": gf, "n": name})
        if v and v[0][0] is not None and v[0][0] < 250000: out.append({"slots": {"place": name}, "answer": int(v[0][0])})
    return out

def l6_sample(conn, gf, rng, k):
    out = []
    for name, x, y, urn in pick(rng, bart_stations(conn, gf), k):
        n = q(conn, "select count(*) from gkg.place where geofence_id=%(g)s and ST_DWithin(ST_Transform(geom,3310), ST_SetSRID(ST_MakePoint(%(x)s,%(y)s),3310), 250)", {"g": gf, "x": x, "y": y})[0][0]
        out.append({"slots": {"station": name}, "answer": n})
    return out

def l7_sample(conn, gf, rng, k):
    out = []
    for name, *_ in pick(rng, [r for r in q(conn, "select name from gkg.road_segment where geofence_id=%(g)s and name is not null and in_core group by name having count(*) >= 5 and (count(*) filter (where is_bridge) > 0 or abs(hashtext(name)) %% 2 = 0)", {"g": gf})], k):
        n = q(conn, "select count(*) from gkg.road_segment where geofence_id=%(g)s and name=%(n)s and is_bridge", {"g": gf, "n": name})[0][0]
        out.append({"slots": {"street": name}, "answer": n})
    return out

def l8_sample(conn, gf, rng, k):
    out = []
    for city in pick(rng, CITIES[gf], k):
        v = q(conn, "select max(elevation_m) from gkg.intersection_node n where n.geofence_id=%(g)s and ST_Within(n.geom,(select core from gkg.geofence where name=%(c)s))", {"g": gf, "c": city})[0][0]
        out.append({"slots": {"city": city_label(city)}, "answer": round(float(v))})
    return out

def l9_sample(conn, gf, rng, k):
    out = []
    for name, *_ in pick(rng, unique_places(conn, gf, ["Park", "School", "Hotel", "GroceryStore"]), k):
        v = q(conn, "select t.zero_vehicle_share from gkg.census_tract t, gkg.place p where t.geofence_id=%(g)s and p.geofence_id=%(g)s and p.name=%(n)s and ST_Within(p.geom, t.geom)", {"g": gf, "n": name})
        if v and v[0][0] is not None: out.append({"slots": {"place": name}, "answer": round(100 * float(v[0][0]), 1)})
    return out

def l10_sample(conn, gf, rng, k):
    out = []
    for name, x, y, urn in pick(rng, bart_stations(conn, gf), k):
        n = q(conn, "select count(*) from gkg.transit_stop s where s.geofence_id=%(g)s and s.uko_class='BusStop' and ST_DWithin(ST_Transform(s.geom,3310), ST_SetSRID(ST_MakePoint(%(x)s,%(y)s),3310), 400)", {"g": gf, "x": x, "y": y})[0][0]
        out.append({"slots": {"station": name}, "answer": n})
    return out

# ------------------------------------------------------------------ template table

T = [
 # id, category, stated_definition, answer kind, text, sampler
 ("cN1", "network", None, "meters", "How many meters is the shortest walk from the {station} BART station to the nearest grocery store? " + WALKDEF + " " + SNAP, n1_sample),
 ("cN2", "network", None, "meters", "How many meters is the shortest road route from {A} to {B} in {city}? " + ROADDEF + " " + SNAP, n2_sample),
 ("cN3", "network", None, "buffer_count", "How many {category} can be reached within a 400 m walk of the {station} BART station? " + WALKDEF + " " + SNAP, n3_sample),
 ("cN4", "network", None, "name", "Which elementary school is nearest by road to {place}? " + ROADDEF + " " + SNAP, n4_sample),
 ("cN5", "network", None, "number", "Between the {station} BART station and {place}, what is the ratio of the walking route length to the straight-line distance between the two points? " + WALKDEF + " " + SNAP + " Measure the straight line between the station and the place themselves. Give the ratio to three decimals.", n5_sample),
 ("cW1", "what-if", None, "meters", "If the road segment {segment} ({segname}) were closed, how many meters longer would the shortest road route from {A} to {B} become? " + ROADDEF + " " + SNAP, w1_sample),
 ("cW2", "what-if", None, "meters", "If every freeway segment (road class motorway) were closed, how many meters longer would the shortest road route from {A} to {B} become? " + ROADDEF + " " + SNAP, w2_sample),
 ("cW3", "what-if", None, "meters", "If every segment of {street} inside {city} were closed, how many meters longer would the shortest walk from the {station} BART station to {place} become? " + WALKDEF + " " + SNAP, w3_sample),
 ("cW4", "what-if", None, "yesno", "If the road segment {segment} were closed, could you still travel by road from intersection {X} to intersection {Y}? " + ROADDEF, w4_sample),
 ("cW5", "what-if", None, "meters", "If all primary and secondary roads were closed, how many meters longer would the shortest road route from {A} to {B} become? " + ROADDEF + " " + SNAP, w5_sample),
 ("cC1", "constrained", True, "meters", "What is the total length, in meters, of streets inside the {city} city boundary? " + STREETDEF + " Count only the part of each street inside the boundary.", c1_sample),
 ("cC2", "constrained", True, "buffer_count", "How many street segments within 500 m (straight line) of {school} have a posted speed limit above 25 mph? " + STREETDEF + " Use only posted limits, not estimated ones.", c2_sample),
 ("cC3", "constrained", True, "buffer_count", "How many fatal or severe-injury crashes (severity 1 or 2) in the years 2021 to 2025 happened at intersections within 300 m (straight line) of the {station} BART station? Count crashes matched to an intersection.", c3_sample),
 ("cC4", "constrained", False, "buffer_count", "How many arterial road segments inside the {city} city boundary have a speed limit that was not posted?", c4_sample),
 ("cC5", "constrained", False, "number", "What percentage of the street length within 400 m (straight line) of the {station} BART station is residential? Give the percentage to one decimal.", c5_sample),
 ("cL1", "lookup", None, "count", "How many {category} are inside the {city} city boundary?", l1_sample),
 ("cL2", "lookup", None, "number", "What is the population of the census tract that contains {place}?", l2_sample),
 ("cL3", "lookup", None, "count", "How many bus stops are inside the {city} city boundary?", l3_sample),
 ("cL4", "lookup", None, "count", "How many injury crashes were recorded inside the {city} city boundary in {year}?", l4_sample),
 ("cL5", "lookup", None, "number", "What is the median household income of the census tract that contains {place}?", l5_sample),
 ("cL6", "lookup", None, "buffer_count", "How many places of any kind lie within 250 m (straight line) of the {station} BART station?", l6_sample),
 ("cL7", "lookup", None, "count", "How many segments of {street} are bridges?", l7_sample),
 ("cL8", "lookup", None, "number", "What is the highest intersection elevation, in meters, inside the {city} city boundary?", l8_sample),
 ("cL9", "lookup", None, "number", "What percentage of households have no vehicle in the census tract that contains {place}? Give the percentage to one decimal.", l9_sample),
 ("cL10", "lookup", None, "buffer_count", "How many bus stops lie within 400 m (straight line) of the {station} BART station?", l10_sample),
]
