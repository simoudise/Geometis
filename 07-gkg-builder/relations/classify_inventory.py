# Step 1 inventory: one row per object property in the five ontologies.
# Columns added to props.csv: family, status, source, method, missing, crash, stored.
import csv, collections, json

S, SP, C, CR, DL, LK, TR, NG, LV, DEP = ("STORED", "STORED-PARTIAL", "COMPUTABLE", "COMPUTABLE-NEEDS-RULE",
    "NEEDS-PUBLIC-DOWNLOAD", "NEEDS-DATA-WE-LACK", "EXCLUDED-TRIP-DATA", "NOT-A-GEOSPATIAL-RELATION",
    "NEEDS-LIVE-FEED", "DEPRECATED")

SEG = "Overture 2026-10-21.0 segments/connectors (gkg.road_segment, gkg.intersection_node)"
PED = "Overture pedestrian layer (gkg.pedestrian_edge, gkg.pedestrian_node, gkg.access_point)"
BLD = "Overture buildings (gkg.building)"
PLC = "Overture places (gkg.place; raw place.parquet for addresses and brand)"
OSM = "OpenStreetMap norcal.osm.pbf on the Mac mini (file of 2026-10-21; not yet loaded; read with GDAL's OSM driver)"
GTFS = "GTFS feeds on the Mac mini (25 feeds in gkg.transit_*)"
TR_ = "Census ACS/TIGER (gkg.census_tract; TIGER 2024 place polygons on disk)"
TIMS = "TIMS crash records (gkg.tims_crash, gkg.crash_attachment)"
TRIP = "client trip tables (Tier 3)"

U = {}
def u(p, fam, st, src="", meth="", miss="", crash="", stored=""):
    U["uko:" + p] = dict(family=fam, status=st, source=src, method=meth, missing=miss, crash=crash, stored=stored)

F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11 = ("Spatial and topological", "Road network and lanes", "Directional",
    "Transit and shared mobility", "Access", "Commercial and business", "Safety, derived from crash or injury data",
    "Safety, other", "Freight and routing constraints", "Provenance, metadata and analysis", "Common space and parks")

# ---- spatial and topological
u("within", F1, SP, SEG + "; " + TR_, "ST_Contains in EPSG:3310 for chosen (feature, area) type pairs",
  stored="view gkg.segment_within_tract (segment midpoint in tract), labeled uko:within; the specific property is withinCensusTract")
u("contains", F1, C, "as uko:within", "inverse of uko:within; store one direction and derive the other")
u("withinCensusTract", F1, SP, "every layer; " + TR_, "point or centroid containment (UKO's comment: centroid for linear features)",
  stored="segment only (view gkg.segment_within_tract, under the label uko:within); place, stop and node to tract are computed only inside 09-demo/test2/export.py")
u("intersects", F1, SP, SEG + "; " + PED + "; rail", "ST_Intersects for chosen layer pairs",
  stored="view gkg.seg_intersects (segment to end node) carries this label; that pair is uko:adjacentSegment (fixed on branch gkg-full)")
u("touches", F1, SP, SEG + "; " + BLD, "segments sharing an end node (the current gkg.seg_adjacent view, relabeled); polygons by ST_Touches",
  stored="gkg.seg_adjacent holds segment pairs that touch; it was labeled uko:adjacentSegment (fixed on branch gkg-full)")
