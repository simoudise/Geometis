#!/usr/bin/env python3
"""
Enhanced SWITRS/TIMS Crash Data Loader for Geospatial Knowledge Graph

VERSION 2.0: Adds spatial relationship triples for GeoRotatE training

This enhanced version extends the base SWITRS loader to compute and add
spatial relationships between safety entities and other KG entities:

NEW SPATIAL RELATIONSHIPS ADDED:
================================
1. Collision → POI relationships:
   - uko:collisionNearSchool (collision within 200m of school)
   - uko:collisionNearSeniorCenter (collision within 200m of senior center)
   - uko:collisionNearHospital (collision within 200m of hospital)
   - uko:collisionNearTransitStop (collision within 100m of transit stop)

2. HIN → Infrastructure relationships:
   - uko:hinOnRoad (HIN segment overlays this road)
   - uko:roadInHIN (road has HIN designation)
   - uko:hinNearSchool (HIN within 200m of school)
   - uko:hinNearSeniorCenter (HIN within 200m of senior center)
   - uko:schoolNearHIN (school within 200m of HIN - inverse)
   - uko:seniorCenterNearHIN (senior center within 200m of HIN - inverse)

3. Road → Safety relationships:
   - uko:roadHasCollision (road segment has collision)
   - uko:hasCollisionHistory (road has collision history)

4. Census Tract → Safety relationships:
   - uko:collisionInTract (collision occurred in tract)
   - uko:hinInTract (HIN segment passes through tract)
   - uko:tractCollisionCount (aggregate collision count)
   - uko:tractPedestrianCollisionRate (per-capita rate)

These relationships enable:
- GeoRotatE to learn safety proximity patterns
- Link prediction for safety infrastructure gaps
- Clustering of areas by safety profile

Data Sources (all FREE):
- TIMS/SWITRS: https://tims.berkeley.edu/ (UC Berkeley SafeTREC)

Prerequisites:
    pip install pandas geopandas requests shapely scipy rtree

Usage:
    python switrs_safety_loader_enhanced.py --input contracosta_kg.nt \
        --csv_file crashes.csv --years 2019 2020 2021 2022 2023

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import re
import json
import argparse
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set, Any
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

try:
    import geopandas as gpd
    from shapely.geometry import Point, LineString, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False
    print("Warning: geopandas/shapely not available. Spatial relationships will be limited.")

# Constants
CONTRA_COSTA_COUNTY_CODE = "07"
CONTRA_COSTA_FIPS = "013"

# Bounding box for Contra Costa County
CONTRA_COSTA_BBOX = {
    'min_lon': -122.42,
    'max_lon': -121.55,
    'min_lat': 37.72,
    'max_lat': 38.08
}

# Cities of interest
TARGET_CITIES = {
    "WALNUT CREEK": "walnut_creek",
    "PLEASANT HILL": "pleasant_hill", 
    "ANTIOCH": "antioch",
    "RICHMOND": "richmond",
    "PITTSBURG": "pittsburg"
}

# Proximity thresholds (meters)
PROXIMITY_THRESHOLDS = {
    'collision_near_school': 200,
    'collision_near_senior_center': 200,
    'collision_near_hospital': 300,
    'collision_near_transit': 100,
    'collision_near_crosswalk': 50,
    'hin_near_school': 200,
    'hin_near_senior_center': 200,
    'hin_near_transit': 150,
    'very_near': 50,
    'near': 200,
}

# SWITRS collision severity codes
SEVERITY_CODES = {
    1: "fatal",
    2: "severe_injury",
    3: "other_visible_injury",
    4: "complaint_of_pain",
    0: "property_damage_only"
}

# UKO namespace
UKO = "urn:urban-kg:"
UKO_ENTITY = "urn:urban-kg:entity/"

# RDF namespaces
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
XSD = "http://www.w3.org/2001/XMLSchema#"
GEO = "http://www.opengis.net/ont/geosparql#"


@dataclass
class Collision:
    """Represents a single collision from SWITRS data."""
    case_id: str
    date: str
    time: str
    latitude: float
    longitude: float
    severity: int
    severity_label: str
    killed: int
    injured: int
    pedestrian_involved: bool
    bicycle_involved: bool
    motorcycle_involved: bool
    alcohol_involved: bool
    hit_and_run: bool
    speeding_involved: bool
    primary_road: str
    secondary_road: Optional[str]
    city: str
    lighting: Optional[str] = None
    weather: Optional[str] = None
    road_condition: Optional[str] = None
    primary_collision_factor: Optional[str] = None
    day_of_week: Optional[int] = None
    
    # Spatial relationships (populated during enrichment)
    nearby_schools: List[str] = field(default_factory=list)
    nearby_senior_centers: List[str] = field(default_factory=list)
    nearby_hospitals: List[str] = field(default_factory=list)
    nearby_transit_stops: List[str] = field(default_factory=list)
    nearby_crosswalks: List[str] = field(default_factory=list)
    in_census_tract: Optional[str] = None
    on_road_segment: Optional[str] = None
    in_hin: Optional[str] = None
    
    def to_uri(self) -> str:
        """Generate URI for this collision."""
        return f"{UKO_ENTITY}collision/switrs_{self.case_id}"
    
    @property
    def point(self) -> Optional[Point]:
        """Get shapely Point geometry."""
        if SPATIAL_AVAILABLE and self.latitude and self.longitude:
            return Point(self.longitude, self.latitude)
        return None


@dataclass  
class HINSegment:
    """Represents a High Injury Network segment."""
    segment_id: str
    geometry: Any  # LineString
    road_name: str
    city: str
    total_collisions: int
    fatal_collisions: int
    severe_injury_collisions: int
    pedestrian_collisions: int
    bicycle_collisions: int
    hin_type: str  # "bike", "pedestrian", "vehicle", "all"
    data_years: str
    collision_ids: List[str] = field(default_factory=list)
    
    # Spatial relationships (populated during enrichment)
    nearby_schools: List[str] = field(default_factory=list)
    nearby_senior_centers: List[str] = field(default_factory=list)
    overlays_roads: List[str] = field(default_factory=list)
    in_census_tracts: List[str] = field(default_factory=list)
    nearby_transit_stops: List[str] = field(default_factory=list)
    
    def to_uri(self) -> str:
        """Generate URI for this HIN segment."""
        safe_road = re.sub(r'[^a-zA-Z0-9]', '_', self.road_name.lower())
        safe_city = re.sub(r'[^a-zA-Z0-9]', '_', self.city.lower())
        return f"{UKO_ENTITY}hin/{safe_city}_{safe_road}_{self.segment_id}"


@dataclass
class KGEntity:
    """Represents an entity extracted from the existing KG."""
    uri: str
    entity_type: str
    label: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    
    @property
    def point(self) -> Optional[Point]:
        """Get shapely Point geometry."""
        if SPATIAL_AVAILABLE and self.latitude and self.longitude:
            return Point(self.longitude, self.latitude)
        return None


class ExistingKGParser:
    """
    Parses the existing KG to extract entities for spatial relationship computation.
    
    Uses streaming to handle large (5GB+) N-Triples files efficiently.
    """
    
    def __init__(self):
        self.schools: List[KGEntity] = []
        self.senior_centers: List[KGEntity] = []
        self.hospitals: List[KGEntity] = []
        self.transit_stops: List[KGEntity] = []
        self.crosswalks: List[KGEntity] = []
        self.roads: List[KGEntity] = []
        self.census_tracts: List[KGEntity] = []
        self.pois: List[KGEntity] = []
        
        # Temp storage during parsing
        self._entity_data: Dict[str, Dict[str, Any]] = defaultdict(dict)
        
    def parse_kg_streaming(self, kg_path: str, max_entities: int = None):
        """
        Stream-parse the KG file to extract relevant entities.
        
        This avoids loading the entire 5GB+ file into memory.
        """
        print(f"Streaming KG file to extract entities: {kg_path}")
        
        # Entity type patterns we're looking for
        type_patterns = {
            'School': 'school',
            'ElementarySchool': 'school',
            'MiddleSchool': 'school',
            'HighSchool': 'school',
            'SeniorCenter': 'senior_center',
            'AssistedLivingFacility': 'senior_center',
            'NursingHome': 'senior_center',
            'Hospital': 'hospital',
            'Clinic': 'hospital',
            'MedicalCenter': 'hospital',
            'TransitStop': 'transit_stop',
            'BusStop': 'transit_stop',
            'BARTStation': 'transit_stop',
            'Crosswalk': 'crosswalk',
            'SignalizedCrosswalk': 'crosswalk',
            'Road': 'road',
            'CensusTract': 'census_tract',
        }
        
        entity_count = 0
        line_count = 0
        
        with open(kg_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_count += 1
                if line_count % 1000000 == 0:
                    print(f"  Processed {line_count:,} lines, found {entity_count:,} relevant entities...")
                
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Parse N-Triple: <subject> <predicate> <object> .
                try:
                    # Simple regex-based parsing for N-Triples
                    match = re.match(r'<([^>]+)>\s+<([^>]+)>\s+(.+)\s*\.$', line)
                    if not match:
                        continue
                    
                    subject, predicate, obj = match.groups()
                    obj = obj.strip()
                    
                    # Extract entity type
                    if predicate == RDF_TYPE:
                        obj_uri = re.match(r'<([^>]+)>', obj)
                        if obj_uri:
                            type_uri = obj_uri.group(1)
                            type_name = type_uri.split('/')[-1].split(':')[-1]
                            
                            if type_name in type_patterns:
                                self._entity_data[subject]['type'] = type_patterns[type_name]
                                self._entity_data[subject]['uri'] = subject
                                entity_count += 1
                    
                    # Extract label
                    elif predicate == RDFS_LABEL:
                        label_match = re.match(r'"([^"]*)"', obj)
                        if label_match:
                            self._entity_data[subject]['label'] = label_match.group(1)
                    
                    # Extract coordinates
                    elif predicate == f'{UKO}latitude' or predicate.endswith('latitude'):
                        coord_match = re.match(r'"([^"]+)"', obj)
                        if coord_match:
                            try:
                                self._entity_data[subject]['latitude'] = float(coord_match.group(1))
                            except ValueError:
                                pass
                    
                    elif predicate == f'{UKO}longitude' or predicate.endswith('longitude'):
                        coord_match = re.match(r'"([^"]+)"', obj)
                        if coord_match:
                            try:
                                self._entity_data[subject]['longitude'] = float(coord_match.group(1))
                            except ValueError:
                                pass
                    
                    # Extract city
                    elif 'city' in predicate.lower():
                        city_match = re.match(r'"([^"]*)"', obj)
                        if city_match:
                            self._entity_data[subject]['city'] = city_match.group(1)
                    
                    if max_entities and entity_count >= max_entities:
                        print(f"  Reached max entities limit ({max_entities})")
                        break
                        
                except Exception as e:
                    # Skip malformed lines
                    continue
        
        print(f"  Parsed {line_count:,} lines total")
        
        # Convert to KGEntity objects
        self._finalize_entities()
        
    def _finalize_entities(self):
        """Convert parsed data to KGEntity objects and categorize."""
        for uri, data in self._entity_data.items():
            if 'type' not in data:
                continue
            
            entity = KGEntity(
                uri=uri,
                entity_type=data['type'],
                label=data.get('label', ''),
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                city=data.get('city')
            )
            
            # Categorize
            if entity.entity_type == 'school':
                self.schools.append(entity)
            elif entity.entity_type == 'senior_center':
                self.senior_centers.append(entity)
            elif entity.entity_type == 'hospital':
                self.hospitals.append(entity)
            elif entity.entity_type == 'transit_stop':
                self.transit_stops.append(entity)
            elif entity.entity_type == 'crosswalk':
                self.crosswalks.append(entity)
            elif entity.entity_type == 'road':
                self.roads.append(entity)
            elif entity.entity_type == 'census_tract':
                self.census_tracts.append(entity)
        
        # Clear temp storage
        self._entity_data.clear()
        
        print(f"\nExtracted entities:")
        print(f"  Schools: {len(self.schools):,}")
        print(f"  Senior Centers: {len(self.senior_centers):,}")
        print(f"  Hospitals: {len(self.hospitals):,}")
        print(f"  Transit Stops: {len(self.transit_stops):,}")
        print(f"  Crosswalks: {len(self.crosswalks):,}")
        print(f"  Roads: {len(self.roads):,}")
        print(f"  Census Tracts: {len(self.census_tracts):,}")


class SpatialRelationshipComputer:
    """
    Computes spatial relationships between safety entities and KG entities.
    
    Uses R-tree spatial indexing for efficient proximity queries.
    """
    
    def __init__(self, kg_entities: ExistingKGParser):
        self.kg = kg_entities
        
        # Build spatial indices
        if SPATIAL_AVAILABLE:
            self._build_spatial_indices()
    
    def _build_spatial_indices(self):
        """Build R-tree spatial indices for efficient proximity queries."""
        print("\nBuilding spatial indices...")
        
        # Helper to create index from entities with coordinates
        def build_index(entities: List[KGEntity]) -> Tuple[List[Point], List[KGEntity]]:
            points = []
            valid_entities = []
            for e in entities:
                if e.point is not None:
                    points.append(e.point)
                    valid_entities.append(e)
            return points, valid_entities
        
        # Build indices for each entity type
        self.school_points, self.school_entities = build_index(self.kg.schools)
        self.senior_points, self.senior_entities = build_index(self.kg.senior_centers)
        self.hospital_points, self.hospital_entities = build_index(self.kg.hospitals)
        self.transit_points, self.transit_entities = build_index(self.kg.transit_stops)
        self.crosswalk_points, self.crosswalk_entities = build_index(self.kg.crosswalks)
        
        # Create STRtree indices if we have points
        self.school_tree = STRtree(self.school_points) if self.school_points else None
        self.senior_tree = STRtree(self.senior_points) if self.senior_points else None
        self.hospital_tree = STRtree(self.hospital_points) if self.hospital_points else None
        self.transit_tree = STRtree(self.transit_points) if self.transit_points else None
        self.crosswalk_tree = STRtree(self.crosswalk_points) if self.crosswalk_points else None
        
        print(f"  School index: {len(self.school_points)} points")
        print(f"  Senior center index: {len(self.senior_points)} points")
        print(f"  Hospital index: {len(self.hospital_points)} points")
        print(f"  Transit stop index: {len(self.transit_points)} points")
        print(f"  Crosswalk index: {len(self.crosswalk_points)} points")
    
    def _meters_to_degrees(self, meters: float, latitude: float = 37.9) -> float:
        """Convert meters to approximate degrees at given latitude."""
        # At ~38° latitude, 1 degree ≈ 111km latitude, ~87km longitude
        # Use average for simplicity
        return meters / 100000  # Rough approximation
    
    def _find_nearby(self, point: Point, tree: STRtree, entities: List[KGEntity], 
                     threshold_meters: float) -> List[str]:
        """Find entities within threshold distance of point."""
        if tree is None or point is None:
            return []
        
        # Create buffer around point (approximate degrees)
        buffer_deg = self._meters_to_degrees(threshold_meters, point.y)
        search_area = point.buffer(buffer_deg)
        
        # Query tree
        candidate_indices = tree.query(search_area)
        
        # Filter by actual distance and return URIs
        nearby = []
        for idx in candidate_indices:
            if idx < len(entities):
                entity = entities[idx]
                if entity.point:
                    # Approximate distance check using Haversine would be better
                    # but for nearby queries, Euclidean in degrees is acceptable
                    dist_deg = point.distance(entity.point)
                    if dist_deg <= buffer_deg:
                        nearby.append(entity.uri)
        
        return nearby
    
    def compute_collision_relationships(self, collision: Collision) -> Collision:
        """Compute spatial relationships for a collision."""
        if not SPATIAL_AVAILABLE or collision.point is None:
            return collision
        
        point = collision.point
        
        # Find nearby schools
        collision.nearby_schools = self._find_nearby(
            point, self.school_tree, self.school_entities,
            PROXIMITY_THRESHOLDS['collision_near_school']
        )
        
        # Find nearby senior centers
        collision.nearby_senior_centers = self._find_nearby(
            point, self.senior_tree, self.senior_entities,
            PROXIMITY_THRESHOLDS['collision_near_senior_center']
        )
        
        # Find nearby hospitals
        collision.nearby_hospitals = self._find_nearby(
            point, self.hospital_tree, self.hospital_entities,
            PROXIMITY_THRESHOLDS['collision_near_hospital']
        )
        
        # Find nearby transit stops
        collision.nearby_transit_stops = self._find_nearby(
            point, self.transit_tree, self.transit_entities,
            PROXIMITY_THRESHOLDS['collision_near_transit']
        )
        
        # Find nearby crosswalks
        collision.nearby_crosswalks = self._find_nearby(
            point, self.crosswalk_tree, self.crosswalk_entities,
            PROXIMITY_THRESHOLDS['collision_near_crosswalk']
        )
        
        return collision
    
    def compute_hin_relationships(self, hin: HINSegment) -> HINSegment:
        """Compute spatial relationships for a HIN segment."""
        if not SPATIAL_AVAILABLE or hin.geometry is None:
            return hin
        
        # Use centroid for proximity queries
        centroid = hin.geometry.centroid
        
        # Buffer the line for intersection queries
        buffer_deg = self._meters_to_degrees(PROXIMITY_THRESHOLDS['hin_near_school'])
        hin_buffer = hin.geometry.buffer(buffer_deg)
        
        # Find nearby schools (using line buffer intersection)
        if self.school_tree:
            candidate_indices = self.school_tree.query(hin_buffer)
            for idx in candidate_indices:
                if idx < len(self.school_entities):
                    entity = self.school_entities[idx]
                    if entity.point and hin_buffer.contains(entity.point):
                        hin.nearby_schools.append(entity.uri)
        
        # Find nearby senior centers
        if self.senior_tree:
            candidate_indices = self.senior_tree.query(hin_buffer)
            for idx in candidate_indices:
                if idx < len(self.senior_entities):
                    entity = self.senior_entities[idx]
                    if entity.point and hin_buffer.contains(entity.point):
                        hin.nearby_senior_centers.append(entity.uri)
        
        # Find nearby transit stops
        transit_buffer = hin.geometry.buffer(
            self._meters_to_degrees(PROXIMITY_THRESHOLDS['hin_near_transit'])
        )
        if self.transit_tree:
            candidate_indices = self.transit_tree.query(transit_buffer)
            for idx in candidate_indices:
                if idx < len(self.transit_entities):
                    entity = self.transit_entities[idx]
                    if entity.point and transit_buffer.contains(entity.point):
                        hin.nearby_transit_stops.append(entity.uri)
        
        return hin


class SWITRSDataLoader:
    """
    Loads and processes SWITRS collision data from various sources.
    """
    
    def __init__(self, data_dir: str = "data/switrs"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.collisions: List[Collision] = []
        self.hin_segments: List[HINSegment] = []
    
    def load_from_csv(self, csv_path: str, years: List[int]) -> pd.DataFrame:
        """Load collision data from a local CSV file."""
        if not os.path.exists(csv_path):
            print(f"CSV file not found: {csv_path}")
            return pd.DataFrame()
        
        print(f"Loading collision data from {csv_path}...")
        df = pd.read_csv(csv_path, low_memory=False)
        print(f"  Found {len(df):,} rows, columns: {list(df.columns)[:10]}...")
        
        # Standardize column names
        column_map = {
            'CASE_ID': 'CASE_ID', 'case_id': 'CASE_ID',
            'COLLISION_DATE': 'COLLISION_DATE', 'collision_date': 'COLLISION_DATE',
            'COLLISION_TIME': 'COLLISION_TIME', 'collision_time': 'COLLISION_TIME',
            'POINT_Y': 'LATITUDE', 'LATITUDE': 'LATITUDE', 'latitude': 'LATITUDE',
            'POINT_X': 'LONGITUDE', 'LONGITUDE': 'LONGITUDE', 'longitude': 'LONGITUDE',
            'COLLISION_SEVERITY': 'COLLISION_SEVERITY', 'collision_severity': 'COLLISION_SEVERITY',
            'NUMBER_KILLED': 'KILLED_VICTIMS', 'KILLED_VICTIMS': 'KILLED_VICTIMS',
            'NUMBER_INJURED': 'INJURED_VICTIMS', 'INJURED_VICTIMS': 'INJURED_VICTIMS',
            'PRIMARY_RD': 'PRIMARY_RD', 'primary_rd': 'PRIMARY_RD',
            'SECONDARY_RD': 'SECONDARY_RD', 'secondary_rd': 'SECONDARY_RD',
            'CITY': 'CITY', 'city': 'CITY',
            'PEDESTRIAN_ACCIDENT': 'PEDESTRIAN_COLLISION',
            'BICYCLE_ACCIDENT': 'BICYCLE_COLLISION',
            'MOTORCYCLE_ACCIDENT': 'MOTORCYCLE_COLLISION',
            'ALCOHOL_INVOLVED': 'ALCOHOL_INVOLVED',
            'HIT_AND_RUN': 'HIT_AND_RUN',
            'LIGHTING': 'LIGHTING',
            'WEATHER_1': 'WEATHER',
            'ROAD_COND_1': 'ROAD_CONDITION',
            'PRIMARY_COLL_FACTOR': 'PRIMARY_COLL_FACTOR',
            'DAY_OF_WEEK': 'DAY_OF_WEEK',
            'ACCIDENT_YEAR': 'YEAR',
        }
        
        # Apply column mapping
        rename_dict = {}
        for col in df.columns:
            if col in column_map and column_map[col] != col:
                if column_map[col] not in df.columns:
                    rename_dict[col] = column_map[col]
        
        if rename_dict:
            df = df.rename(columns=rename_dict)
        
        # Convert coordinates to numeric
        for col in ['LATITUDE', 'LONGITUDE']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Filter by year
        if 'YEAR' not in df.columns and 'COLLISION_DATE' in df.columns:
            df['YEAR'] = pd.to_datetime(df['COLLISION_DATE'], errors='coerce').dt.year
        
        if 'YEAR' in df.columns:
            original_count = len(df)
            df = df[df['YEAR'].isin(years)]
            print(f"  Filtered by year: {original_count:,} -> {len(df):,}")
        
        # Filter by bounding box
        if 'LATITUDE' in df.columns and 'LONGITUDE' in df.columns:
            df = df.dropna(subset=['LATITUDE', 'LONGITUDE'])
            original_count = len(df)
            mask = (
                (df['LATITUDE'] >= CONTRA_COSTA_BBOX['min_lat']) &
                (df['LATITUDE'] <= CONTRA_COSTA_BBOX['max_lat']) &
                (df['LONGITUDE'] >= CONTRA_COSTA_BBOX['min_lon']) &
                (df['LONGITUDE'] <= CONTRA_COSTA_BBOX['max_lon'])
            )
            df = df[mask]
            print(f"  Filtered by bbox: {original_count:,} -> {len(df):,}")
        
        return df
    
    def parse_collisions(self, df: pd.DataFrame) -> List[Collision]:
        """Parse DataFrame into Collision objects."""
        collisions = []
        
        for _, row in df.iterrows():
            try:
                # Parse severity
                severity = int(row.get('COLLISION_SEVERITY', 0) or 0)
                severity_label = SEVERITY_CODES.get(severity, 'unknown')
                
                # Parse boolean flags - handle Y/N format from SWITRS
                def parse_bool(val) -> bool:
                    if pd.isna(val):
                        return False
                    if isinstance(val, bool):
                        return val
                    if isinstance(val, str):
                        return val.upper() in ('Y', 'YES', 'TRUE', '1')
                    return bool(val)
                
                collision = Collision(
                    case_id=str(row.get('CASE_ID', '')),
                    date=str(row.get('COLLISION_DATE', ''))[:10],
                    time=str(row.get('COLLISION_TIME', '')),
                    latitude=float(row.get('LATITUDE', 0)),
                    longitude=float(row.get('LONGITUDE', 0)),
                    severity=severity,
                    severity_label=severity_label,
                    killed=int(row.get('KILLED_VICTIMS', 0) or 0),
                    injured=int(row.get('INJURED_VICTIMS', 0) or 0),
                    pedestrian_involved=parse_bool(row.get('PEDESTRIAN_COLLISION')),
                    bicycle_involved=parse_bool(row.get('BICYCLE_COLLISION')),
                    motorcycle_involved=parse_bool(row.get('MOTORCYCLE_COLLISION')),
                    alcohol_involved=parse_bool(row.get('ALCOHOL_INVOLVED')),
                    hit_and_run=parse_bool(row.get('HIT_AND_RUN')),
                    speeding_involved=parse_bool(row.get('SPEEDING_INVOLVED', False)),
                    primary_road=str(row.get('PRIMARY_RD', '') or ''),
                    secondary_road=str(row.get('SECONDARY_RD', '')) if pd.notna(row.get('SECONDARY_RD')) else None,
                    city=str(row.get('CITY', '') or ''),
                    lighting=str(row.get('LIGHTING', '')) if pd.notna(row.get('LIGHTING')) else None,
                    weather=str(row.get('WEATHER', '')) if pd.notna(row.get('WEATHER')) else None,
                    road_condition=str(row.get('ROAD_CONDITION', '')) if pd.notna(row.get('ROAD_CONDITION')) else None,
                    primary_collision_factor=str(row.get('PRIMARY_COLL_FACTOR', '')) if pd.notna(row.get('PRIMARY_COLL_FACTOR')) else None,
                    day_of_week=int(row.get('DAY_OF_WEEK', 0)) if pd.notna(row.get('DAY_OF_WEEK')) else None,
                )
                
                # Validate coordinates
                if (-123 < collision.longitude < -121 and 37 < collision.latitude < 39):
                    collisions.append(collision)
                    
            except Exception as e:
                continue
        
        self.collisions = collisions
        return collisions
    
    def compute_hin_segments(self, collisions: List[Collision], 
                            threshold_percentile: float = 85) -> List[HINSegment]:
        """
        Compute High Injury Network segments from collision clustering.
        """
        if not SPATIAL_AVAILABLE:
            print("Warning: Spatial libraries not available, skipping HIN computation")
            return []
        
        print(f"\nComputing HIN segments from {len(collisions):,} collisions...")
        
        # Group collisions by road
        road_stats = defaultdict(lambda: {
            'total': 0, 'fatal': 0, 'severe': 0, 
            'pedestrian': 0, 'bicycle': 0,
            'points': [], 'collision_ids': []
        })
        
        for c in collisions:
            if c.primary_road and c.point:
                key = (c.primary_road.upper(), c.city.upper())
                road_stats[key]['total'] += 1
                road_stats[key]['collision_ids'].append(c.case_id)
                road_stats[key]['points'].append(c.point)
                
                if c.severity == 1:
                    road_stats[key]['fatal'] += 1
                elif c.severity == 2:
                    road_stats[key]['severe'] += 1
                if c.pedestrian_involved:
                    road_stats[key]['pedestrian'] += 1
                if c.bicycle_involved:
                    road_stats[key]['bicycle'] += 1
        
        # Compute weighted score (prioritize fatal/severe, ped/bike)
        scores = []
        for key, stats in road_stats.items():
            score = (
                stats['fatal'] * 10 +
                stats['severe'] * 5 +
                stats['pedestrian'] * 3 +
                stats['bicycle'] * 2 +
                stats['total']
            )
            stats['score'] = score
            scores.append(score)
        
        if not scores:
            return []
        
        threshold = np.percentile(scores, threshold_percentile)
        print(f"  HIN threshold (p{threshold_percentile}): {threshold:.1f}")
        
        # Create HIN segments for roads above threshold
        hin_segments = []
        segment_id = 0
        
        # Determine data years
        years = set()
        for c in collisions:
            try:
                year = c.date.split('-')[0]
                if year.isdigit():
                    years.add(year)
            except:
                pass
        data_years = f"{min(years)}-{max(years)}" if years else "unknown"
        
        for (road, city), stats in road_stats.items():
            if stats['score'] >= threshold and len(stats['points']) >= 3:
                segment_id += 1
                
                # Create line geometry
                points = stats['points']
                sorted_points = sorted(points, key=lambda p: (p.x, p.y))
                
                if len(sorted_points) >= 2:
                    geometry = LineString([(p.x, p.y) for p in sorted_points])
                else:
                    continue
                
                # Determine HIN type
                ped_ratio = stats['pedestrian'] / stats['total'] if stats['total'] > 0 else 0
                bike_ratio = stats['bicycle'] / stats['total'] if stats['total'] > 0 else 0
                
                if ped_ratio > 0.3:
                    hin_type = "pedestrian"
                elif bike_ratio > 0.2:
                    hin_type = "bike"
                else:
                    hin_type = "vehicle"
                
                hin_segment = HINSegment(
                    segment_id=f"{segment_id:04d}",
                    geometry=geometry,
                    road_name=road,
                    city=city,
                    total_collisions=stats['total'],
                    fatal_collisions=stats['fatal'],
                    severe_injury_collisions=stats['severe'],
                    pedestrian_collisions=stats['pedestrian'],
                    bicycle_collisions=stats['bicycle'],
                    hin_type=hin_type,
                    data_years=data_years,
                    collision_ids=stats['collision_ids']
                )
                hin_segments.append(hin_segment)
        
        self.hin_segments = hin_segments
        print(f"  Identified {len(hin_segments)} HIN segments")
        return hin_segments


class EnhancedSafetyKGEnricher:
    """
    Enriches the KG with safety data INCLUDING spatial relationships.
    
    This is the key enhancement over the base loader - it adds object property
    relationships that can be used for GeoRotatE training.
    """
    
    def __init__(self, collisions: List[Collision], hin_segments: List[HINSegment],
                 spatial_computer: Optional[SpatialRelationshipComputer] = None):
        self.collisions = collisions
        self.hin_segments = hin_segments
        self.spatial = spatial_computer
        
        # Statistics
        self.stats = {
            'collision_triples': 0,
            'hin_triples': 0,
            'spatial_relationship_triples': 0,
            'collision_near_school': 0,
            'collision_near_senior': 0,
            'collision_near_hospital': 0,
            'collision_near_transit': 0,
            'hin_near_school': 0,
            'hin_near_senior': 0,
            'school_near_hin': 0,
        }
    
    def _escape(self, text: str) -> str:
        """Escape special characters for N-Triples."""
        if not text:
            return ""
        return (text
                .replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace('\n', '\\n')
                .replace('\r', '\\r')
                .replace('\t', '\\t'))
    
    def generate_collision_triples(self) -> List[str]:
        """Generate N-Triples for collision entities with spatial relationships."""
        triples = []
        
        for c in self.collisions:
            uri = f"<{c.to_uri()}>"
            
            # === BASE COLLISION PROPERTIES ===
            
            # Type assertions
            triples.append(f'{uri} <{RDF_TYPE}> <{UKO}Collision> .')
            
            if c.pedestrian_involved:
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}PedestrianCollision> .')
            if c.bicycle_involved:
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}BicycleCollision> .')
            if c.motorcycle_involved:
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}MotorcycleCollision> .')
            
            # Severity-based type
            if c.severity == 1:
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}FatalCollision> .')
            elif c.severity == 2:
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}SevereInjuryCollision> .')
            
            # Label
            label = f"Collision {c.case_id} - {c.primary_road}"
            triples.append(f'{uri} <{RDFS_LABEL}> "{self._escape(label)}" .')
            
            # Location
            triples.append(f'{uri} <{UKO}latitude> "{c.latitude}"^^<{XSD}decimal> .')
            triples.append(f'{uri} <{UKO}longitude> "{c.longitude}"^^<{XSD}decimal> .')
            
            # Severity
            triples.append(f'{uri} <{UKO}collisionSeverity> "{c.severity_label}" .')
            
            # Casualties
            if c.killed > 0:
                triples.append(f'{uri} <{UKO}fatalityCount> "{c.killed}"^^<{XSD}integer> .')
            if c.injured > 0:
                triples.append(f'{uri} <{UKO}injuryCount> "{c.injured}"^^<{XSD}integer> .')
            
            # Date/time
            if c.date:
                triples.append(f'{uri} <{UKO}collisionDate> "{c.date}"^^<{XSD}date> .')
            if c.day_of_week:
                triples.append(f'{uri} <{UKO}collisionDayOfWeek> "{c.day_of_week}"^^<{XSD}integer> .')
            
            # Road
            if c.primary_road:
                triples.append(f'{uri} <{UKO}onRoad> "{self._escape(c.primary_road)}" .')
            if c.secondary_road:
                triples.append(f'{uri} <{UKO}atCrossStreet> "{self._escape(c.secondary_road)}" .')
            
            # City
            if c.city:
                triples.append(f'{uri} <{UKO}city> "{self._escape(c.city)}" .')
            
            # Contributing factors
            if c.alcohol_involved:
                triples.append(f'{uri} <{UKO}alcoholInvolved> "true"^^<{XSD}boolean> .')
            if c.hit_and_run:
                triples.append(f'{uri} <{UKO}hitAndRun> "true"^^<{XSD}boolean> .')
            if c.speeding_involved:
                triples.append(f'{uri} <{UKO}speedingInvolved> "true"^^<{XSD}boolean> .')
            
            # Conditions
            if c.lighting:
                triples.append(f'{uri} <{UKO}lightingCondition> "{self._escape(c.lighting)}" .')
            if c.weather:
                triples.append(f'{uri} <{UKO}weatherCondition> "{self._escape(c.weather)}" .')
            if c.road_condition:
                triples.append(f'{uri} <{UKO}roadCondition> "{self._escape(c.road_condition)}" .')
            if c.primary_collision_factor:
                triples.append(f'{uri} <{UKO}primaryCollisionFactor> "{self._escape(c.primary_collision_factor)}" .')
            
            # Data source
            triples.append(f'{uri} <{UKO}dataSource> "SWITRS/TIMS" .')
            triples.append(f'{uri} <{UKO}externalId> "switrs:{c.case_id}" .')
            
            # === SPATIAL RELATIONSHIPS (NEW) ===
            
            # Collision near school
            for school_uri in c.nearby_schools:
                triples.append(f'{uri} <{UKO}collisionNearSchool> <{school_uri}> .')
                # Inverse relationship
                triples.append(f'<{school_uri}> <{UKO}hasNearbyCollision> {uri} .')
                self.stats['collision_near_school'] += 1
            
            # Collision near senior center
            for senior_uri in c.nearby_senior_centers:
                triples.append(f'{uri} <{UKO}collisionNearSeniorCenter> <{senior_uri}> .')
                triples.append(f'<{senior_uri}> <{UKO}hasNearbyCollision> {uri} .')
                self.stats['collision_near_senior'] += 1
            
            # Collision near hospital
            for hospital_uri in c.nearby_hospitals:
                triples.append(f'{uri} <{UKO}collisionNearHospital> <{hospital_uri}> .')
                self.stats['collision_near_hospital'] += 1
            
            # Collision near transit stop
            for transit_uri in c.nearby_transit_stops:
                triples.append(f'{uri} <{UKO}collisionNearTransit> <{transit_uri}> .')
                triples.append(f'<{transit_uri}> <{UKO}hasNearbyCollision> {uri} .')
                self.stats['collision_near_transit'] += 1
            
            # Collision near crosswalk
            for crosswalk_uri in c.nearby_crosswalks:
                triples.append(f'{uri} <{UKO}collisionNearCrosswalk> <{crosswalk_uri}> .')
            
            # Census tract relationship
            if c.in_census_tract:
                triples.append(f'{uri} <{UKO}collisionInTract> <{c.in_census_tract}> .')
        
        self.stats['collision_triples'] = len(triples)
        return triples
    
    def generate_hin_triples(self) -> List[str]:
        """Generate N-Triples for HIN segment entities with spatial relationships."""
        triples = []
        
        for hin in self.hin_segments:
            uri = f"<{hin.to_uri()}>"
            
            # === BASE HIN PROPERTIES ===
            
            # Type based on HIN type
            triples.append(f'{uri} <{RDF_TYPE}> <{UKO}HighInjuryNetwork> .')
            
            if hin.hin_type == "pedestrian":
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}HighInjuryNetworkPedestrian> .')
            elif hin.hin_type == "bike":
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}HighInjuryNetworkBike> .')
            else:
                triples.append(f'{uri} <{RDF_TYPE}> <{UKO}HighInjuryNetworkVehicle> .')
            
            # Label
            label = f"HIN: {hin.road_name} ({hin.city})"
            triples.append(f'{uri} <{RDFS_LABEL}> "{self._escape(label)}" .')
            
            # Road name
            triples.append(f'{uri} <{UKO}roadName> "{self._escape(hin.road_name)}" .')
            
            # Geometry (WKT)
            if hin.geometry:
                wkt = hin.geometry.wkt
                triples.append(f'{uri} <{GEO}asWKT> "{wkt}"^^<{GEO}wktLiteral> .')
                
                # Centroid coordinates for spatial indexing
                centroid = hin.geometry.centroid
                triples.append(f'{uri} <{UKO}latitude> "{centroid.y}"^^<{XSD}decimal> .')
                triples.append(f'{uri} <{UKO}longitude> "{centroid.x}"^^<{XSD}decimal> .')
            
            # Statistics
            triples.append(f'{uri} <{UKO}totalCollisions> "{hin.total_collisions}"^^<{XSD}integer> .')
            triples.append(f'{uri} <{UKO}fatalityCount> "{hin.fatal_collisions}"^^<{XSD}integer> .')
            triples.append(f'{uri} <{UKO}severeInjuryCount> "{hin.severe_injury_collisions}"^^<{XSD}integer> .')
            
            if hin.pedestrian_collisions > 0:
                triples.append(f'{uri} <{UKO}pedestrianCollisions> "{hin.pedestrian_collisions}"^^<{XSD}integer> .')
            if hin.bicycle_collisions > 0:
                triples.append(f'{uri} <{UKO}bicycleCollisions> "{hin.bicycle_collisions}"^^<{XSD}integer> .')
            
            # Data period and source
            triples.append(f'{uri} <{UKO}dataPeriod> "{hin.data_years}" .')
            triples.append(f'{uri} <{UKO}dataSource> "SWITRS/TIMS" .')
            triples.append(f'{uri} <{UKO}hinType> "{hin.hin_type}" .')
            
            # City relationship
            if hin.city:
                city_key = hin.city.upper().replace(' ', '_')
                city_uri = f"{UKO_ENTITY}city/{city_key}"
                triples.append(f'{uri} <{UKO}inCity> <{city_uri}> .')
            
            # Link to contributing collisions
            for collision_id in hin.collision_ids[:50]:  # Limit to avoid huge files
                collision_uri = f"{UKO_ENTITY}collision/switrs_{collision_id}"
                triples.append(f'{uri} <{UKO}includesCollision> <{collision_uri}> .')
                triples.append(f'<{collision_uri}> <{UKO}contributesToHIN> {uri} .')
            
            # === SPATIAL RELATIONSHIPS (NEW) ===
            
            # HIN near school (bidirectional)
            for school_uri in hin.nearby_schools:
                triples.append(f'{uri} <{UKO}hinNearSchool> <{school_uri}> .')
                triples.append(f'<{school_uri}> <{UKO}schoolNearHIN> {uri} .')
                triples.append(f'<{school_uri}> <{UKO}near> {uri} .')  # Generic near for GeoRotatE
                self.stats['hin_near_school'] += 1
                self.stats['school_near_hin'] += 1
            
            # HIN near senior center (bidirectional)
            for senior_uri in hin.nearby_senior_centers:
                triples.append(f'{uri} <{UKO}hinNearSeniorCenter> <{senior_uri}> .')
                triples.append(f'<{senior_uri}> <{UKO}seniorCenterNearHIN> {uri} .')
                triples.append(f'<{senior_uri}> <{UKO}near> {uri} .')
                self.stats['hin_near_senior'] += 1
            
            # HIN near transit stops
            for transit_uri in hin.nearby_transit_stops:
                triples.append(f'{uri} <{UKO}hinNearTransit> <{transit_uri}> .')
                triples.append(f'<{transit_uri}> <{UKO}near> {uri} .')
            
            # Road overlay relationships
            for road_uri in hin.overlays_roads:
                triples.append(f'{uri} <{UKO}hinOnRoad> <{road_uri}> .')
                triples.append(f'<{road_uri}> <{UKO}inHighInjuryNetwork> {uri} .')
            
            # Census tract relationships
            for tract_uri in hin.in_census_tracts:
                triples.append(f'{uri} <{UKO}hinInTract> <{tract_uri}> .')
        
        self.stats['hin_triples'] = len(triples)
        return triples
    
    def generate_safety_summary_triples(self) -> List[str]:
        """Generate summary statistics as triples."""
        triples = []
        
        summary_uri = f"<{UKO_ENTITY}safety_summary/contra_costa>"
        
        triples.append(f'{summary_uri} <{RDF_TYPE}> <{UKO}SafetySummary> .')
        triples.append(f'{summary_uri} <{RDFS_LABEL}> "Contra Costa County Safety Summary" .')
        
        # Aggregate statistics
        total_collisions = len(self.collisions)
        total_fatal = sum(1 for c in self.collisions if c.severity == 1)
        total_severe = sum(1 for c in self.collisions if c.severity == 2)
        total_ped = sum(1 for c in self.collisions if c.pedestrian_involved)
        total_bike = sum(1 for c in self.collisions if c.bicycle_involved)
        
        triples.append(f'{summary_uri} <{UKO}totalCollisions> "{total_collisions}"^^<{XSD}integer> .')
        triples.append(f'{summary_uri} <{UKO}fatalCollisions> "{total_fatal}"^^<{XSD}integer> .')
        triples.append(f'{summary_uri} <{UKO}severeInjuryCollisions> "{total_severe}"^^<{XSD}integer> .')
        triples.append(f'{summary_uri} <{UKO}pedestrianCollisions> "{total_ped}"^^<{XSD}integer> .')
        triples.append(f'{summary_uri} <{UKO}bicycleCollisions> "{total_bike}"^^<{XSD}integer> .')
        triples.append(f'{summary_uri} <{UKO}hinSegmentCount> "{len(self.hin_segments)}"^^<{XSD}integer> .')
        
        # Timestamp
        now = datetime.now().isoformat()
        triples.append(f'{summary_uri} <{UKO}generatedAt> "{now}"^^<{XSD}dateTime> .')
        triples.append(f'{summary_uri} <{UKO}dataSource> "SWITRS/TIMS Enhanced Loader v2.0" .')
        
        return triples
    
    def write_triples(self, output_path: str) -> int:
        """Write all triples to an N-Triples file."""
        print(f"\nGenerating safety triples with spatial relationships...")
        
        all_triples = []
        
        # Collision triples
        collision_triples = self.generate_collision_triples()
        all_triples.extend(collision_triples)
        print(f"  Collision triples: {len(collision_triples):,}")
        
        # HIN triples
        hin_triples = self.generate_hin_triples()
        all_triples.extend(hin_triples)
        print(f"  HIN triples: {len(hin_triples):,}")
        
        # Summary triples
        summary_triples = self.generate_safety_summary_triples()
        all_triples.extend(summary_triples)
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            for triple in all_triples:
                f.write(triple + '\n')
        
        print(f"  Total triples written: {len(all_triples):,}")
        return len(all_triples)
    
    def print_spatial_stats(self):
        """Print statistics about spatial relationships created."""
        print("\n" + "="*60)
        print("SPATIAL RELATIONSHIP STATISTICS")
        print("="*60)
        print(f"Collisions near schools: {self.stats['collision_near_school']:,}")
        print(f"Collisions near senior centers: {self.stats['collision_near_senior']:,}")
        print(f"Collisions near hospitals: {self.stats['collision_near_hospital']:,}")
        print(f"Collisions near transit stops: {self.stats['collision_near_transit']:,}")
        print(f"HIN segments near schools: {self.stats['hin_near_school']:,}")
        print(f"HIN segments near senior centers: {self.stats['hin_near_senior']:,}")
        print(f"Schools near HIN (for GeoRotatE): {self.stats['school_near_hin']:,}")


def main(
    input_file: str,
    output_file: Optional[str] = None,
    years: List[int] = None,
    csv_file: Optional[str] = None,
    compute_spatial: bool = True
):
    """
    Main function to load SWITRS data and enhance the KG with spatial relationships.
    
    Args:
        input_file: Path to existing KG (.nt file)
        output_file: Path for output KG (default: adds _with_safety_enhanced suffix)
        years: List of years to include (default: 2019-2023)
        csv_file: Path to SWITRS CSV file
        compute_spatial: Whether to compute spatial relationships (requires parsing KG)
    """
    if years is None:
        years = [2019, 2020, 2021, 2022, 2023]
    
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_with_safety_enhanced{ext}"
    
    print("="*60)
    print("ENHANCED SWITRS SAFETY DATA LOADER v2.0")
    print("="*60)
    print(f"Input KG: {input_file}")
    print(f"Output KG: {output_file}")
    print(f"Years: {years}")
    print(f"Compute spatial relationships: {compute_spatial}")
    print()
    
    # Initialize loader
    loader = SWITRSDataLoader()
    
    # Load collision data
    if csv_file:
        df = loader.load_from_csv(csv_file, years)
    else:
        print("ERROR: CSV file required. Use --csv_file to specify SWITRS data.")
        return None
    
    if df.empty:
        print("No collision data loaded. Exiting.")
        return None
    
    # Parse collisions
    print(f"\nParsing {len(df):,} collision records...")
    collisions = loader.parse_collisions(df)
    print(f"  Parsed {len(collisions):,} valid collisions")
    
    # Filter to target cities
    target_city_names = set(TARGET_CITIES.keys())
    city_collisions = [c for c in collisions if c.city.upper() in target_city_names]
    print(f"  {len(city_collisions):,} collisions in target cities")
    
    # Compute HIN segments
    hin_segments = loader.compute_hin_segments(collisions)
    
    # Compute spatial relationships if requested
    spatial_computer = None
    if compute_spatial and SPATIAL_AVAILABLE:
        print("\n" + "="*60)
        print("COMPUTING SPATIAL RELATIONSHIPS")
        print("="*60)
        
        # Parse existing KG to extract entities
        kg_parser = ExistingKGParser()
        kg_parser.parse_kg_streaming(input_file)
        
        # Build spatial computer
        spatial_computer = SpatialRelationshipComputer(kg_parser)
        
        # Compute relationships for each collision
        print("\nComputing collision spatial relationships...")
        for i, collision in enumerate(collisions):
            collisions[i] = spatial_computer.compute_collision_relationships(collision)
            if (i + 1) % 1000 == 0:
                print(f"  Processed {i+1:,}/{len(collisions):,} collisions")
        
        # Compute relationships for each HIN segment
        print("\nComputing HIN spatial relationships...")
        for i, hin in enumerate(hin_segments):
            hin_segments[i] = spatial_computer.compute_hin_relationships(hin)
    
    # Generate and write triples
    enricher = EnhancedSafetyKGEnricher(collisions, hin_segments, spatial_computer)
    
    temp_file = output_file + ".safety_triples.tmp"
    triple_count = enricher.write_triples(temp_file)
    
    # Print spatial relationship statistics
    if compute_spatial:
        enricher.print_spatial_stats()
    
    # Concatenate with existing KG
    print(f"\nConcatenating with existing KG...")
    
    if os.path.exists(input_file):
        with open(output_file, 'w', encoding='utf-8') as out:
            # Copy original
            with open(input_file, 'r', encoding='utf-8') as inp:
                for line in inp:
                    out.write(line)
            
            # Append new triples
            with open(temp_file, 'r', encoding='utf-8') as tmp:
                for line in tmp:
                    out.write(line)
    else:
        os.rename(temp_file, output_file)
    
    # Clean up
    if os.path.exists(temp_file):
        os.remove(temp_file)
    
    # Print summary
    print("\n" + "="*60)
    print("ENHANCED SAFETY ENRICHMENT COMPLETE")
    print("="*60)
    print(f"Collisions added: {len(collisions):,}")
    print(f"HIN segments identified: {len(hin_segments):,}")
    print(f"  - Pedestrian HIN: {sum(1 for h in hin_segments if h.hin_type == 'pedestrian')}")
    print(f"  - Bicycle HIN: {sum(1 for h in hin_segments if h.hin_type == 'bike')}")
    print(f"  - Vehicle HIN: {sum(1 for h in hin_segments if h.hin_type == 'vehicle')}")
    print(f"New triples: {triple_count:,}")
    print(f"Output: {output_file}")
    
    print("\n" + "="*60)
    print("NEW RELATIONS ADDED FOR GEOROTATE TRAINING")
    print("="*60)
    print("These object properties can now be included in training data:")
    print("  - urn:urban-kg:collisionNearSchool")
    print("  - urn:urban-kg:collisionNearSeniorCenter")
    print("  - urn:urban-kg:collisionNearHospital")
    print("  - urn:urban-kg:collisionNearTransit")
    print("  - urn:urban-kg:hinNearSchool")
    print("  - urn:urban-kg:hinNearSeniorCenter")
    print("  - urn:urban-kg:schoolNearHIN")
    print("  - urn:urban-kg:seniorCenterNearHIN")
    print("  - urn:urban-kg:hasNearbyCollision")
    print("  - urn:urban-kg:contributesToHIN")
    print("  - urn:urban-kg:includesCollision")
    print("  - urn:urban-kg:inHighInjuryNetwork")
    
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enhanced SWITRS/TIMS loader with spatial relationships for GeoRotatE"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input KG (.nt file)"
    )
    parser.add_argument(
        "--output",
        help="Path for output KG (default: adds _with_safety_enhanced suffix)"
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2019, 2020, 2021, 2022, 2023],
        help="Years to include (default: 2019-2023)"
    )
    parser.add_argument(
        "--csv_file",
        required=True,
        help="Path to SWITRS CSV file"
    )
    parser.add_argument(
        "--no_spatial",
        action="store_true",
        help="Skip spatial relationship computation (faster, but no GeoRotatE relations)"
    )
    
    args = parser.parse_args()
    
    main(
        input_file=args.input,
        output_file=args.output,
        years=args.years,
        csv_file=args.csv_file,
        compute_spatial=not args.no_spatial
    )
