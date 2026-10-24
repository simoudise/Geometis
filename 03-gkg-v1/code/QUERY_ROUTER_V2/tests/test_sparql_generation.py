#!/usr/bin/env python3
"""
Unit Tests for Query Router

These tests verify SPARQL generation WITHOUT loading the knowledge graph.
Run these before any integration testing to catch issues early.

Usage:
    python -m pytest tests/test_sparql_generation.py -v
    or
    python tests/test_sparql_generation.py

Copyright (c) 2025 Synapse Partners, LLC
"""

import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entity_extractors import EntityExtractor, extract_entities
from sparql_generator import SPARQLGenerator, generate_sparql
from query_classifier import QueryClassifier, QueryType, classify_query
import sparql_templates as templates


class TestEntityExtraction:
    """Test entity extraction from queries."""
    
    def test_extract_antioch(self):
        """Should extract Antioch from query."""
        entities = extract_entities("Which schools in Antioch have the most collisions?")
        assert entities.city == "Antioch"
    
    def test_extract_walnut_creek(self):
        """Should extract Walnut Creek (two words)."""
        entities = extract_entities("Find schools near HIN in Walnut Creek")
        assert entities.city == "Walnut Creek"
    
    def test_extract_pleasant_hill(self):
        """Should extract Pleasant Hill."""
        entities = extract_entities("How many collisions in Pleasant Hill?")
        assert entities.city == "Pleasant Hill"
    
    def test_no_city(self):
        """Should return None when no city mentioned."""
        entities = extract_entities("Find all schools with collisions")
        assert entities.city is None
    
    def test_extract_fatal(self):
        """Should detect fatal severity."""
        entities = extract_entities("Which roads have the most fatal collisions?")
        assert entities.severity == "fatal"
    
    def test_extract_entity_name(self):
        """Should extract entity name from 'around X' pattern."""
        entities = extract_entities("What infrastructure exists around Lincoln Elementary?")
        assert entities.entity_name is not None
        assert "lincoln" in entities.entity_name.lower()
    
    def test_extract_limit(self):
        """Should extract limit from 'top N' pattern."""
        entities = extract_entities("Show top 5 schools with most collisions")
        assert entities.limit == 5


class TestQueryClassification:
    """Test query classification."""
    
    def test_aggregation_most(self):
        """'most collisions' should classify as AGGREGATION."""
        result = classify_query("Which schools have the most collisions?")
        assert result.query_type == QueryType.AGGREGATION
    
    def test_aggregation_count(self):
        """'how many' should classify as AGGREGATION."""
        result = classify_query("How many schools are in Antioch?")
        assert result.query_type == QueryType.AGGREGATION
    
    def test_similarity(self):
        """'similar to' should classify as SIMILARITY."""
        result = classify_query("Find schools similar to Lincoln Elementary")
        assert result.query_type == QueryType.SIMILARITY
    
    def test_clustering(self):
        """'cluster' should classify as CLUSTERING."""
        result = classify_query("Cluster schools by safety profile")
        assert result.query_type == QueryType.CLUSTERING
    
    def test_prediction(self):
        """'predict which need' should classify as PREDICTION."""
        result = classify_query("Predict which schools need crosswalks")
        assert result.query_type == QueryType.PREDICTION
    
    def test_infrastructure(self):
        """'infrastructure around' should classify as INFRASTRUCTURE."""
        result = classify_query("What pedestrian infrastructure exists around Lincoln Elementary?")
        assert result.query_type == QueryType.INFRASTRUCTURE
    
    def test_schema(self):
        """'what types' should classify as SCHEMA."""
        result = classify_query("What types of entities exist?")
        assert result.query_type == QueryType.SCHEMA


