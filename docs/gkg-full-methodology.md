# GKG full build: methodology

Version: November 22, 2026, 14:15 Pacific (ontology release 2026-11-22b). This file is the complete method for the full geospatial knowledge graph (GKG) of San
Francisco and the five Contra Costa cities (Antioch, Concord, Pittsburg, Pleasant Hill, Walnut Creek). It replaces
the method notes scattered across the Step 1 inventory, `docs/gkg-full-decisions.md`, the Step 2 feasibility study
and the Step 3 build report; those files remain as the record of how each decision was reached. The relation-by-relation
definitions with counts are in the data dictionary (`docs/gkg-full-data-dictionary.md`; the Drive copy carries counts).

## 1. Purpose and scope

The GKG stores every relation from Synapse's ontologies that public data supports for the two geofences
`us-ca-san-francisco` and `us-ca-contra-costa-5`. Each edge records where it came from (source, method, code version,
ontology release) so that a reader can trace and reproduce it. The graph holds no client trip data: every input is
public data (Tier P), and crash records (Tier R) appear only in relations marked crash-derived.

The build ran in three steps, and each step stopped for Evangelos's approval:

1. Inventory (November 20): all object properties in the ontologies, classified by whether the data supports them.
2. Feasibility (November 20): sample runs that sized every relation family and timed the build.
3. Build (November 20, revised November 22): entities, edges, provenance, distance measurements, checks.

## 2. Inputs

| Input | Version | Used for |
|---|---|---|
| Overture Maps transportation, buildings, places | release 2026-10-21.0 | road segments, intersections, pedestrian network, rail, buildings, places, brands, truck access rules |
| OpenStreetMap, Northern California extract (`norcal.osm.pbf`) | 2026-10-21 | parks and other common spaces, natural areas, parking facilities |
| US Census TIGER/Line 2024; ACS 5-year | 2024; 2019-2023 | census tracts, cities (places with legal/statistical area code 25 or 57), counties |
| GTFS feeds from the Mobility Database archive | one dataset per feed, nearest to the reference service day (listed in `gkg.build.source_versions`) | stops, routes, agencies, trips, stop times, calendars, exceptions, transfers, Fares v1 |
| Bay Wheels GBFS 2.3 | downloaded 2026-11-20 | bike-share system and stations |
| DataSF: SF Find Neighborhoods (pty2-tcw4), Analysis Neighborhoods (j2bu-swwd), Supervisor Districts 2022 (f2zs-jevy), 2024 High Injury Network (enwt-3u8m) | downloaded 2026-11-20 | neighborhoods, supervisor districts, High Injury Network |
| MTC Priority Development Areas, Plan Bay Area 2050+ | downloaded 2026-11-20 | districts and transit-station anchors |
| TIMS (SafeTREC) SWITRS crash records | downloaded 2026-11-10 | crash records, collision factors, lighting, weather, road surface (crash-derived only) |

| American Community Survey (ACS) 5-year, table-based summary files | 2020-2024 | tract statistics with margins of error: B01003 population, B19013 median household income, B19001 households by income, B25044 vehicles available, B08301 means of transportation to work |
| LEHD Origin-Destination Employment Statistics (LODES8), workplace area characteristics, all jobs (S000, JT00), with the LODES8 block crosswalk | 2024 | job counts by block, summed to tracts, the city and H3 cells |
| 2020 Census block populations and internal points (TIGER/Line 2020 tabblock20, California file) | 2020 | population weights inside San Francisco tracts (factors 3 and 5) |
| TIGER/Line 2024 tracts and places (ALAND) | 2024 | land area |

The public downloads sit on the Mac mini in `~/geometis-data/gkg/public/2026-11-20/` with `MANIFEST.tsv` (URL, time,
size, SHA-256 and feature count of each file); the November 22 downloads sit in `~/geometis-data/gkg/public/2026-11-22b/`
and are listed with their SHA-256 in `gkg.download_manifest`. The ACS files are those the tract stage cached.

## 3. Ontologies

