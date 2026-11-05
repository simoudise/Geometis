"""Run the URN registry on two cached Overture releases for one geofence and report aggregates only.

Usage: ~/geometis-venv/bin/python analysis/urn_refresh_test.py us-ca-contra-costa-5 2026-09-23.1 2026-10-21.0
Whole vehicular segments serve as pieces (key = GERS id), which tests rules 1, 2 and 5 on real data and
rules 3 and 4 wherever Overture split or merged a segment between the releases.
"""
import json
import sys
import time

import duckdb
import shapely
from pyproj import Transformer
from shapely.ops import transform  # deprecated in Shapely 2.1; kept for pyproj callables

sys.path.insert(0, ".")
from gkg import config, urn_registry as ur
from gkg.geofence import fetch

gid, old_rel, new_rel = sys.argv[1], sys.argv[2], sys.argv[3]
to_m = Transformer.from_crs("EPSG:4326", config.METRIC_CRS, always_xy=True).transform
core, extent, _ = fetch(gid)
con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")


def load(rel):
    p = config.DATA_ROOT / "overture" / rel / gid / "segment.parquet"
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall()]
    sub = "AND subtype = 'road'" if "subtype" in cols else ""
    wkb = "wkb" if "wkb" in cols else "ST_AsWKB(geometry)"
    rows = con.execute(f"SELECT id, class, {wkb} FROM read_parquet('{p}') WHERE true {sub}").fetchall()
    out = []
    for i, c, w in rows:
        if c in config.PEDESTRIAN_CLASSES:
            continue
        g = shapely.from_wkb(bytes(w))
        if g.geom_type == "LineString" and extent.intersects(g):
            out.append(ur.Piece(f"{i}|0|1", i, transform(to_m, g)))
    return out


t0 = time.time()
old, new = load(old_rel), load(new_rel)
for o in old:
    o.urn = ur.mint("RoadSegment", o.key, old_rel)
a = ur.assign(old, new, new_rel)
print(json.dumps({"geofence": gid, "old_release": old_rel, "new_release": new_rel, "old_pieces": len(old),
                  "new_pieces": len(new), **ur.summary(a), "seconds": round(time.time() - t0, 1)}))
