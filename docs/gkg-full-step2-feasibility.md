# GKG full build — Step 2: feasibility (November 20, 2026)

Synapse Partners, LLC. Confidential and proprietary. Nothing was built: every number below comes from timed samples in scratch schemas that the jobs dropped afterward. This document holds no coordinates, trip data or query rows; counts are aggregates.

## 1. Method

- **Job 206** (`07-gkg-builder/relations/feasibility.py`, 2 percent sample): for each relation family and geofence, the job computes the relation for a random 2 percent of source entities (`abs(hashtext(urn)) % 100 < 2`) in PostGIS, on copies of each layer projected to California Albers (EPSG:3310) with spatial indexes. It records sampled sources, rows, seconds and bytes per row (table plus one index), then scales rows, seconds and size by (all sources / sampled sources). Walking distances use SciPy Dijkstra (2 km limit) from 40 random landmark targets per area on the Test 2 walk graph (`work/test2-export`). The whole job took 104 seconds; the Python process peaked at 0.7 GB.
- **Job 207** (`07-gkg-builder/relations/feasibility2.sh`): loads the OpenStreetMap layers from `norcal.osm.pbf` for each area (timed), counts park, parking, district and tag coverage, times two park relations, counts place pairs that share a building, and tests the join between TIMS and the raw CCRS crash files.
- **Status jobs s212 to s215**: class names in the place table, free disk space, a block-polygon test, and the fields in the raw TIMS files.
- **Scaling caveat.** Seconds scale linearly with sources; joins that use spatial indexes scale close to linearly, so the minutes below are estimates within perhaps a factor of two, not measurements of the full build.

## 2. Results by relation family

Rows and sizes are for the full build of both areas. "GB" uses the current table design, where every edge stores two text URNs (about 200 bytes per row with one index).

| Family | Relation | Rows, Contra Costa | Rows, San Francisco | Minutes, both | GB, both |
|---|---|---|---|---|---|
| Proximity | uko:near (200 m; places, stops, intersections) | 11,616,050 | 65,186,311 | 22.7 | 15.26 |
| Proximity | uko:veryNear (50 m; same sets) | 1,361,691 | 7,051,267 | 22.5 | 1.70 |
| Proximity | uko:nearTransitStop (buildings, 400 m) | 516,530 | 3,067,713 | 0.1 | 0.72 |
| Proximity | uko:hasVulnerablePopulationNearby (200 m) | 36,108 | 247,631 | 0.3 | 0.08 |
| Proximity | uko:nearVulnerablePopulation (road segments, 200 m) | 29,060 | 70,493 | 0.1 | 0.03 |
| Access | uko:accessibleBy / frontageOn / providesAccessTo (nearest street within 30 m) | 177,968 | 186,286 | 0.2 | 0.15 |
| Access | uko:accessibleBySidewalk (50 m) | 19,513 | 81,506 | 0.1 | 0.05 |
| Access | uko:alongsideOf (sidewalk to road) | 4,970 | 12,879 | 0.0 | 0.01 |
| Containment | uko:withinCensusTract (places, stops, intersections) | 90,698 | 124,647 | 0.1 | 0.08 |
| Topology | uko:sharesWallWith (buildings) | 7,336 | 241,737 | 0.2 | 0.08 |
| Topology | uko:crossesOver / crossesUnder | 1,518 | 1,215 | 0.1 | 0.01 |
| Topology | uko:parallelTo | 12,983 | 7,764 | 0.1 | 0.01 |
| Landmarks and districts | distances to landmark buildings (2 km, straight line) | 1,060,385 | 30,426,999 | 8.0 | 6.30 |
| Landmarks and districts | distances to districts (2 km to boundary, 0 inside) | 91,101 | 2,998,995 | 0.2 | 0.48 |
| Landmarks and districts | walking distance (Dijkstra, 2 km; 223 and 1,249 targets) | 525,934 node distances | 10,437,237 node distances | under 1 for the search; joining to entities not timed | (a column on the rows above) |
| Safety, crash-flagged | uko:inHighInjuryNetwork (SF 2024 network) | — | 10,381 segments | 0.1 | 0.01 |
| Road network | candidates for continuesAs, feedsInto, branchesFrom, mergesInto (segment pairs at a shared node) | 165,459 | 108,461 | 0.2 | small |
| Transit | stop times (stored) and trips | 34,972 / 1,493 trips | 385,120 / 12,733 trips | small | small |
| Commercial | partOfChain / operatedByOrg (branded places) | 2,704 | 3,284 | small | small |
| Freight | constrainsSegment candidates (segments with access restrictions) | 25,202 | 26,011 | small | small |
| Common space (job 207) | bordersCommonSpace (roads within 15 m of a park boundary) | 4,958 | 10,070 | 3.7 | small |
| Common space (job 207) | pathThroughCommonSpace (pedestrian edges in parks) | 4,164 | 17,022 | (same) | small |
| Commercial (job 207) | sharesBuildingWith (place pairs in one building) | 209,950 | 1,398,251 | under 1 | about 0.3 |
| OSM load (job 207) | park, parking, district and road-tag layers | 59,202 polygons, 77,240 lines | 436,403 polygons, 172,995 lines | 3.9 | scratch only |
| **Total sampled families** | | | | **about 60** | **about 25.3** |