The build classifies and checks against the coordinated release 2026-11-22b: UKO 15.8.0, TKO 8.5.2, MLO 1.8.0,
REO 1.8.0 and FKO 1.2.4 (`01-ontologies/`, commit 3531fef). UKO 15.8 imports the SOSA module (Sensor, Observation,
Sample, and Actuator, the core of the W3C Semantic Sensor Network ontology, Recommendation of October 19, 2017),
stored with its provenance in `01-ontologies/external/`. `tools/make_release_2026_11_22b.py` produces 15.8 and its
companions from the earlier release of the same day, which `tools/make_uko_15_7.py` and
`tools/make_companions_2026_11_22.py` produce from the November 20 release; each file's header carries its change log.
UKO 15.8, MLO 1.8.0 and REO 1.8.0 implement the design note "O4 O5 incidents" that Evangelos approved on November 22:
measured values aligned with SOSA, place statistics (O4), the fingerprint (O5), transfer evaluations, and
police-reported incidents other than collisions, stored as monthly counts. `tools/check_stack.py` reports zero problems (no undeclared term, every property with a domain and a
range, OWL 2 datatypes only, every import present), and the HermiT reasoner finds the five ontologies consistent,
also with test individuals of every class and property that 15.7 changed or added.

UKO 15.7 exists because the November 20 build showed eight property domains to be narrower than the data
(sharesBuildingWith, insideMall, partOfChain, operatedByOrg, nearestTransitStop, hasDataSource,
pathThroughCommonSpace, constrainsSegment) and two subclass axioms to be missing (schools and hospitals as
vulnerable-population facilities, Evangelos's decision B1). At Evangelos's request it also carries items O2, O3 and
O12 of the ontology sufficiency audit, part 1 (November 22, section 4): an intersection control type on graph nodes
(uko:hasControlType), traffic, pedestrian and cyclist volume observations (uko:TrafficVolumeObservation), and smaller
additions (numeric maximum grade, typical lane width, pavement condition index, a real-time flag on data sources,
airport enplanements). REO 1.7.0 carries item O1: a crash-to-segment relation (reo:onRoadSegment), the KABCO
severity scale with a per-state mapping table (reo:SeverityCodeMapping; California SWITRS rows included),
source-neutral crash fields, and crash-derived marks on every crash-record term. TKO, MLO and FKO change only
because each imports UKO by version; TKO also corrects one comment that cited the old domain of uko:hasDataSource.
Tests 1 and 2 stay frozen on UKO 15.5 and its companions.

## 4. Entities

- Every entity gets one row in `gkg.entity`: an integer key (`eid`), its URN, its geofence, its UKO or REO class and
  its source table. The Contra Costa and San Francisco extents overlap, so an entity is unique by geofence and URN,
  and the same Overture feature can have one key in each geofence.
- Entities from the earlier builder stages keep their URNs and classes. Pedestrian edges become uko:SidewalkSegment,
  uko:Crosswalk, uko:Cycleway, uko:Trail (Overture class `path`) or uko:PedestrianNetworkEdge.
- Landmark classes (decision 5 of Step 3): a place with Overture category `performing_arts_venue` is a uko:Theater;
  within `performing_arts_venue` and `music_venue`, a name containing "opera" makes it a uko:OperaHouse, and a name
  containing "symphony", "concert hall", "philharmonic" or "music hall" makes it a uko:ConcertHall; a government
  place named "city hall" is a uko:CityHall. These overrides live in `gkg.entity` only; the stage-3 place mapping
  does not yet carry them.
- New entities from public data sit in `gkg.aux_entity` with their geometry: neighborhoods, supervisor districts,
  Priority Development Areas, cities and counties, city blocks, common spaces, natural areas, parking facilities,
  brand organizations, data-source records, High Injury Network features and the network itself, intersection risk
  profiles, truck restrictions, trips, stop times, service exceptions, fare products, service areas and Bay Wheels
  stations and system.
- New URNs follow `urn:urban-kg:<Class>:<scheme>:<id>`. The id is the publisher's identifier where one exists (DataSF,
  MTC, TIGER GEOID, OpenStreetMap id, GBFS station id); otherwise it is a hash, with the scheme `gkgfull` for derived
  entities such as city blocks and service areas. GTFS-derived entities use the builder's UUID-5 namespace, so a
  trip's URN is the same whenever the same feed and trip id are loaded.
- City blocks (decision 4): the faces of the street network formed by all named-class roads except service roads,
  tracks, motorways, ramps, tunnels and bridges, kept when their area lies between 200 m² and 2 km².
- Truck restrictions: one entity per Overture access rule whose mode list contains `hgv`. A rule of access type
  `designated` is a uko:TruckRouteDesignation; any other is a uko:RegulatoryRoutingConstraint.
