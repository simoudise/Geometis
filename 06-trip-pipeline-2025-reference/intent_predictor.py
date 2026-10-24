"""
Trip Intent Predictor Module - FIXED VERSION
Predicts trip intent/purpose using ML and rule-based approaches
References TKO ontology for intent classification hierarchy

FIXES:
1. Improved rule matching logic that properly prioritizes destination-based intents
2. Healthcare intents now get priority over commute intents when appropriate
3. Added missing intent types (TransitAccess, DiningOut, SchoolDropOff, SchoolPickup)
4. Better POI matching with weighted scoring
"""

import numpy as np
import pandas as pd
from datetime import datetime, time
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from rdflib import Graph, Namespace
from collections import defaultdict
import logging


# TKO Namespace
TKO = Namespace("urn:trip-kg:")
UKO = Namespace("urn:urban-kg:")


@dataclass
class IntentPrediction:
    """Trip intent prediction with confidence"""
    intent_class: str  # TKO ontology class
    intent_subclass: str  # More specific intent
    confidence: float
    inference_method: str  # 'rule_based', 'ml_model', 'hybrid'
    supporting_evidence: List[str]
    
    def to_dict(self) -> Dict:
        return {
            'primary_intent': {
                'intent_class': self.intent_class,
                'intent_subclass': self.intent_subclass,
                'confidence': round(self.confidence, 3),
                'inference_method': self.inference_method
            },
            'supporting_evidence': self.supporting_evidence
        }


