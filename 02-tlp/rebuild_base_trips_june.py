"""
GeoMetis TLP — load the June 2024 delivery into base trips (June variant of version 2).

June differs from April in layout only: each day arrives as 16 files (8 monomodal, 8 multimodal),
every trip sits whole in the files of the day it started (2,543 trips cross midnight, none is split),
and no row is duplicated (audit job 012, 2026-10-23). This variant therefore reads the 16 files of a
day as one batch, holds nothing for the next day, and APPENDS to the tables April already filled.
It never renames or empties tables: run it without --rebuild.

Original description of version 2 follows.

What it does
  1. One-time migration: renames a pre-existing base_trips table (and its file log)
     to *_legacy_<YYYYMMDD>. Nothing is dropped. (Already done on 2026-10-20.)
  2. For each daily vendor CSV, in date order:
       - removes exact duplicate segment rows (April 1-3 repeat rows up to 4x);
       - treats each vendor trip_id as one trip (segments are contiguous);
       - JOINS TRIPS THAT CROSS MIDNIGHT: a trip still running at the end of a file
         is held back and merged with its continuation in the next day's file
         before it is judged;
       - tags start_city / end_city in PostGIS and keeps only trips whose start AND
         end both fall in one of the five target cities;
       - stores kept trips in base_trips and their segments in base_trip_links;
       - records the vendor's whole panel for the day (all devices and trips in the
         file, kept or not) in base_trips_file_log.
     Each file is loaded in one transaction, including the held-back trips, which
     are stored in base_trips_carry until the next file arrives.
  3. Stops at the first file that is still being copied (order matters for the
     midnight join). Rerun after copying finishes.
  4. When no file exists for the day after the last loaded file, held-back trips
     are finalized as they are.

Rerunning on tables loaded by version 1:
     python3 rebuild_base_trips.py --rebuild
  empties base_trips, base_trip_links, base_trips_file_log and base_trips_carry
  (all derived from the CSVs) and reloads every file. The legacy tables are untouched.

Tier 3: origin/destination coordinates and the vendor geoids (9-character geohashes,
~5 m cells) are stored only in these tables. The script prints counts, never rows.

Requires: pip install duckdb psycopg2-binary   (PostGIS must be in the database)
Run:      python3 rebuild_base_trips.py [--rebuild]
"""
import glob
import re
import os
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import duckdb
import psycopg2

# ----------------------------------------------------------------------------- settings
DATA_DIRECTORY = Path.home() / "geometis-data" / "June Data"
DB_CONFIG = {"dbname": "geometis"}            # Mac mini, local socket

TARGET_CITIES = ["Walnut Creek", "Pleasant Hill", "Concord", "Antioch", "Pittsburg"]
BOUNDARY_TABLE = "all_boundaries"
CITY_COLUMN = "city"
GEOM_COLUMN = "geom"

INGEST_VERSION = "segments-dedup-v2"
SETTLE_SECONDS = 15                 # file size must be unchanged for this long
MIN_AGE_SECONDS = 60                # and the file must not have been modified this recently
HOLD_MINUTES = 10                   # hold trips whose last segment ends within this many
                                    # minutes of the next midnight, or after it

# Vendor CSV schema, fixed so every day parses identically.
VENDOR_COLUMNS = {
    "device_id": "VARCHAR", "origin_geoid": "VARCHAR", "destination_geoid": "VARCHAR",
    "origin_lat": "DOUBLE", "origin_long": "DOUBLE", "destination_lat": "DOUBLE", "destination_long": "DOUBLE",
    "start_timestamp": "TIMESTAMP", "end_timestamp": "TIMESTAMP",
    "hour_of_day": "DOUBLE", "time_period": "VARCHAR", "day_of_week": "VARCHAR",
    "trip_duration_sec": "DOUBLE", "trip_distance_m": "DOUBLE", "trip_speed_mps": "DOUBLE",
    "year": "DOUBLE", "iso_week": "DOUBLE", "iso_week_start_date": "DATE", "iso_week_end_date": "DATE",
    "travel_mode": "VARCHAR", "trip_event": "VARCHAR", "trip_id": "VARCHAR",
    "osm_way_id": "DOUBLE", "osm_way_version": "DOUBLE", "pt_trip_id": "VARCHAR", "pt_route_id": "VARCHAR",
}
PG_TYPE = {"VARCHAR": "text", "DOUBLE": "double precision", "TIMESTAMP": "timestamp", "DATE": "date"}
VCOLS = ", ".join(VENDOR_COLUMNS)