- Brand organizations: one uko:Organization per distinct brand name (case-insensitive) in each geofence.
- Crash records: one reo:HistoricalIncidentRecord per TIMS case attached to the network in that geofence (stage 4).
- `gkg.entity_type` holds extra asserted types. Under UKO 15.7 it is empty; the November 20 build used it for the
  types that 15.7 now states as axioms.

## 5. Edges and provenance

- `gkg.edge` holds one row per edge: relation code, subject key, object key, provenance code and, for relations that
  carry a distance, `value_m` in meters.
- A symmetric relation is stored once, with subject key < object key. Of an inverse pair only one property is stored
  (for example uko:within, not uko:contains).
- An edge never joins two geofences.
- `gkg.provenance` has one row per way of producing a relation's edges: source, method, code version, ontology release
  and the crash flag. `gkg.relation_type` holds each relation's domain and range as read from the ontology, its
  symmetry, its inverse and the rule in words.
- `gkg.distance_measurement` holds each uko:DistanceMeasurement: subject, target, straight-line meters, walking meters,
  whether the measure goes to a point or a boundary, and whether the subject lies inside the target.
- uko:veryNear is not stored separately: it is uko:near with `value_m` of 50 m or less (view `gkg.rel_very_near`).
  uko:onSameBlock is computed at query time from uko:within building -> city block.

## 6. Geometry and networks

- All metric work uses California Albers (EPSG:3310); stored geometry stays in WGS 84 (EPSG:4326).
- Points: places and stops use their points; buildings use a point on their surface; road segments use their
  midpoint where a relation needs a point.
- Walking network: road segments except motorways, pedestrian edges and the access points that join the two layers
  (zero length). Walking distances use Dijkstra's algorithm (SciPy) with a 2 km limit; each end snaps to its nearest
  network node, and the snap distances are added. A walking distance is left empty when the walk exceeds 2 km.
- Districts: the straight distance goes to the district boundary (zero inside); the walking distance goes to the
  nearest network node inside the district or within 20 m of it, so it can be up to about 20 m shorter than the
  straight distance.

## 7. Relation rules

Section 14 lists every relation with its ontology domain and range and the rule the build applies. The rules carry
Evangelos's decisions: the distances of decision B1 (near 200 m, veryNear 50 m, nearTransitStop 400 m, vulnerable
facilities 200 m, street access 30 m, bike lane and sidewalk 50 m, parking 100 m, truck parking 500 m), the road
hierarchy of B3, the commercial rule of B4, the transit rules of B5, the High Injury Network rule of B6, the
recreation rule of B7, the landmark and district distances (2 km, straight and walking), and on November 22 the
crosswalk rule and government buildings as landmarks.

Two rules rest on measurements made for this purpose:

- Crosswalks (November 22): Overture crosswalk edges seldom cross the road centerline, so a geometric crossing test
  found 11 to 44 of 18,980. The build links a crosswalk to the road segment nearest its midpoint when that segment
  lies within 7 m and runs within 30 degrees of perpendicular to the crosswalk. The cut-offs come from the measured
  distribution (status job s222): 79 to 95 percent of crosswalks within 7 m run across the road, against 53 percent
  at 7 to 8 m and less beyond. Evangelos asked for the tightest constraint that keeps accuracy.
- Government buildings stay landmarks for distance measurements (Evangelos, November 22): many kinds of traveler go
  to them, and governments build mobility infrastructure around them quickly (for example under the Americans with
  Disabilities Act).

Crash records link to REO individuals through SWITRS codes, exact matches only:

| SWITRS field | Codes -> REO individual |
|---|---|
| Collision type | A head-on, B sideswipe, C rear end, D broadside, F overturned, G vehicle-pedestrian, E and H other |
| Lighting | A daylight, B dusk or dawn, C dark with street lights, D dark without street lights, '-' not stated |
| Road surface | A dry, B wet, C snowy or icy, D slippery, '-' not stated |
| Weather (WEATHER_1) | A clear, B cloudy, C raining, D snowing, E fog, G windy, '-' not stated |
| Primary collision factor category | 01 DUI, 03 unsafe speed, 04 following too closely, 07 unsafe lane change, 21 unsafe starting or backing, 00 unknown; other codes get no edge |
| Collision severity -> KABCO | 1 fatal K, 2 severe injury A, 3 other visible injury B, 4 complaint of pain C, 0 property damage only O (REO rows reo:SEVMAP_SWITRS_CA_*) |

## 8. Place statistics and fingerprints (UKO 15.8)

