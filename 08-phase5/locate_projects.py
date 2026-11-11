"""Phase 5: place SFMTA quick-build corridors on the San Francisco graph and count injury crashes before and after.

Input: a CSV of corridors (street, from street, to street, completion year and month, scope), kept on the Mac mini.
For each corridor:
  1. Candidate segments: San Francisco road segments whose name has the same key as the corridor street
     (gkg.road_key: first word after removing accents, punctuation and direction prefixes), service roads excluded.
  2. End nodes: intersection nodes that touch a candidate segment and a segment named like the from street (or the to
     street). Among the candidate end-node pairs, the pair joined by the shortest path along candidate segments wins.
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
    return conn.execute("SELECT gkg.road_key(%s)", (s,)).fetchone()[0]


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
            k, kf, kt = key(conn, r["street"]), key(conn, r["from_st"]), key(conn, r["to_st"])
            segs = conn.execute(
                """SELECT urn, from_node, to_node, length_m FROM gkg.road_segment
                   WHERE geofence_id = %s AND gkg.road_key(name) = %s AND coalesce(road_classification,'') <> 'service'""",
                (G, k)).fetchall()
            adj = defaultdict(list)
            for urn, a, b, l in segs:
                adj[a].append((b, l, urn))
                adj[b].append((a, l, urn))
            def ends(kx):
                return [n for (n,) in conn.execute(
                    """SELECT DISTINCT s.from_node FROM gkg.road_segment s WHERE s.geofence_id = %(g)s AND gkg.road_key(s.name) = %(kx)s
                       UNION SELECT DISTINCT s.to_node FROM gkg.road_segment s WHERE s.geofence_id = %(g)s AND gkg.road_key(s.name) = %(kx)s""",
                    {"g": G, "kx": kx}).fetchall() if n in adj]
            A, B = ends(kf), ends(kt)
            best = None
            for a in A[:20]:
                for b in B[:20]:
                    d, path = shortest(adj, a, b)
                    if d is not None and (best is None or d < best[0]):
                        best = (d, path)
            row = {**{k2: r[k2] for k2 in ["corridor", "street", "from_st", "to_st", "completed_year", "completed_month", "scope"]},
                   "street_segments": len(segs), "from_nodes": len(A), "to_nodes": len(B)}
            if best:
                d, (sp, npath) = best
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
