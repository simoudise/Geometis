"""Smoke test of network_path on both geofences and both networks. No model calls."""
import random, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loop
conn = loop.db()
for gf in ["us-ca-contra-costa-5", "us-ca-san-francisco"]:
    for net in ["road", "walk"]:
        t = time.time(); g = loop._graph(conn, gf, net)
        import networkx as nx
        comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
        print(gf, net, "nodes", g.number_of_nodes(), "edges", g.number_of_edges(), "largest component share",
              round(comps[0]/g.number_of_nodes(), 3), "build s", round(time.time()-t, 1), flush=True)
        big = max(nx.connected_components(g), key=len); nodes = list(big)
        random.seed(1)
        for _ in range(3):
            a, b = random.sample(nodes, 2)
            t = time.time(); r = loop.network_path(conn, gf, a, b, network=net)
            seg = r["segments"][len(r["segments"])//2]["urn"] if r.get("segments") else None
            r2 = loop.network_path(conn, gf, a, b, network=net, remove_segments=[seg]) if seg else {}
            print("  path", r.get("length_m"), "edges", r.get("edge_count"), "after removal", r2.get("length_m", r2.get("error")),
                  "s", round(time.time()-t, 2), flush=True)