`relations/stats_build.py` loads these for the San Francisco geofence, in the order Evangelos set: statistics from
`gkg.census_tract`, then LODES and ACS B08301, then the tract fingerprints.

- **Storage.** Every measured value is an entity (uko:PlaceStatistic or uko:FactorValue) with one row in
  `gkg.measured_value`: number, unit, margin of error and confidence level, period, procedure, source table and the
  other value properties of UKO 15.8. Its area, variable, source, procedure and mode are edges.
- **Tract statistics** (all 261 tracts of the geofence): population, households, median household income,
  households below 35,000 dollars and at 100,000 dollars or more, share of households with no vehicle (ACS
  2020-2024), land area (TIGER 2024 ALAND). Margins come from the summary files at the 90 percent level. A sum of
  lines takes the square root of the summed squared margins; a share uses the Census Bureau's proportion formula and
  falls back to the ratio formula when the proportion formula fails.
- **City of San Francisco:** the same figures summed over its 244 tracts (the city and the county coincide), and
  the land area of the TIGER place (GEOID 0667000). The city's median income is not derived from tract medians.
- **Jobs:** LODES8 2024 jobs by block, placed by the block's internal point from the LODES crosswalk, summed per
  tract, for the city, and per H3 cell at resolution 8 for every cell of the city that holds a job. The period
  recorded is the second quarter of 2024, the LODES reference quarter; this reading of the LODES documentation still
  needs checking.
- **Commute mode shares:** ACS B08301, workers 16 and over and the share of each of ten modes per tract and for the
  city, with margins.
- **Jobs reachable on foot within 30 minutes** (variable uko:VAR_JOBS_REACHABLE, mode walk, threshold 30): from the
  tract's population-weighted centroid (2020 block populations), on the walking network, at 4.8 km/h (2,400 m).
  The walking speed is an assumption; jobs at blocks more than 200 m from the network are not counted. Car and
  transit reach wait for a router.
- **Tract fingerprints**, version `sf-tract-v1`, for the 244 San Francisco tracts, with nine components from the
  factors defined at tract level in the Fingerprint Factor Specification (draft v0.1):
  - Factor 1, street pattern, on vehicular segments (all road classes except tracks, parking aisles and driveways),
    each assigned to the tract that holds its midpoint: (a) orientation order phi = 1 - ((H - 1.386)/(3.584 -
    1.386))^2, with H the Shannon entropy of segment bearings (start to end, on the ellipsoid) in 36 bins of 10
    degrees centered on multiples of 10, weighted by length and counted in both directions (Boeing 2019); (b)
    circuity = total segment length / total straight-line distance between segment ends; (c) the shares of
    intersection nodes with four or more ways and of dead ends, among nodes whose degree is not 2; (d) the median
    block shape factor (block area / area of the circle on the block's longest internal distance) over the city
    blocks whose point on surface lies in the tract. Part (d) stores the median, not the full histogram in
    logarithmic area bins that the specification describes.
  - Factor 3: jobs reachable on foot within 30 minutes, as above.
  - Factor 5: share of residents (2020 block populations; the specification's scaling to ACS totals cancels in a
    share) within 400 m of network walking of a stop with at least four departures in each hour from 07:00 to 19:00,
    on each feed's stored reference service day (most San Francisco feeds: Wednesday, April 17, 2024; the
    specification asks for the second Tuesday of the target month). The snap distance of the stop is not added.
  - Factor 8: median household income and the share of households with no vehicle. The income segregation index
    is a city-level measure and is computed at query time from the tract income bands.
  - Reference set `sf-tracts-2026-11-22`: the tracts with population and all nine components (234 of 244). Each
    component is standardized against it (sample standard deviation). Tracts outside the set keep their raw values
    and no standardized value.
  - Distances between every pair of reference-set tracts: weighted Euclidean over the standardized components; each
    factor weighs 1, split equally over its components (weights version `equal-factor-v1`). Each pair is stored once.
  - Factor 7's scaling adjustment applies across cities and is not used at tract level (uko:scalingResidual false).
- **Incident counts** (REO 1.8.0) are not loaded: they wait for the ontology audit chat to confirm each source's
  fields and licence.

## 9. Crash-derived relations

Eleven relations come from crash data: uko:inHighInjuryNetwork, uko:hinSegmentOf, uko:hasIntersectionRiskProfile and
the eight REO crash relations, including reo:onRoadSegment and reo:hasKABCOSeverity (REO 1.7.0). Each is marked in `gkg.relation_type` and `gkg.provenance`. A crash-prediction model
reads edges only through the view `gkg.edge_for_crash_prediction`, which drops these relations and every edge that
touches a crash record, a risk profile or a High Injury Network entity. Crash records may serve as labels only.

