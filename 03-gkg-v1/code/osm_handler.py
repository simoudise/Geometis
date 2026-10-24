"""
Enhanced OSM Handler v2.0

Processes OpenStreetMap data and builds a rich, queryable knowledge graph
with support for:
- Standard entity extraction and spatial relationships
- Vulnerable population proximity analysis
- Safety infrastructure relationships
- Neighborhood/district containment

Copyright (c) 2025 Synapse Partners, LLC
"""

import osmium
import rdflib
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD
from shapely import wkb
from shapely.geometry import Polygon, Point, LineString
from collections import defaultdict
import re
from typing import List, Tuple, Dict, Set, Optional, Union
from dataclasses import dataclass
import math
import time
import logging

from osm_to_uko_mapper import (
    OSM_UKO_MAPPER, 
    TAG_PRIORITIES,
    VULNERABLE_POPULATION_CLASSES,
    SAFETY_INFRASTRUCTURE_CLASSES,
    NEIGHBORHOOD_CLASSES,
    DISTRICT_CLASSES
)

# Setup logging
logger = logging.getLogger(__name__)

# Define namespaces
UKO = Namespace("urn:urban-kg:")
UKO_ENTITY = Namespace("urn:urban-kg:entity/osm/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


@dataclass
class EntityCandidate:
    """Represents a potential entity for relationship processing."""
    uri: str
    name: str
    uko_class: str
    geometry: Union[Point, Polygon, LineString]
    osm_tags: dict


class SpatialRelationshipResolver:
    """
    Calculates multiple types of spatial relationships with a multi-pronged strategy.
    
    v2.0 Additions:
    - Vulnerable population proximity (roads/transit near nursing homes, senior centers)
    - Safety infrastructure relationships (roads with/without crossings, traffic calming)
    - Cycling infrastructure relationships
    """
    
    def __init__(self, graph: Graph):
        self.graph = graph
        
        # Distance thresholds (in meters)
        self.thresholds = {
            "adjacentTo": 20, 
            "withinWalkingDistanceOf": 400,
            "withinCyclingDistanceOf": 1500,  # NEW: ~1.5km cycling distance
            "near": 200, 
            "accessibleVia": 15,
            "road_infrastructure": 30,
            "vulnerable_population_buffer": 150,  # NEW: 150m buffer around vulnerable facilities
            "transit_vulnerable_buffer": 300,     # NEW: Transit stops near vulnerable facilities
            "safety_infrastructure": 50,          # NEW: Crossings, signals near intersections
        }
        
        # Major landmark classes (high-value destinations)
        self.major_landmark_classes = {
            str(UKO.Hospital), str(UKO.MedicalComplex), str(UKO.School), 
            str(UKO.University), str(UKO.College), str(UKO.EducationalComplex), 
            str(UKO.ShoppingCenter), str(UKO.ShoppingMall), str(UKO.ShoppingComplex),
            str(UKO.Supermarket), str(UKO.TownHall), str(UKO.CityHall), 
            str(UKO.PoliceStation), str(UKO.FireStation), str(UKO.Library), 
            str(UKO.Park), str(UKO.TrainStation), str(UKO.BusStation), 
            str(UKO.CommunityCenter), str(UKO.Courthouse)
        }
        
        # Residential classes
        self.residential_classes = {
            str(UKO.House), str(UKO.DetachedHouse), str(UKO.ApartmentBuilding),
            str(UKO.ResidentialBuilding), str(UKO.Dormitory)
        }
        
        # Building/POI classes
        self.building_poi_classes = self.residential_classes.union(self.major_landmark_classes).union({
            str(UKO.Restaurant), str(UKO.FastFoodRestaurant), str(UKO.Cafe), 
            str(UKO.ConvenienceStore), str(UKO.RetailBuilding), str(UKO.CommercialBuilding), 
            str(UKO.OfficeBuilding), str(UKO.DoctorsOffice), str(UKO.DentistOffice), 
            str(UKO.Clinic)
        })
        
        # Active mobility infrastructure
        self.active_mobility_classes = {
            str(UKO.Sidewalk), str(UKO.ProtectedBikeLane), str(UKO.UnprotectedBikeLane),
            str(UKO.PedestrianZone), str(UKO.Path), str(UKO.BicycleLane), str(UKO.Steps),
            str(UKO.Footway), str(UKO.Cycleway), str(UKO.PedestrianCrossing), 
            str(UKO.BridleWay), str(UKO.Track)
        }
        
        # Road classes
        self.road_classes = {
            str(UKO.ServiceRoad), str(UKO.ResidentialRoad), str(UKO.PrimaryRoad),
            str(UKO.SecondaryRoad), str(UKO.TertiaryRoad), str(UKO.UnclassifiedRoad),
            str(UKO.LivingStreet), str(UKO.Motorway), str(UKO.TrunkRoad)
        }
        
        # Transit classes
        self.transit_classes = {
            str(UKO.BusStop), str(UKO.BusStation), str(UKO.TrainStation),
            str(UKO.Platform), str(UKO.TransitStation), str(UKO.TramStop),
            str(UKO.LightRailStation), str(UKO.SubwayStation)
        }
        
        # NEW: Vulnerable population classes (imported from mapper)
        self.vulnerable_population_classes = VULNERABLE_POPULATION_CLASSES
        
        # NEW: Safety infrastructure classes (imported from mapper)
        self.safety_infrastructure_classes = SAFETY_INFRASTRUCTURE_CLASSES

    def create_all_relationships(self, entities: List[EntityCandidate]):
        """Create all spatial relationships between entities."""
        print("\n" + "="*60)
        print("PHASE 2: SPATIAL RELATIONSHIP RESOLUTION")
        print("="*60)
        
        # Categorize entities
        major_landmarks = [e for e in entities if str(e.uko_class) in self.major_landmark_classes]
        residentials = [e for e in entities if str(e.uko_class) in self.residential_classes]
        other_pois = [e for e in entities if not (str(e.uko_class) in self.residential_classes)]
        building_pois = [e for e in entities if str(e.uko_class) in self.building_poi_classes]
        active_mobility = [e for e in entities if str(e.uko_class) in self.active_mobility_classes]
        road_entities = [e for e in entities if str(e.uko_class) in self.road_classes]
        transit_entities = [e for e in entities if str(e.uko_class) in self.transit_classes]
        
        # NEW: Categorize vulnerable population facilities
        vulnerable_facilities = [e for e in entities if str(e.uko_class) in self.vulnerable_population_classes]
        
        # NEW: Categorize safety infrastructure
        safety_infrastructure = [e for e in entities if str(e.uko_class) in self.safety_infrastructure_classes]
        
        print(f"Found {len(major_landmarks):,} landmarks, {len(residentials):,} residentials,")
        print(f"      {len(active_mobility):,} active mobility segments, {len(road_entities):,} roads,")
        print(f"      {len(transit_entities):,} transit stops, {len(vulnerable_facilities):,} vulnerable population facilities,")
        print(f"      and {len(safety_infrastructure):,} safety infrastructure elements.")
        
        total_rels = 0
        
        # Original relationships
        print("\nProcessing Landmark-to-POI relationships...")
        landmark_rels = self._calculate_proximity_relationships(major_landmarks, other_pois)
        print(f"✓ Created {landmark_rels:,} landmark-to-POI relationships.")
        total_rels += landmark_rels
        
        print("\nProcessing Residential-to-Landmark relationships...")
        residential_rels = self._calculate_proximity_relationships(residentials, major_landmarks)
        print(f"✓ Created {residential_rels:,} residential-to-landmark relationships.")
        total_rels += residential_rels
        
        print("\nProcessing Building-to-Accessibility relationships...")
        accessibility_rels = self._calculate_accessibility_relationships(building_pois, active_mobility)
        print(f"✓ Created {accessibility_rels:,} building-to-infrastructure relationships.")
        total_rels += accessibility_rels
        
        print("\nProcessing Road-to-Infrastructure relationships...")
        road_infra_rels = self._calculate_road_infrastructure_relationships(road_entities, active_mobility)
        print(f"✓ Created {road_infra_rels:,} road-to-infrastructure relationships.")
        total_rels += road_infra_rels
        
        print("\nProcessing Transit-to-Destination relationships...")
        transit_rels = self._calculate_transit_accessibility_relationships(transit_entities, building_pois)
        print(f"✓ Created {transit_rels:,} transit-to-destination relationships.")
        total_rels += transit_rels
        
        # NEW: Vulnerable Population Relationships
        if vulnerable_facilities:
            print("\nProcessing Vulnerable Population proximity relationships...")
            vulnerable_rels = self._calculate_vulnerable_population_relationships(
                vulnerable_facilities, road_entities, transit_entities
            )
            print(f"✓ Created {vulnerable_rels:,} vulnerable population relationships.")
            total_rels += vulnerable_rels
        
        # NEW: Safety Infrastructure Relationships
        if safety_infrastructure:
            print("\nProcessing Safety Infrastructure relationships...")
            safety_rels = self._calculate_safety_infrastructure_relationships(
                safety_infrastructure, road_entities
            )
            print(f"✓ Created {safety_rels:,} safety infrastructure relationships.")
            total_rels += safety_rels
        
        # NEW: Cycling Distance Relationships (extended range for bike-friendly analysis)
        print("\nProcessing Cycling Distance relationships...")
        cycling_rels = self._calculate_cycling_relationships(building_pois, major_landmarks)
        print(f"✓ Created {cycling_rels:,} cycling distance relationships.")
        total_rels += cycling_rels
        
        print(f"\n✓ Created a total of {total_rels:,} meaningful spatial relationships.")

    def _calculate_proximity_relationships(self, group1: List[EntityCandidate], 
                                          group2: List[EntityCandidate]) -> int:
        """Calculate proximity relationships between two entity groups."""
        relationships_created = 0
        for i, entity1 in enumerate(group1):
            for entity2 in group2:
                if entity1.uri == entity2.uri:
                    continue
                try:
                    distance = self._calculate_centroid_distance(entity1.geometry, entity2.geometry)
                    if distance <= self.thresholds["adjacentTo"]:
                        self._add_symmetric_relationship(entity1, entity2, UKO.adjacentTo)
                        relationships_created += 1
                    elif distance <= self.thresholds["near"]:
                        self._add_symmetric_relationship(entity1, entity2, UKO.near)
                        relationships_created += 1
                    elif distance <= self.thresholds["withinWalkingDistanceOf"]:
                        self._add_symmetric_relationship(entity1, entity2, UKO.withinWalkingDistanceOf)
                        relationships_created += 1
                except Exception:
                    continue
            if (i + 1) % 1000 == 0:
                print(f"  ... processed {i+1:,} entities, found {relationships_created:,} relationships.")
        return relationships_created

    def _calculate_accessibility_relationships(self, buildings: List[EntityCandidate], 
                                              infrastructures: List[EntityCandidate]) -> int:
        """Calculate accessibility relationships (buildings to sidewalks/bike lanes)."""
        relationships_created = 0
        for i, building in enumerate(buildings):
            for infra in infrastructures:
                try:
                    distance_m = self._calculate_centroid_distance(building.geometry, infra.geometry)
                    if distance_m <= self.thresholds["accessibleVia"]:
                        self._add_directional_relationship(building, infra, UKO.accessibleVia)
                        relationships_created += 1
                except Exception:
                    continue
            if (i + 1) % 5000 == 0:
                print(f"  ... processed {i+1:,} buildings, found {relationships_created:,} accessibility links.")
        return relationships_created

    def _calculate_road_infrastructure_relationships(self, roads: List[EntityCandidate],
                                                    infrastructure: List[EntityCandidate]) -> int:
        """Calculate relationships between roads and pedestrian/cycling infrastructure."""
        relationships_created = 0
        
        sidewalk_classes = {str(UKO.Sidewalk), str(UKO.Footway)}
        bike_classes = {str(UKO.Cycleway), str(UKO.ProtectedBikeLane), str(UKO.UnprotectedBikeLane)}
        
        for i, road in enumerate(roads):
            has_sidewalk = False
            has_bike = False
            
            for infra in infrastructure:
                try:
                    distance = self._calculate_centroid_distance(road.geometry, infra.geometry)
                    if distance <= self.thresholds["road_infrastructure"]:
                        if str(infra.uko_class) in sidewalk_classes:
                            if not has_sidewalk:
                                self._add_directional_relationship(road, infra, UKO.hasSidewalk)
                                has_sidewalk = True
                                relationships_created += 1
                        elif str(infra.uko_class) in bike_classes:
                            if not has_bike:
                                self._add_directional_relationship(road, infra, UKO.hasBikeLane)
                                has_bike = True
                                relationships_created += 1
                except Exception:
                    continue
                    
            if (i + 1) % 2000 == 0:
                print(f"  ... processed {i+1:,} roads.")
                
        return relationships_created

    def _calculate_transit_accessibility_relationships(self, transit: List[EntityCandidate],
                                                       destinations: List[EntityCandidate]) -> int:
        """Calculate transit accessibility relationships."""
        relationships_created = 0
        
        for i, stop in enumerate(transit):
            for dest in destinations:
                try:
                    distance = self._calculate_centroid_distance(stop.geometry, dest.geometry)
                    if distance <= self.thresholds["withinWalkingDistanceOf"]:
                        self._add_directional_relationship(dest, stop, UKO.transitAccessible)
                        relationships_created += 1
                except Exception:
                    continue
            if (i + 1) % 500 == 0:
                print(f"  ... processed {i+1:,} transit stops.")
                
        return relationships_created

    def _calculate_vulnerable_population_relationships(self, vulnerable_facilities: List[EntityCandidate],
                                                       roads: List[EntityCandidate],
                                                       transit: List[EntityCandidate]) -> int:
        """
        NEW: Calculate relationships for vulnerable population facilities.
        
        Creates:
        - nearVulnerablePopulation: roads within buffer of nursing homes, senior centers, etc.
        - transitServesVulnerable: transit stops within buffer of vulnerable facilities
        """
        relationships_created = 0
        
        # Roads near vulnerable facilities
        for facility in vulnerable_facilities:
            for road in roads:
                try:
                    distance = self._calculate_centroid_distance(facility.geometry, road.geometry)
                    if distance <= self.thresholds["vulnerable_population_buffer"]:
                        self._add_directional_relationship(road, facility, UKO.nearVulnerablePopulation)
                        relationships_created += 1
                except Exception:
                    continue
            
            # Transit serving vulnerable facilities
            for stop in transit:
                try:
                    distance = self._calculate_centroid_distance(facility.geometry, stop.geometry)
                    if distance <= self.thresholds["transit_vulnerable_buffer"]:
                        self._add_directional_relationship(stop, facility, UKO.servesVulnerablePopulation)
                        relationships_created += 1
                except Exception:
                    continue
        
        return relationships_created

    def _calculate_safety_infrastructure_relationships(self, safety_infra: List[EntityCandidate],
                                                       roads: List[EntityCandidate]) -> int:
        """
        NEW: Calculate relationships between roads and safety infrastructure.
        
        Creates:
        - hasCrossing: road has pedestrian crossing nearby
        - hasTrafficCalming: road has speed bumps, etc.
        - hasTrafficSignal: road has traffic signals
        """
        relationships_created = 0
        
        crossing_classes = {
            str(UKO.PedestrianCrossing), str(UKO.SignalizedCrossing), 
            str(UKO.ZebraCrossing), str(UKO.CrossingIsland), str(UKO.BicycleCrossing)
        }
        calming_classes = {
            str(UKO.SpeedBump), str(UKO.SpeedHump), str(UKO.SpeedTable),
            str(UKO.Chicane), str(UKO.TrafficIsland), str(UKO.TrafficCalming)
        }
        signal_classes = {str(UKO.TrafficSignal)}
        
        for road in roads:
            for infra in safety_infra:
                try:
                    distance = self._calculate_centroid_distance(road.geometry, infra.geometry)
                    if distance <= self.thresholds["safety_infrastructure"]:
                        infra_class = str(infra.uko_class)
                        
                        if infra_class in crossing_classes:
                            self._add_directional_relationship(road, infra, UKO.hasCrossing)
                            relationships_created += 1
                        elif infra_class in calming_classes:
                            self._add_directional_relationship(road, infra, UKO.hasTrafficCalming)
                            relationships_created += 1
                        elif infra_class in signal_classes:
                            self._add_directional_relationship(road, infra, UKO.hasTrafficSignal)
                            relationships_created += 1
                except Exception:
                    continue
        
        return relationships_created

    def _calculate_cycling_relationships(self, pois: List[EntityCandidate],
                                         destinations: List[EntityCandidate]) -> int:
        """
        NEW: Calculate cycling distance relationships (1.5km range).
        
        Creates withinCyclingDistanceOf relationships for bike-friendly analysis.
        """
        relationships_created = 0
        
        for i, poi in enumerate(pois):
            for dest in destinations:
                if poi.uri == dest.uri:
                    continue
                try:
                    distance = self._calculate_centroid_distance(poi.geometry, dest.geometry)
                    # Only create cycling relationships for things beyond walking but within cycling
                    if (distance > self.thresholds["withinWalkingDistanceOf"] and 
                        distance <= self.thresholds["withinCyclingDistanceOf"]):
                        self._add_symmetric_relationship(poi, dest, UKO.withinCyclingDistanceOf)
                        relationships_created += 1
                except Exception:
                    continue
            
            if (i + 1) % 2000 == 0:
                print(f"  ... processed {i+1:,} POIs for cycling distance.")
        
        return relationships_created

    def _calculate_centroid_distance(self, geom1, geom2) -> float:
        """Calculate distance between centroids in meters (approximate)."""
        c1 = geom1.centroid
        c2 = geom2.centroid
        
        # Haversine formula
        lat1, lon1 = math.radians(c1.y), math.radians(c1.x)
        lat2, lon2 = math.radians(c2.y), math.radians(c2.x)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Earth's radius in meters
        r = 6371000
        return c * r

    def _add_symmetric_relationship(self, entity1: EntityCandidate, entity2: EntityCandidate, 
                                    predicate: URIRef):
        """Add a symmetric relationship (A rel B and B rel A)."""
        self.graph.add((URIRef(entity1.uri), predicate, URIRef(entity2.uri)))
        self.graph.add((URIRef(entity2.uri), predicate, URIRef(entity1.uri)))

    def _add_directional_relationship(self, entity1: EntityCandidate, entity2: EntityCandidate,
                                      predicate: URIRef):
        """Add a directional relationship (A rel B only)."""
        self.graph.add((URIRef(entity1.uri), predicate, URIRef(entity2.uri)))


class CompositionalEntityResolver:
    """Resolves complex entities from component parts."""
    
    def __init__(self, graph: Graph):
        self.graph = graph
        
        self.complex_patterns = {
            "medical_complex": {
                "anchor_classes": {str(UKO.Hospital)},
                "component_classes": {
                    str(UKO.DoctorsOffice), str(UKO.Clinic), str(UKO.Pharmacy),
                    str(UKO.DentistOffice), str(UKO.MedicalLaboratory)
                },
                "radius_m": 200,
                "result_class": UKO.MedicalComplex
            },
            "educational_complex": {
                "anchor_classes": {str(UKO.School), str(UKO.University), str(UKO.College)},
                "component_classes": {
                    str(UKO.Library), str(UKO.SportsCenter), str(UKO.Stadium),
                    str(UKO.Dormitory), str(UKO.Cafeteria)
                },
                "radius_m": 300,
                "result_class": UKO.EducationalComplex
            },
            "shopping_complex": {
                "anchor_classes": {str(UKO.ShoppingCenter), str(UKO.ShoppingMall)},
                "component_classes": {
                    str(UKO.Restaurant), str(UKO.Cafe), str(UKO.Cinema),
                    str(UKO.ParkingFacility), str(UKO.RetailBuilding)
                },
                "radius_m": 150,
                "result_class": UKO.ShoppingComplex
            },
            # NEW: Senior care complex
            "senior_care_complex": {
                "anchor_classes": {str(UKO.NursingHome), str(UKO.AssistedLivingFacility)},
                "component_classes": {
                    str(UKO.SeniorCenter), str(UKO.AdultDayCare),
                    str(UKO.Clinic), str(UKO.Pharmacy)
                },
                "radius_m": 200,
                "result_class": UKO.SeniorCareComplex
            }
        }
    
    def resolve_complex_entities(self, entities: List[EntityCandidate]) -> List[Dict]:
        """Identify and create complex entity relationships."""
        complexes_found = []
        
        for pattern_name, pattern in self.complex_patterns.items():
            anchors = [e for e in entities if str(e.uko_class) in pattern["anchor_classes"]]
            components = [e for e in entities if str(e.uko_class) in pattern["component_classes"]]
            
            for anchor in anchors:
                nearby_components = []
                for comp in components:
                    try:
                        dist = self._calculate_distance(anchor.geometry, comp.geometry)
                        if dist <= pattern["radius_m"]:
                            nearby_components.append(comp)
                    except Exception:
                        continue
                
                if len(nearby_components) >= 2:
                    complex_uri = URIRef(f"{anchor.uri}_complex")
                    self.graph.add((complex_uri, RDF.type, pattern["result_class"]))
                    self.graph.add((complex_uri, RDFS.label, Literal(f"{anchor.name} Complex")))
                    self.graph.add((complex_uri, UKO.hasAnchor, URIRef(anchor.uri)))
                    
                    for comp in nearby_components:
                        self.graph.add((complex_uri, UKO.hasComponent, URIRef(comp.uri)))
                    
                    complexes_found.append({
                        "type": pattern_name,
                        "anchor": anchor.name,
                        "components": [c.name for c in nearby_components]
                    })
        
        return complexes_found
    
    def _calculate_distance(self, geom1, geom2) -> float:
        """Calculate distance in meters."""
        c1 = geom1.centroid
        c2 = geom2.centroid
        
        lat1, lon1 = math.radians(c1.y), math.radians(c1.x)
        lat2, lon2 = math.radians(c2.y), math.radians(c2.x)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return c * 6371000


class EnhancedOSMHandler(osmium.SimpleHandler):
    """Enhanced OSM handler that builds a rich, queryable knowledge graph."""
    
    def __init__(self, graph: Graph, bounding_box: list, city_geofences: dict, **kwargs):
        super().__init__()
        self.graph = graph
        self.bbox = bounding_box
        self.city_geofences = city_geofences
        self.bbox_polygon = self._create_bbox_polygon()
        self.city_polygons = {name: self._create_polygon_from_bbox(bbox) 
                             for name, bbox in city_geofences.items()}
        self.wkb_factory = osmium.geom.WKBFactory()
        
        self.compositional_resolver = CompositionalEntityResolver(graph)
        self.spatial_resolver = SpatialRelationshipResolver(graph)

        self.node_count = 0
        self.way_count = 0
        self.area_count = 0
        self.stored_entity_count = 0
        self.rejected_bbox_count = 0
        self.rejected_no_uko_count = 0
        self.rejected_geometry_count = 0
        self.entity_candidates = []
        self.debug_mode = kwargs.get('debug_mode', False)

        self._create_city_entities()

    def _create_city_entities(self):
        """Creates the city entities in the graph so they can be queried as anchors."""
        logger.info("Creating city entities in the knowledge graph...")
        for city_name, bbox in self.city_geofences.items():
            city_uri_name = city_name.replace(' ', '_')
            city_uri = UKO_ENTITY[f"city/{city_uri_name}"]
            self.graph.add((city_uri, RDF.type, UKO.City))
            self.graph.add((city_uri, RDFS.label, Literal(city_name, lang='en')))
            city_poly = self._create_polygon_from_bbox(bbox)
            self.graph.add((city_uri, GEO.hasGeometry, city_uri))
            self.graph.add((city_uri, GEO.asWKT, Literal(city_poly.wkt, datatype=GEO.wktLiteral)))

    def _create_polygon_from_bbox(self, bbox: list):
        lat_min, lat_max, lon_min, lon_max = bbox
        return Polygon([(lon_min, lat_min), (lon_max, lat_min), 
                       (lon_max, lat_max), (lon_min, lat_max)])

    def _add_city_containment_triple(self, subject_uri, wkb_geom):
        try:
            geom = wkb.loads(wkb_geom).centroid
            for city_name, city_polygon in self.city_polygons.items():
                if city_polygon.contains(geom):
                    city_uri_name = city_name.replace(' ', '_')
                    city_uri = UKO_ENTITY[f"city/{city_uri_name}"]
                    self.graph.add((subject_uri, UKO.partOf, city_uri))
                    return
        except Exception:
            pass

    def _create_bbox_polygon(self):
        lat_min, lat_max, lon_min, lon_max = self.bbox
        return Polygon([(lon_min, lat_min), (lon_max, lat_min), 
                       (lon_max, lat_max), (lon_min, lat_max)])

    def _get_uko_class_from_tags(self, tags):
        candidates = []
        for key, mapping in OSM_UKO_MAPPER.items():
            if key in tags and tags[key] in mapping:
                candidates.append((TAG_PRIORITIES.get(key, 0), mapping[tags[key]]))
        if candidates:
            return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]
        return None

    def _add_common_triples(self, osm_object, subject_uri, uko_class):
        self.graph.add((subject_uri, RDF.type, uko_class))
        name = osm_object.tags.get('name', f"{str(uko_class).split('/')[-1]} {osm_object.id}")
        self.graph.add((subject_uri, RDFS.label, Literal(name)))
        
        # Capture transit network and operator if present
        if 'network' in osm_object.tags:
            self.graph.add((subject_uri, UKO.transitNetwork, Literal(osm_object.tags['network'])))
        if 'operator' in osm_object.tags:
            self.graph.add((subject_uri, UKO.transitOperator, Literal(osm_object.tags['operator'])))

    def _add_geometry_triples(self, subject_uri, wkb_geom):
        try:
            geom = wkb.loads(wkb_geom)
            self.graph.add((subject_uri, GEO.hasGeometry, subject_uri))
            self.graph.add((subject_uri, GEO.asWKT, Literal(geom.wkt, datatype=GEO.wktLiteral)))
            center = geom.centroid
            self.graph.add((subject_uri, UKO.latitude, Literal(center.y, datatype=XSD.double)))
            self.graph.add((subject_uri, UKO.longitude, Literal(center.x, datatype=XSD.double)))
        except Exception:
            pass

    def _store_entity_candidate(self, subject_uri, uko_class, wkb_geom, osm_object):
        geom = wkb.loads(wkb_geom)
        name = osm_object.tags.get('name', f"{str(uko_class).split('/')[-1]} {osm_object.id}")
        self.entity_candidates.append(EntityCandidate(
            uri=str(subject_uri),
            name=name,
            uko_class=str(uko_class),
            geometry=geom,
            osm_tags=dict(osm_object.tags)
        ))
        self.stored_entity_count += 1

    def _update_progress(self):
        if self.debug_mode and (self.node_count + self.way_count) % 100000 == 0:
            print(f"Progress: {self.node_count + self.way_count:,} entities processed...", end='\r')

    def node(self, n):
        self.node_count += 1
        uko_class = self._get_uko_class_from_tags(n.tags)
        if not uko_class:
            return
        try:
            wkb_geom = self.wkb_factory.create_point(n)
            if not self.bbox_polygon.contains(wkb.loads(wkb_geom)):
                return
        except Exception:
            return
        subject_uri = UKO_ENTITY[f"node/{n.id}"]
        self._add_common_triples(n, subject_uri, uko_class)
        self._add_geometry_triples(subject_uri, wkb_geom)
        self._add_city_containment_triple(subject_uri, wkb_geom)
        self._store_entity_candidate(subject_uri, uko_class, wkb_geom, n)
        self._update_progress()

    def way(self, w):
        self.way_count += 1
        uko_class = self._get_uko_class_from_tags(w.tags)
        if not uko_class:
            return
        try:
            is_poly = 'area' in w.tags and w.tags['area'] != 'no' and w.is_closed()
            wkb_geom = self.wkb_factory.create_polygon(w) if is_poly else self.wkb_factory.create_linestring(w)
            if not self.bbox_polygon.intersects(wkb.loads(wkb_geom)):
                return
        except Exception:
            return
        subject_uri = UKO_ENTITY[f"way/{w.id}"]
        self._add_common_triples(w, subject_uri, uko_class)
        self._add_geometry_triples(subject_uri, wkb_geom)
        self._add_city_containment_triple(subject_uri, wkb_geom)
        self._store_entity_candidate(subject_uri, uko_class, wkb_geom, w)
        self._update_progress()

    def area(self, a):
        self.area_count += 1
        uko_class = self._get_uko_class_from_tags(a.tags)
        if not uko_class:
            return
        try:
            wkb_geom = self.wkb_factory.create_multipolygon(a)
            if not self.bbox_polygon.intersects(wkb.loads(wkb_geom)):
                return
        except Exception:
            return
        subject_uri = UKO_ENTITY[f"area/{a.id}"]
        self._add_common_triples(a, subject_uri, uko_class)
        self._add_geometry_triples(subject_uri, wkb_geom)
        self._add_city_containment_triple(subject_uri, wkb_geom)
        self._store_entity_candidate(subject_uri, uko_class, wkb_geom, a)
        self._update_progress()

    def finalize(self):
        """Finalize processing by resolving complex entities and spatial relationships."""
        print("\n" + "="*60)
        print("FINALIZING KNOWLEDGE GRAPH")
        print("="*60)
        complex_entities = self.compositional_resolver.resolve_complex_entities(self.entity_candidates)
        print(f"✓ Finalized compositional reasoning. Created {len(complex_entities)} complex entities.")
        self.spatial_resolver.create_all_relationships(self.entity_candidates)
        return complex_entities