# ----------------------------------------------------------------------------- schema
DDL = """
CREATE TABLE base_trips (
  unique_trip_id      text PRIMARY KEY,          -- YYYYMMDD_<vendor trip_id>; date of the file holding the first segment
  original_trip_id    text NOT NULL,
  device_id           text NOT NULL,
  start_time          timestamp NOT NULL,        -- vendor local time (America/Los_Angeles); source has no offset
  end_time            timestamp NOT NULL,
  elapsed_time_sec    double precision,
  total_duration_sec  double precision,
  total_distance_m    double precision,
  total_distance_km   double precision,
  total_duration_min  double precision,
  avg_speed_kmh       double precision,          -- total_distance_m / elapsed_time_sec
  origin_lat          double precision,          -- Tier 3
  origin_long         double precision,          -- Tier 3
  destination_lat     double precision,          -- Tier 3
  destination_long    double precision,          -- Tier 3
  segment_count       integer,
  travel_mode         text,                      -- single mode, or 'multimodal (a/b/...)' with modes sorted
  has_completed_end   boolean,
  day_of_week         text,
  hour_of_day         integer,
  source_file         text,                      -- 'a.csv' or 'a.csv+b.csv' when joined across midnight
  start_city          text NOT NULL,
  end_city            text NOT NULL,
  trip_pair_type      text NOT NULL,             -- 'intra' or 'inter'
  n_legs              integer,
  mode_set            text,
  max_gap_sec         double precision,
  max_jump_m          double precision,
  raw_copies          smallint,
  spans_files         boolean NOT NULL DEFAULT false,
  ingest_version      text NOT NULL
);
CREATE INDEX base_trips_device_start_idx ON base_trips (device_id, start_time);
CREATE INDEX base_trips_cities_idx       ON base_trips (start_city, end_city);

CREATE TABLE base_trip_links (
  unique_trip_id      text NOT NULL REFERENCES base_trips (unique_trip_id) ON DELETE CASCADE,
  link_seq            integer NOT NULL,
  travel_mode         text,
  trip_event          text,
  start_time          timestamp NOT NULL,
  end_time            timestamp NOT NULL,
  duration_sec        double precision,
  distance_m          double precision,
  speed_mps           double precision,
  osm_way_id          bigint,
  osm_way_version     integer,
  pt_trip_id          text,
  pt_route_id         text,
  origin_lat          double precision,          -- Tier 3
  origin_long         double precision,          -- Tier 3
  destination_lat     double precision,          -- Tier 3
  destination_long    double precision,          -- Tier 3
  origin_geoid        text,                      -- Tier 3 (geohash-9)
  destination_geoid   text,                      -- Tier 3 (geohash-9)
  raw_copies          smallint,
  PRIMARY KEY (unique_trip_id, link_seq)
);
CREATE INDEX base_trip_links_way_idx ON base_trip_links (osm_way_id);

CREATE TABLE base_trips_file_log (
  file_name           text PRIMARY KEY,
  file_size_bytes     bigint,
  raw_rows            bigint,
  distinct_rows       bigint,
  copies_min          integer,
  copies_max          integer,
  vendor_trips        bigint,
  trips_kept          bigint,
  trips_intra         bigint,
  trips_inter         bigint,
  links_kept          bigint,
  ingest_version      text,
  loaded_at           timestamptz DEFAULT now()
);
"""

# Added in version 2; safe to run on tables created by version 1.
DDL_V2 = f"""
ALTER TABLE base_trips          ADD COLUMN IF NOT EXISTS spans_files boolean NOT NULL DEFAULT false;
ALTER TABLE base_trips_file_log ADD COLUMN IF NOT EXISTS vendor_devices    bigint;   -- all devices in the file
ALTER TABLE base_trips_file_log ADD COLUMN IF NOT EXISTS kept_devices      bigint;   -- devices with >= 1 kept trip
ALTER TABLE base_trips_file_log ADD COLUMN IF NOT EXISTS trips_carried_in  bigint;   -- held trips joined from the previous file
ALTER TABLE base_trips_file_log ADD COLUMN IF NOT EXISTS trips_carried_out bigint;   -- trips held for the next file
CREATE TABLE IF NOT EXISTS base_trips_carry (
  {", ".join(f"{c} {PG_TYPE[t]}" for c, t in VENDOR_COLUMNS.items())},
  raw_copies  integer,
  day_tag     text,                              -- file date of the trip's first segment
  src_file    text
);
"""