u("overlaps", F1, C, TR_ + "; " + BLD + "; " + OSM, "ST_Overlaps for polygon pairs (tract, park, neighborhood, building)")
u("adjacentTo", F1, C, TR_ + "; " + BLD, "polygons sharing a boundary (ST_Touches or ST_Intersects of boundaries within 0.5 m)")
u("near", F1, CR, "any two layers", "pairs within a distance; UKO gives no distance for near", miss="distance threshold and type pairs (decision)")
u("veryNear", F1, C, "any two layers", "pairs within 50 m (UKO comment: ~50 m) for chosen type pairs", miss="type pairs (decision); SF has 78,789 places, so all-pairs is large")
u("acrossFrom", F1, CR, SEG + "; " + BLD + "; " + PLC, "two features whose connecting line crosses exactly one road segment", miss="definition (decision)")
u("crosses", F1, C, SEG + "; " + PED + "; rail; " + TR_, "ST_Crosses: road over rail, crosswalk across road, road across tract boundary")
u("crossesOver", F1, C, SEG + " (is_bridge, level_rules) and " + OSM + " (layer tag)", "segments whose lines cross with no shared node, ordered by bridge flag or level")
u("crossesUnder", F1, C, "as uko:crossesOver", "inverse of crossesOver")
u("parallelTo", F1, CR, SEG + "; " + PED, "line pairs within a distance and angle tolerance", miss="distance and angle tolerance (decision)")
u("intersectsRoad", F1, C, SEG, "segments of different named roads that meet at a shared node or cross")
u("adjacentNeighborhood", F1, DL, "SF Analysis Neighborhoods (DataSF)", "polygon adjacency", miss="SF neighborhood polygons (public); Contra Costa has no official neighborhood polygons (only OSM place=neighbourhood points)")
u("containsFeature", F1, DL, "as inNeighborhood", "inverse of inNeighborhood", miss="neighborhood polygons")
u("inNeighborhood", F1, DL, "SF Analysis Neighborhoods (DataSF)", "point or centroid containment", miss="SF neighborhood polygons (public); none for Contra Costa")
u("inDistrict", F1, LK, "", "", miss="no source or definition for uko:District instances (functional or informal districts)")
u("overlapsDistrict", F1, LK, "", "", miss="no source for districts; needs neighborhoods too")
u("inSupervisorDistrict", F1, DL, "SF Supervisor Districts (DataSF)", "containment", miss="SF district polygons (public); Contra Costa city council districts are published per city, not on hand")
u("hasJurisdiction", F1, C, TR_ + " (TIGER place polygons); geofence county list", "containment in city polygon, else county")
u("onSameBlock", F1, C, BLD + "; " + SEG, "blocks as faces of the street network (ST_Polygonize); pairs of buildings on one face", miss="pairwise storage is large; a building-to-block membership is smaller")
u("sharesWallWith", F1, C, BLD, "building polygons whose boundaries share a length above a minimum (e.g. 1 m)")
u("sharesBuildingWith", F1, C, PLC + "; gkg.place_building", "pairs of places linked to one building",
  stored="gkg.place_building links place to building; the pairs are not stored")
u("insideMall", F1, C, PLC + "; " + BLD, "place point inside a building polygon that holds a place of class ShoppingMall")
# ---- road network and lanes
u("adjacentSegment", F2, S, SEG, "segment end nodes", stored="columns road_segment.from_node, to_node; view gkg.seg_intersects (segment to node) was labeled uko:intersects; UKO runs node to segment")
u("connectsTo", F2, S, SEG, "segment A's end node is segment B's start node", stored="view gkg.seg_connects_to (digitized direction; one-way rules not applied; Overture access_restrictions could add them)")
u("continuesAs", F2, CR, SEG, "a road whose name changes at a node where the line runs on with a small turn angle", miss="angle threshold (decision)")
u("branchesFrom", F2, C, SEG + " (subclass link, access_restrictions)", "ramp segment whose start node lies on a through road")
u("mergesInto", F2, C, SEG, "ramp segment whose end node lies on a through road")
u("feedsInto", F2, CR, SEG, "a lower-class road meeting a higher-class road", miss="class order and one-way rule (decision)")
u("distributesTo", F2, CR, SEG, "inverse of feedsInto")
u("connectsFromLane", F2, LK, "", "", miss="lane geometry and lane connectors (HD map); Overture has none; OSM has lane counts only")
u("connectsToLane", F2, LK, "", "", miss="lane geometry and lane connectors (HD map)")
u("eHorizonFeatureOf", F2, LK, "", "", miss="ADAS e-horizon map data")
u("nearbyLandmark", F2, CR, PLC + "; " + SEG, "prominent places within a distance of a decision point", miss="definition of decision point and landmark (decision)")
# ---- directional
for p in ["northOf", "southOf", "eastOf", "westOf"]:
    u(p, F3, CR, "any layer", "compare projected coordinates for pairs inside a scope", miss="scope (decision): all pairs is n squared; computing at query time is cheaper than storing")