## 10. Checks

`relations/validate.py` writes a JSON file of counts and checks to the Mac mini share (never to the repository):

- Invariants that must be zero: edges without provenance, provenance of another relation, edges to missing entities,
  symmetric edges out of order, self-loops, edges between geofences, duplicate edges, crash flags that disagree,
  near edges beyond 200 m, distance rows beyond 2 km.
- Domain and range: the enforce step removes every edge whose subject or object is not an instance of the property's
  domain or range under the class hierarchy (`gkg.class_closure`, built from UKO and REO); `gkg.edge_rejected` counts
  the removals. The check then re-tests a 1 percent sample.
- Geometry: 500 random near distances and 500 random building-in-tract links recomputed from the source geometry.
- Examples: five random edges for each of 13 relations, with names, for reading by eye.

## 11. Reproducing the build

On the Mac mini, from `~/Geometis-mini/work/07-gkg-builder`, through the job runner:
`~/geometis-venv/bin/python -m relations.build [STEP ...]`. The steps run in this order: schema, catalogue,
entities, aux, blocks, work, stored, containment, proximity, topology, roadnet, access, commons, other, tims,
transit, distances, recreation, retype, index, enforce, views, cleanup. Place statistics and fingerprints follow with
`python -m relations.stats_build` (steps schema, individuals, tracts, downloads, lodes, commute, blocks,
fingerprints, statedges, check), then the build's work, enforce and views steps. Each step deletes and rewrites its own
output, so a failed step can run again alone; the entities step renumbers every key, so after it every later step
must run. The relation catalogue (`relations/catalogue/*.tsv`) comes from the ontology files:
`python -m relations.build --catalogue` in the cloud workspace, then copy the files to the Mac mini. Then run
`python -m relations.validate OUT.json` before the cleanup step, because the geometry checks read the work tables.

## 12. Not built

- uko:hasControlType: OpenStreetMap signal, roundabout, stop and give-way tags are not loaded (audit data gap D3).
- uko:TrafficVolumeObservation: no volume source is loaded (audit data gap; public HPMS volumes cover arterials only).
- O12 values: the maximum grade already sits in `gkg.road_segment.max_abs_grade` and maps to uko:maxGradePercent;
  lane width, pavement condition and airport enplanements have no loaded source; the build does not yet set
  uko:isRealTime on its data-source records (all loaded sources are static).

- uko:hasStreetAddress, and the address rule of uko:servesAsMainAccess: the loaded place files have no address
  fields; servesAsMainAccess uses the nearest street.
- uko:hasAccessToCommonSpace: no distance rule approved.
- uko:servesNeighborhood: needs a rule.
- uko:servesVehicleType: Bay Wheels lists vehicle types per system, not per station.
- North, south, east and west of (decision B2); acrossFrom, nearbyLandmark, segmentBetween, from and to cross
  street, and the commercial competition relations (skipped by decision).
- Incident counts (REO 1.8.0): waiting for the audit chat's check of each source's fields and licence.
- City-level fingerprints, factor values for factors other than 1, 3, 5 and 8, transfer evaluations
  (mlo:TransferEvaluation) and a second fingerprint version: not computed yet. With one city, no city-to-city
  distance exists.
- uko:derivedFrom has no edges: `gkg.urn_lineage` is empty because one Overture release has been loaded.

## 13. Known limits

- Overture place classes are noisy (some places classed ShoppingMall are shops).
- Transit relations cover the reference service day only.
- uko:continuesAs follows the digitized direction of segments, so it misses name changes where two segments point
  against each other.
- Only one feed has transfers.txt, and its pairs fall outside the stored stops; all transfer edges come from the
  200 m rule.
- The architecture document (v19) lists uko:connectsToTransit from stop to road; the build follows UKO (road to
  stop). v19 has not been checked section by section against the build.

## 14. Relations