HAVERSINE = """6371008.8*2*asin(sqrt(pow(sin(radians({lat2}-{lat1})/2),2)
              + cos(radians({lat1}))*cos(radians({lat2}))*pow(sin(radians({lon2}-{lon1})/2),2)))"""


# ----------------------------------------------------------------------------- migration
def table_exists(cur, name):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
    return cur.fetchone()[0]


def has_column(cur, table, column):
    cur.execute("""SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s AND column_name=%s)""", (table, column))
    return cur.fetchone()[0]


def rename_with_indexes(cur, table, new_name):
    suffix = new_name[len(table):]
    cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename=%s", (table,))
    for (idx,) in cur.fetchall():
        cur.execute(f'ALTER INDEX "{idx}" RENAME TO "{(idx + suffix)[:63]}"')
    cur.execute(f'ALTER TABLE "{table}" RENAME TO "{new_name}"')


def migrate(pg, rebuild):
    with pg, pg.cursor() as cur:
        if not (table_exists(cur, "base_trips") and has_column(cur, "base_trips", "ingest_version")):
            stamp = date.today().strftime("%Y%m%d")
            for t in ("base_trips", "base_trips_file_log"):
                if table_exists(cur, t):
                    legacy = f"{t}_legacy_{stamp}"
                    if table_exists(cur, legacy):
                        raise SystemExit(f"{legacy} already exists; rename or drop it, then rerun.")
                    rename_with_indexes(cur, t, legacy)
                    print(f"Renamed {t} -> {legacy} (kept, not dropped)")
            cur.execute(DDL)
            print("Created new base_trips, base_trip_links, base_trips_file_log")
        cur.execute(DDL_V2)

        cur.execute("SELECT count(*) FROM base_trips_file_log WHERE ingest_version IS DISTINCT FROM %s",
                    (INGEST_VERSION,))
        older = cur.fetchone()[0]
        if older and not rebuild:
            raise SystemExit(f"{older} files were loaded by an earlier version of this script.\n"
                             f"Rerun with --rebuild to empty the derived tables and reload all files.")
        if rebuild:
            cur.execute("TRUNCATE base_trip_links, base_trips, base_trips_file_log, base_trips_carry")
            print("--rebuild: emptied base_trips, base_trip_links, base_trips_file_log, base_trips_carry")


def check_boundaries(pg):
    with pg, pg.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {CITY_COLUMN} FROM {BOUNDARY_TABLE}")
        present = {r[0] for r in cur.fetchall()}
    missing = [c for c in TARGET_CITIES if c not in present]
    if missing:
        raise SystemExit(f"Target cities not found in {BOUNDARY_TABLE}.{CITY_COLUMN}: {missing}\n"
                         f"Names present: {sorted(present)}")


# ----------------------------------------------------------------------------- files
def file_day(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))   # 'YYYY-MM-DD.csv' or a June day glob
    return date.fromisoformat(m.group(1))


def day_glob(day):
    return str(DATA_DIRECTORY / f"citydata_contra_costa_county_ca_us_2024-06_deviceTrips_routes_{day.isoformat()}_*.csv")


def file_is_ready(path):
    parts = glob.glob(path)
    return len(parts) == 16 and all(os.path.getsize(p) > 0 for p in parts)


def file_is_ready_single(path):
    st1 = os.stat(path)
    if time.time() - st1.st_mtime < MIN_AGE_SECONDS or st1.st_size == 0:
        return False
    time.sleep(SETTLE_SECONDS)
    st2 = os.stat(path)
    if st2.st_size != st1.st_size or st2.st_mtime != st1.st_mtime:
        return False
    with open(path, "rb") as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) == b"\n"


def read_vendor_csv_sql(path):
    # Types are bound by column NAME, so a change in the vendor's column order is harmless.
    cols = ", ".join(f"'{c}': '{t}'" for c, t in VENDOR_COLUMNS.items())
    return f"read_csv('{path}', header=true, types={{{cols}}})"