for p in ["onNorthSideOf", "onSouthSideOf", "onEastSideOf", "onWestSideOf"]:
    u(p, F3, C, PED + " (subclass sidewalk); " + SEG, "side of the road line for each sidewalk paired by alongsideOf",
      miss="Contra Costa sidewalk mapping is sparse (6,438 sidewalk edges against 15,399 in SF)")
# ---- transit and shared mobility
u("servesStop", F4, S, GTFS, "route of a stop time at the stop", stored="column transit_stop.route_urns (stop to route; the inverse direction)")
u("parentStation", F4, S, GTFS, "stops.txt parent_station", stored="column transit_stop.parent_urn")
u("hasChildStop", F4, S, GTFS, "inverse of parentStation", stored="column transit_stop.parent_urn (inverse)")
u("atStop", F4, SP, GTFS, "stop_times.txt stop_id", stored="gkg.transit_stop_time.stop_urn; stop times have no URN, so no StopTime entity exists")
u("hasStopTime", F4, C, GTFS + " (trips.txt)", "trip to its stop times", miss="a trip table and stop-time URNs (builder change)")
u("hasTrip", F4, C, GTFS + " (trips.txt)", "route to trip", stored="trip_id text only in transit_stop_time")
u("belongsToRoute", F4, C, GTFS, "inverse of hasTrip", stored="route_urn and trip_id text in transit_stop_time")
u("hasServiceCalendar", F4, C, GTFS, "trips.txt service_id", stored="gkg.service_calendar exists; no trip link")
u("hasServiceException", F4, C, GTFS + " (calendar_dates.txt, in 24 of 25 feeds)", "calendar to its exception dates")
u("gtfsOperatedBy", F4, S, GTFS, "routes.txt agency_id", stored="column transit_route.agency_urn")
u("operatesRoute", F4, S, GTFS, "inverse of gtfsOperatedBy", stored="column transit_route.agency_urn (inverse)")
u("hasTransferTo", F4, C, GTFS + " (transfers.txt in 11 of 25 feeds)", "transfers.txt pairs; a walking-distance rule could fill the other feeds", miss="rule for feeds without transfers.txt (decision)")
u("pathwayFromStop", F4, LK, GTFS, "", miss="pathways.txt (no loaded feed has it)")
u("pathwayToStop", F4, LK, GTFS, "", miss="pathways.txt (no loaded feed has it)")
u("fareProductOfAgency", F4, CR, GTFS + " (fare_attributes.txt, Fares v1, in 23 feeds)", "fare_attributes row to agency", miss="UKO's FareProduct follows GTFS Fares v2 (fare_products.txt), which no loaded feed has; mapping v1 rows to it is a decision")
u("hasServiceArea", F4, CR, GTFS + " (shapes.txt)", "buffer of route shapes or stops", miss="buffer rule (decision)")
u("anchorStation", F4, DL, "MTC Priority Development Areas or TOD polygons", "station inside TOD polygon", miss="TOD area polygons (public, not on hand)")
u("connectsToTransit", F4, S, SEG + "; " + GTFS, "nearest non-motorway segment within 50 m of each stop", stored="table gkg.stop_road (stop, segment) with no declared direction; README item 4; UKO runs Road to TransitStop; fixed on branch gkg-full")
u("nearTransitStop", F4, CR, BLD + "; " + GTFS, "buildings within a distance of a stop", miss="distance (decision; UKO subproperty of near)")
u("nearestTransitStop", F4, C, PLC + "; " + GTFS, "nearest boardable stop to each place (straight line or walk network)")
u("hasTransitAccess", F4, C, BLD + "; gkg.walkshed_area", "building inside a stop's stored 800 m walkshed")
u("walkshedOrigin", F4, S, GTFS + "; " + PED, "network walkshed per stop", stored="column walkshed_area.origin_urn")
u("operatedBySystem", F4, DL, "GBFS feeds (Bay Wheels)", "station_information to system", miss="GBFS feeds (public, not on hand); Bay Wheels covers SF, not the five Contra Costa cities")
u("servesVehicleType", F4, DL, "GBFS vehicle_types", "", miss="GBFS feeds (public, not on hand)")
# ---- access
u("hasAccessPoint", F5, S, PED + "; " + SEG, "inter-layer access points", stored="table gkg.access_point (one row per access point with its intersection node and pedestrian node)")
u("accessibleBy", F5, CR, BLD + "; " + SEG, "nearest road segment to each building", miss="distance rule (decision)")
u("accessibleByBikeLane", F5, CR, BLD + "; " + SEG + " and " + OSM + " (cycleway tags)", "building near a cycleway or a road with a bike lane", miss="distance rule; Overture marks bike lanes only as separate cycleway segments")
u("accessibleBySidewalk", F5, CR, BLD + "; " + PED, "building near a sidewalk edge", miss="distance rule; sparse Contra Costa sidewalk mapping")
u("hasParking", F5, CR, OSM + " (amenity=parking); " + PLC, "building near or sharing a lot with a parking facility", miss="rule (decision)")
u("providesAccessTo", F5, CR, SEG, "road nearest to a feature", miss="rule (decision)")
u("servesAsMainAccess", F5, CR, SEG + "; " + PLC, "road the place's address names, else nearest", miss="rule (decision)")
u("servesAsEmergencyAccess", F5, LK, OSM, "", miss="emergency access designation (OSM emergency=* is sparse)")
u("dependsOn", F5, LK, "", "", miss="UKO gives no definition; nothing to compute")
u("requiresAccessTo", F5, LK, "", "", miss="UKO gives no definition")
u("frontageOn", F5, CR, BLD + "; " + SEG, "street segment facing the building within a distance", miss="distance rule (decision)")
u("hasStreetAddress", F5, C, PLC + " (addresses.street)", "match the place's street name to segment names within a distance", miss="Overture buildings carry no address; buildings get the link through gkg.place_building")
u("alongsideOf", F5, C, PED + " (subclass sidewalk); " + SEG, "sidewalk edge to the nearest roughly parallel road segment within 25 m", miss="sparse Contra Costa sidewalk mapping")
u("segmentBetween", F5, CR, PED + "; " + SEG, "sidewalk segment between two cross streets", miss="UKO's range is one road although the comment names two cross streets (ontology gap); rule (decision)")
# ---- common space and parks
u("adjacentToCommonSpace", F11, C, BLD + "; " + OSM + " (leisure=park and similar)", "building touching or within 5 m of a park polygon", miss="park polygons must first be loaded from OSM")
u("bordersCommonSpace", F11, C, SEG + "; " + OSM, "road within 15 m of a park boundary", miss="park polygons from OSM")
u("bordersNaturalArea", F11, C, OSM, "park polygon touching a natural area polygon (natural=wood, scrub, wetland)")
u("crossesThroughCommonSpace", F11, C, SEG + "; " + OSM, "ST_Crosses road and park polygon")
u("overlooksCommonSpace", F11, LK, BLD + " (height partly filled)", "", miss="line-of-sight definition and complete heights")
u("hasAccessToCommonSpace", F11, CR, BLD + "; " + PED + "; " + OSM, "park within a walking distance", miss="distance (decision)")
u("hasTrailConnection", F11, C, OSM + "; " + PED + " (path)", "trail line touching a park polygon", miss="UKO models Trail as a CommonSpace subclass (areal), while trails are lines (ontology gap)")
u("pathThroughCommonSpace", F11, C, PED + "; " + OSM, "pedestrian edge intersecting a park polygon")
u("providesRecreationFor", F11, CR, OSM + "; " + TR_, "park to tracts within a walking distance", miss="rule (decision)")
u("servesNeighborhood", F11, DL, OSM + "; SF neighborhoods", "park to neighborhood", miss="neighborhood polygons; rule")
# ---- commercial
u("competitiveWith", F6, CR, PLC, "same-category places within a distance", miss="category grouping and distance (decision)")
u("directCompetitor", F6, CR, PLC, "same basic_category within a distance", miss="distance (decision)")
u("complementaryTo", F6, CR, PLC, "category pairs from a stated table within a distance", miss="complementary category table (decision)")
u("synergisticWith", F6, CR, PLC, "subset of complementaryTo", miss="definition (decision)")
u("partOfChain", F6, C, PLC + " (brand names and Wikidata IDs)", "place to an Organization node per brand", miss="2,704 Contra Costa and 3,284 SF places carry a brand")
u("franchiseOf", F6, LK, PLC, "", miss="franchise versus company-owned status")
u("ownedBy", F6, LK, "", "", miss="property ownership (county assessor rolls; SF publishes parcels but not owner names)")
u("operatedByOrg", F6, CR, PLC + " (brand); " + OSM + " (operator tag)", "brand or operator to Organization", miss="rule for brand versus operator (decision)")
u("anchorTenant", F6, CR, PLC + "; " + BLD, "largest tenant or department-store category inside a shopping center", miss="rule (decision)")
u("characterizedBy", F6, LK, "", "", miss="FunctionalDistrict instances (no source)")
u("recognizedBy", F6, LK, "", "", miss="neighborhood recognition records")
# ---- safety
u("inHighInjuryNetwork", F7, CR, TIMS + "; SF Vision Zero HIN (SFDPH, public)", "segments above an injury-crash threshold, or the published SF HIN", miss="HIN rule for Contra Costa (decision); SF HIN file not on hand", crash="YES")
u("hinSegmentOf", F7, CR, "as inHighInjuryNetwork", "HIN segment to the road it overlays", crash="YES")
u("overlapsHIN", F7, CR, "as inHighInjuryNetwork", "inverse of hinSegmentOf", crash="YES")
u("hasIntersectionRiskProfile", F7, C, TIMS, "node to a profile of attached crash counts (gkg.crash_attachment node_urn)", crash="YES",
  stored="counts exist per segment in gkg.segment_crash_stats; no profile entity")
