SELECT 
    count(*) AS total_speed_outliers,
    count(*) FILTER (WHERE unique_trip_id NOT LIKE '%_0') AS outliers_that_are_subtrips,
    count(*) FILTER (WHERE segment_count = 1) AS outliers_with_only_1_segment,
    round(100.0 * count(*) FILTER (WHERE unique_trip_id NOT LIKE '%_0' OR segment_count = 1) / count(*), 1) AS pct_caused_by_fragmentation
FROM base_trips
WHERE avg_speed_kmh > 150;