# ----------------------------------------------------------------------------- DuckDB build
def build_batch(con, csv_path, carry_csv):
    """Build trips from one vendor file (or none) plus held-back segments (or none)."""
    if csv_path:
        day_tag = file_day(csv_path).strftime("%Y%m%d")
        con.execute(f"""
          CREATE OR REPLACE TEMP TABLE d AS
          SELECT {VCOLS}, count(*) AS raw_copies FROM {read_vendor_csv_sql(csv_path)} GROUP BY ALL""")
        stats = con.execute("""SELECT sum(raw_copies), count(*), min(raw_copies), max(raw_copies),
                                      count(DISTINCT trip_id), count(DISTINCT device_id) FROM d""").fetchone()
        con.execute(f"""CREATE OR REPLACE TEMP TABLE segs AS
                        SELECT *, '{day_tag}' AS day_tag, '{os.path.basename(csv_path)}' AS src_file FROM d""")
        con.execute("DROP TABLE d")
    else:
        stats = (0, 0, None, None, 0, 0)               # finalizing held trips only; no new file
        con.execute("CREATE OR REPLACE TEMP TABLE segs AS SELECT * FROM carry LIMIT 0")

    carried_in = 0
    if carry_csv:
        carried_in = con.execute("SELECT count(DISTINCT trip_id) FROM carry").fetchone()[0]
        # Join held segments to today's; a segment present in both files is kept once.
        con.execute(f"""
          CREATE OR REPLACE TEMP TABLE segs AS
          SELECT {VCOLS}, max(raw_copies) AS raw_copies, min(day_tag) AS day_tag, min(src_file) AS src_file
          FROM (SELECT * FROM segs UNION ALL BY NAME SELECT * FROM carry)
          GROUP BY {VCOLS}""")

    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE links AS
      SELECT min(day_tag) OVER (PARTITION BY trip_id) || '_' || trip_id AS unique_trip_id,
             trip_id, device_id, day_tag, src_file,
             row_number() OVER (PARTITION BY trip_id
                                ORDER BY start_timestamp, end_timestamp, osm_way_id) AS link_seq,
             travel_mode, trip_event,
             start_timestamp AS start_time, end_timestamp AS end_time,
             epoch(end_timestamp) - epoch(start_timestamp) AS duration_sec,
             trip_distance_m AS distance_m, trip_speed_mps AS speed_mps,
             CAST(osm_way_id AS BIGINT) AS osm_way_id, CAST(osm_way_version AS INTEGER) AS osm_way_version,
             pt_trip_id, pt_route_id,
             origin_lat, origin_long, destination_lat, destination_long,
             origin_geoid, destination_geoid, raw_copies
      FROM segs
      WHERE trip_id IS NOT NULL AND device_id IS NOT NULL
        AND start_timestamp IS NOT NULL AND end_timestamp IS NOT NULL""")
    jump = HAVERSINE.format(lat1="lag(destination_lat) OVER w", lon1="lag(destination_long) OVER w",
                            lat2="origin_lat", lon2="origin_long")
    con.execute(f"""
      CREATE OR REPLACE TEMP TABLE trips AS
      WITH g AS (
        SELECT *, epoch(start_time) - epoch(lag(end_time) OVER w) AS gap_s, {jump} AS jump_m
        FROM links WINDOW w AS (PARTITION BY trip_id ORDER BY link_seq)),
      a AS (
        SELECT unique_trip_id, any_value(trip_id) AS original_trip_id, any_value(device_id) AS device_id,
               min(start_time) AS start_time, max(end_time) AS end_time,
               sum(duration_sec) AS total_duration_sec, sum(distance_m) AS total_distance_m,
               arg_min(origin_lat, link_seq) AS origin_lat, arg_min(origin_long, link_seq) AS origin_long,
               arg_max(destination_lat, link_seq) AS destination_lat,
               arg_max(destination_long, link_seq) AS destination_long,
               count(*) AS segment_count,
               list_sort(list_distinct(list(travel_mode))) AS modes,
               arg_max(trip_event, link_seq) IN ('end', 'start-end') AS has_completed_end,
               sum((trip_event IN ('start', 'start-end'))::int) AS n_legs,
               coalesce(max(gap_s), 0) AS max_gap_sec, coalesce(max(jump_m), 0) AS max_jump_m,
               max(raw_copies) AS raw_copies,
               string_agg(DISTINCT src_file, '+' ORDER BY src_file) AS source_file,
               count(DISTINCT src_file) > 1 AS spans_files
        FROM g GROUP BY unique_trip_id)
      SELECT unique_trip_id, original_trip_id, device_id, start_time, end_time,
             epoch(end_time) - epoch(start_time) AS elapsed_time_sec,
             total_duration_sec, total_distance_m,
             round(total_distance_m / 1000.0, 2) AS total_distance_km,
             round(total_duration_sec / 60.0, 2) AS total_duration_min,
             CASE WHEN epoch(end_time) > epoch(start_time)
                  THEN round(total_distance_m / (epoch(end_time) - epoch(start_time)) * 3.6, 2) END AS avg_speed_kmh,
             origin_lat, origin_long, destination_lat, destination_long, segment_count,
             CASE WHEN len(modes) = 1 THEN modes[1]
                  ELSE 'multimodal (' || array_to_string(modes, '/') || ')' END AS travel_mode,
             has_completed_end, dayname(start_time) AS day_of_week, hour(start_time) AS hour_of_day,
             source_file, n_legs, array_to_string(modes, '+') AS mode_set,
             max_gap_sec, max_jump_m, raw_copies, spans_files
      FROM a""")
    return stats, carried_in


def mark_held(con, next_midnight):
    """Trips still running near the next midnight wait for the next file."""
    if next_midnight is None:
        con.execute("CREATE OR REPLACE TEMP TABLE held AS SELECT original_trip_id AS trip_id FROM trips LIMIT 0")
    else:
        cutoff = next_midnight - timedelta(minutes=HOLD_MINUTES)
        con.execute(f"""CREATE OR REPLACE TEMP TABLE held AS
                        SELECT original_trip_id AS trip_id FROM trips
                        WHERE end_time >= TIMESTAMP '{cutoff:%Y-%m-%d %H:%M:%S}'""")
    return con.execute("SELECT count(*) FROM held").fetchone()[0]


def duck_to_pg(con, cur, query, pg_target, tmpdir, name):
    path = os.path.join(tmpdir, f"{name}.csv")
    con.execute(f"COPY ({query}) TO '{path}' (HEADER true, DELIMITER '\t', NULL '')")
    with open(path) as f:
        cols = f.readline().rstrip("\n").split("\t")
        f.seek(0)
        cur.copy_expert(f"COPY {pg_target} ({','.join(cols)}) FROM STDIN "
                        f"WITH (FORMAT CSV, HEADER true, DELIMITER E'\\t', NULL '')", f)
    os.remove(path)


def load_carry(con, pg, tmpdir):
    """Copy held segments from PostgreSQL into DuckDB table `carry`. Returns the CSV path or None."""
    path = os.path.join(tmpdir, "carry.csv")
    with pg.cursor() as cur, open(path, "w") as f:
        cur.copy_expert(f"COPY (SELECT {VCOLS}, raw_copies, day_tag, src_file FROM base_trips_carry) "
                        f"TO STDOUT WITH (FORMAT CSV, HEADER true)", f)
    cols = ", ".join(f"'{c}': '{t}'" for c, t in VENDOR_COLUMNS.items())
    con.execute(f"""CREATE OR REPLACE TEMP TABLE carry AS
                    SELECT {VCOLS}, raw_copies, day_tag, src_file FROM read_csv('{path}', header=true,
                      types={{{cols}, 'raw_copies': 'BIGINT', 'day_tag': 'VARCHAR', 'src_file': 'VARCHAR'}})""")
    n = con.execute("SELECT count(*) FROM carry").fetchone()[0]
    return path if n else None


# ----------------------------------------------------------------------------- one batch
def load_batch(con, pg, csv_path, next_midnight, log_name):
    with tempfile.TemporaryDirectory() as tmp:
        carry_csv = load_carry(con, pg, tmp)
        if csv_path is None and carry_csv is None:
            return
        (raw_rows, distinct_rows, cmin, cmax, n_vendor, n_devices), carried_in = build_batch(con, csv_path, carry_csv)
        n_held = mark_held(con, next_midnight)

        with pg, pg.cursor() as cur:
            cur.execute("""CREATE TEMP TABLE stage (LIKE base_trips INCLUDING DEFAULTS) ON COMMIT DROP;
                           ALTER TABLE stage ALTER COLUMN start_city DROP NOT NULL,
                                             ALTER COLUMN end_city DROP NOT NULL,
                                             ALTER COLUMN trip_pair_type DROP NOT NULL,
                                             ALTER COLUMN ingest_version DROP NOT NULL;""")
            duck_to_pg(con, cur, "SELECT * FROM trips ANTI JOIN held ON trips.original_trip_id = held.trip_id",
                       "stage", tmp, "trips")

            point = "ST_Transform(ST_SetSRID(ST_MakePoint(s.{lon}, s.{lat}), 4326), ST_SRID(c.{g}))"
            for col, lat, lon in (("start_city", "origin_lat", "origin_long"),
                                  ("end_city", "destination_lat", "destination_long")):
                cur.execute(f"""
                  UPDATE stage s SET {col} = c.{CITY_COLUMN}
                  FROM {BOUNDARY_TABLE} c
                  WHERE c.{CITY_COLUMN} = ANY(%s)
                    AND ST_Contains(c.{GEOM_COLUMN}, {point.format(lon=lon, lat=lat, g=GEOM_COLUMN)})""",
                            (TARGET_CITIES,))

            cur.execute("""
              INSERT INTO base_trips
                (unique_trip_id, original_trip_id, device_id, start_time, end_time,
                 elapsed_time_sec, total_duration_sec, total_distance_m, total_distance_km,
                 total_duration_min, avg_speed_kmh, origin_lat, origin_long,
                 destination_lat, destination_long, segment_count, travel_mode,
                 has_completed_end, day_of_week, hour_of_day, source_file,
                 start_city, end_city, trip_pair_type,
                 n_legs, mode_set, max_gap_sec, max_jump_m, raw_copies, spans_files, ingest_version)
              SELECT s.unique_trip_id, s.original_trip_id, s.device_id, s.start_time, s.end_time,
                     s.elapsed_time_sec, s.total_duration_sec, s.total_distance_m, s.total_distance_km,
                     s.total_duration_min, s.avg_speed_kmh, s.origin_lat, s.origin_long,
                     s.destination_lat, s.destination_long, s.segment_count, s.travel_mode,
                     s.has_completed_end, s.day_of_week, s.hour_of_day, s.source_file,
                     s.start_city, s.end_city,
                     CASE WHEN s.start_city = s.end_city THEN 'intra' ELSE 'inter' END,
                     s.n_legs, s.mode_set, s.max_gap_sec, s.max_jump_m, s.raw_copies, s.spans_files, %s
              FROM stage s
              WHERE s.start_city IS NOT NULL AND s.end_city IS NOT NULL
              RETURNING unique_trip_id, trip_pair_type, device_id""", (INGEST_VERSION,))
            kept = cur.fetchall()

            con.execute("CREATE OR REPLACE TEMP TABLE kept (unique_trip_id VARCHAR)")
            if kept:
                con.executemany("INSERT INTO kept VALUES (?)", [(k[0],) for k in kept])
            link_cols = ("unique_trip_id, link_seq, travel_mode, trip_event, start_time, end_time, duration_sec, "
                         "distance_m, speed_mps, osm_way_id, osm_way_version, pt_trip_id, pt_route_id, "
                         "origin_lat, origin_long, destination_lat, destination_long, "
                         "origin_geoid, destination_geoid, raw_copies")
            duck_to_pg(con, cur, f"SELECT {link_cols} FROM links SEMI JOIN kept USING (unique_trip_id)",
                       "base_trip_links", tmp, "links")
            n_links = con.execute("SELECT count(*) FROM links SEMI JOIN kept USING (unique_trip_id)").fetchone()[0]

            # Replace the held-back set with today's.
            cur.execute("TRUNCATE base_trips_carry")
            duck_to_pg(con, cur, f"""SELECT {VCOLS}, raw_copies, day_tag, src_file FROM segs
                                     SEMI JOIN held USING (trip_id)""", "base_trips_carry", tmp, "carry_out")

            n_intra = sum(1 for k in kept if k[1] == "intra")
            n_kept_dev = len({k[2] for k in kept})
            size = sum(os.path.getsize(p) for p in glob.glob(csv_path)) if csv_path else None
            cur.execute("""INSERT INTO base_trips_file_log
                           (file_name, file_size_bytes, raw_rows, distinct_rows, copies_min, copies_max,
                            vendor_trips, trips_kept, trips_intra, trips_inter, links_kept, ingest_version,
                            vendor_devices, kept_devices, trips_carried_in, trips_carried_out)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (log_name, size, raw_rows, distinct_rows, cmin, cmax, n_vendor, len(kept), n_intra,
                         len(kept) - n_intra, n_links, INGEST_VERSION, n_devices, n_kept_dev, carried_in, n_held))

    if csv_path:
        print(f"  {log_name}: {raw_rows:,} rows -> {distinct_rows:,} distinct segments (copies {cmin}-{cmax}); "
              f"{n_vendor:,} vendor trips from {n_devices:,} devices; {carried_in:,} joined from previous day; "
              f"{n_held:,} held for next day; {len(kept):,} kept ({n_intra:,} intra, {len(kept)-n_intra:,} inter)")
    else:
        print(f"  {log_name}: {carried_in:,} held trips finalized; {len(kept):,} kept")