class TestSPARQLGeneration:
    """Test SPARQL generation - CRITICAL TESTS."""
    
    def test_schools_collisions_with_city_has_filter(self):
        """
        CRITICAL: Schools with collisions in Antioch MUST have city filter.
        This was the bug that caused Richmond schools to appear.
        """
        result = generate_sparql("Which schools in Antioch have the most collisions?")
        
        assert result is not None, "Should generate SPARQL"
        assert result.city == "Antioch", f"Should extract city, got {result.city}"
        assert result.has_city_filter, "MUST have city filter"
        assert "Antioch" in result.sparql, "SPARQL must contain Antioch"
        assert "partOf" in result.sparql, "Must use partOf for city filter"
    
    def test_schools_collisions_pittsburg(self):
        """Should filter by Pittsburg."""
        result = generate_sparql("Schools in Pittsburg with most collisions nearby")
        
        assert result is not None
        assert result.city == "Pittsburg"
        assert "Pittsburg" in result.sparql
    
    def test_schools_collisions_richmond(self):
        """Should filter by Richmond."""
        result = generate_sparql("Which kindergartens in Richmond have collisions?")
        
        assert result is not None
        assert result.city == "Richmond"
        assert "Richmond" in result.sparql
    
    def test_schools_collisions_no_city_no_filter(self):
        """Without city, should NOT have city filter."""
        result = generate_sparql("Which schools have the most collisions?")
        
        assert result is not None
        assert result.city is None
        assert result.has_city_filter is False
    
    def test_schools_near_hin_with_city(self):
        """Schools near HIN should have city filter."""
        result = generate_sparql("Find schools near HIN in Walnut Creek")
        
        assert result is not None
        assert result.city == "Walnut Creek"
        assert "Walnut_Creek" in result.sparql  # URI format
    
    def test_count_schools_with_city(self):
        """Count schools should have city filter."""
        result = generate_sparql("How many schools in Pleasant Hill?")
        
        assert result is not None
        assert result.city == "Pleasant Hill"
        assert "Pleasant_Hill" in result.sparql
    
    def test_infrastructure_uses_name_not_city(self):
        """Infrastructure queries use name matching, not city filter."""
        result = generate_sparql("What infrastructure around Lincoln Elementary?")
        
        assert result is not None
        assert "lincoln" in result.sparql.lower()
        # This query uses name matching, so has_city_filter may be False
    
    def test_roads_collisions_with_city(self):
        """Roads with collisions should have city filter."""
        result = generate_sparql("Which roads in Antioch have the most fatal collisions?")
        
        assert result is not None
        assert result.city == "Antioch"
        assert "Antioch" in result.sparql
    
    def test_transit_near_schools_with_city(self):
        """Transit near schools should have city filter."""
        result = generate_sparql("Find transit stops near schools in Richmond")
        
        assert result is not None
        assert result.city == "Richmond"
        assert "Richmond" in result.sparql


class TestSPARQLTemplates:
    """Test SPARQL template functions directly."""
    
    def test_schools_with_most_collisions_city(self):
        """Template should include city filter when city provided."""
        sparql = templates.schools_with_most_collisions(city="Antioch", limit=20)
        
        assert "Antioch" in sparql
        assert "partOf" in sparql
        assert "collisionNearSchool" in sparql
    
    def test_schools_with_most_collisions_no_city(self):
        """Template should NOT include city filter when city is None."""
        sparql = templates.schools_with_most_collisions(city=None, limit=20)
        
        assert "Antioch" not in sparql
        assert "partOf" not in sparql or "partOf" in sparql and "city" not in sparql
    
    def test_city_filter_function(self):
        """City filter helper should generate correct SPARQL."""
        filter_str = templates.get_city_filter("Walnut Creek", "school")
        
        assert "Walnut_Creek" in filter_str  # Spaces replaced with underscores
        assert "?school" in filter_str
        assert "partOf" in filter_str
    
    def test_collision_city_filter(self):
        """Collision city filter should use uko:city property."""
        filter_str = templates.get_collision_city_filter("Antioch")
        
        assert "ANTIOCH" in filter_str  # Upper case for FILTER
        assert "uko:city" in filter_str


def run_all_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestEntityExtraction,
        TestQueryClassification,
        TestSPARQLGeneration,
        TestSPARQLTemplates,
    ]
    
    total = 0
    passed = 0
    failed = []
    
    print("=" * 60)
    print("RUNNING QUERY ROUTER UNIT TESTS (No KG Required)")
    print("=" * 60)
    
    for test_class in test_classes:
        print(f"\n{test_class.__name__}:")
        instance = test_class()
        
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                total += 1
                try:
                    getattr(instance, method_name)()
                    print(f"  ✓ {method_name}")
                    passed += 1
                except AssertionError as e:
                    print(f"  ✗ {method_name}")
                    print(f"    FAILED: {e}")
                    failed.append((test_class.__name__, method_name, str(e)))
                except Exception as e:
                    print(f"  ✗ {method_name}")
                    print(f"    ERROR: {e}")
                    failed.append((test_class.__name__, method_name, traceback.format_exc()))
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 60)
    
    if failed:
        print("\nFAILED TESTS:")
        for class_name, method, error in failed:
            print(f"\n  {class_name}.{method}:")
            print(f"    {error[:200]}")
        return 1
    else:
        print("\n✓ ALL TESTS PASSED")
        return 0


if __name__ == '__main__':
    sys.exit(run_all_tests())