### Road network topology

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:adjacentSegment | uko:IntersectionNode -> uko:RoadSegment | intersection node to each road segment that ends at it |
| uko:connectsTo | uko:RoadInfrastructure -> uko:RoadInfrastructure | segment A's end node is segment B's start node (digitized direction) |
| uko:touches (symmetric) | uko:GeographicFeature -> uko:GeographicFeature | road segments that share an end node |
| uko:intersectsRoad (symmetric) | uko:Road -> uko:Road | segments of differently named roads that meet at a shared node |
| uko:crosses | uko:LinearFeature -> uko:GeographicFeature | road segment crosses rail segment; crosswalk to the road segment nearest its midpoint, within 7 m and 30 degrees of perpendicular |
| uko:crossesOver | uko:Road -> uko:Road | road segments whose lines cross with no shared node; bridge over non-bridge, or non-tunnel over tunnel |
| uko:continuesAs | uko:Road -> uko:Road | named road changes name at a node with a turn of 30 degrees or less |
| uko:branchesFrom | uko:Road -> uko:Road | ramp (subclass link) whose start node lies on a non-ramp motorway, trunk or primary segment |
| uko:mergesInto | uko:Road -> uko:Road | ramp whose end node lies on a non-ramp motorway, trunk or primary segment |
| uko:feedsInto | uko:Road -> uko:Road | lower-class road meets higher-class road at a shared node (class order of decision B3) |
| uko:parallelTo (symmetric) | uko:LinearFeature -> uko:LinearFeature | segments within 30 m, 15 degrees, running together at least 50 m |
| uko:hasAccessPoint | uko:RoadSegment or uko:IntersectionNode or uko:PedestrianNetworkNode or uko:PedestrianNetworkEdge -> uko:AccessPoint | intersection node or pedestrian node to the access point joining them |

### Containment and administrative areas

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:within | uko:GeographicFeature -> uko:GeographicFeature | building in city block; place in building (place_building) |
| uko:withinCensusTract | uko:GeographicFeature -> uko:CensusTract | point (or midpoint, or building centroid) in tract |
| uko:hasJurisdiction | uko:GeographicFeature -> uko:AdministrativeArea | feature to its city (TIGER place), else its county |
| uko:inNeighborhood | uko:GeographicFeature -> uko:Neighborhood | feature in a San Francisco neighborhood (SF Find and Analysis Neighborhoods) |
| uko:inSupervisorDistrict | uko:SpatialEntity -> uko:SupervisorDistrict | feature in a San Francisco supervisor district (2022) |
| uko:overlaps (symmetric) | uko:GeographicFeature -> uko:GeographicFeature | district polygon overlaps census tract polygon (shared area >= 1 percent) |
| uko:adjacentTo (symmetric) | uko:GeographicFeature -> uko:GeographicFeature | census tracts whose boundaries share a line |
| uko:adjacentNeighborhood (symmetric) | uko:Neighborhood -> uko:Neighborhood | neighborhoods of the same scheme sharing a boundary |

### Proximity and distance

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:near (symmetric) | uko:GeographicFeature -> uko:GeographicFeature | places, stops, intersections within 200 m (value_m = meters); veryNear is value_m <= 50 |
| uko:hasDistanceMeasurement | uko:SpatialEntity -> uko:DistanceMeasurement | stored in gkg.distance_measurement, not gkg.edge: place, stop or intersection to landmark or district within 2 km |
| uko:hasVulnerablePopulationNearby | uko:SpatialEntity -> uko:VulnerablePopulationFacility | place, stop or intersection within 200 m of a school, senior or care facility, or hospital |
| uko:nearVulnerablePopulation | uko:Road -> uko:VulnerablePopulationFacility | road segment within 200 m of such a facility |

### Buildings, places and access

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:sharesWallWith (symmetric) | uko:Building -> uko:Building | buildings sharing at least 1 m of boundary |
| uko:sharesBuildingWith (symmetric) | uko:PointOfInterest -> uko:PointOfInterest | places linked to the same building (gkg.place_building) |
| uko:insideMall | uko:PointOfInterest -> uko:ShoppingMall | place in the same building as a ShoppingMall place |
| uko:accessibleBy | uko:Building -> uko:RoadInfrastructure | building to nearest street segment within 30 m |
| uko:frontageOn | uko:Building -> uko:Road | building to nearest street segment within 30 m |
| uko:providesAccessTo | uko:Road -> uko:GeographicFeature | street segment to each building whose nearest street it is (within 30 m) |
| uko:servesAsMainAccess | uko:Road -> uko:GeographicFeature | nearest street segment to each place (no address field loaded; decision B3 fallback) |
| uko:accessibleByBikeLane | uko:Building -> uko:Cycleway | building to nearest cycleway edge within 50 m |
| uko:accessibleBySidewalk | uko:Building -> uko:Sidewalk | building to nearest sidewalk edge within 50 m |
| uko:hasParking | uko:Building -> uko:ParkingFacility | building to parking facilities within 100 m |
| uko:partOfChain | uko:PointOfInterest -> uko:Organization | branded place to its brand organization |
| uko:operatedByOrg | uko:PointOfInterest -> uko:Organization | branded place to its brand organization (decision B4) |