Other counts from job 207: park polygons 861 (Contra Costa extent) and 3,595 (San Francisco extent); road lines with truck tags (hgv, maxweight, maxheight, maxlength) 1,746 and 6,803; with bike-lane tags 2,147 and 5,651; with sidewalk tags 1,928 and 9,643; OSM named-district points 31 and 155 (including Financial District, Marina District, Castro District and Fillmore District). The natural-area count failed on a SQL keyword (`natural` needs quoting) and will be repeated in Step 3.

## 3. What the samples show

1. **Two relations make up 85 percent of the size.** uko:near in San Francisco (65 million rows, about 490 neighbors per entity within 200 m downtown) and the landmark distances in San Francisco (30 million rows). Everything else together is under 3 GB.
2. **uko:veryNear needs no rows of its own.** Every veryNear pair is also a near pair; storing the distance on each near row and marking veryNear as near with distance up to 50 m saves 8.4 million rows and 1.7 GB.
3. **Walking distance is cheap to search and costly to store as a separate table.** The Dijkstra search takes about one second per area. I propose storing the walking distance as a second column on the landmark-distance rows, which adds about 4 bytes per row.
4. **Text URNs dominate the storage.** About 200 bytes per row comes mostly from two URNs of about 60 characters each. A table that stores each edge as two 8-byte entity numbers (with a lookup table from number to URN), a 2-byte relation code, the distances and a provenance code would take about 60 to 70 bytes per row with its indexes. The full build would then need about 9 GB instead of about 25 to 35 GB (the larger figure counts a second index on the object column and the provenance column).
5. **City blocks.** UKO already has uko:CityBlock. A block test on one 1 km tile in Contra Costa found 11 closed blocks holding 264 buildings and 4,541 building pairs on the same block, about 17 pairs per building. San Francisco's tile test failed (the core's representative point fell outside the street grid), so I have no San Francisco figure. A rough estimate of 3 to 6 million building pairs for both areas suggests storing blocks as entities with uko:within edges (about 375,000 rows) and leaving uko:onSameBlock to be computed from them at query time, unless you want the pairs stored.
6. **Crash fields.** The TIMS crash IDs do not match any ID column in the raw CCRS files (0 of 7,297 crashes in 2024), so joining the two is not possible by ID. The raw TIMS files on the Mac mini (`tims-incoming`) already carry WEATHER_1, WEATHER_2, ROAD_SURFACE, ROAD_COND_1 and LIGHTING, which the Stage 4 loader does not load. reo:incidentWeatherCondition and reo:incidentRoadSurface can come from those fields, with a change to the Stage 4 loader. Both stay crash-flagged.
7. **Places and the new UKO.** No Overture category in the place table matches a class added in UKO 15.6 (status job s212), so switching the builder to 15.6 changes no place's class. Theaters, concert and opera halls are not classified yet: Overture puts them under performing_arts_venue (135 places) and music_venue (265 places), and the crosswalk maps neither. The landmark sample counted all of them, so its sizes are an upper bound. Step 3 would map performing_arts_venue to uko:Theater and name-match concert halls and opera houses within music_venue and performing_arts_venue; that mapping needs your review.

