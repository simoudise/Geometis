"""Reference machinery for Test 1, written separately from loop.py's network tool (Fable defect 3).

Networks (stated in every question that uses one):
  road: every road segment, both directions, length in meters.
  walk: road segments other than motorways, pedestrian edges, and access points (length 0) joining
        intersections to pedestrian nodes, both directions.
Snapping (stated in every question): a place, stop or station is attached to the network node nearest to it in
straight-line distance (EPSG:3310), among nodes of that network's largest connected component.
Routes are shortest paths by length (SciPy Dijkstra). One-way rules are ignored.
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree

_cache = {}

def edges(conn, gf, net):
    q = ("select urn, from_node, to_node, length_m, coalesce(road_classification,''), coalesce(name,'') "
         "from gkg.road_segment where geofence_id = %(g)s")
    if net == "walk":
        q += (" and coalesce(road_classification,'') <> 'motorway'"
              " union all select urn, from_node, to_node, length_m, 'pedestrian', '' from gkg.pedestrian_edge where geofence_id = %(g)s"
              " union all select urn, intersection_node, pedestrian_node, 0, 'access', '' from gkg.access_point where geofence_id = %(g)s")
    with conn.cursor() as cur:
        cur.execute(q, {"g": gf})
        rows = [r for r in cur.fetchall() if r[1] and r[2] and r[1] != r[2]]
    conn.rollback()
    return rows

def nodes_xy(conn, gf, net):
    q = "select urn, ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.intersection_node where geofence_id = %(g)s"
    if net == "walk":
        q += " union all select urn, ST_X(ST_Transform(geom,3310)), ST_Y(ST_Transform(geom,3310)) from gkg.pedestrian_node where geofence_id = %(g)s"
    with conn.cursor() as cur:
        cur.execute(q, {"g": gf})
        rows = cur.fetchall()
    conn.rollback()
    return rows

class Net:
    def __init__(self, conn, gf, net):
        self.gf, self.net = gf, net
        self.rows = edges(conn, gf, net)
        pts = nodes_xy(conn, gf, net)
        self.idx = {u: i for i, (u, _, _) in enumerate(pts)}
        self.urn = [u for u, _, _ in pts]
        self.xy = np.array([[x, y] for _, x, y in pts])
        keep = [r for r in self.rows if r[1] in self.idx and r[2] in self.idx]
        self.edge_urn = [r[0] for r in keep]
        self.edge_cls = [r[4] for r in keep]
        self.edge_name = [r[5] for r in keep]
        self.a = np.array([self.idx[r[1]] for r in keep]); self.b = np.array([self.idx[r[2]] for r in keep])
        self.w = np.array([max(float(r[3]), 0.01) for r in keep])
        self.n = len(pts)
        g = self.matrix(np.ones(len(keep), bool))
        _, lab = connected_components(g, directed=False)
        big = np.bincount(lab).argmax()
        deg = np.bincount(np.r_[self.a, self.b], minlength=self.n)
        self.main = np.where((lab == big) & (deg > 0))[0]
        self.tree = cKDTree(self.xy[self.main])

    def matrix(self, mask):
        # Parallel edges: csr sums duplicates, so keep the minimum explicitly.
        a, b, w = self.a[mask], self.b[mask], self.w[mask]
        key = np.minimum(a, b) * self.n + np.maximum(a, b)
        order = np.lexsort((w, key)); key, a, b, w = key[order], a[order], b[order], w[order]
        first = np.r_[True, key[1:] != key[:-1]]
        a, b, w = a[first], b[first], w[first]
        return coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(self.n, self.n)).tocsr()

    def snap(self, x, y):
        d, i = self.tree.query([x, y])
        return int(self.main[i]), float(d)

    def dist(self, src, dst=None, remove_urns=(), avoid_cls=()):
        mask = np.ones(len(self.w), bool)
        if remove_urns:
            s = set(remove_urns); mask &= np.array([u not in s for u in self.edge_urn])
        if avoid_cls:
            s = set(avoid_cls); mask &= np.array([c not in s for c in self.edge_cls])
        d = dijkstra(self.matrix(mask), directed=False, indices=src)
        return d if dst is None else float(d[dst])

    def path_edges(self, src, dst):
        """Edge urns of one shortest path (for choosing what-if segments; not used to score)."""
        g = self.matrix(np.ones(len(self.w), bool))
        d, pred = dijkstra(g, directed=False, indices=src, return_predecessors=True)
        lookup = {}
        for k in range(len(self.w)):
            key = (min(self.a[k], self.b[k]), max(self.a[k], self.b[k]))
            if key not in lookup or self.w[k] < self.w[lookup[key]]:
                lookup[key] = k
        out, v = [], dst
        while v != src and pred[v] >= 0:
            u = pred[v]; out.append(lookup[(min(u, v), max(u, v))]); v = u
        return out[::-1]

def net(conn, gf, kind):
    k = (gf, kind)
    if k not in _cache:
        _cache[k] = Net(conn, gf, kind)
    return _cache[k]
