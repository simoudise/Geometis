import os, io, glob
from pathlib import Path
import psycopg2
from psycopg2 import sql
import pandas as pd
import numpy as np

DATA_DIRECTORY = Path.home() / "Downloads" / "store-trips" / "raw-gps-data"
FILE_PATTERN = "*.csv"

DB_CONFIG = {
    "dbname": "contracosta",
    "user": "esimoudis",
    "host": "127.0.0.1",
    "port": 5432
}

# --- CALIBRATED THRESHOLDS ---
MAX_TIME_GAP_SEC = 300.0    # 5-minute dwell threshold for legitimate trip stops
MAX_DISP_METERS = 1500.0    # 1.5 km gap to prevent fracturing moving highway traffic


def haversine_vectorized(lat1, lon1, lat2, lon2):
    R = 6371008.8
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0)**2
    return 2.0 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def get_already_processed_files(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT file_name FROM base_trips_file_log WHERE status = 'SUCCESS';")
        return {r[0] for r in cur.fetchall()}


def transform_csv_to_base_trips(file_path):
    cols = [
        'trip_id', 'device_id', 'start_timestamp', 'end_timestamp',
        'origin_lat', 'origin_long', 'destination_lat', 'destination_long',
        'trip_distance_m', 'trip_duration_sec', 'travel_mode', 'trip_event'
    ]
    df = pd.read_csv(file_path, usecols=lambda c: c in cols)
    initial_rows = len(df)
    if initial_rows == 0:
        return pd.DataFrame(), 0

    df['start_timestamp'] = pd.to_datetime(df['start_timestamp'], format='ISO8601')
    df['end_timestamp'] = pd.to_datetime(df['end_timestamp'], format='ISO8601')

    # Drop null coordinates or IDs
    df = df.dropna(subset=['trip_id', 'origin_lat', 'origin_long', 'start_timestamp', 'end_timestamp'])
    df['calc_duration'] = (df['end_timestamp'] - df['start_timestamp']).dt.total_seconds()
    df = df[df['calc_duration'] >= 0]
    df = df.sort_values(by=['trip_id', 'start_timestamp']).reset_index(drop=True)

    # Detect gaps between consecutive links
    prev_end_time = df.groupby('trip_id')['end_timestamp'].shift(1)
    prev_dest_lat = df.groupby('trip_id')['destination_lat'].shift(1)
    prev_dest_lon = df.groupby('trip_id')['destination_long'].shift(1)

    time_gaps = (df['start_timestamp'] - prev_end_time).dt.total_seconds().fillna(0)
    disp_gaps = haversine_vectorized(prev_dest_lat, prev_dest_lon, df['origin_lat'], df['origin_long']).fillna(0)

    # Calibrated split: genuine dwell (> 5 mins) or large telematics jump (> 1.5 km)
    df['is_split'] = (time_gaps > MAX_TIME_GAP_SEC) | (disp_gaps > MAX_DISP_METERS)
    df['sub_trip_index'] = df.groupby('trip_id')['is_split'].cumsum()

    # Prepend date prefix for globally unique IDs across files
    date_tag = Path(file_path).stem.replace('-', '')
    df['unique_trip_id'] = date_tag + "_" + df['trip_id'] + "_" + df['sub_trip_index'].astype(str)

    trips = df.groupby('unique_trip_id', sort=False).agg(
        original_trip_id=('trip_id', 'first'),
        device_id=('device_id', 'first'),
        start_time=('start_timestamp', 'first'),
        end_time=('end_timestamp', 'last'),
        origin_lat=('origin_lat', 'first'),
        origin_long=('origin_long', 'first'),
        destination_lat=('destination_lat', 'last'),
        destination_long=('destination_long', 'last'),
        total_distance_m=('trip_distance_m', 'sum'),
        total_duration_sec=('calc_duration', 'sum'),
        segment_count=('trip_id', 'count'),
        events=('trip_event', lambda s: list(s.dropna().unique())),
        modes=('travel_mode', lambda s: list(s.dropna().unique()))
    ).reset_index()

    trips['elapsed_time_sec'] = (trips['end_time'] - trips['start_time']).dt.total_seconds()
    trips['has_completed_end'] = trips['events'].apply(lambda ev: 'end' in ev or 'start-end' in ev)
    trips['travel_mode'] = trips['modes'].apply(lambda m: m[0] if len(m) == 1 else "multimodal (" + "/".join(m) + ")")
    trips['day_of_week'] = trips['start_time'].dt.day_name()
    trips['hour_of_day'] = trips['start_time'].dt.hour

    # Robust speed calculation avoiding 1-second division anomalies
    effective_duration = np.maximum(trips['elapsed_time_sec'], trips['total_duration_sec'])
    trips['avg_speed_kmh'] = np.where(
        effective_duration > 0,
        (trips['total_distance_m'] / effective_duration) * 3.6,
        0.0
    ).round(2)

    trips['total_distance_m'] = trips['total_distance_m'].round(1)
    trips['total_distance_km'] = (trips['total_distance_m'] / 1000.0).round(2)
    trips['total_duration_min'] = (trips['total_duration_sec'] / 60.0).round(2)

    trips.drop(columns=['events', 'modes'], inplace=True)
    return trips, initial_rows


def copy_dataframe_to_postgres(conn, df, target_table):
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, sep="\t", na_rep="")
    buffer.seek(0)
    
    columns = [sql.Identifier(col) for col in df.columns]
    copy_query = sql.SQL("COPY {table} ({fields}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '')").format(
        table=sql.Identifier(target_table),
        fields=sql.SQL(", ").join(columns)
    )
    with conn.cursor() as cur:
        cur.copy_expert(copy_query, buffer)


