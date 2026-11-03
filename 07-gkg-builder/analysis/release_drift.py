"""Compare two Overture releases inside one geofence extent, to set the URN matching tolerance.

Reports aggregates only: how many vehicular segments keep their GERS id between the releases, how far
retained segments move, and, for segments whose id changed, how close the nearest old segment lies.
"""
import json
import sys

import duckdb
import numpy as np
import shapely
from pyproj import Transformer
from shapely.ops import transform

sys.path.insert(0, ".")
from gkg import config
from gkg.geofence import fetch

OLD = sys.argv[2] if len(sys.argv) > 2 else "2026-09-23.1"
gid = sys.argv[1] if len(sys.argv) > 1 else "us-ca-contra-costa-5"
to_m = Transformer.from_crs("EPSG:4326", config.METRIC_CRS, always_xy=True).transform

core, extent, _ = fetch(gid)
xmin, ymin, xmax, ymax = extent.bounds
out = config.DATA_ROOT / "overture" / OLD / gid
out.mkdir(parents=True, exist_ok=True)
old_path = out / "segment.parquet"
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
con.execute(f"SET memory_limit='3GB'; SET threads=4; SET preserve_insertion_order=false; SET temp_directory='{out}'")
if not old_path.exists():
    base = f"s3://overturemaps-us-west-2/release/{OLD}/theme=transportation"
    con.execute(f"""COPY (SELECT id, class, ST_AsWKB(geometry) AS wkb
        FROM read_parquet('{base}/type=segment/*', hive_partitioning=1)
        WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}
          AND subtype = 'road') TO '{old_path}' (FORMAT parquet)""")
new_path = config.DATA_ROOT / "overture" / config.OVERTURE_RELEASE / gid / "segment.parquet"


def load(p):
    rows = con.execute(f"SELECT id, class, wkb FROM read_parquet('{p}')").fetchall()
    keep = {}
    for i, c, w in rows:
        if c in config.PEDESTRIAN_CLASSES:
            continue
        g = shapely.from_wkb(bytes(w))
        if extent.intersects(g):
            keep[i] = transform(to_m, g)
    return keep


old, new = load(old_path), load(new_path)
same = set(old) & set(new)
gone, added = set(old) - set(new), set(new) - set(old)


def pct(a):
    a = np.asarray(a)
    return {f"p{q}": round(float(np.percentile(a, q)), 2) for q in (50, 90, 95, 99, 99.9)} | {"max": round(float(a.max()), 2)} if len(a) else {}


def ends(a, b):
    a0, a1 = shapely.Point(a.coords[0]), shapely.Point(a.coords[-1])
    b0, b1 = shapely.Point(b.coords[0]), shapely.Point(b.coords[-1])
    return min(max(a0.distance(b0), a1.distance(b1)), max(a0.distance(b1), a1.distance(b0)))


# Movement of segments that kept their id
moved = [shapely.hausdorff_distance(old[i], new[i]) for i in same]
lenchg = [abs(new[i].length - old[i].length) / max(old[i].length, 1e-6) for i in same]

# For each new segment with a new id, the best candidate among old segments whose id disappeared
gone_ids = list(gone)
tree = shapely.STRtree([old[i] for i in gone_ids])
best, matched, ambiguous = [], 0, 0
for i in added:
    g = new[i]
    cands = [gone_ids[k] for k in tree.query(g.buffer(25))]
    scored = []
    for c in cands:
        o = old[c]
        e, h = ends(o, g), shapely.hausdorff_distance(o, g)
        lr = abs(g.length - o.length) / max(o.length, 1e-6)
        scored.append((h, e, lr, c))
    if scored:
        scored.sort()
        best.append(scored[0][:3])
    passing = [s for s in scored if s[1] <= 5 and s[0] <= 10 and s[2] <= 0.10]
    if len(passing) == 1:
        matched += 1
    elif len(passing) > 1:
        ambiguous += 1

res = {
    "old_release": OLD, "new_release": config.OVERTURE_RELEASE, "geofence": gid,
    "old_segments": len(old), "new_segments": len(new), "kept_id": len(same),
    "kept_id_share_of_new": round(len(same) / len(new), 4),
    "ids_gone": len(gone), "ids_added": len(added),
    "kept_id_hausdorff_m": pct(moved), "kept_id_length_change": pct(lenchg),
    "kept_id_moved_over_1m": int(sum(m > 1 for m in moved)),
    "added_best_candidate_hausdorff_m": pct([b[0] for b in best]),
    "added_best_candidate_end_m": pct([b[1] for b in best]),
    "added_with_no_candidate_within_25m": len(added) - len(best),
    "added_matched_by_rule_5m_10m_10pct": matched,
    "added_ambiguous_under_rule": ambiguous,
}
print(json.dumps(res, indent=1))