class IntentPredictor:
    """
    Predicts trip intent using multiple strategies:
    1. Rule-based inference from POI types, time, day of week
    2. Pattern-based inference from trip history
    3. ML-based prediction (future enhancement)
    """
    
    # Time of day categories
    TIME_CATEGORIES = {
        'early_morning': (time(5, 0), time(7, 0)),
        'morning': (time(7, 0), time(9, 0)),
        'mid_morning': (time(9, 0), time(12, 0)),
        'midday': (time(12, 0), time(14, 0)),
        'afternoon': (time(14, 0), time(17, 0)),
        'evening': (time(17, 0), time(20, 0)),
        'night': (time(20, 0), time(23, 0)),
        'late_night': (time(23, 0), time(5, 0))
    }
    
    # Intent rules based on POI type, time, and day
    # FIXED: Added priority weights and better classification
    INTENT_RULES = {
        # Work-related intents (origin-based)
        'tko:CommuteToWork': {
            'destination_poi_types': ['OfficeBuilding', 'IndustrialBuilding', 'Warehouse', 'Factory'],
            'time_of_day': ['morning', 'early_morning'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.85,
            'priority_weight': 1.0  # Standard priority
        },
        'tko:CommuteFromWork': {
            'origin_poi_types': ['OfficeBuilding', 'IndustrialBuilding', 'Warehouse', 'Factory'],
            'time_of_day': ['evening', 'afternoon'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.85,
            'priority_weight': 1.0
        },
        'tko:BusinessMeeting': {
            'destination_poi_types': ['OfficeBuilding', 'ConferenceCenter', 'Hotel'],
            'time_of_day': ['morning', 'mid_morning', 'afternoon'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.70,
            'priority_weight': 1.1  # Slightly higher than commute
        },
        
        # Healthcare intents (destination-based, HIGH PRIORITY)
        'tko:HospitalVisit': {
            'destination_poi_types': ['Hospital', 'EmergencyDepartment'],
            'time_of_day': ['morning', 'mid_morning', 'afternoon', 'evening', 'night'],
            'day_of_week': ['any'],
            'confidence_base': 0.90,
            'priority_weight': 1.5  # HIGH priority over commute
        },
        'tko:DoctorVisit': {
            'destination_poi_types': ['DoctorsOffice', 'Clinic', 'MedicalBuilding'],
            'time_of_day': ['morning', 'mid_morning', 'afternoon'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.85,
            'priority_weight': 1.5,  # HIGH priority over commute
            'dwell_time_min': 600  # Expect at least 10 min visit
        },
        'tko:DentistVisit': {
            'destination_poi_types': ['DentistOffice'],
            'time_of_day': ['morning', 'mid_morning', 'afternoon'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.90,
            'priority_weight': 1.5,
            'dwell_time_min': 600
        },
        
        # Shopping intents (destination-based)
        'tko:GroceryShopping': {
            'destination_poi_types': ['Supermarket', 'GroceryStore'],
            'time_of_day': ['afternoon', 'evening', 'weekend_any'],
            'day_of_week': ['any'],
            'confidence_base': 0.80,
            'dwell_time_min': 300,
            'priority_weight': 1.2
        },
        'tko:MallShopping': {
            'destination_poi_types': ['ShoppingMall', 'ShoppingCenter'],
            'time_of_day': ['midday', 'afternoon', 'evening'],
            'day_of_week': ['weekend', 'any'],
            'confidence_base': 0.75,
            'dwell_time_min': 600,
            'priority_weight': 1.2
        },
        
        # Dining intents (destination-based)
        'tko:DiningOut': {
            'destination_poi_types': ['Restaurant', 'Cafe', 'FastFoodRestaurant'],
            'time_of_day': ['midday', 'evening', 'night'],
            'day_of_week': ['any'],
            'confidence_base': 0.75,
            'dwell_time_min': 600,
            'priority_weight': 1.2
        },
        
        # Recreation intents (destination-based or origin-based)
        'tko:ParkVisit': {
            'destination_poi_types': ['Park', 'Garden', 'RecreationGround', 'Playground'],
            'origin_poi_types': ['Park', 'Garden', 'RecreationGround', 'Playground'],
            'time_of_day': ['mid_morning', 'midday', 'afternoon', 'morning'],
            'day_of_week': ['weekend', 'weekday', 'any'],
            'confidence_base': 0.75,
            'modality': ['walking', 'bicycling', 'driving'],
            'priority_weight': 1.3
        },
        'tko:GymVisit': {
            'destination_poi_types': ['Gym', 'FitnessCenter', 'SportsCenter'],
            'time_of_day': ['early_morning', 'morning', 'evening'],
            'day_of_week': ['any'],
            'confidence_base': 0.80,
            'priority_weight': 1.2
        },
        'tko:TheaterVisit': {
            'destination_poi_types': ['Theater', 'Cinema', 'ArtsCenter'],
            'time_of_day': ['evening', 'night', 'afternoon'],
            'day_of_week': ['any'],
            'confidence_base': 0.85,
            'priority_weight': 1.3
        },
        
        # Transit access intents (destination-based, HIGH PRIORITY)
        'tko:TransitAccess': {
            'destination_poi_types': ['BusStop', 'TransitStation', 'TrainStation', 'SubwayStation', 'BusStation'],
            'time_of_day': ['early_morning', 'morning', 'mid_morning', 'afternoon', 'evening'],
            'day_of_week': ['weekday', 'weekend', 'any'],
            'confidence_base': 0.85,
            'modality': ['walking', 'bicycling', 'driving'],
            'priority_weight': 1.4,  # High priority - very specific destination
            'dwell_time_min': 60  # Expect some wait time
        },
        
        # Education intents (destination-based, HIGH PRIORITY)
        'tko:SchoolDropOff': {
            'destination_poi_types': ['School', 'Kindergarten', 'Preschool'],
            'time_of_day': ['early_morning', 'morning'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.90,
            'priority_weight': 1.5
        },
        'tko:SchoolPickup': {
            'origin_poi_types': ['School', 'Kindergarten', 'Preschool'],
            'time_of_day': ['afternoon', 'mid_morning'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.90,
            'priority_weight': 1.5
        },
        
        # Fleet Management intents
        'tko:CustomerDelivery': {
            'destination_poi_types': ['ResidentialBuilding', 'House', 'ApartmentBuilding', 'OfficeBuilding'],
            'time_of_day': ['morning', 'mid_morning', 'afternoon'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.70,
            'modality': ['driving'],
            'use_case': ['fleet_management'],
            'priority_weight': 1.0
        },
        'tko:WarehousePickup': {
            'origin_poi_types': ['Warehouse', 'DistributionCenter', 'LogisticsHub'],
            'time_of_day': ['early_morning', 'morning', 'mid_morning'],
            'day_of_week': ['weekday'],
            'confidence_base': 0.85,
            'use_case': ['fleet_management'],
            'priority_weight': 1.0
        }
    }
    
    def __init__(self, tko_file: Optional[str] = None):
        """
        Initialize Intent Predictor
        
        Args:
            tko_file: Optional TKO ontology file for intent hierarchy
        """
        self.logger = logging.getLogger(__name__)
        
        # Load TKO ontology if provided
        self.tko_graph = None
        if tko_file:
            try:
                self.tko_graph = Graph()
                self.tko_graph.parse(tko_file, format="turtle")
                print(f"✓ Loaded TKO ontology with {len(self.tko_graph):,} triples")
            except Exception as e:
                print(f"⚠  Could not load TKO ontology: {e}")
        
        # TODO: Load trained ML model if available
        self.ml_model = None
    
    def predict_intent(self,
                      trip_data: Dict,
                      use_case: str = 'consumer') -> IntentPrediction:
        """
        Predict trip intent from trip data
        
        Args:
            trip_data: Dictionary with trip information
            use_case: 'consumer', 'fleet_management', 'transportation_planning'
            
        Returns:
            IntentPrediction object
        """
        # Extract features
        features = self._extract_intent_features(trip_data)
        
        # Try rule-based prediction first (most reliable)
        rule_prediction = self._rule_based_prediction(features, use_case)
        
        if rule_prediction and rule_prediction.confidence > 0.6:
            return rule_prediction
        
        # Try ML model if available
        if self.ml_model:
            ml_prediction = self._ml_based_prediction(features, use_case)
            if ml_prediction and ml_prediction.confidence > rule_prediction.confidence:
                return ml_prediction
        
        # Fallback to generic intent with low confidence
        if rule_prediction:
            return rule_prediction
        
        return self._default_prediction(features, use_case)
    
    def _extract_intent_features(self, trip_data: Dict) -> Dict:
        """Extract features relevant for intent prediction"""
        features = {}
        
        # Time features
        start_time = trip_data.get('start_time')
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        
        if start_time:
            features['time_of_day'] = self._categorize_time(start_time.time())
            features['day_of_week'] = 'weekday' if start_time.weekday() < 5 else 'weekend'
            features['hour'] = start_time.hour
            features['is_weekend'] = start_time.weekday() >= 5
        
        # POI features
        origin_poi = trip_data.get('origin_poi', {})
        dest_poi = trip_data.get('destination_poi', {})
        
        features['origin_poi_type'] = self._extract_poi_type(origin_poi)
        features['destination_poi_type'] = self._extract_poi_type(dest_poi)
        features['origin_poi_name'] = origin_poi.get('name', '')
        features['destination_poi_name'] = dest_poi.get('name', '')
        
        # Trip characteristics
        features['modality'] = trip_data.get('modality', 'unknown')
        features['distance_meters'] = trip_data.get('distance_meters', 0)
        features['duration_seconds'] = trip_data.get('duration_seconds', 0)
        features['dwell_time'] = trip_data.get('dwell_time', 0)
        
        # Calculate average speed
        if features['duration_seconds'] > 0:
            features['average_speed_mps'] = features['distance_meters'] / features['duration_seconds']
        else:
            features['average_speed_mps'] = 0
        
        return features
    
    def _rule_based_prediction(self, features: Dict, use_case: str) -> Optional[IntentPrediction]:
        """
        Apply rule-based intent inference with improved POI matching
        FIXED: Properly prioritizes destination-based intents over origin-based
        """
        
        origin_based_candidates = []
        destination_based_candidates = []
        both_poi_candidates = []
        
        for intent_class, rules in self.INTENT_RULES.items():
            # Skip if use case doesn't match
            if 'use_case' in rules and use_case not in rules['use_case']:
                continue
            
            score = 0.0
            evidence = []
            matches = 0
            checks = 0
            
            has_origin_rule = 'origin_poi_types' in rules
            has_dest_rule = 'destination_poi_types' in rules
            
            origin_matched = False
            dest_matched = False
            
            # Check origin POI type
            if has_origin_rule:
                checks += 1
                if features.get('origin_poi_type') in rules['origin_poi_types']:
                    score += 0.5
                    matches += 1
                    origin_matched = True
                    evidence.append(f"Origin POI type: {features.get('origin_poi_type')}")
            
            # Check destination POI type
            if has_dest_rule:
                checks += 1
                if features.get('destination_poi_type') in rules['destination_poi_types']:
                    score += 0.5
                    matches += 1
                    dest_matched = True
                    evidence.append(f"Destination POI type: {features.get('destination_poi_type')}")
            
            # CRITICAL: Skip if no POI match when POI rules exist
            if (has_origin_rule or has_dest_rule) and not (origin_matched or dest_matched):
                continue
            
            # Check time of day
            if 'time_of_day' in rules:
                checks += 1
                if features.get('time_of_day') in rules['time_of_day']:
                    score += 0.2
                    matches += 1
                    evidence.append(f"Time of day: {features.get('time_of_day')}")
            
            # Check day of week
            if 'day_of_week' in rules:
                checks += 1
                rule_days = rules['day_of_week']
                if 'any' in rule_days or features.get('day_of_week') in rule_days:
                    score += 0.2
                    matches += 1
                    evidence.append(f"Day of week: {features.get('day_of_week')}")
            
            # Check modality
            if 'modality' in rules:
                checks += 1
                if features.get('modality') in rules['modality']:
                    score += 0.1
                    matches += 1
                    evidence.append(f"Modality: {features.get('modality')}")
            
            # Check dwell time
            if 'dwell_time_min' in rules:
                checks += 1
                if features.get('dwell_time', 0) >= rules['dwell_time_min']:
                    score += 0.15
                    matches += 1
                    evidence.append(f"Sufficient dwell time")
            
            # Calculate final confidence
            if matches > 0 and checks > 0:
                # Normalize score by number of checks
                normalized_score = (matches / checks)
                # Apply base confidence from rules
                base_confidence = rules.get('confidence_base', 0.7)
                # Apply priority weight
                priority_weight = rules.get('priority_weight', 1.0)
                
                final_confidence = normalized_score * base_confidence * priority_weight
                
                candidate = {
                    'intent_class': intent_class,
                    'confidence': final_confidence,
                    'evidence': evidence,
                    'priority_weight': priority_weight
                }
                
                # Categorize by match type
                if origin_matched and dest_matched:
                    both_poi_candidates.append(candidate)
                elif dest_matched:
                    destination_based_candidates.append(candidate)
                elif origin_matched:
                    origin_based_candidates.append(candidate)
        
        # PRIORITY SELECTION: Destination > Both > Origin
        # This ensures healthcare/service destinations override work origins
        
        best_candidate = None
        
        if destination_based_candidates:
            best_candidate = max(destination_based_candidates, key=lambda x: x['confidence'])
        elif both_poi_candidates:
            best_candidate = max(both_poi_candidates, key=lambda x: x['confidence'])
        elif origin_based_candidates:
            best_candidate = max(origin_based_candidates, key=lambda x: x['confidence'])
        
        if best_candidate:
            subclass = best_candidate['intent_class'].split(':')[-1]
            return IntentPrediction(
                intent_class=best_candidate['intent_class'],
                intent_subclass=subclass,
                confidence=best_candidate['confidence'],
                inference_method='rule_based',
                supporting_evidence=best_candidate['evidence']
            )
        
        return None
    
    def _ml_based_prediction(self, features: Dict, use_case: str) -> Optional[IntentPrediction]:
        """ML-based intent prediction (placeholder for future enhancement)"""
        # TODO: Implement ML model prediction
        return None
    
    def _default_prediction(self, features: Dict, use_case: str) -> IntentPrediction:
        """Fallback prediction when no confident match"""
        return IntentPrediction(
            intent_class='tko:Unknown',
            intent_subclass='Unknown',
            confidence=0.3,
            inference_method='default',
            supporting_evidence=['No confident intent match found']
        )
    
    def _categorize_time(self, t: time) -> str:
        """Categorize time into time-of-day bucket"""
        for category, (start, end) in self.TIME_CATEGORIES.items():
            if category == 'late_night':
                if t >= start or t < end:
                    return category
            else:
                if start <= t < end:
                    return category
        return 'unknown'
    
    def _extract_poi_type(self, poi: Dict) -> str:
        """Extract POI type from POI data"""
        poi_type = poi.get('type', '')
        if isinstance(poi_type, str):
            return poi_type.split(':')[-1].split('/')[-1]
        return 'Unknown'
    
    def predict_secondary_intents(self, primary_intent: IntentPrediction,
                                  trip_data: Dict) -> List[IntentPrediction]:
        """Predict secondary/chained intents"""
        # TODO: Implement secondary intent prediction
        return []
    
    def get_intent_hierarchy(self, intent_class: str) -> List[str]:
        """Get intent class hierarchy from TKO ontology"""
        if not self.tko_graph:
            return [intent_class]
        
        hierarchy = [intent_class]
        
        query = f"""
        PREFIX tko: <urn:trip-kg:>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?superclass
        WHERE {{
            <{intent_class}> rdfs:subClassOf+ ?superclass .
        }}
        """
        
        try:
            results = self.tko_graph.query(query)
            for row in results:
                hierarchy.append(str(row.superclass))
        except Exception as e:
            self.logger.warning(f"Could not query intent hierarchy: {e}")
        
        return hierarchy
    
    def analyze_trip_pattern(self, trips: List[Dict]) -> Dict:
        """Analyze patterns across multiple trips for a traveler"""
        patterns = {
            'recurring_intents': defaultdict(int),
            'time_of_day_distribution': defaultdict(int),
            'day_of_week_distribution': defaultdict(int),
            'common_destinations': defaultdict(int),
            'modality_distribution': defaultdict(int)
        }
        
        for trip in trips:
            features = self._extract_intent_features(trip)
            intent = self.predict_intent(trip)
            
            patterns['recurring_intents'][intent.intent_class] += 1
            patterns['time_of_day_distribution'][features.get('time_of_day', 'unknown')] += 1
            patterns['day_of_week_distribution'][features.get('day_of_week', 'unknown')] += 1
            patterns['modality_distribution'][features.get('modality', 'unknown')] += 1
            
            dest_poi = trip.get('destination_poi', {})
            dest_name = dest_poi.get('name', 'Unknown')
            patterns['common_destinations'][dest_name] += 1
        
        return dict(patterns)
    
    def explain_prediction(self, prediction: IntentPrediction) -> str:
        """Generate human-readable explanation of prediction"""
        explanation = f"Predicted intent: {prediction.intent_subclass} "
        explanation += f"(confidence: {prediction.confidence:.1%})\n\n"
        explanation += f"Inference method: {prediction.inference_method}\n\n"
        
        if prediction.supporting_evidence:
            explanation += "Supporting evidence:\n"
            for evidence in prediction.supporting_evidence:
                explanation += f"  • {evidence}\n"
        
        return explanation


# Example usage
if __name__ == "__main__":
    import sys
    
    tko_file = sys.argv[1] if len(sys.argv) > 1 else "tko_ontology_v2.ttl"
    predictor = IntentPredictor(tko_file)
    
    print("\n" + "="*60)
    print("TESTING TRIP INTENT PREDICTION - FIXED VERSION")
    print("="*60)
    
    # Test case that was failing: Doctor visit from office
    test_trip = {
        'name': 'Doctor Visit from Office (Fixed)',
        'origin_poi': {
            'name': 'Workplace',
            'type': 'uko:OfficeBuilding'
        },
        'destination_poi': {
            'name': 'Medical Center',
            'type': 'uko:DoctorsOffice'
        },
        'start_time': datetime(2025, 1, 16, 14, 0),  # Thursday 2pm
        'end_time': datetime(2025, 1, 16, 14, 30),
        'modality': 'driving',
        'distance_meters': 5000,
        'duration_seconds': 1800,
        'dwell_time': 2400  # 40 minutes
    }
    
    print(f"\n--- Test: {test_trip['name']} ---")
    print(f"Origin: {test_trip['origin_poi']['name']} ({test_trip['origin_poi']['type'].split(':')[-1]})")
    print(f"Destination: {test_trip['destination_poi']['name']} ({test_trip['destination_poi']['type'].split(':')[-1]})")
    print(f"Time: {test_trip['start_time'].strftime('%A, %I:%M %p')}")
    print(f"Modality: {test_trip['modality']}")
    print(f"Dwell time: {test_trip['dwell_time']/60:.0f} minutes")
    
    prediction = predictor.predict_intent(test_trip, use_case='consumer')
    print(f"\n{predictor.explain_prediction(prediction)}")
    
    print("\n" + "="*60)
    print("EXPECTED: DoctorVisit (not CommuteFromWork)")
    print("="*60)