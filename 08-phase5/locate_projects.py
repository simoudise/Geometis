"""Phase 5: place SFMTA quick-build corridors on the San Francisco graph and count injury crashes before and after.

Input: a CSV of corridors (street, from street, to street, completion year and month, scope), kept on the Mac mini.
For each corridor:
  1. Candidate segments: San Francisco road segments whose name has the same key as the corridor street
     (gkg.road_key: first word after removing accents, punctuation and direction prefixes), service roads excluded.
  2. End nodes: intersection nodes that touch a candidate segment and a segment named like the from street (or the to
     street). When the two streets share no node, the corridor street's node nearest the limit street stands in, up to
     MAX_GAP_M away, and the output records the gap. Among the candidate end-node pairs, the pair joined by the
     shortest path along candidate segments wins.
  3. Corridor: the segments and nodes on that shortest path.
  4. Crashes: TIMS injury crashes attached (Stage 4) to those segments or nodes, in the 36 months before the completion
     month and the 36 months after it (the completion month itself is left out), with the same counts for all of San
     Francisco as a crude comparison.
Output: one aggregate row per corridor (public crash data; no trip data), written to a CSV on the Mac mini.
"""
import csv
import heapq
import sys
from collections import defaultdict

import psycopg

G = "us-ca-san-francisco"


def key(conn, s):
    # "Embarcadero" and "The Embarcadero" must give the same key, so a leading "The" is dropped first.
    return conn.execute("SELECT gkg.road_key(regexp_replace(%s, '^[Tt]he ', ''))", (s,)).fetchone()[0]


KEY_SQL = "gkg.road_key(regexp_replace(coalesce(name, ''), '^[Tt]he ', ''))"

# Largest distance in meters between a limit street and the corridor street's nearest node when the two share no node.
MAX_GAP_M = 150


def shortest(adj, a, b):
    dist, prev, pq = {a: 0.0}, {}, [(0.0, a)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == b:
            break
        if d > dist.get(u, 1e18):
            continue
        for v, w, urn in adj[u]:
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v], prev[v] = nd, (u, urn)
                heapq.heappush(pq, (nd, v))
    if b not in dist:
        return None, None
    segs, nodes, u = [], [b], b
    while u != a:
        u, urn = prev[u]
        segs.append(urn)
        nodes.append(u)
    return dist[b], (segs, nodes)


def window_counts(conn, segs, nodes, y, m):
    q = """
    WITH w AS (SELECT make_date(%(y)s, %(m)s, 1) c),
    x AS (SELECT c.* FROM gkg.crash_attachment a JOIN gkg.tims_crash c USING (case_id)
          WHERE a.geofence_id = %(g)s AND (a.segment_urn = ANY(%(s)s) AND a.node_urn IS NULL OR a.node_urn = ANY(%(n)s)))
    SELECT
      count(*) FILTER (WHERE x.collision_date >= w.c - interval '36 months' AND x.collision_date < w.c),
      count(*) FILTER (WHERE x.collision_date >= w.c + interval '1 month' AND x.collision_date < w.c + interval '37 months'),
      count(*) FILTER (WHERE x.severity <= 2 AND x.collision_date >= w.c - interval '36 months' AND x.collision_date < w.c),
      count(*) FILTER (WHERE x.severity <= 2 AND x.collision_date >= w.c + interval '1 month' AND x.collision_date < w.c + interval '37 months'),
      count(*) FILTER (WHERE (x.pedestrian OR x.bicycle) AND x.collision_date >= w.c - interval '36 months' AND x.collision_date < w.c),
      count(*) FILTER (WHERE (x.pedestrian OR x.bicycle) AND x.collision_date >= w.c + interval '1 month' AND x.collision_date < w.c + interval '37 months')
    FROM x, w"""
    r = conn.execute(q, {"y": y, "m": m, "g": G, "s": segs, "n": nodes}).fetchone()
    city = conn.execute("""
      WITH w AS (SELECT make_date(%(y)s, %(m)s, 1) c)
      SELECT count(*) FILTER (WHERE c.collision_date >= w.c - interval '36 months' AND c.collision_date < w.c),
             count(*) FILTER (WHERE c.collision_date >= w.c + interval '1 month' AND c.collision_date < w.c + interval '37 months')
      FROM gkg.crash_attachment a JOIN gkg.tims_crash c USING (case_id), w WHERE a.geofence_id = %(g)s""",
                        {"y": y, "m": m, "g": G}).fetchone()
    return list(r) + list(city)


