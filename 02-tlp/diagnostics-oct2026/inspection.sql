-- 1. Which travel modes account for the speed outliers?
SELECT 
    travel_mode,
    count(*) AS outlier_count,
    round(avg(avg_speed_kmh)::numeric, 1) AS avg_speed,
    round(avg(total_distance_km)::numeric, 2) AS avg_km,
    round(avg(elapsed_time_sec)::numeric, 1) AS avg_elapsed_sec
FROM base_trips
WHERE avg_speed_kmh > 150
GROUP BY travel_mode
ORDER BY outlier_count DESC
LIMIT 10;

-- 2. Inspect 5 sample outlier records
SELECT 
    unique_trip_id,
    travel_mode,
    segment_count,
    total_distance_km,
    elapsed_time_sec,
    round(avg_speed_kmh::numeric, 1) AS avg_speed_kmh
FROM base_trips
WHERE avg_speed_kmh > 150
ORDER BY avg_speed_kmh DESC
LIMIT 5;
