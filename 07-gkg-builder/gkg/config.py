"""Pinned source versions and local paths for the Knowledge Builder.

Every build records these values in gkg.build.source_versions, so that two builds of the
same geofence can be compared (geofence input spec, "Pinned source versions").
"""
import os
from pathlib import Path

BUILDER_VERSION = "0.1.0"
SPEC_VERSION = "geofence-input-spec 2026-11-03"

# Overture release fixed at the first Phase 1 download and reused for every reference-set geofence.
OVERTURE_RELEASE = "2026-10-21.0"
OVERTURE_BASE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=transportation"

TIGER_VINTAGE = 2024
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER{v}/{layer_upper}/tl_{v}_{state}_{layer}.zip"

# Buffer test (spec, "Buffer rule").
BUFFER_START_M = 3000
BUFFER_STEP_M = 1000
BUFFER_MAX_M = 30000
BUFFER_OUTSIDE_THRESHOLD = 0.005  # share of total route length allowed outside the extent

OSRM_CAR_URL = os.environ.get("GEOMETIS_OSRM_CAR", "http://127.0.0.1:5001")
OSRM_REGION = "Geofabrik norcal extract on the Mac mini"

DATA_ROOT = Path(os.environ.get("GEOMETIS_DATA", str(Path.home() / "geometis-data"))) / "gkg"
PG_DSN = os.environ.get("GEOMETIS_PG_DSN", "dbname=geometis")

METRIC_CRS = "EPSG:5070"  # CONUS Albers, used for buffers and areas
STORE_CRS = "EPSG:4326"

# Overture road classes. Classes not listed here (for example "unknown") are treated as vehicular.
PEDESTRIAN_CLASSES = {"footway", "pedestrian", "steps", "path", "cycleway", "bridleway"}

# URN matching on an Overture refresh (v19, URNs: "within the tolerance recorded in the GKG network version").
# A segment whose GERS id changed keeps an old URN only if both ends lie within URN_MATCH_END_M of the old
# segment's ends, the Hausdorff distance is at most URN_MATCH_HAUSDORFF_M, and the length differs by at most
# URN_MATCH_LENGTH_SHARE; a candidate must be the only old segment that passes. Set 3 November 2026 from the
# 2026-09-23 to 2026-10-21 comparison for Contra Costa (analysis/release_drift.py).
URN_MATCH_END_M = 5.0
URN_MATCH_HAUSDORFF_M = 10.0
URN_MATCH_LENGTH_SHARE = 0.10

# Stage 3 transit. The reference date is a Wednesday in April 2024, the month of the first client trip delivery,
# so that the transit graph matches the trips. v19 asks for walksheds with "the v15.4 decay parameters" but
# neither v19 nor UKO 15.5 gives their values; the three values below are placeholders until they are set.
TRANSIT_REFERENCE_DATE = "20240417"
WALKSHED_THRESHOLD_M = 800.0
WALKSHED_BETA = 0.002          # exponential decay per metre: weight = exp(-beta * network distance)
WALKSHED_MAX_SNAP_M = 150.0    # a stop farther than this from the walkable network gets no walkshed
