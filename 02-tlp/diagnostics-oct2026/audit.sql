-- ==============================================================
-- CHECK 1: File Ingestion Status & Total Row Audit
-- ==============================================================
SELECT 
    status, 
    count(*) AS total_files,
    to_char(sum(segment_rows_read), 'FM999,999,999') AS total_segments_ingested,
    to_char(sum(base_trips_created), 'FM999,999,999') AS total_base_trips_created
FROM base_trips_file_log
GROUP BY status;

-- ==============================================================
-- CHECK 2: Daily Calendar Continuity (Look for Missing Days)
-- ==============================================================
SELECT 
    start_time::date AS trip_date,
    day_of_week,
    count(*) AS trip_count,
    round(avg(total_distance_km)::numeric, 2) AS avg_km,
    round(avg(avg_speed_kmh)::numeric, 1) AS avg_kmh
FROM base_trips
GROUP BY 1, 2
ORDER BY 1;

-- ==============================================================
-- CHECK 3: Spatial Tagging Coverage (Target Study Cities)
-- ==============================================================
SELECT 
    count(*) AS total_trips_countywide,
    count(start_city) AS origins_in_study_cities,
    count(end_city) AS dests_in_study_cities,
    count(*) FILTER (WHERE start_city IS NOT NULL AND end_city IS NOT NULL) AS full_study_trips,
    round(100.0 * count(*) FILTER (WHERE start_city IS NOT NULL AND end_city IS NOT NULL) / count(*), 2) AS study_cohort_pct
FROM base_trips;

-- ==============================================================
-- CHECK 4: Physics & GPS Glitch Audit
-- ==============================================================
SELECT 
    count(*) FILTER (WHERE elapsed_time_sec <= 0) AS non_positive_elapsed_time,
    count(*) FILTER (WHERE total_distance_m <= 0) AS zero_distance_trips,
    count(*) FILTER (WHERE avg_speed_kmh > 150) AS extreme_speed_outliers_over_150kmh,
    count(*) FILTER (WHERE segment_count = 1) AS single_ping_trips,
    count(*) FILTER (WHERE has_completed_end IS FALSE) AS uncompleted_or_truncated_trips
FROM base_trips;

-- ==============================================================
-- CHECK 5: Full Month Target Study Cohort (Type 1 vs. Type 2)
-- ==============================================================
SELECT 
    trip_type,
    count(*) AS total_trips,
    round(100.0 * count(*) / sum(count(*)) over (), 1) AS share_pct,
    round(avg(total_distance_km)::numeric, 2) AS avg_distance_km,
    round(avg(total_duration_min)::numeric, 1) AS avg_duration_min,
    round(avg(avg_speed_kmh)::numeric, 1) AS avg_speed_kmh
FROM target_study_trips
GROUP BY trip_type
ORDER BY trip_type;
