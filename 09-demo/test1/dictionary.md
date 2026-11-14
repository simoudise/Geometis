# Data dictionary

You answer questions using a PostgreSQL/PostGIS database, schema `gkg`. Geometries are EPSG:4326. Transform to
EPSG:3310 (California Albers, meters) for distances, lengths and areas.

## Areas
`gkg.geofence(geofence_id, name, members, core, extent)`. Two study areas: `us-ca-contra-costa-5` (five cities)
and `us-ca-san-francisco`. The city boundaries are rows named 'Antioch', 'Concord', 'Pittsburg', 'Pleasant Hill',
'Walnut Creek' and 'San Francisco city'; use `ST_Within(x.geom, (select core from gkg.geofence where name = ...))`
to restrict to a city. Every other table has a `geofence_id` column holding the study area; its `in_core` column
means inside the union of the city boundaries, not inside one city.

## Tables
- `road_segment`: one row per piece of road between two intersections (urn, name, road_classification, subclass,
  length_m, speed_limit_mph, speed_limit_source, grade, max_abs_grade, is_bridge, is_tunnel, from_node, to_node).
  Count a road as a street when road_classification is trunk, primary, secondary, tertiary, residential,
  unclassified or living_street and subclass is not 'link'. Trunk roads are state highways that run at grade
  through towns; people walk along and across them. Major roads (arterials): trunk, primary and secondary.
  Freeways: motorway only. Ramps: subclass 'link'.
- `intersection_node`: one row per road intersection (urn, degree = number of road legs, node_kind, elevation_m).
  Road segments meet intersections through road_segment.from_node and to_node, which hold intersection urns.
- `pedestrian_edge`: mapped walkways (edge_class footway, path, steps or cycleway; subclass sidewalk, crosswalk,
  cycle_crossing or empty).
- `place`: businesses and facilities (name, uko_class, basic_category, brand, operating_status). The column
  uko_class holds a cleaned-up category; useful values: GroceryStore, ConvenienceStore, Restaurant,
  FastFoodRestaurant, Bar, Cafe, CoffeeShop, EntertainmentVenue, Hotel, Clinic, HealthcareFacility, Hospital,
  DentalClinic, School, ElementarySchool, Preschool, EducationalFacility, OfficeBuilding, RetailEstablishment,
  Park, GasStation, Bank, Warehouse. basic_category holds the source's own category (e.g. ev_charging_station,
  storage_facility, b2b_transportation_and_storage_service, manufacturer, warehouse_club_store).
- `building`: building footprints (subtype, class, height, num_floors, area_m2); `place_building` links places
  to footprints.
- `census_tract`: Census tracts (geoid, population, households, zero_vehicle_share, median_household_income,
  households_below_35k, households_100k_plus, share_in_core). American Community Survey 5-year estimates, 2020-2024.
- `transit_stop`: stops and stations (name, uko_class BusStop / TransitStation / StationEntrance / TransitStop,
  location_type 1 = a station whose platforms and entrances point to it through parent_urn,
  departures_on_service_day, route_urns).
- `transit_route`: routes (short_name, long_name, route_type, uko_class, agency_urn, trips_on_service_day);
  `transit_agency` (name, feed_id). BART is the agency named 'Bay Area Rapid Transit'. Stops join agencies on
  feed_id.
- `transit_stop_time`: scheduled departures (stop_urn, route_urn, trip_id, departure_time).
- `walkshed_area`: for each stop, the area reachable within 800 m along the walkable network (origin_urn = stop
  urn, distance_threshold_m 800).
- `stop_road`: the road segment nearest to each stop.
- `tims_crash`: injury crashes from the state crash records (case_id, accident_year, collision_date,
  collision_time 'HHMM', severity 1 fatal, 2 severe injury, 3 other visible injury, 4 complaint of pain; killed,
  severe_injured, pedestrian, bicycle, motorcycle, truck flags, pcf = primary collision factor, lighting,
  primary_rd, secondary_rd, intersection).
- `crash_attachment`: the road segment each crash is matched to (case_id, segment_urn) and, for intersection
  crashes, the intersection (node_urn).
- `segment_crash_stats`: crash counts per road segment or intersection (urn, entity 'segment' or 'intersection',
  year_from, year_to in {2015-2025, 2019-2023, 2021-2025}, crashes, fatal, severe, ksi, pedestrian, bicycle,
  motorcycle). Segment counts leave out crashes matched to an intersection. KSI = killed or severely injured.

## Useful operations
- Inside a city, a tract or a walking area: ST_Within or ST_Intersects with the boundary polygon.
- Near something: ST_DWithin on EPSG:3310 geometries (meters).
- Connected roads: two segments share an intersection through from_node or to_node.
- Which routes serve a stop: route_urns, or transit_stop_time.
- A place is within walking reach of a stop if it lies inside the stop's walkshed_area polygon.

## Limits of the data (state the ones that affect your answer)
1. Sidewalks and crosswalks come from OpenStreetMap and are mapped sparsely in the Contra Costa cities (about 20
   to 35 percent of street segments have a sidewalk within 20 m, against 60 to 75 percent in San Francisco).
   A missing sidewalk in the data does not mean no sidewalk exists.
2. Speed limits: speed_limit_source 'posted' is observed; 'statutory' (25 mph residential) and 'class_median'
   are estimates. Say which you used.
3. The data has no lane counts.
4. The data has no traffic volumes, so crash counts are not crash rates. Never call a count a risk rate.
5. Crashes are injury crashes only. 2026 is a partial year; use complete years.
6. Transit schedules describe one weekday around April 2024; County Connection and Tri Delta Transit use the
   nearest available schedules (January and August 2024).
7. Place categories come from Overture Maps and a cleanup step; about 13 percent of places have no cleaned-up
   category. Place counts are not jobs or visits.
8. Census values are survey estimates with margins of error; tract values apply to the whole tract.
9. The data has no traffic signals or crossing controls.