## 4. Mac mini or Google Cloud

- **Compute.** About one hour of database time for the sampled families, plus index builds (likely 20 to 40 minutes on 100 million rows), plus about 30 minutes for the smaller families and loading OSM, GTFS trips, GBFS and the public polygons: **about 2 to 2.5 hours on the Mac mini in total.** No family needs a GPU or more than the Mac mini's 24 GB of memory: the largest Python step is the Dijkstra search (about 0.3 GB per batch of 256 targets), and PostgreSQL works within its settings.
- **PostgreSQL settings.** The server runs with shared_buffers 160 MB and work_mem 4 MB. The build jobs would raise work_mem and maintenance_work_mem per session (no restart). Raising shared_buffers needs a restart, which is your decision; the build does not depend on it.
- **Storage.** With entity numbers: about 9 GB plus up to 20 GB of temporary space during index builds. With text URNs: about 25 to 35 GB. The data volume showed 71 GiB free at 14:28 Pacific, down from 126 GiB at 11:39. macOS recreated Time Machine local snapshots at 11:50, 12:54 and 13:54; they probably hold part of that space, and macOS releases them when the disk fills. The build fits either way, with more margin under the entity-number design.
- **Google Cloud: not needed.** No family justifies a cloud machine; the estimated cost of Google Cloud is therefore zero, and no public data goes there.

## 5. Decisions for Step 3

1. **Run approval.** The build will run longer than one hour (estimate 2 to 2.5 hours on the Mac mini; no API or cloud spending). It produces the approved relations for both areas with provenance on every edge, validation counts, spot checks against domain and range, and a data dictionary.
2. **Edge storage design.** Proposed: one edge table keyed by entity numbers, with a lookup table to URNs, distances as columns, and a provenance table referenced by code (about 9 GB). The alternative keeps text URNs on every row (about 25 to 35 GB).
3. **uko:veryNear as a marked subset of uko:near** (no separate rows). Proposed: yes.
4. **City blocks.** Store uko:CityBlock entities with uko:within edges and compute uko:onSameBlock at query time (proposed), or also store the building pairs (about 3 to 6 million rows).
5. **Theater, concert hall and opera house classes.** Approve the mapping rule in section 3, item 7, or give another.
6. **Crash weather and road surface.** Extend the Stage 4 loader to read WEATHER_1, ROAD_SURFACE and ROAD_COND_1 from the TIMS files, for reo:incidentWeatherCondition and reo:incidentRoadSurface (crash-flagged). Proposed: yes.

## 6. What I did not sample

- uko:hasJurisdiction, uko:inNeighborhood, uko:inSupervisorDistrict and the polygon-to-polygon relations (overlaps, adjacentTo for tracts): each is a containment or adjacency join over a few thousand polygons and is small.
- Transit relations that need the trips table (hasTrip, belongsToRoute, hasServiceCalendar, hasServiceException), transfers, fares, service areas, Bay Wheels stations and anchorStation: the counts in section 2 bound them below one million rows in total.
- hasStreetAddress (address matching) and servesAsMainAccess: bounded by the number of places (107,393).
- The road-hierarchy rules (continuesAs, feedsInto, branchesFrom, mergesInto) keep a subset of the 273,920 candidate pairs counted.
- uko:onSameBlock in San Francisco (the tile test failed, section 3, item 5).

*Synapse Partners, LLC — Confidential and Proprietary*