u("hasSafetyScore", F7, LK, "", "", miss="UKO defines SafetyScore only as a composite score; inputs unstated", crash="PROBABLE")
u("hasSafetyConcern", F8, LK, "", "", miss="SafetyConcern source undefined (could be 311 reports or crash data)", crash="UNKNOWN")
u("affectsRoad", F8, LK, "", "", miss="SafetyConcern instances", crash="UNKNOWN")
u("affectsIntersection", F8, LK, "", "", miss="SafetyConcern instances", crash="UNKNOWN")
u("hazardAhead", F8, LK, "", "", miss="SafetyConcern instances", crash="UNKNOWN")
u("hasVulnerablePopulationNearby", F8, CR, PLC + " (schools, senior and care facilities, hospitals by uko_class)", "facility within a buffer", miss="buffer distance (UKO: 'safety buffer distance', unstated)")
u("nearVulnerablePopulation", F8, CR, SEG + "; " + PLC, "road segment within a buffer of a facility", miss="buffer distance (decision)")
# ---- freight
u("constrainsSegment", F9, C, SEG + " (access_restrictions) and " + OSM + " (hgv, maxweight, maxheight)", "one constraint entity per restriction, linked to segments")
u("hasTruckRoutingConstraint", F9, C, "as constrainsSegment", "segment or node to its constraints")
u("hasTruckParkingFacility", F9, CR, OSM + " (amenity=parking with hgv tags; truck stops)", "facility within a distance of a segment", miss="sparse data; distance rule")
u("hasCargoTheftHotspot", F9, LK, "", "", miss="cargo theft hotspot zones (proprietary)")
# ---- provenance, metadata and analysis
u("derivedFrom", F10, S, "gkg.urn_lineage", "URN split and merge lineage", stored="table gkg.urn_lineage (old_urn, new_urn) and gkg.urn_registry")
u("extractedFrom", F10, C, "gkg.build.source_versions", "every entity to a DataSource node per source release")
u("hasDataSource", F10, C, "gkg.build.source_versions", "same as extractedFrom")
u("hasQualityAssessment", F10, LK, "", "", miss="DataQualityAssessment definition")
u("inferredBy", F10, LK, "", "", miss="the graph holds no LLM-inferred features")
u("derivedFromEntity", F10, NG, "", "analysis products, created by analyses, not by the base graph")
u("affectsEntitySet", F10, NG, "", "analysis layer")
u("appliesToInterventionType", F10, NG, "", "analysis layer")
u("hasMemberEntity", F10, NG, "", "analysis layer")
u("eHorizonFeatureOf", F2, LK, "", "", miss="ADAS e-horizon map data")

