CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS base_trips_file_log (
    file_name VARCHAR(255) PRIMARY KEY,
    file_size_bytes BIGINT,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    segment_rows_read INT,
    base_trips_created INT,
    status VARCHAR(50) DEFAULT 'SUCCESS'
);

CREATE TABLE base_trips (
    unique_trip_id VARCHAR(100) PRIMARY KEY,
    original_trip_id VARCHAR(64) NOT NULL,
    device_id VARCHAR(128) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    elapsed_time_sec DOUBLE PRECISION,
    total_duration_sec DOUBLE PRECISION,
    total_distance_m DOUBLE PRECISION,
    total_distance_km DOUBLE PRECISION,
    total_duration_min DOUBLE PRECISION,
    avg_speed_kmh DOUBLE PRECISION,
    origin_lat DOUBLE PRECISION NOT NULL,
    origin_long DOUBLE PRECISION NOT NULL,
    destination_lat DOUBLE PRECISION NOT NULL,
    destination_long DOUBLE PRECISION NOT NULL,
    segment_count INT,
    travel_mode VARCHAR(64),
    has_completed_end BOOLEAN,
    day_of_week VARCHAR(16),
    hour_of_day INT,
    source_file VARCHAR(255),
    start_city VARCHAR(64),
    end_city VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_base_trips_start_city ON base_trips(start_city);
CREATE INDEX idx_base_trips_end_city ON base_trips(end_city);