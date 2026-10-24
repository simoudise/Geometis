#!/usr/bin/env python3
"""
Validate Embeddings Match Knowledge Graph Entities

This script verifies that the trained embeddings contain the actual
entities that appear in KG query results.

Usage:
    python validate_embeddings.py \
        --kg contracosta_kg_final_with_safety_enhanced.nt \
        --embeddings embeddings_output/entity_embeddings.pt

Copyright (c) 2025 Synapse Partners, LLC
"""

import argparse
import sys
import torch
from rdflib import Graph


def main():
    parser = argparse.ArgumentParser(
        description='Validate embeddings match KG entities'
    )
    parser.add_argument('--kg', required=True, help='Path to knowledge graph')
    parser.add_argument('--embeddings', required=True, help='Path to embeddings .pt file')
    args = parser.parse_args()
    
    print("=" * 60)
    print("VALIDATING EMBEDDINGS AGAINST KNOWLEDGE GRAPH")
    print("=" * 60)
    
    # Load embeddings
    print(f"\nLoading embeddings from {args.embeddings}...")
    data = torch.load(args.embeddings, map_location='cpu')
    
    print(f"  Keys in file: {list(data.keys())}")
    
    embeddings = data.get('embeddings')
    print(f"  Embedding tensor shape: {embeddings.shape if embeddings is not None else 'None'}")
    
    # Get entity mapping (handle both formats)
    if 'entity_to_idx' in data:
        entity_to_idx = data['entity_to_idx']
        print(f"  entity_to_idx entries: {len(entity_to_idx)}")
    elif 'id_to_entity' in data:
        id_to_entity = data['id_to_entity']
        entity_to_idx = {v: k for k, v in id_to_entity.items()}
        print(f"  id_to_entity entries: {len(id_to_entity)} (converted to entity_to_idx)")
    else:
        print("  ✗ No entity mapping found!")
        return 1
    
    # Sample entities from embeddings
    sample_entities = list(entity_to_idx.keys())[:5]
    print(f"\n  Sample entities in embeddings:")
    for e in sample_entities:
        print(f"    {e}")
    
    # Check if these look like instances
    instance_count = sum(1 for e in entity_to_idx.keys() if '/entity/' in str(e))
    schema_count = len(entity_to_idx) - instance_count
    print(f"\n  Instance entities: {instance_count:,}")
    print(f"  Schema entities: {schema_count:,}")
    
    if instance_count < 1000:
        print(f"\n  ⚠️  WARNING: Low instance count. Embeddings may be trained on schema only.")
    
    # Load KG and run test query
    print(f"\nLoading KG from {args.kg}...")
    g = Graph()
    g.parse(args.kg, format='nt')
    print(f"  Loaded {len(g):,} triples")
    
    # Query for schools in Antioch
    print("\nRunning test query: Schools in Antioch...")
    query = """
    PREFIX uko: <urn:urban-kg:>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?school ?name WHERE {
        ?school a uko:School .
        ?school uko:partOf <urn:urban-kg:entity/osm/city/Antioch> .
        OPTIONAL { ?school rdfs:label ?name }
    }
    LIMIT 10
    """
    
    results = list(g.query(query))
    print(f"  Found {len(results)} schools in Antioch")
    
    # Check if these schools are in embeddings
    print("\nChecking if query results are in embeddings:")
    found = 0
    not_found = 0
    
    for row in results:
        school_uri = str(row[0])
        school_name = str(row[1]) if row[1] else "Unknown"
        
        if school_uri in entity_to_idx:
            idx = entity_to_idx[school_uri]
            emb_norm = torch.norm(embeddings[idx]).item()
            print(f"  ✓ {school_name[:40]}")
            print(f"      URI: {school_uri}")
            print(f"      Index: {idx}, ||emb||: {emb_norm:.3f}")
            found += 1
        else:
            print(f"  ✗ {school_name[:40]}")
            print(f"      URI: {school_uri}")
            print(f"      NOT IN EMBEDDINGS")
            not_found += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"\nSchools in Antioch:")
    print(f"  Found in embeddings: {found}")
    print(f"  Missing from embeddings: {not_found}")
    
    if found > 0 and not_found == 0:
        print(f"\n✓ VALIDATION PASSED - Embeddings contain KG entities!")
        return 0
    elif found > 0:
        print(f"\n⚠️  PARTIAL MATCH - Some entities missing")
        return 0
    else:
        print(f"\n✗ VALIDATION FAILED - No KG entities found in embeddings")
        print(f"\n  This means the embeddings were trained on schema, not instances.")
        print(f"  Please retrain using extract_training_triples.py and train_instance_embeddings.py")
        return 1


if __name__ == '__main__':
    sys.exit(main())