# ----------------------------------------------------------------------------- main
def main():
    rebuild = "--rebuild" in sys.argv
    if not DATA_DIRECTORY.is_dir():
        raise SystemExit(f"Directory not found: {DATA_DIRECTORY}")
    pg = psycopg2.connect(**DB_CONFIG)
    check_boundaries(pg)
    migrate(pg, rebuild)

    with pg, pg.cursor() as cur:
        cur.execute("SELECT file_name FROM base_trips_file_log")
        done = {r[0] for r in cur.fetchall()}

    days = sorted({file_day(f) for f in glob.glob(str(DATA_DIRECTORY / "*.csv"))})
    files = [day_glob(d) for d in days]
    by_day = {d: day_glob(d) for d in days}
    pending = [day_glob(d) for d in days if f"{d.isoformat()}.csv" not in done]
    pending = pending[:int(os.environ.get("JUNE_MAX_DAYS", "999"))]   # test on one day first
    print(f"{len(files)} files found, {len(done)} already loaded, {len(pending)} pending")

    con = duckdb.connect()
    spill = Path(tempfile.gettempdir()) / "rebuild_base_trips_duckdb"
    con.execute(f"SET enable_progress_bar=false; SET preserve_insertion_order=false; SET temp_directory='{spill}'")

    last_day, stopped = None, False
    for path in pending:
        name = f"{file_day(path).isoformat()}.csv"      # logged under the day, like April
        if not file_is_ready(path):
            print(f"  {name}: still being copied; stopping here so trips crossing midnight join correctly")
            stopped = True
            break
        day = file_day(path)
        next_day = day + timedelta(days=1)
        next_midnight = None                         # June: trips are never split across days; hold nothing
        try:
            load_batch(con, pg, path, next_midnight, name)
            last_day = day
        except Exception as e:                       # the file's transaction was rolled back
            print(f"  ERROR {name}: {e}")
            stopped = True
            break

    # Finalize held trips when no file exists for the following day.
    if not stopped:
        with pg, pg.cursor() as cur:
            cur.execute("SELECT max(file_name) FROM base_trips_file_log WHERE file_name LIKE '____-__-__.csv'")
            last_loaded = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM base_trips_carry")
            n_carry = cur.fetchone()[0]
        if last_loaded and n_carry:
            last_day = file_day(last_loaded)
            if last_day + timedelta(days=1) not in by_day:
                load_batch(con, pg, None, None, f"carry-after-{last_day.isoformat()}")

    with pg, pg.cursor() as cur:
        cur.execute("""SELECT count(*), count(DISTINCT device_id),
                              count(*) FILTER (WHERE trip_pair_type='intra'),
                              count(*) FILTER (WHERE trip_pair_type='inter'),
                              count(*) FILTER (WHERE spans_files) FROM base_trips""")
        n, devs, intra, inter, spans = cur.fetchone()
        cur.execute("""SELECT count(*) FROM (SELECT original_trip_id FROM base_trips
                       GROUP BY original_trip_id HAVING count(*) > 1) x""")
        multi = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT trip_id) FROM base_trips_carry")
        waiting = cur.fetchone()[0]
    print(f"\nbase_trips holds {n:,} trips from {devs:,} devices ({intra:,} intra-city, {inter:,} inter-city); "
          f"{spans:,} were joined across midnight.")
    print(f"Vendor trip_ids still stored under more than one day: {multi:,}")
    if waiting:
        print(f"{waiting:,} trips are held waiting for the next day's file.")
    pg.close()
    con.close()
    shutil.rmtree(spill, ignore_errors=True)


def date_to_dt(d):
    from datetime import datetime
    return datetime(d.year, d.month, d.day)


if __name__ == "__main__":
    main()
