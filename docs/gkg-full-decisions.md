# GKG full build: decisions

Decisions by Evangelos on the Step 1 inventory (November 20, 2026, 13:25 Pacific). Step 1 document: Drive SPECTRA > GKG FULL, "GKG FULL Step 1 relation inventory 2026-11-20 11.10.md".

## A. Inventory

Approved (285 object properties; 99 buildable from data we can access).

## B. Rules

1. Distance relations, as proposed:
   - uko:near 200 m straight line; uko:veryNear 50 m (UKO comment). Both between places, transit stops and intersections only, not buildings.
   - nearTransitStop (building to stop) 400 m.
   - hasVulnerablePopulationNearby and nearVulnerablePopulation 200 m.
   - accessibleBy, frontageOn, providesAccessTo: nearest street segment within 30 m of the building.
   - accessibleByBikeLane, accessibleBySidewalk 50 m. hasParking 100 m. hasTruckParkingFacility 500 m.
   - **Addition by Evangelos:** record distances to important buildings and districts, for example museums, concert and opera halls, public buildings, and districts such as a theater district or a shopping district. Details to confirm in Step 2 (section D below).
2. North, south, east, west of: not stored; computed at query time.
3. Road hierarchy: continuesAs at a turn of 30 degrees or less with a name change; parallelTo within 30 m and 15 degrees over at least 50 m; feedsInto and distributesTo by class order motorway, trunk, primary, secondary, tertiary, residential and unclassified, service; servesAsMainAccess = the street in the place's address, else the nearest street. acrossFrom, nearbyLandmark and segmentBetween are skipped.
4. Commercial: build operatedByOrg from the brand field; skip competitiveWith, directCompetitor, complementaryTo, synergisticWith and anchorTenant.
5. Transit: hasServiceArea = 400 m around the route's stops; fareProductOfAgency from GTFS Fares v1 files, each edge labeled v1; hasTransferTo from transfers.txt where present (11 of 25 feeds), else stops of different routes within 200 m.
6. High Injury Network: San Francisco only, from the city's published Vision Zero network; Contra Costa skipped. Every edge carries the crash flag.
7. providesRecreationFor: tracts within an 800 m walk of a park.

## C. Public downloads

Approved and done (jobs 202 to 204; Mac mini folder `~/geometis-data/gkg/public/2026-11-20/`, with `MANIFEST.tsv` giving URL, time, size, SHA-256 and feature count for each file):

| File | Source | Features |
|---|---|---|
| sf_analysis_neighborhoods.geojson | DataSF j2bu-swwd (Analysis Neighborhoods) | 41 |
| sf_find_neighborhoods.geojson | DataSF pty2-tcw4 (SF Find Neighborhoods) | 117 |
| sf_supervisor_districts_2022.geojson | DataSF f2zs-jevy | 11 |
| sf_hin_2024.geojson | DataSF enwt-3u8m (2024 High Injury Network, injuries 2020 to 2024) | 5,917 segments |
| sf_hin_2022.geojson | DataSF 8vtn-qytr (2022 High Injury Network, injuries 2017 to 2021) | 7,988 segments |
| mtc_pda_pba2050plus.geojson | MTC ArcGIS, Priority Development Areas, Plan Bay Area 2050+ | 223 (25 in the six cities) |
| gbfs/*.json | Bay Wheels GBFS 2.3 (gbfs.lyftbikes.com): system, station, vehicle type, region and pricing files; no live status | 658 stations |

Notes: the first neighborhood downloads from the Socrata resource endpoint came back without geometry; the v3 export endpoint returned complete files, and the manifest keeps only the complete ones. San Francisco publishes a 2024 network that replaces the 2022 one; the build will use 2024 unless Evangelos says otherwise. The 2024 network counts injuries from 2020 to 2024, which overlaps the Test 2 label years (2021 to 2025); it is crash-flagged and never an input to a crash-prediction test.

## D. Open items for Step 2

- Landmark and district distances (Evangelos's addition): the set of target classes, the radius, and the distance measure (straight line, walking network or both).
- UKO 15.5 corrections and v19 items (see the Step 1 document, section 8); Evangelos to decide whether to issue UKO 15.6.

## E. Asked, not yet answered

- Whether connectsToTransit follows UKO (road segment to stop), not v19 section 9.4 (the branch currently follows UKO).
- Whether crash-flagged relations are built and tagged (proposed), with crash-prediction exports dropping them by rule.