### Sidewalks

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:alongsideOf | uko:Sidewalk -> uko:Road | sidewalk edge to nearest road segment within 25 m at most 20 degrees apart |
| uko:onNorthSideOf | uko:Sidewalk -> uko:Road | alongsideOf pair, sidewalk north of the road line |
| uko:onSouthSideOf | uko:Sidewalk -> uko:Road | alongsideOf pair, sidewalk south of the road line |
| uko:onEastSideOf | uko:Sidewalk -> uko:Road | alongsideOf pair, sidewalk east of the road line |
| uko:onWestSideOf | uko:Sidewalk -> uko:Road | alongsideOf pair, sidewalk west of the road line |

### Transit and shared mobility

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:servesStop | uko:TransitRoute -> uko:TransitStop | route to each stop it serves on the reference service day |
| uko:parentStation | uko:TransitStop -> uko:TransitStation | GTFS parent_station |
| uko:hasTrip | uko:TransitRoute -> uko:TransitTrip | route to its trips on the reference service day |
| uko:hasStopTime | uko:TransitTrip -> uko:StopTime | trip to its stop times |
| uko:atStop | uko:StopTime -> uko:TransitStop | stop time to its stop |
| uko:hasServiceCalendar | uko:TransitTrip -> uko:ServiceCalendar | trip to its GTFS service_id calendar |
| uko:hasServiceException | uko:ServiceCalendar -> uko:ServiceException | calendar to its calendar_dates.txt exceptions |
| uko:gtfsOperatedBy | uko:TransitRoute -> uko:TransitAgency | route to agency |
| uko:hasTransferTo | uko:TransitStop -> uko:TransitStop | transfers.txt pairs; feeds without transfers.txt: stops of different routes within 200 m |
| uko:fareProductOfAgency | uko:FareProduct -> uko:TransitAgency | GTFS Fares v1 fare_attributes row to its agency |
| uko:hasServiceArea | uko:TransitRoute -> uko:ServiceArea | route to the area within 400 m of its stops |
| uko:anchorStation | uko:TransitOrientedDevelopment or uko:PriorityDevelopmentArea -> uko:TransitStation | Priority Development Area to each transit station inside it |
| uko:connectsToTransit | uko:Road -> uko:TransitStop | road segment to the stop it serves (nearest walkable segment within 50 m) |
| uko:nearTransitStop | uko:Building -> uko:TransitStop | building within 400 m of a stop (value_m) |
| uko:nearestTransitStop | uko:GeographicFeature -> uko:TransitStop | place to its nearest boardable stop (value_m) |
| uko:hasTransitAccess | uko:Building -> uko:TransitStop | building centroid inside a stop's 800 m walkshed |
| uko:walkshedOrigin | uko:WalkShedArea -> uko:GeographicFeature | walkshed to its stop |
| uko:operatedBySystem | uko:SharedMobilityStation -> uko:SharedMobilitySystem | Bay Wheels station to the Bay Wheels system |

### Common spaces

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:adjacentToCommonSpace | uko:Building -> uko:CommonSpace | building within 5 m of a park or other common space polygon |
| uko:bordersCommonSpace | uko:Road -> uko:CommonSpace | road segment within 15 m of a common space boundary |
| uko:bordersNaturalArea | uko:CommonSpace -> uko:NaturalArea | common space polygon touching or within 5 m of a natural area polygon |
| uko:crossesThroughCommonSpace | uko:Road -> uko:CommonSpace | road segment crossing a common space polygon |
| uko:hasTrailConnection | uko:CommonSpace -> uko:Trail | common space to path edges (uko:Trail) touching or inside it |
| uko:pathThroughCommonSpace | uko:PedestrianInfrastructure or uko:PedestrianNetworkEdge or uko:Trail or uko:Cycleway -> uko:CommonSpace | pedestrian edge intersecting a common space polygon |
| uko:providesRecreationFor | uko:CommonSpace -> uko:ConceptualArea | common space to each census tract within an 800 m walk |