def main(inp, out):
    rows = list(csv.DictReader(open(inp)))
    with psycopg.connect("dbname=geometis") as conn:
        res = []
        for r in rows:
            # A corridor along several streets lists them separated by "/" (for example Evans/Hunters Point/Innes).
            ks = [key(conn, x) for x in r["street"].split("/")]
            # Optional columns from_st_map and to_st_map name the street to match in the map when the limit street
            # named in the project list has since been renamed or realigned (Mission Rock moved the junction of
            # Terry A. Francois Boulevard and 3rd Street; the new street there is Toni Stone Crossing).
            kf = key(conn, r.get("from_st_map") or r["from_st"])
            kt = key(conn, r.get("to_st_map") or r["to_st"])
            segs = conn.execute(
                f"""SELECT urn, from_node, to_node, length_m FROM gkg.road_segment
                   WHERE geofence_id = %s AND {KEY_SQL} = ANY(%s) AND coalesce(road_classification,'') <> 'service'""",
                (G, ks)).fetchall()
            adj = defaultdict(list)
            for urn, a, b, l in segs:
                adj[a].append((b, l, urn))
                adj[b].append((a, l, urn))
            def ends(kx):
                """Return (candidate end nodes, gap in meters). The gap is 0 when the limit street meets the corridor
                street at a shared node."""
                shared = [n for (n,) in conn.execute(
                    f"""SELECT DISTINCT s.from_node FROM gkg.road_segment s WHERE s.geofence_id = %(g)s AND {KEY_SQL.replace('name', 's.name')} = %(kx)s
                       UNION SELECT DISTINCT s.to_node FROM gkg.road_segment s WHERE s.geofence_id = %(g)s AND {KEY_SQL.replace('name', 's.name')} = %(kx)s""",
                    {"g": G, "kx": kx}).fetchall() if n in adj]
                if shared:
                    return shared, 0
                # No shared node. In the map the limit street can stop short of the corridor street (Natoma Street ends
                # about 110 m from Beale Street, 24th Street about 85 m from Indiana Street), or meet it through a ramp
                # or alley. Use the corridor street's node nearest the limit street, if it lies within MAX_GAP_M, plus any
                # node no more than 15 m farther away. Keeping only the nearest nodes stops the shortest-path step from
                # picking a node part way along the corridor and cutting the corridor short. The gap goes to the output
                # so that a reader can see which corridors rest on this rule.
                near = conn.execute(
                    f"""SELECT i.urn, x.d FROM gkg.intersection_node i
                        JOIN LATERAL (SELECT min(ST_Distance(i.geom::geography, s.geom::geography)) d FROM gkg.road_segment s
                                      WHERE s.geofence_id = %(g)s AND {KEY_SQL.replace('name', 's.name')} = %(kx)s
                                        AND s.geom && ST_Expand(i.geom, 0.003)) x ON true
                        WHERE i.geofence_id = %(g)s AND i.urn = ANY(%(nodes)s) AND x.d <= %(mx)s ORDER BY x.d""",
                    {"g": G, "kx": kx, "nodes": list(adj), "mx": MAX_GAP_M}).fetchall()
                if not near:
                    return [], None
                return [n for n, d in near if d <= near[0][1] + 15], round(near[0][1])
            (A, gap_from), (B, gap_to) = ends(kf), ends(kt)
            best = None
            for a in A[:20]:
                for b in B[:20]:
                    d, path = shortest(adj, a, b)
                    if d is not None and (best is None or d < best[0]):
                        best = (d, path)
            row = {**{k2: r[k2] for k2 in ["corridor", "street", "from_st", "to_st", "completed_year", "completed_month", "scope"]},
                   "from_st_map": r.get("from_st_map") or "", "to_st_map": r.get("to_st_map") or "",
                   "street_segments": len(segs), "from_nodes": len(A), "to_nodes": len(B),
                   "from_gap_m": gap_from, "to_gap_m": gap_to}
            if best:
                d, (sp, npath) = best
                # Divided streets have one segment per direction; the path follows one. Add the corridor street's
                # segments that run alongside the path (both ends within 30 m of it) and their end nodes, so crashes
                # attached to the other carriageway count too.
                extra = conn.execute(
                    f"""WITH p AS (SELECT ST_Union(geom) g FROM gkg.road_segment WHERE geofence_id = %(g)s AND urn = ANY(%(sp)s))
                        SELECT s.urn, s.from_node, s.to_node FROM gkg.road_segment s, p
                        WHERE s.geofence_id = %(g)s AND {KEY_SQL.replace('name', 's.name')} = ANY(%(ks)s) AND NOT s.urn = ANY(%(sp)s)
                          AND ST_DWithin(ST_StartPoint(s.geom)::geography, p.g::geography, 30)
                          AND ST_DWithin(ST_EndPoint(s.geom)::geography, p.g::geography, 30)""",
                    {"g": G, "sp": sp, "ks": ks}).fetchall()
                sp = sp + [e[0] for e in extra]
                npath = list(set(npath) | {e[1] for e in extra} | {e[2] for e in extra})
                c = window_counts(conn, sp, npath, int(r["completed_year"]), int(r["completed_month"]))
                row.update(located=True, corridor_m=round(d), segments=len(sp), nodes=len(npath),
                           crashes_before=c[0], crashes_after=c[1], ksi_before=c[2], ksi_after=c[3],
                           ped_bike_before=c[4], ped_bike_after=c[5], city_before=c[6], city_after=c[7])
            else:
                row.update(located=False)
            res.append(row)
            print(row["corridor"], row.get("located"), row.get("corridor_m"), row.get("crashes_before"), row.get("crashes_after"), flush=True)
    fields = sorted({k2 for r in res for k2 in r}, key=lambda f: list(res[0]).index(f) if f in res[0] else 99)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(res)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
