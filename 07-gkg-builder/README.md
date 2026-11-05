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

## Stage 3 transit on the five Contra Costa cities (build 7)

`run_stage3_transit.py` reads GTFS-static from the Mobility Database archive (refresh token in
`MOBILITY_DB_TOKEN`, from `~/.geometis-env` on the Mac mini). The reference date is Wednesday
17 April 2024, the month of the first client trip delivery. For each feed whose bounding box touches the
extent, the loader takes the archived dataset whose calendar covers that date; when none does, it takes the
nearest one and records the gap. A deprecated feed and the feed it redirects to count as one feed.

| Item | Value |
|---|---|
| Feeds loaded | 12 (9 cover 17 April 2024; 3 use the nearest dataset) |
| Stops inside the extent | 1,639 (1,254 inside the core): 1,389 bus stops, 8 BART stations, 8 platforms, 9 entrances |
| Routes serving those stops | 61, with 1,535 trips on the service day |
| Stop times kept | 34,972 |
| Walksheds | 1,634 (5 stops lie more than 150 m from the walkable network); median area 0.69 km2 |
| Stops matched to a road segment (uko:connectsToTransit) | 1,627, median distance 5.6 m |
| Time | 22 s |

### Gaps

1. **April 2024 schedules are missing for the two main bus agencies.** The archive holds County Connection
   only for 12 November 2023 to 13 January 2024 (95 days before the reference date) and Tri Delta Transit
   only from 11 August 2024 (116 days after). This build uses those nearest datasets, and each stop's service
   counts come from a Wednesday inside the dataset's own calendar (10 January 2024 and 14 August 2024).
   AC Transit (2 stops inside the extent) is 46 days off. Evangelos is deciding whether to fetch the
   April 2024 versions from Transitland or from the agencies.
2. **Unserved County Connection stops.** 218 County Connection stops have no departure on 10 January 2024.
   Only 12 of them lie within 30 m of a served stop, so most are not duplicates; they are probably stops of
   weekend, school or discontinued routes. They are kept and marked with zero departures.
3. **Walkshed parameters.** v19 asks for walksheds "using the v15.4 decay parameters", but neither v19 nor
   UKO 15.5 states the values. This build uses placeholders set in `gkg/config.py`: an 800 m network
   threshold and exponential decay with beta 0.002 per metre. The walkable network is every vehicular
   segment except motorways, plus the pedestrian layer, joined at access points.
4. **Direction of uko:connectsToTransit.** v19 section 9.4 lists the edge as (TransitStop, connectsToTransit,
   RoadSegment). UKO 15.5 declares the property with domain uko:Road and range uko:TransitStop, the
   opposite direction. The table `gkg.stop_road` stores the pair without choosing; the graph export must
   follow one of the two, and v19 or UKO should change to match the other.
5. **city2graph.** v19 names city2graph for the GTFS graph. The loader reads the GTFS files directly with
   pandas instead, as Stage 1 does for Overture.
6. **Feed search by bounding box.** The Mobility Database search returns feeds whose recorded bounding box
   touches the extent, including some far away (Renfe, Chatham Area Transit). The loader drops every feed
   with no stop inside the extent, so these do not reach the graph.

## Stage 6 street-pattern measures

`run_stage6_street_pattern.py` computes three measures from Boeing (2019, *Applied Network Science* 4:67) for
the union and for each of the five one-city fingerprint records: orientation order (phi, 0 for uniform
bearings, 1 for a perfect grid), average circuity, and node shares on the simplified graph (segments merged
through degree-2 nodes). It measures all vehicular segments, and again without service roads and tracks.

| City | phi | Circuity | Dead ends | 3-way | 4-way or more | Intersections per km2 |
|---|---|---|---|---|---|---|
| Antioch | 0.166 | 1.077 | 0.174 | 0.632 | 0.194 | 41.1 |
| Concord | 0.049 | 1.065 | 0.326 | 0.520 | 0.155 | 41.2 |
| Pittsburg | 0.261 | 1.089 | 0.267 | 0.545 | 0.188 | 31.8 |
| Pleasant Hill | 0.228 | 1.067 | 0.365 | 0.494 | 0.141 | 60.7 |
| Walnut Creek | 0.041 | 1.080 | 0.387 | 0.478 | 0.134 | 34.4 |

(Network without service roads and tracks; the build record holds both versions.)

Gaps: Boeing builds his graphs from OpenStreetMap through OSMnx; this build uses Overture segments, which
split at different points and include more service roads, so values are comparable across GeoMetis geofences
but not exactly with Boeing's published city values. Boeing's "drive" network filter is not reproduced
exactly; excluding service roads and tracks is an approximation.

## San Francisco (task A4, 4 November 2026)