### Freight

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:hasTruckRoutingConstraint | uko:RoadSegment or uko:IntersectionNode -> uko:TruckRoutingConstraint | segment to its truck restriction (Overture access_restrictions, mode hgv) |
| uko:constrainsSegment | uko:OperationalRoutingConstraint or uko:TruckRoutingConstraint -> uko:RoadSegment | truck restriction to the segment it applies to |
| uko:hasTruckParkingFacility | uko:RoadSegment -> uko:TruckParkingFacility | segment within 500 m of a truck parking facility |

### Safety (crash-derived: never an input to crash prediction)

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:inHighInjuryNetwork (crash-derived) | uko:SpatialEntity -> uko:HighInjuryNetwork | road segment with at least half its length within 10 m of the SF 2024 HIN |
| uko:hinSegmentOf (crash-derived) | uko:HighInjuryNetwork -> uko:Road | SF 2024 HIN feature to each road segment it overlaps |
| uko:hasIntersectionRiskProfile (crash-derived) | uko:IntersectionNode -> uko:IntersectionRiskProfile | intersection node with attached injury crashes to its risk profile |
| reo:atIntersectionNode (crash-derived) | reo:ReportedTrafficIncident -> uko:IntersectionNode | crash record to its attached intersection node (50 m) |
| reo:onRoadSegment (crash-derived) | reo:ReportedTrafficIncident -> uko:RoadSegment | crash record to the road segment stage 4 attached it to (value_m = snap distance) |
| reo:hasKABCOSeverity (crash-derived) | reo:HistoricalIncidentRecord -> reo:KABCOSeverity | crash record to its KABCO level through the SWITRS COLLISION_SEVERITY mapping rows (1 K, 2 A, 3 B, 4 C, 0 O) |
| reo:hasCollisionCausationFactor (crash-derived) | reo:HistoricalIncidentRecord -> reo:CollisionCausationFactor | crash record to its primary collision factor (exact SWITRS matches only) |
| reo:incidentCollisionType (crash-derived) | reo:HistoricalIncidentRecord -> reo:CollisionType | crash record to its collision type |
| reo:incidentLighting (crash-derived) | reo:HistoricalIncidentRecord -> reo:LightingCondition | crash record to its lighting condition |
| reo:incidentRoadSurface (crash-derived) | reo:HistoricalIncidentRecord -> reo:RoadSurfaceCondition | crash record to its road surface |
| reo:incidentWeatherCondition (crash-derived) | reo:HistoricalIncidentRecord -> reo:WeatherCondition | crash record to its weather (WEATHER_1) |

### Lineage and sources

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:derivedFrom | uko:GeographicFeature -> uko:GeographicFeature | URN lineage (gkg.urn_lineage) |
| uko:hasDataSource | owl:Thing -> uko:DataSource | entity to the data source release it came from |

### Measured values: place statistics (O4)

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:hasPlaceStatistic | uko:SpatialEntity -> uko:PlaceStatistic | area (tract, city, grid cell) to each of its place statistics |
| sosa:observedProperty |  ->  | place statistic to its variable (uko:PlaceVariable) |
| uko:valueSource | uko:MeasuredValue -> uko:DataSource | measured value to the data source release it comes from |
| sosa:usedProcedure |  ->  | measured value to its estimation procedure |
| uko:travelMode | uko:MeasuredValue -> uko:TravelMode | mode-specific statistic (commute share, jobs reachable) to its mode |

### Fingerprints (O5)

| Relation | Domain -> range | Rule |
|---|---|---|
| uko:fingerprintOf | uko:Fingerprint -> uko:SpatialEntity | fingerprint to the area it describes |
| uko:usesReferenceSet | uko:Fingerprint -> uko:ReferenceSet | fingerprint to the reference set that standardizes it |
| uko:hasReferenceMember | uko:ReferenceSet -> uko:SpatialEntity | reference set to each member area |
| uko:hasFactorValue | uko:Fingerprint -> uko:FactorValue | fingerprint to each of its factor values |
| uko:valueOfFactor | uko:FactorValue -> uko:FingerprintFactor | factor value to its fingerprint factor |
| uko:distanceFrom | uko:FingerprintDistance -> uko:Fingerprint | fingerprint distance to its first fingerprint (lower entity key) |
| uko:distanceTo | uko:FingerprintDistance -> uko:Fingerprint | fingerprint distance to its second fingerprint |
| uko:factorSetUsed | uko:FingerprintDistance -> uko:FingerprintFactor | fingerprint distance to each factor it uses |