def process_file(conn, file_path):
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    print(f"\n--- Processing: {file_name} ({file_size / (1024*1024):.1f} MB) ---")

    trips_df, input_rows = transform_csv_to_base_trips(file_path)
    if trips_df.empty:
        print("  Warning: No valid trips generated. Skipping.")
        return

    trips_df['source_file'] = file_name
    trips_df['start_city'] = None
    trips_df['end_city'] = None

    ordered_columns = [
        'unique_trip_id', 'original_trip_id', 'device_id', 'start_time', 'end_time',
        'elapsed_time_sec', 'total_duration_sec', 'total_distance_m', 'total_distance_km',
        'total_duration_min', 'avg_speed_kmh', 'origin_lat', 'origin_long',
        'destination_lat', 'destination_long', 'segment_count', 'travel_mode',
        'has_completed_end', 'day_of_week', 'hour_of_day', 'source_file',
        'start_city', 'end_city'
    ]
    trips_df = trips_df[ordered_columns]

    try:
        with conn:
            # 1. Bulk insert
            copy_dataframe_to_postgres(conn, trips_df, "base_trips")

            # 2. Tag origin and destination cities in PostGIS
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE base_trips b
                    SET start_city = c.city
                    FROM all_boundaries c
                    WHERE b.source_file = %s
                      AND b.start_city IS NULL
                      AND ST_Contains(c.geom, ST_SetSRID(ST_MakePoint(b.origin_long, b.origin_lat), 4326));

                    UPDATE base_trips b
                    SET end_city = c.city
                    FROM all_boundaries c
                    WHERE b.source_file = %s
                      AND b.end_city IS NULL
                      AND ST_Contains(c.geom, ST_SetSRID(ST_MakePoint(b.destination_long, b.destination_lat), 4326));

                    INSERT INTO base_trips_file_log 
                    (file_name, file_size_bytes, segment_rows_read, base_trips_created, status)
                    VALUES (%s, %s, %s, %s, 'SUCCESS');
                """, (file_name, file_name, file_name, file_size, input_rows, len(trips_df)))
        
        print(f"  Success: Loaded and spatially tagged {len(trips_df):,} base trips from {input_rows:,} link segments.")
    except Exception as e:
        conn.rollback()
        print(f"  ERROR processing {file_name}: {e}")


def main():
    if not os.path.isdir(DATA_DIRECTORY):
        print(f"Directory not found: {DATA_DIRECTORY}")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    all_files = sorted(glob.glob(os.path.join(DATA_DIRECTORY, FILE_PATTERN)))
    processed_files = get_already_processed_files(conn)
    pending_files = [f for f in all_files if os.path.basename(f) not in processed_files]

    print(f"Found {len(all_files)} total file(s) in {DATA_DIRECTORY}")
    print(f"Already processed: {len(processed_files)}")
    print(f"Pending to process: {len(pending_files)}")

    for file_path in pending_files:
        process_file(conn, file_path)

    conn.close()
    print("\nPipeline run complete.")


if __name__ == "__main__":
    main()
