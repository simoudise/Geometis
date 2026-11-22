# GKG full build: methodology

Version: November 22, 2026. This file is the complete method for the full geospatial knowledge graph (GKG) of San
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

The public downloads sit on the Mac mini in `~/geometis-data/gkg/public/2026-11-20/` with `MANIFEST.tsv` (URL, time,
size, SHA-256 and feature count of each file).

## 3. Ontologies

The build classifies and checks against the coordinated release of November 22, 2026: UKO 15.7.0, TKO 8.5.1,
MLO 1.7.2, REO 1.7.0 and FKO 1.2.3 (`01-ontologies/`). The generators `tools/make_uko_15_7.py` and
`tools/make_companions_2026_11_22.py` produce the files from the November 20 release, and each file's header carries
its change log. `tools/check_stack.py` reports zero problems (no undeclared term, every property with a domain and a
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

Section 13 lists every relation with its ontology domain and range and the rule the build applies. The rules carry
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

## 8. Crash-derived relations

Eleven relations come from crash data: uko:inHighInjuryNetwork, uko:hinSegmentOf, uko:hasIntersectionRiskProfile and
the eight REO crash relations, including reo:onRoadSegment and reo:hasKABCOSeverity (REO 1.7.0). Each is marked in `gkg.relation_type` and `gkg.provenance`. A crash-prediction model
reads edges only through the view `gkg.edge_for_crash_prediction`, which drops these relations and every edge that
touches a crash record, a risk profile or a High Injury Network entity. Crash records may serve as labels only.

## 9. Checks

`relations/validate.py` writes a JSON file of counts and checks to the Mac mini share (never to the repository):

- Invariants that must be zero: edges without provenance, provenance of another relation, edges to missing entities,
  symmetric edges out of order, self-loops, edges between geofences, duplicate edges, crash flags that disagree,
  near edges beyond 200 m, distance rows beyond 2 km.
- Domain and range: the enforce step removes every edge whose subject or object is not an instance of the property's
  domain or range under the class hierarchy (`gkg.class_closure`, built from UKO and REO); `gkg.edge_rejected` counts
  the removals. The check then re-tests a 1 percent sample.
- Geometry: 500 random near distances and 500 random building-in-tract links recomputed from the source geometry.
- Examples: five random edges for each of 13 relations, with names, for reading by eye.

## 10. Reproducing the build

On the Mac mini, from `~/Geometis-mini/work/07-gkg-builder`, through the job runner:
`~/geometis-venv/bin/python -m relations.build [STEP ...]`. The steps run in this order: schema, catalogue,
entities, aux, blocks, work, stored, containment, proximity, topology, roadnet, access, commons, other, tims,
transit, distances, recreation, retype, index, enforce, views, cleanup. Each step deletes and rewrites its own
output, so a failed step can run again alone; the entities step renumbers every key, so after it every later step
must run. The relation catalogue (`relations/catalogue/*.tsv`) comes from the ontology files:
`python -m relations.build --catalogue` in the cloud workspace, then copy the files to the Mac mini. Then run
`python -m relations.validate OUT.json` before the cleanup step, because the geometry checks read the work tables.

## 11. Not built

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
- uko:derivedFrom has no edges: `gkg.urn_lineage` is empty because one Overture release has been loaded.

## 12. Known limits

- Overture place classes are noisy (some places classed ShoppingMall are shops).
- Transit relations cover the reference service day only.
- uko:continuesAs follows the digitized direction of segments, so it misses name changes where two segments point
  against each other.
- Only one feed has transfers.txt, and its pairs fall outside the stored stops; all transfer edges come from the
  200 m rule.
- The architecture document (v19) lists uko:connectsToTransit from stop to road; the build follows UKO (road to
  stop). v19 has not been checked section by section against the build.

## 13. Relations
