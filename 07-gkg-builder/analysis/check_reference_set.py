"""Check the reference-set GEOIDs against TIGER place names and write one geofence definition per city."""
import json
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, ".")
from gkg.geofence import tiger_zip

ref = json.loads(Path("geofences/reference_set_v1.json").read_text())
cities = {**ref["groups"]["waymo_public_service"], **ref["groups"]["comparison"]}
by_state = {}
for name, g in cities.items():
    by_state.setdefault(g[:2], []).append((name, g))
ok = True
for st, items in sorted(by_state.items()):
    places = gpd.read_file(f"zip://{tiger_zip('place', st)}", columns=["GEOID", "NAME", "NAMELSAD", "ALAND"])
    names = dict(zip(places["GEOID"], places["NAME"]))
    land = dict(zip(places["GEOID"], places["ALAND"]))
    for name, g in items:
        found = names.get(g)
        flag = "OK " if found == name else "BAD"
        ok &= found == name
        print(f"{flag} {g} expected={name!r} tiger={found!r} land_km2={land.get(g, 0)/1e6:.0f}")
        if found == name:
            gid = "us-" + {"04":"az","06":"ca","08":"co","32":"nv","13":"ga","48":"tx","12":"fl","47":"tn","25":"ma","53":"wa","17":"il","36":"ny"}[st] + "-" + name.split(" metropolitan")[0].split("-")[0].lower().replace(" ", "-")
            Path(f"geofences/{gid}.json").write_text(json.dumps(
                {"geofence_id": gid, "name": f"{name} city", "state_fips": st,
                 "members": [{"geoid": g, "name": name}], "fingerprint_records": False}, indent=2) + "\n")
print("ALL OK" if ok else "SOME GEOIDS WRONG")
