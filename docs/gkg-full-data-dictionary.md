# GKG full build: data dictionary for the new relations

Release: GKG full, built November 20, 2026 and revised November 22 on the Mac mini (database `geometis`, schema `gkg`), checked against UKO 15.8.0, REO 1.8.0 and MLO 1.8.0. The method is in `docs/gkg-full-methodology.md`. Code: `07-gkg-builder/relations/build.py`; checks: `relations/validate.py`.

## Tables

| Table | One row is | Key columns |
|---|---|---|
| `gkg.entity` | one entity in one geofence | `eid` (integer key), `urn`, `geofence_id`, `uko_class`, `src` (source table or `aux:<kind>`) |
| `gkg.entity_type` | an extra asserted type of an entity | `eid`, `uko_class`, `rule` |
| `gkg.aux_entity` | an entity that the earlier stages did not store (districts, blocks, parks, organizations, trips and others) | `geofence_id`, `urn`, `uko_class`, `kind`, `name`, `props`, `geom` |
| `gkg.relation_type` | one ontology property | `rid`, `curie`, `domain_classes`, `range_classes`, `crash_derived`, `is_symmetric`, `inverse_curie`, `method` |
| `gkg.provenance` | one way of producing edges of one relation | `pid`, `rid`, `source`, `method`, `code_version`, `ontology_version`, `crash_derived` |
| `gkg.edge` | one edge | `rid`, `subj`, `obj` (entity keys), `pid`, `value_m` (meters, where the relation has a distance) |
| `gkg.distance_measurement` | one uko:DistanceMeasurement | `subj`, `target`, `straight_m`, `walk_m`, `measured_to` (`point` or `boundary`), `inside_target`, `pid` |
| `gkg.edge_rejected` | edges removed because the subject or object failed the property's domain or range | `rid`, `reason`, `n`, example classes |
| `gkg.measured_value` | one measured value (place statistic or fingerprint factor value): number, unit, margin of error and its confidence level, period, procedure, source table, source, travel mode and threshold, factor component, formula version, standardized value | `eid` (the value's entity), `kind`, `feature_eid`, `variable` |
| `gkg.fingerprint_distance` | one distance between two tract fingerprints | `eid`, `from_fp`, `to_fp`, `value`, `metric`, `weights_version`, `computed_on` |
| `gkg.census_block_2020`, `gkg.lodes_wac` | public block-level inputs (2020 block populations and internal points; LODES jobs by block) | `geoid` |
| `gkg.download_manifest` | one downloaded file: URL, path, time, size, SHA-256 | `url` |
| `gkg.class_closure` | a class and one of its named ancestors (UKO 15.8 + REO 1.8.0 + MLO 1.8.0 + SOSA) | `uko_class`, `ancestor` |

## Views

- `gkg.edge_named`: every edge with relation name, URNs, classes, geofence and provenance.
- `gkg.rel_very_near`: uko:veryNear, which is uko:near with `value_m` <= 50. The build stores no separate veryNear rows.
- `gkg.edge_for_crash_prediction`: the only edge source a crash-prediction export may use. It drops every relation marked `crash_derived` and every edge that touches a crash record, a risk profile or a High Injury Network entity.

## Conventions

- A symmetric relation is stored once, with subject key < object key. Read it in both directions.
- For a pair of inverse properties the build stores only the property listed below; the inverse (`inverse_curie`) follows from it.
- Metric work uses California Albers (EPSG:3310). Walking distances use the stored walking network: road segments except motorways, pedestrian edges and access points.
- An edge never joins entities of two geofences. The Contra Costa and San Francisco extents overlap, so the same Overture feature can appear in both geofences with two entity keys.
- New URNs use the `gkgfull` source tag (for example `urn:urban-kg:CityBlock:gkgfull:<hash>`). Public-data URNs keep the publisher's identifier where one exists (DataSF, MTC, TIGER, OpenStreetMap, GBFS).
- The enforce step removes edges whose subject or object is not an instance of the property's `rdfs:domain` or `rdfs:range` under the UKO 15.8 class hierarchy plus `gkg.entity_type`. Removed counts are in `gkg.edge_rejected`.

## Asserted extra types

None under UKO 15.7. The November 20 build asserted types per entity that UKO 15.6 lacked (schools and hospitals as vulnerable-population facilities, pedestrian network edges as pedestrian infrastructure, truck restrictions as operational constraints); UKO 15.7 states the first as axioms and widens the domains that needed the others.

## Road network topology

### uko:adjacentSegment

- Domain: uko:IntersectionNode; range: uko:RoadSegment.
- Rule: intersection node to each road segment that ends at it.

### uko:connectsTo

- Domain: uko:RoadInfrastructure; range: uko:RoadInfrastructure.
- Rule: segment A's end node is segment B's start node (digitized direction).

### uko:touches

- Domain: uko:GeographicFeature; range: uko:GeographicFeature. Symmetric.
- Rule: road segments that share an end node.

### uko:intersectsRoad

- Domain: uko:Road; range: uko:Road. Symmetric.
- Rule: segments of differently named roads that meet at a shared node.

### uko:crosses

- Domain: uko:LinearFeature; range: uko:GeographicFeature.
- Rule: road segment crosses rail segment; crosswalk to the road segment nearest its midpoint, within 7 m and 30 degrees of perpendicular.

### uko:crossesOver

- Domain: uko:Road; range: uko:Road. Inverse: uko:crossesUnder.
- Rule: road segments whose lines cross with no shared node; bridge over non-bridge, or non-tunnel over tunnel.

### uko:continuesAs

- Domain: uko:Road; range: uko:Road.
- Rule: named road changes name at a node with a turn of 30 degrees or less.

### uko:branchesFrom

- Domain: uko:Road; range: uko:Road. Inverse: uko:mergesInto.
- Rule: ramp (subclass link) whose start node lies on a non-ramp motorway, trunk or primary segment.

### uko:mergesInto

- Domain: uko:Road; range: uko:Road. Inverse: uko:branchesFrom.
- Rule: ramp whose end node lies on a non-ramp motorway, trunk or primary segment.

### uko:feedsInto

- Domain: uko:Road; range: uko:Road. Inverse: uko:distributesTo.
- Rule: lower-class road meets higher-class road at a shared node (class order of decision B3).

### uko:parallelTo

- Domain: uko:LinearFeature; range: uko:LinearFeature. Symmetric.
- Rule: segments within 30 m, 15 degrees, running together at least 50 m.

### uko:hasAccessPoint

- Domain: uko:RoadSegment or uko:IntersectionNode or uko:PedestrianNetworkNode or uko:PedestrianNetworkEdge; range: uko:AccessPoint.
- Rule: intersection node or pedestrian node to the access point joining them.

## Containment and administrative areas

### uko:within

- Domain: uko:GeographicFeature; range: uko:GeographicFeature. Inverse: uko:contains.
- Rule: building in city block; place in building (place_building).

### uko:withinCensusTract

- Domain: uko:GeographicFeature; range: uko:CensusTract.
- Rule: point (or midpoint, or building centroid) in tract.

### uko:hasJurisdiction

- Domain: uko:GeographicFeature; range: uko:AdministrativeArea.
- Rule: feature to its city (TIGER place), else its county.

### uko:inNeighborhood

- Domain: uko:GeographicFeature; range: uko:Neighborhood. Inverse: uko:containsFeature.
- Rule: feature in a San Francisco neighborhood (SF Find and Analysis Neighborhoods).

### uko:inSupervisorDistrict

- Domain: uko:SpatialEntity; range: uko:SupervisorDistrict.
- Rule: feature in a San Francisco supervisor district (2022).

### uko:overlaps

- Domain: uko:GeographicFeature; range: uko:GeographicFeature. Symmetric.
- Rule: district polygon overlaps census tract polygon (shared area >= 1 percent).

### uko:adjacentTo

- Domain: uko:GeographicFeature; range: uko:GeographicFeature. Symmetric.
- Rule: census tracts whose boundaries share a line.

### uko:adjacentNeighborhood

- Domain: uko:Neighborhood; range: uko:Neighborhood. Symmetric.
- Rule: neighborhoods of the same scheme sharing a boundary.

## Proximity and distance

### uko:near

- Domain: uko:GeographicFeature; range: uko:GeographicFeature. Symmetric.
- Rule: places, stops, intersections within 200 m (value_m = meters); veryNear is value_m <= 50.

### uko:hasDistanceMeasurement

- Domain: uko:SpatialEntity; range: uko:DistanceMeasurement.
- Rule: stored in gkg.distance_measurement, not gkg.edge: place, stop or intersection to landmark or district within 2 km.

### uko:hasVulnerablePopulationNearby

- Domain: uko:SpatialEntity; range: uko:VulnerablePopulationFacility.
- Rule: place, stop or intersection within 200 m of a school, senior or care facility, or hospital.

### uko:nearVulnerablePopulation

- Domain: uko:Road; range: uko:VulnerablePopulationFacility.
- Rule: road segment within 200 m of such a facility.

## Buildings, places and access

### uko:sharesWallWith

- Domain: uko:Building; range: uko:Building. Symmetric.
- Rule: buildings sharing at least 1 m of boundary.

### uko:sharesBuildingWith

- Domain: uko:PointOfInterest; range: uko:PointOfInterest. Symmetric.
- Rule: places linked to the same building (gkg.place_building).

### uko:insideMall

- Domain: uko:PointOfInterest; range: uko:ShoppingMall.
- Rule: place in the same building as a ShoppingMall place.

### uko:accessibleBy

- Domain: uko:Building; range: uko:RoadInfrastructure.
- Rule: building to nearest street segment within 30 m.

### uko:frontageOn

- Domain: uko:Building; range: uko:Road.
- Rule: building to nearest street segment within 30 m.

### uko:providesAccessTo

- Domain: uko:Road; range: uko:GeographicFeature.
- Rule: street segment to each building whose nearest street it is (within 30 m).

### uko:servesAsMainAccess

- Domain: uko:Road; range: uko:GeographicFeature.
- Rule: nearest street segment to each place (no address field loaded; decision B3 fallback).

### uko:accessibleByBikeLane

- Domain: uko:Building; range: uko:Cycleway.
- Rule: building to nearest cycleway edge within 50 m.

### uko:accessibleBySidewalk

- Domain: uko:Building; range: uko:Sidewalk.
- Rule: building to nearest sidewalk edge within 50 m.

### uko:hasParking

- Domain: uko:Building; range: uko:ParkingFacility.
- Rule: building to parking facilities within 100 m.

### uko:partOfChain

- Domain: uko:PointOfInterest; range: uko:Organization.
- Rule: branded place to its brand organization.

### uko:operatedByOrg

- Domain: uko:PointOfInterest; range: uko:Organization.
- Rule: branded place to its brand organization (decision B4).

## Sidewalks

### uko:alongsideOf

- Domain: uko:Sidewalk; range: uko:Road.
- Rule: sidewalk edge to nearest road segment within 25 m at most 20 degrees apart.

### uko:onNorthSideOf

- Domain: uko:Sidewalk; range: uko:Road.
- Rule: alongsideOf pair, sidewalk north of the road line.

### uko:onSouthSideOf

- Domain: uko:Sidewalk; range: uko:Road.
- Rule: alongsideOf pair, sidewalk south of the road line.

### uko:onEastSideOf

- Domain: uko:Sidewalk; range: uko:Road.
- Rule: alongsideOf pair, sidewalk east of the road line.

### uko:onWestSideOf

- Domain: uko:Sidewalk; range: uko:Road.
- Rule: alongsideOf pair, sidewalk west of the road line.

## Transit and shared mobility

### uko:servesStop

- Domain: uko:TransitRoute; range: uko:TransitStop.
- Rule: route to each stop it serves on the reference service day.

### uko:parentStation

- Domain: uko:TransitStop; range: uko:TransitStation. Inverse: uko:hasChildStop.
- Rule: GTFS parent_station.

### uko:hasTrip

- Domain: uko:TransitRoute; range: uko:TransitTrip. Inverse: uko:belongsToRoute.
- Rule: route to its trips on the reference service day.

### uko:hasStopTime

- Domain: uko:TransitTrip; range: uko:StopTime.
- Rule: trip to its stop times.

### uko:atStop

- Domain: uko:StopTime; range: uko:TransitStop.
- Rule: stop time to its stop.

### uko:hasServiceCalendar

- Domain: uko:TransitTrip; range: uko:ServiceCalendar.
- Rule: trip to its GTFS service_id calendar.

### uko:hasServiceException

- Domain: uko:ServiceCalendar; range: uko:ServiceException.
- Rule: calendar to its calendar_dates.txt exceptions.

### uko:gtfsOperatedBy

- Domain: uko:TransitRoute; range: uko:TransitAgency. Inverse: uko:operatesRoute.
- Rule: route to agency.

### uko:hasTransferTo

- Domain: uko:TransitStop; range: uko:TransitStop.
- Rule: transfers.txt pairs; feeds without transfers.txt: stops of different routes within 200 m.

### uko:fareProductOfAgency

- Domain: uko:FareProduct; range: uko:TransitAgency.
- Rule: GTFS Fares v1 fare_attributes row to its agency.

### uko:hasServiceArea

- Domain: uko:TransitRoute; range: uko:ServiceArea.
- Rule: route to the area within 400 m of its stops.

### uko:anchorStation

- Domain: uko:TransitOrientedDevelopment or uko:PriorityDevelopmentArea; range: uko:TransitStation.
- Rule: Priority Development Area to each transit station inside it.

### uko:connectsToTransit

- Domain: uko:Road; range: uko:TransitStop.
- Rule: road segment to the stop it serves (nearest walkable segment within 50 m).

### uko:nearTransitStop

- Domain: uko:Building; range: uko:TransitStop.
- Rule: building within 400 m of a stop (value_m).

### uko:nearestTransitStop

- Domain: uko:GeographicFeature; range: uko:TransitStop.
- Rule: place to its nearest boardable stop (value_m).

### uko:hasTransitAccess

- Domain: uko:Building; range: uko:TransitStop.
- Rule: building centroid inside a stop's 800 m walkshed.

### uko:walkshedOrigin

- Domain: uko:WalkShedArea; range: uko:GeographicFeature.
- Rule: walkshed to its stop.

### uko:operatedBySystem

- Domain: uko:SharedMobilityStation; range: uko:SharedMobilitySystem.
- Rule: Bay Wheels station to the Bay Wheels system.

## Common spaces

### uko:adjacentToCommonSpace

- Domain: uko:Building; range: uko:CommonSpace.
- Rule: building within 5 m of a park or other common space polygon.

### uko:bordersCommonSpace

- Domain: uko:Road; range: uko:CommonSpace.
- Rule: road segment within 15 m of a common space boundary.

### uko:bordersNaturalArea

- Domain: uko:CommonSpace; range: uko:NaturalArea.
- Rule: common space polygon touching or within 5 m of a natural area polygon.

### uko:crossesThroughCommonSpace

- Domain: uko:Road; range: uko:CommonSpace.
- Rule: road segment crossing a common space polygon.

### uko:hasTrailConnection

- Domain: uko:CommonSpace; range: uko:Trail.
- Rule: common space to path edges (uko:Trail) touching or inside it.

### uko:pathThroughCommonSpace

- Domain: uko:PedestrianInfrastructure or uko:PedestrianNetworkEdge or uko:Trail or uko:Cycleway; range: uko:CommonSpace.
- Rule: pedestrian edge intersecting a common space polygon.

### uko:providesRecreationFor

- Domain: uko:CommonSpace; range: uko:ConceptualArea.
- Rule: common space to each census tract within an 800 m walk.

## Freight

### uko:hasTruckRoutingConstraint

- Domain: uko:RoadSegment or uko:IntersectionNode; range: uko:TruckRoutingConstraint.
- Rule: segment to its truck restriction (Overture access_restrictions, mode hgv).

### uko:constrainsSegment

- Domain: uko:OperationalRoutingConstraint or uko:TruckRoutingConstraint; range: uko:RoadSegment.
- Rule: truck restriction to the segment it applies to.

### uko:hasTruckParkingFacility

- Domain: uko:RoadSegment; range: uko:TruckParkingFacility.
- Rule: segment within 500 m of a truck parking facility.

## Safety (crash-derived: never an input to crash prediction)

### uko:inHighInjuryNetwork

- Domain: uko:SpatialEntity; range: uko:HighInjuryNetwork. **Crash-derived.**
- Rule: road segment with at least half its length within 10 m of the SF 2024 HIN.

### uko:hinSegmentOf

- Domain: uko:HighInjuryNetwork; range: uko:Road. Inverse: uko:overlapsHIN. **Crash-derived.**
- Rule: SF 2024 HIN feature to each road segment it overlaps.

### uko:hasIntersectionRiskProfile

- Domain: uko:IntersectionNode; range: uko:IntersectionRiskProfile. **Crash-derived.**
- Rule: intersection node with attached injury crashes to its risk profile.

### reo:atIntersectionNode

- Domain: reo:ReportedTrafficIncident; range: uko:IntersectionNode. **Crash-derived.**
- Rule: crash record to its attached intersection node (50 m).

### reo:onRoadSegment

- Domain: reo:ReportedTrafficIncident; range: uko:RoadSegment. **Crash-derived.**
- Rule: crash record to the road segment stage 4 attached it to (value_m = snap distance).

### reo:hasKABCOSeverity

- Domain: reo:HistoricalIncidentRecord; range: reo:KABCOSeverity. **Crash-derived.**
- Rule: crash record to its KABCO level through the SWITRS COLLISION_SEVERITY mapping rows (1 K, 2 A, 3 B, 4 C, 0 O).

### reo:hasCollisionCausationFactor

- Domain: reo:HistoricalIncidentRecord; range: reo:CollisionCausationFactor. **Crash-derived.**
- Rule: crash record to its primary collision factor (exact SWITRS matches only).

### reo:incidentCollisionType

- Domain: reo:HistoricalIncidentRecord; range: reo:CollisionType. **Crash-derived.**
- Rule: crash record to its collision type.

### reo:incidentLighting

- Domain: reo:HistoricalIncidentRecord; range: reo:LightingCondition. **Crash-derived.**
- Rule: crash record to its lighting condition.

### reo:incidentRoadSurface

- Domain: reo:HistoricalIncidentRecord; range: reo:RoadSurfaceCondition. **Crash-derived.**
- Rule: crash record to its road surface.

### reo:incidentWeatherCondition

- Domain: reo:HistoricalIncidentRecord; range: reo:WeatherCondition. **Crash-derived.**
- Rule: crash record to its weather (WEATHER_1).

## Lineage and sources

### uko:derivedFrom

- Domain: uko:GeographicFeature; range: uko:GeographicFeature.
- Rule: URN lineage (gkg.urn_lineage).

### uko:hasDataSource

- Domain: owl:Thing; range: uko:DataSource.
- Rule: entity to the data source release it came from.

## Measured values: place statistics (O4)

### uko:hasPlaceStatistic

- Domain: uko:SpatialEntity; range: uko:PlaceStatistic. Inverse: uko:statisticOf.
- Rule: area (tract, city, grid cell) to each of its place statistics.

### sosa:observedProperty

- Domain: (none); range: (none).
- Rule: place statistic to its variable (uko:PlaceVariable).

### uko:valueSource

- Domain: uko:MeasuredValue; range: uko:DataSource.
- Rule: measured value to the data source release it comes from.

### sosa:usedProcedure

- Domain: (none); range: (none).
- Rule: measured value to its estimation procedure.

### uko:travelMode

- Domain: uko:MeasuredValue; range: uko:TravelMode.
- Rule: mode-specific statistic (commute share, jobs reachable) to its mode.

## Fingerprints (O5)

### uko:fingerprintOf

- Domain: uko:Fingerprint; range: uko:SpatialEntity.
- Rule: fingerprint to the area it describes.

### uko:usesReferenceSet

- Domain: uko:Fingerprint; range: uko:ReferenceSet.
- Rule: fingerprint to the reference set that standardizes it.

### uko:hasReferenceMember

- Domain: uko:ReferenceSet; range: uko:SpatialEntity.
- Rule: reference set to each member area.

### uko:hasFactorValue

- Domain: uko:Fingerprint; range: uko:FactorValue.
- Rule: fingerprint to each of its factor values.

### uko:valueOfFactor

- Domain: uko:FactorValue; range: uko:FingerprintFactor.
- Rule: factor value to its fingerprint factor.

### uko:distanceFrom

- Domain: uko:FingerprintDistance; range: uko:Fingerprint.
- Rule: fingerprint distance to its first fingerprint (lower entity key).

### uko:distanceTo

- Domain: uko:FingerprintDistance; range: uko:Fingerprint.
- Rule: fingerprint distance to its second fingerprint.

### uko:factorSetUsed

- Domain: uko:FingerprintDistance; range: uko:FingerprintFactor.
- Rule: fingerprint distance to each factor it uses.

## Not built, and why

- uko:veryNear: stored as uko:near with `value_m` <= 50 (decision 3); read `gkg.rel_very_near`.
- uko:onSameBlock: computed at query time from uko:within building -> uko:CityBlock (decision 4).
- uko:hasStreetAddress and address-based uko:servesAsMainAccess: the place files the builder loaded carry no address fields. servesAsMainAccess uses the nearest street instead.
- uko:hasAccessToCommonSpace: no distance rule was approved.
- uko:servesNeighborhood: needs a rule (which stops or routes serve which neighborhood).
- uko:servesVehicleType: the static Bay Wheels GBFS files list vehicle types per system, not per station.
- North, south, east and west relations between features (decision B2); acrossFrom, nearbyLandmark, segmentBetween, from/toCrossStreet and the commercial competition relations (skipped by decision).
- uko:derivedFrom: the relation is wired to `gkg.urn_lineage`, which is empty because the build has used one Overture release.