| Stage | Result | Time |
|---|---|---|
| Geofence and buffer test | 244 tract points, 10,000 sampled car routes; 367 pairs dropped because a tract point lies more than 500 m from a road (probably the tract that includes the Farallon Islands; not checked); 0.0 per cent outside core plus 3,000 m, so the buffer stays at 3,000 m | 19 s |
| Stage 1 | 61,175 vehicular edges (3,336 km, 2,391 km in the core), 72,482 pedestrian edges, 21,556 access points; OSM crosswalk covers 99.1 per cent of length; 90 components, the largest holding 87 per cent of length (islands and the Presidio and port networks account for the rest); Stage 8 passed | 51 s, 79 s with checks |
| Stage 2 | 261 tracts, ACS 2020-2024, none missing | 7 s |
| Stage 3 places | 78,789 places, 87.6 per cent mapped to UKO by rule | 15 s |
| Stage 3 transit | 18 feeds, 3,849 stops (3,548 in the core), 170 routes, 385,120 stop times; Muni (dataset of 4 March 2024) covers the reference date | 70 s |
| Stage 6 street pattern | phi 0.369, circuity 1.032, four-way-or-more share 0.426 (network without service roads and tracks) | 2 s |

Whole build: under 4 minutes.

### Problems found and fixed during the San Francisco build

1. **Buffer test and island tracts.** The first run stopped at the 30 km cap: 7 per cent of route length lay outside the core plus 3 km, and the share fell only slowly. Routes to a tract point far from any road (probably on the Farallon Islands) snap to a distant road. Pairs whose tract point lies more than `BUFFER_MAX_SNAP_M` (500 m) from a road are now left out of the test and counted in the build record.
2. **Slow Stage 8 check.** With a 30 km extent the crosswalk-coverage check ran for 37 minutes on stale planner statistics. `checks.run` now runs ANALYZE first, and the crosswalk has an index on segment URN.
3. **Transit feeds wholly inside the extent were missed.** The Mobility Database filter "partially_enclosed" leaves out feeds whose bounding box lies completely inside the query box, so Muni was missing. The loader now queries "completely_enclosed" as well and merges the two. Contra Costa's result did not change.

### Gap

4. **Densities now use land area (fixed 5 November 2026).** The TIGER place polygon for San Francisco covers about
   600 km2, most of it bay and ocean. Stage 6 now divides by the member places' TIGER land area (ALAND), and the
   fields are renamed `intersections_per_km2_land` and `street_km_per_km2_land`. Without service roads and tracks:
   San Francisco 77.7 intersections and 15.9 street-km per km2 of land (120.9 km2); the five Contra Costa cities
   40.7 and 9.1 (270.0 km2); Pittsburg changes most among them (45.8 km2 of land in a 51.1 km2 place).
5. **Tract shares on land (fixed 5 November 2026).** Stage 2 now removes TIGER AREAWATER from each tract before
   computing its share inside the core. San Francisco's population weighted by share stays at 830,235, because
   every San Francisco tract lies wholly inside the city; the change matters for tracts split by a shoreline
   boundary.

## URN registry (5 November 2026)

`gkg/urn_registry.py` assigns URNs to a new Overture release from the previous one, in five rules: same piece
and geometry within tolerance keeps its URN; otherwise a unique geometric match keeps the old URN; an old piece
covered end to end by a chain of new pieces is a split; a new piece covering a chain of old pieces is a merge;
the rest are retired or added. Splits and merges mint new URNs and write lineage rows (`gkg.urn_lineage`).
The tolerances are the ones in `gkg/config.py` (ends 5 m, Hausdorff 10 m, length 10 per cent, unique candidate).
`python -m gkg.urn_registry` runs a synthetic self-test of every rule, including an ambiguous match that must
not reuse a URN.

On real data (`analysis/urn_refresh_test.py`, whole vehicular segments as pieces, Contra Costa extent):

| Releases | Old | New | Kept | Rematched | Split (new pieces) | Merge | Added | Retired | Time |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-23.1 to 2026-10-21.0 | 52,574 | 52,586 | 52,557 | 0 | 4 (from 2 old) | 0 | 25 | 15 | 2.8 s |
| 2026-09-23.0 to 2026-09-23.1 | 52,574 | 52,574 | 52,574 | 0 | 0 | 0 | 0 | 0 | 2.8 s |

The two splits are segments that kept their GERS id but were shortened, with the rest of the road carried by a
new segment; the earlier drift analysis counted them among the 22 retained segments whose geometry changed.

Not done yet: Stage 1 still mints URNs directly from the GERS id and split fractions. The next step is to make
Stage 1 call the registry when a previous release is loaded for the same extent, and to write `gkg.urn_registry`
rows at every build.
