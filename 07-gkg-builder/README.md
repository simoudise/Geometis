# Knowledge Builder, Phase 1

Loaders that build the GeoMetis knowledge graph for any geofence. Each loader reads one geofence
record (see `docs/geofence-input-spec.md`) as its only geographic input.

Status, 3 November 2026: the geofence record, Stage 1 (base road network and pedestrian
multiplex) and Stage 2 (Census tracts and ACS) run on the Mac mini. Stage 3 follows (task A3).

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

## Overture release drift, September to October 2026

`analysis/release_drift.py` compared releases 2026-09-23 and 2026-10-21 for the Contra Costa extent
(vehicular segments only):

- 52,559 of 52,586 October segments (99.95 per cent) kept their GERS id. 15 ids disappeared and 27 appeared.
- Of the segments that kept their id, 22 changed geometry by more than 1 m (at most 27 m).
- None of the 27 new segments lies within 10 m of a disappeared segment; the nearest lies 42 m away at the
  median. The new ids belong to new or redrawn roads, not to renamed copies of old ones. The matching rule
  (ends within 5 m, Hausdorff at most 10 m, length within 10 per cent) therefore matched none of them, which
  is the correct result.
- Overture keeps only recent releases on its public bucket, so a longer interval could not be tested.

Two consequences. First, v19's figure of about 20 per cent GERS churn between releases does not hold for
transportation segments here: one month changed 0.05 per cent. v19 gives no source for the 20 per cent.
Second, the URN of a piece also depends on where its parent segment is split, so a new connector on an
unchanged GERS id changes the URNs of that segment's pieces. The URN registry must match pieces of a
retained GERS id by geometry as well, not only segments whose GERS id changed.

## Stage 2 on the five Contra Costa cities (build 3)

`run_stage2.py` loads every 2024 TIGER tract that intersects the core, whole, with the share of its area
inside the core, and attaches ACS 5-year values (2020-2024): population, median household income, the
share of households without a vehicle, and household counts below 35,000 dollars and at 100,000 dollars
or more. 116 tracts cover the whole core; none lacks ACS values; the area-weighted population inside the
core is about 393,000. The Census Data API now requires a key, so Stage 2 reads the Census Bureau's
table-based summary files instead, which need none.

## Stage 3, places, on the five Contra Costa cities (build 5)

`run_stage3_places.py` loads 28,604 Overture places (release 2026-10-21.0) inside the extent. A place
gets a UKO 15.5 class when a UKO class name equals its Overture category (25 per cent of places), and
otherwise through the reviewed crosswalk in `mappings/overture_to_uko_v1.json`. Together the two rules
classify 85 per cent of places; 12 per cent are left unclassified on purpose (contractors, storage,
historic sites and other categories that are not trip destinations or have no UKO class); about 3 per
cent remain, mostly places with no Overture category. The LLM-assisted classifier that v19 names for
ambiguous categories is not built yet, and the crosswalk needs Evangelos's review.

Gap against v19: section 9.3 Stage 3 says each POI is classified "into the UKO uko:PointOfInterest
hierarchy", but UKO 15.5 puts restaurants, shops, schools and hospitals under uko:Building, not under
uko:PointOfInterest, whose subclasses are street furniture and small sites (ATMs, charging stations,
monuments). Either v19's wording or the UKO hierarchy needs to change.

GTFS (the transit part of Stage 3) waits for a Mobility Database token, and Foursquare OS Places is not
loaded yet.