# ---- TKO, MLO, REO, FKO
def other(onto, p, dom, rng, dep):
    if dep: return dict(family="(deprecated)", status=DEP, source="", method="", missing="", crash="", stored="")
    n = p.split(":")[1]
    if onto == "MLO":
        return dict(family="Label system and access control", status=NG, source="", method="", missing="label registry and accounts, not geography", crash="", stored="")
    if onto == "FKO":
        return dict(family="Freight load", status=LK, source="", method="", missing="fleet dispatch and cargo records", crash="", stored="")
    if onto == "TKO":
        crash = "YES" if n in ("routeOnHIN", "segmentOnHIN") else ("PROBABLE" if n == "routeOnPSN" else "")
        if n in ("hasIdentifierResolutionPolicy", "scoreDimension", "dimensionRiskTier", "remediationTriggerDimension"):
            return dict(family="Fleet dispatch and risk", status=NG, source="", method="", missing="vocabulary or pipeline configuration", crash="", stored="")
        if n in ("hasAssignedRoute", "hasCargoProfile") or any(k in dom for k in ("Dispatch", "Driver", "RiskVector", "DimensionScore", "Remediation", "RouteOption", "ActiveTripSession", "HOS")):
            return dict(family="Fleet dispatch and risk", status=LK, source="", method="", missing="fleet dispatch, driver and route-risk records", crash=crash, stored="")
        if n in ("hasIdentifierResolutionPolicy", "scoreDimension", "dimensionRiskTier"):
            return dict(family="Fleet dispatch and risk", status=NG, source="", method="", missing="vocabulary or pipeline configuration", crash="", stored="")
        return dict(family="Trip and route", status=TR, source=TRIP, method="", missing="client trip data is excluded from this work", crash=crash, stored="")
    if onto == "REO":
        if "HistoricalIncidentRecord" in dom:
            m = {"atIntersectionNode": ("gkg.crash_attachment.node_urn (50 m snap)", S if False else SP),
                 "hasCollisionCausationFactor": ("tims_crash.pcf", C), "incidentCollisionType": ("tims_crash.collision_type", C),
                 "incidentLighting": ("tims_crash.lighting", C),
                 "incidentRoadSurface": ("raw CCRS files 2016-2025 on the Mac mini have RoadwaySurfaceCode; not loaded into tims_crash; the CCRS-to-TIMS case-id join is not checked", C),
                 "incidentWeatherCondition": ("raw CCRS files have Weather 1 and Weather 2; not loaded into tims_crash; the CCRS-to-TIMS case-id join is not checked", C)}[n]
            return dict(family="Historical crash record", status=m[1], source=TIMS, method="crash record to " + rng, missing=m[0] if n.startswith("incidentRoad") or n.startswith("incidentWeather") else "",
                        crash="YES", stored=m[0] if m[1] == SP else ("value stored as text in " + m[0] + "; no link to REO individuals" if m[0].startswith("tims_crash") else ""))
        if "FleetEventSensitivity" in dom or "EventFeedConnector" in dom or "ActiveRouteRisk" in dom or n == "triggeredAlertFor":
            return dict(family="Fleet alerting configuration", status=NG if "Fleet" in dom or "Feed" in dom else LK, source="", method="", missing="fleet configuration, not geography", crash="", stored="")
        return dict(family="Live events", status=LV, source="", method="", missing="live event feeds (511 incidents, closures, weather alerts); none on hand", crash="", stored="")

rows = []
for r in csv.DictReader(open("props.csv")):
    c = U.get(r["prop"]) if r["onto"] == "UKO" else other(r["onto"], r["prop"], r["domain"], r["range"], r["deprecated"])
    if c is None: raise SystemExit("unclassified " + r["prop"])
    rows.append({**r, **c})
assert len([r for r in rows if r["onto"] == "UKO"]) == 128
w = csv.DictWriter(open("inventory.csv", "w"), fieldnames=list(rows[0].keys()))
w.writeheader(); w.writerows(rows)
cnt = collections.Counter((r["onto"], r["family"], r["status"]) for r in rows)
json.dump({"|".join(k): v for k, v in cnt.items()}, open("counts.json", "w"), indent=0)
print(len(rows))
print(collections.Counter((r["onto"], r["status"]) for r in rows))
print(collections.Counter(r["crash"] for r in rows))
