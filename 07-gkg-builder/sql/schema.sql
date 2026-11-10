-- GeoMetis Knowledge Builder, Phase 1 schema (Stage 1: base road network and pedestrian multiplex).
-- Every table is keyed by geofence, so that overlapping geofences can share URNs without conflict.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS gkg;

CREATE TABLE IF NOT EXISTS gkg.geofence (
    geofence_id        text PRIMARY KEY,
    name               text NOT NULL,
    members            text[] NOT NULL,          -- 7-digit Census place GEOIDs
    graph_geofence_id  text NOT NULL,            -- the geofence whose graph this record uses
    boundary_source    text NOT NULL,
    core               geometry(MultiPolygon, 4326) NOT NULL,
    buffer_m           integer,
    buffer_test        jsonb,
    extent             geometry(MultiPolygon, 4326),
    states             text[],
    counties           text[],
    source_versions    jsonb NOT NULL,
    spec_version       text NOT NULL,
    created            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gkg.build (
    build_id         serial PRIMARY KEY,
    geofence_id      text NOT NULL,           -- no foreign key: builds stay on record when a geofence is rebuilt
    stage            text NOT NULL,
    builder_version  text NOT NULL,
    source_versions  jsonb NOT NULL,
    started          timestamptz NOT NULL DEFAULT now(),
    finished         timestamptz,
    status           text NOT NULL DEFAULT 'running',
    stats            jsonb
);

ALTER TABLE gkg.build DROP CONSTRAINT IF EXISTS build_geofence_id_fkey;

CREATE TABLE IF NOT EXISTS gkg.intersection_node (
    geofence_id   text NOT NULL,
    urn           text NOT NULL,
    connector_id  text NOT NULL,           -- Overture connector id (source reference, not the VID)
    degree        integer NOT NULL,        -- number of segment ends at the node
    node_kind     text NOT NULL,           -- intersection | through | dead_end
    in_core       boolean NOT NULL,
    geom          geometry(Point, 4326) NOT NULL,
    build_id      integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);

CREATE TABLE IF NOT EXISTS gkg.road_segment (
    geofence_id         text NOT NULL,
    urn                 text NOT NULL,
    gers_id             text NOT NULL,     -- Overture segment id, stored as a joinable attribute
    gers_from_frac      double precision NOT NULL,
    gers_to_frac        double precision NOT NULL,
    from_node           text NOT NULL,
    to_node             text NOT NULL,
    road_classification text,
    subclass            text,
    speed_limit_value   integer,
    speed_limit_unit    text,
    surface_type        text,
    name                text,
    length_m            double precision NOT NULL,
    in_core             boolean NOT NULL,
    access_restrictions jsonb,
    geom                geometry(LineString, 4326) NOT NULL,
    build_id            integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);

CREATE TABLE IF NOT EXISTS gkg.pedestrian_node (
    geofence_id   text NOT NULL,
    urn           text NOT NULL,
    connector_id  text NOT NULL,
    degree        integer NOT NULL,
    in_core       boolean NOT NULL,
    geom          geometry(Point, 4326) NOT NULL,
    build_id      integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);

CREATE TABLE IF NOT EXISTS gkg.pedestrian_edge (
    geofence_id         text NOT NULL,
    urn                 text NOT NULL,
    gers_id             text NOT NULL,
    gers_from_frac      double precision NOT NULL,
    gers_to_frac        double precision NOT NULL,
    from_node           text NOT NULL,
    to_node             text NOT NULL,
    edge_class          text,
    subclass            text,
    surface_type        text,
    length_m            double precision NOT NULL,
    in_core             boolean NOT NULL,
    geom                geometry(LineString, 4326) NOT NULL,
    build_id            integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);

-- Rail track pieces (Overture segments of subtype rail), so that rail trip legs can be conflated.
-- UKO 15.5 has rail routes but no class for rail track; the URN kind RailSegment is provisional.
CREATE TABLE IF NOT EXISTS gkg.rail_segment (
    geofence_id         text NOT NULL,
    urn                 text NOT NULL,
    gers_id             text NOT NULL,
    gers_from_frac      double precision NOT NULL,
    gers_to_frac        double precision NOT NULL,
    from_connector      text NOT NULL,
    to_connector        text NOT NULL,
    rail_class          text,
    name                text,
    length_m            double precision NOT NULL,
    in_core             boolean NOT NULL,
    geom                geometry(LineString, 4326) NOT NULL,
    build_id            integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);
CREATE INDEX IF NOT EXISTS rail_segment_geom ON gkg.rail_segment USING gist (geom);

-- An access point is an Overture connector shared by the vehicular and the pedestrian layer.
CREATE TABLE IF NOT EXISTS gkg.access_point (
    geofence_id          text NOT NULL,
    urn                  text NOT NULL,
    intersection_node    text NOT NULL,
    pedestrian_node      text NOT NULL,
    geom                 geometry(Point, 4326) NOT NULL,
    build_id             integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);

-- Versioned crosswalk from OpenStreetMap ways to segment URNs (v19 section 10.3.1).
-- Fractions are positions along the segment URN, from 0 to 1.
CREATE TABLE IF NOT EXISTS gkg.osm_crosswalk (
    geofence_id     text NOT NULL,
    layer           text NOT NULL,          -- vehicular | pedestrian
    segment_urn     text NOT NULL,
    osm_way_id      bigint NOT NULL,
    osm_version     integer,
    seg_from_frac   double precision NOT NULL,
    seg_to_frac     double precision NOT NULL,
    build_id        integer NOT NULL
);

CREATE INDEX IF NOT EXISTS road_segment_geom ON gkg.road_segment USING gist (geom);
CREATE INDEX IF NOT EXISTS intersection_node_geom ON gkg.intersection_node USING gist (geom);
CREATE INDEX IF NOT EXISTS pedestrian_edge_geom ON gkg.pedestrian_edge USING gist (geom);
CREATE INDEX IF NOT EXISTS osm_crosswalk_way ON gkg.osm_crosswalk (geofence_id, osm_way_id);
CREATE INDEX IF NOT EXISTS osm_crosswalk_seg ON gkg.osm_crosswalk (geofence_id, layer, segment_urn);
CREATE INDEX IF NOT EXISTS road_segment_nodes ON gkg.road_segment (geofence_id, from_node, to_node);

-- Edges are views over the segment table, so that they cost no disk.
-- uko:intersects: segment to each of its end nodes.
CREATE OR REPLACE VIEW gkg.seg_intersects AS
    SELECT geofence_id, urn AS segment_urn, from_node AS node_urn, 'start' AS position FROM gkg.road_segment
    UNION ALL
    SELECT geofence_id, urn, to_node, 'end' FROM gkg.road_segment;

-- uko:adjacentSegment: two segments that share an end node (symmetric).
CREATE OR REPLACE VIEW gkg.seg_adjacent AS
    SELECT a.geofence_id, a.segment_urn AS segment_a, b.segment_urn AS segment_b, a.node_urn AS via_node
    FROM gkg.seg_intersects a JOIN gkg.seg_intersects b
      ON a.geofence_id = b.geofence_id AND a.node_urn = b.node_urn AND a.segment_urn <> b.segment_urn;

-- uko:connectsTo: segment A ends where segment B starts, in digitized direction.
-- Turn restrictions and one-way rules are not applied yet (see README, open items).
CREATE OR REPLACE VIEW gkg.seg_connects_to AS
    SELECT a.geofence_id, a.urn AS from_segment, b.urn AS to_segment, a.to_node AS via_node
    FROM gkg.road_segment a JOIN gkg.road_segment b
      ON a.geofence_id = b.geofence_id AND a.to_node = b.from_node AND a.urn <> b.urn;

-- Stage 2: Census tracts, kept whole, with the share of each tract's area inside the core.
CREATE TABLE IF NOT EXISTS gkg.census_tract (
    geofence_id              text NOT NULL,
    urn                      text NOT NULL,
    geoid                    text NOT NULL,
    share_in_core            double precision NOT NULL,
    population               double precision,
    median_household_income  double precision,
    zero_vehicle_share       double precision,
    households               double precision,
    households_below_35k     double precision,
    households_100k_plus     double precision,
    acs5_end_year            integer NOT NULL,
    geom                     geometry(MultiPolygon, 4326) NOT NULL,
    build_id                 integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);
CREATE INDEX IF NOT EXISTS census_tract_geom ON gkg.census_tract USING gist (geom);

-- uko:within: each road segment lies in the tract that contains its midpoint.
-- Segments in the buffer ring outside every loaded tract get no row.
CREATE OR REPLACE VIEW gkg.segment_within_tract AS
    SELECT s.geofence_id, s.urn AS segment_urn, t.urn AS tract_urn
    FROM gkg.road_segment s
    JOIN gkg.census_tract t
      ON t.geofence_id = s.geofence_id AND ST_Contains(t.geom, ST_LineInterpolatePoint(s.geom, 0.5));

-- Stage 3: places from Overture, with the UKO class assigned by rule where one applies.
CREATE TABLE IF NOT EXISTS gkg.place (
    geofence_id        text NOT NULL,
    urn                text NOT NULL,
    gers_id            text NOT NULL,
    name               text,
    basic_category     text,
    taxonomy_primary   text,
    taxonomy_hierarchy jsonb,
    confidence         double precision,
    operating_status   text,
    brand              text,
    uko_class          text,
    uko_class_via      text,
    classified_by      text,          -- rule | llm (not built yet) | null
    in_core            boolean NOT NULL,
    geom               geometry(Point, 4326) NOT NULL,
    build_id           integer NOT NULL,
    PRIMARY KEY (geofence_id, urn)
);
CREATE INDEX IF NOT EXISTS place_geom ON gkg.place USING gist (geom);

-- Stage 3 transit (GTFS-static). Stops are kept when they lie inside the extent; routes, agencies and stop
-- times are kept when they serve such a stop on the service day.
CREATE TABLE IF NOT EXISTS gkg.transit_agency (
    geofence_id text NOT NULL, urn text NOT NULL, feed_id text NOT NULL, agency_id text, name text, url text,
    build_id integer NOT NULL, PRIMARY KEY (geofence_id, urn));
CREATE TABLE IF NOT EXISTS gkg.transit_route (
    geofence_id text NOT NULL, urn text NOT NULL, feed_id text NOT NULL, route_id text NOT NULL,
    short_name text, long_name text, route_type integer, uko_class text, agency_urn text,
    trips_on_service_day integer, service_day text, build_id integer NOT NULL, PRIMARY KEY (geofence_id, urn));
CREATE TABLE IF NOT EXISTS gkg.transit_stop (
    geofence_id text NOT NULL, urn text NOT NULL, feed_id text NOT NULL, stop_id text NOT NULL, name text,
    uko_class text NOT NULL, location_type integer, parent_urn text, departures_on_service_day integer,
    route_urns text[], wheelchair_boarding text, in_core boolean NOT NULL, geom geometry(Point, 4326) NOT NULL,
    build_id integer NOT NULL, PRIMARY KEY (geofence_id, urn));
CREATE INDEX IF NOT EXISTS transit_stop_geom ON gkg.transit_stop USING gist (geom);
CREATE TABLE IF NOT EXISTS gkg.transit_stop_time (
    geofence_id text NOT NULL, stop_urn text NOT NULL, route_urn text NOT NULL, feed_id text NOT NULL,
    trip_id text NOT NULL, arrival_time text, departure_time text, stop_sequence integer, service_day text,
    build_id integer NOT NULL);
CREATE INDEX IF NOT EXISTS transit_stop_time_stop ON gkg.transit_stop_time (geofence_id, stop_urn);
CREATE TABLE IF NOT EXISTS gkg.service_calendar (
    geofence_id text NOT NULL, urn text NOT NULL, feed_id text NOT NULL, service_id text NOT NULL,
    service_day text, build_id integer NOT NULL, PRIMARY KEY (geofence_id, urn));
CREATE TABLE IF NOT EXISTS gkg.walkshed_area (
    geofence_id text NOT NULL, urn text NOT NULL, origin_urn text NOT NULL, distance_threshold_m double precision,
    decay_method text, beta double precision, snap_m double precision, nodes_reached integer,
    decay_weighted_nodes double precision, area_m2 double precision, geom geometry(Polygon, 4326) NOT NULL,
    build_id integer NOT NULL, PRIMARY KEY (geofence_id, urn));
-- uko:connectsToTransit runs from a road to a stop in UKO 15.5 (domain uko:Road, range uko:TransitStop).
CREATE TABLE IF NOT EXISTS gkg.stop_road (
    geofence_id text NOT NULL, segment_urn text NOT NULL, stop_urn text NOT NULL, distance_m double precision,
    build_id integer NOT NULL);

-- URN registry (gkg/urn_registry.py). One row per URN ever issued for an Overture-derived entity, with the
-- releases in which it was first and last present, and lineage rows for splits and merges.
CREATE TABLE IF NOT EXISTS gkg.urn_registry (
    urn text PRIMARY KEY, kind text NOT NULL, gers_id text, piece_key text NOT NULL,
    release_first text NOT NULL, release_last text NOT NULL, retired_release text,
    how_assigned text NOT NULL,             -- minted | kept | rematched | split | merge | added
    tolerance jsonb);
CREATE INDEX IF NOT EXISTS urn_registry_key ON gkg.urn_registry (piece_key);
CREATE TABLE IF NOT EXISTS gkg.urn_lineage (
    old_urn text NOT NULL, new_urn text NOT NULL, relation text NOT NULL, release text NOT NULL,
    PRIMARY KEY (old_urn, new_urn));
