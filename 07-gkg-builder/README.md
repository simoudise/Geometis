# Knowledge Builder, Phase 1

Loaders that build the GeoMetis knowledge graph for any geofence. Each loader reads one geofence
record (see `docs/geofence-input-spec.md`) as its only geographic input.

Status, 3 November 2026: the geofence record and Stage 1 (base road network and pedestrian
multiplex) run on the Mac mini. Stages 2 and 3 follow (task A3).

## Run

On the Mac mini, through the job runner:

    ~/geometis-venv/bin/python -u run_stage1.py geofences/us-ca-contra-costa-5.json

The script creates the `gkg` schema if needed, builds and stores the geofence records, extracts
the Overture release named in `gkg/config.py`, loads Stage 1 into PostgreSQL and runs the Stage 8
checks that apply to Stage 1. Raw downloads go to `~/geometis-data/gkg`.

## First build: five Contra Costa cities (build 2)

| Item | Value |
|---|---|
| Buffer test | 87 tract points, 3,741 car routes; 0.0 per cent of route length outside the core plus 3,000 m, so the buffer stays at 3,000 m |
| Overture release | 2026-10-21.0 |
| Vehicular segments | 89,695 (6,707 km, of which 4,019 km inside the core) |
| Nodes | 44,052 intersections, 12,535 through nodes, 15,360 dead ends |
| Pedestrian edges and nodes | 24,310 and 22,429 |
| Access points | 10,755 |
| OSM crosswalk | covers 99.4 per cent of vehicular length |
| Connected components | 81; the largest holds 97.7 per cent of length |
| Segments with a posted speed | 7.6 per cent |
| Time | 24 s for the geofence records, 22 s for Stage 1, 5 s for the checks |
| Stage 8 result | passed |

## Open items and gaps against v19

1. **The five cities (resolved 3 November 2026).** Evangelos chose Concord over Richmond. The v19
   Vision Zero scenario now names Concord, matching section 9.3 and the database.
2. **Segment URNs.** v19 now states that the Knowledge Builder mints the source id of every
   Overture entity as a UUID, keeps the GERS id as a separate attribute, and keeps a URN registry
   so that a refresh reuses a URN when the GERS id or the geometry still matches (section on URNs,
   updated 3 November 2026). This build mints a name-based UUID from the GERS id and the piece's
   position, so the URNs repeat exactly for the same release. The registry and the refresh rule are
   not built yet, and v19 leaves the geometry tolerance to the GKG network version, which does not
   set it yet.
3. **city2graph.** v19 names city2graph as the Stage 1 tool. It is not installed on the Mac mini;
   this loader uses DuckDB and Shapely instead. Its output follows the same tables either way.
4. **Elevation.** v19 Stage 1 step 3 asks for elevation from a DEM. No DEM source is pinned and
   rasterio is not installed, so elevation is empty.
5. **Speed limits.** Overture carries a posted speed on 7.6 per cent of segments. SPECTRA and the
   risk models need more; candidates are OSM maxspeed through the crosswalk and class defaults.
6. **Direction.** `seg_connects_to` follows digitized direction only. One-way rules and turn
   restrictions are stored in `access_restrictions` but not applied yet.
7. **OSM fallback.** Not implemented. Overture covers the Contra Costa extent; the fallback is
   needed only where a later geofence shows sparse Overture coverage.
8. **Splitting rule.** Segments split at every connector that more than one segment uses. Nodes
   where only two segments meet are kept and marked `through`.
