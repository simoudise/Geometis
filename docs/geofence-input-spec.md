# Geofence input for the GKG builder

Task A1 of the City Fingerprint Work Plan. Status: draft for Evangelos's approval, 2 November 2026.

## Purpose

Every Knowledge Builder loader takes one geofence record as its only geographic input. No loader may hard-code a county code, a bounding box, a city list or a file path. With this rule, the builder that produces the Contra Costa graph in Phase 1 can produce the San Francisco graph (task A4) and the reference-set graphs by changing only the record.

## The geofence record

| Field | Meaning | Contra Costa example |
| --- | --- | --- |
| `geofence_id` | A lower-case slug, unique and stable | `us-ca-contra-costa-5` |
| `name` | A readable name | Five Contra Costa cities |
| `members` | The Census place GEOIDs (state FIPS + place FIPS, 7 digits) whose union forms the core | Antioch, Concord, Pittsburg, Pleasant Hill, Walnut Creek |
| `boundary_source` | Census TIGER/Line Places, with its vintage | TIGER/Line 2024 |
| `core` | The union of the member boundaries, stored in EPSG:4326 | |
| `buffer_m` | The width of the ring added around the core for the network extent | Set by the rule below |
| `extent` | The core buffered by `buffer_m`, computed in EPSG:5070 (CONUS Albers) and stored in EPSG:4326 | |
| `states`, `counties` | Derived from the members by intersecting the extent with TIGER state and county boundaries; never typed by hand | 06; 013 |
| `source_versions` | The pinned version of every source the build reads (next section) | |
| `created`, `spec_version` | Build metadata | |

A single city is a geofence with one member. San Francisco is `us-ca-san-francisco`, member GEOID 0667000. The fingerprint stream computes factors per city, so each of the five Contra Costa cities also gets its own one-member record. Those five records share the union graph instead of producing five separate builds.

## Core and extent: which loader reads which

The builder keeps two polygons because two needs conflict. Map matching and walksheds need the network to continue past the city line. Fingerprint factors must describe the city alone.

| Stage | Loader reads | Entities outside the core |
| --- | --- | --- |
| 1 Road network | Overture transportation inside the extent; OSM fallback | Loaded, flagged `inCore = false` |
| 2 Tracts and ACS | Every tract that intersects the core, kept whole and not clipped | Each tract records the share of its area inside the core |
| 3 POIs and transit | POIs and stops inside the extent; every GTFS feed with at least one stop inside the extent | Loaded, flagged `inCore = false` |
| 4 Collisions | The state adapter for each state in `states` (SWITRS for California); FARS fatal crashes where a state has no adapter | Loaded, flagged |
| 5, 6 Derived analytics | Computed over the extent | Reported for the core only |
| 8 Validation | Integrity and coverage checks over the extent | |

## Buffer rule

v19 §9.3 Stage 1 (megapatch item F6) requires a buffer "sufficient to contain the routes of trips between" the member cities, but gives no number and no test. I propose a test that uses no trip data:

1. Start with `buffer_m` = 3,000.
2. Route by car, with OSRM, between every pair of tract centroids inside the core.
3. Measure the share of total route length that falls outside the extent.
4. If more than 0.5 per cent falls outside, add 1,000 m and repeat.
5. Record the final `buffer_m` and the measured share in the record.

The Mac mini's OSRM data covers Northern California only. Until other regions have OSRM extracts, geofences outside Northern California use the 3,000 m default and record that the test was not run.

## Pinned source versions

Each build records the exact version of every source, so that two builds of the same geofence can be compared.

| Source | What is pinned |
| --- | --- |
| Overture transportation and places | Release identifier, fixed at the first Phase 1 download and reused for every reference-set geofence |
| OSM (fallback) | Geofabrik extract name and date, with its checksum |
| Census boundaries | TIGER/Line vintage |
| ACS | The 5-year release used, with its end year |
| GTFS | The Mobility Database feed identifier and the archived version in effect in the target month |
| Collisions | Adapter name, years loaded and download date |

## Changes to the existing loaders

The January 2026 loaders in `03-gkg-v1/code` select their area in five different ways. Each one must read the geofence record instead:

- `utils.get_city_bounding_box` asks Nominatim for a bounding box; replace it with the record's `extent`.
- `census_tract_loader_fast.py` hard-codes county 013 (`CONTRA_COSTA_FIPS`); read `states` and `counties`.
- `overture_poi_loader_fast.py` hard-codes `CONTRA_COSTA_BBOX`; clip to `extent`, not to a bounding box.
- `switrs_safety_loader_enhanced.py` hard-codes county code 07 and a CSV path; select by `extent` through a state adapter.
- `04-transit/GTFS_to_kg_loader.py` lists four Bay Area feeds by URL; find the feeds from the Mobility Database by `extent`.

## Storage

The Mac mini's `geometis` database gets a table `gkg_geofence` that holds the records. The existing city tables and the `all_boundaries` view stay unchanged; the Contra Costa records are built from the same TIGER boundaries that `02-tlp/setup/setup_boundaries.py` downloaded.

## Decisions needed

1. Approve the buffer test and its 0.5 per cent threshold.
2. Confirm that the five Contra Costa cities form one union geofence for the graph, with five one-member records for the fingerprint.

## Gap against v19

v19 §9.3 Stage 1 states the buffer requirement for the initial geofence only and names no test. The next megapatch should state the general rule and the test above, and should add the core and extent distinction to §9.3.
