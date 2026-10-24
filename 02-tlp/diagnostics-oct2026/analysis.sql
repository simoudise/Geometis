-- 1. Create the study cohort view (Type 1: Intra-City vs Type 2: Inter-City)
CREATE OR REPLACE VIEW target_study_trips AS
SELECT 
    unique_trip_id,
    device_id,
    start_city,
    end_city,
    CASE 
        WHEN start_city = end_city THEN 'Type 1: Intra-City'
        ELSE 'Type 2: Inter-City'
    END AS trip_type,
    travel_mode,
    total_distance_km,
    total_duration_min,
    avg_speed_kmh,
    start_time,
    end_time
FROM base_trips
WHERE start_city IN ('Walnut Creek', 'Pleasant Hill', 'Antioch', 'Pittsburg', 'Concord')
  AND end_city   IN ('Walnut Creek', 'Pleasant Hill', 'Antioch', 'Pittsburg', 'Concord');

-- 2. Breakdown by City Pair and Trip Type
SELECT 
    trip_type,
    start_city,
    end_city,
    count(*) AS trip_count,
    round(avg(total_distance_km)::numeric, 2) AS avg_km,
    round(avg(total_duration_min)::numeric, 1) AS avg_min
FROM target_study_trips
GROUP BY trip_type, start_city, end_city
ORDER BY trip_type, trip_count DESC;

-- 3. High-level Summary: Total Type 1 vs Type 2 Trips
SELECT 
    trip_type,
    count(*) AS total_trips,
    round(avg(total_distance_km)::numeric, 2) AS avg_km,
    round(avg(total_duration_min)::numeric, 1) AS avg_min
FROM target_study_trips
GROUP BY trip_type
ORDER BY trip_type;
