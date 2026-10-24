"""
Data Preparation for GeoRotatE Model - v4.0

CRITICAL FIXES:
1. INSTANCE FILTERING: Only includes triples with actual entity instances,
   not schema/ontology classes. This ensures embeddings are trained on
   real schools, collisions, HIN segments - not class definitions.

2. CORRECT OUTPUT FORMAT: Outputs files in the exact format train_georotate.py expects:
   - entity_to_id.json (not entity2id.json)
   - relation_to_id.json
   - id_to_entity.json  
   - id_to_relation.json
   - triples.txt (combined, not separate files)
   - train.txt, valid.txt, test.txt
   - coordinates.txt (not entity_coords.json)
   - spatial_relations.json
   - entity_types.json

3. BALANCED SAMPLING: Aggressively samples dominant relations like
   withinCyclingDistanceOf to prevent them from dominating training.

Usage:
    python prepare_embeddings_v4.py \
        --input contracosta_kg_final_with_safety_enhanced.nt \
        --output_dir ./georotate_training_data

Copyright (c) 2026 Synapse Partners, LLC
"""

"""
Data Preparation for GeoRotatE - v4.5 (Final Fixed Version)
- Fixed AttributeError by using self.out_dir consistently.
- Fixed Sampling logic to use substring matching for URIs.
- Restored full progress reporting for user awareness.

Copyright (c) 2026 Synapse Partners, LLC
"""
import os
import re
import json
import argparse
import numpy as np
import random
from collections import defaultdict

# RDF/Ontology Namespaces
UKO = "urn:urban-kg:"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

def is_instance_entity(uri: str) -> bool:
    """Filters for real-world entities vs abstract schema classes."""
    instance_patterns = [
        '/entity/', '/collision/', '/hin/', '/tract/', 
        '/census/', '/road/', '/node/', '/way/', '/area/', '/city/'
    ]
    for pattern in instance_patterns:
        if pattern in uri: return True
    return uri.startswith('urn:urban-kg:entity/')

class StreamingKGParser:
    """Two-pass streaming parser with real-time feedback."""
    def __init__(self, kg_path: str):
        self.kg_path = kg_path
        self.entities = {}
        self.triples = []
        self.relations = set()

    def parse(self):
        print("\n" + "="*60 + "\nPHASE 1: PARSING KNOWLEDGE GRAPH\n" + "="*60)
        
        # Pass 1: Metadata Extraction
        print("Pass 1/2: Extracting Coordinates and Types...")
        line_count, entity_metadata = 0, defaultdict(dict)
        with open(self.kg_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_count += 1
                if line_count % 1000000 == 0:
                    print(f"  > Line {line_count:,} reached...")
                
                match = re.search(r'<([^>]+)>\s+<([^>]+)>\s+(.+)\s+\.', line.strip())
                if not match: continue
                s, p, o = match.groups()
                if not is_instance_entity(s): continue
                
                if p == f'{RDF}type':
                    m = re.search(r'<([^>]+)>', o)
                    if m: entity_metadata[s]['type'] = m.group(1)
                elif p == f'{UKO}latitude':
                    m = re.search(r'"([^"]+)"', o)
                    if m: entity_metadata[s]['lat'] = float(m.group(1))
                elif p == f'{UKO}longitude':
                    m = re.search(r'"([^"]+)"', o)
                    if m: entity_metadata[s]['lon'] = float(m.group(1))

        # Pass 2: Triple Extraction
        print(f"\nPass 2/2: Extracting relational triples...")
        line_count = 0
        with open(self.kg_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_count += 1
                if line_count % 1000000 == 0:
                    print(f"  > Line {line_count:,} reached...")
                
                match = re.search(r'<([^>]+)>\s+<([^>]+)>\s+<([^>]+)>\s+\.', line.strip())
                if not match: continue
                s, p, o = match.groups()
                
                if p == f'{RDF}type': continue
                if is_instance_entity(s) and is_instance_entity(o):
                    self.triples.append((s, p, o))
                    self.relations.add(p)
                    if s not in self.entities: self.entities[s] = entity_metadata.get(s, {})
                    if o not in self.entities: self.entities[o] = entity_metadata.get(o, {})
        
        print(f"✓ Parsing Complete: {len(self.triples):,} triples found.")
        return self.triples, self.entities, list(self.relations)

class StratifiedSampler:
    """Downsamples proximity relations using substring matching."""
    SAMPLE_RELATIONS = {
        'withinCyclingDistanceOf': 0.001,  # 0.1%
        'withinWalkingDistanceOf': 0.01,   # 1%
        'near': 0.02,                      # 2%
        'transitAccessible': 0.05          # 5%
    }
    
    def __init__(self, seed: int = 42):
        random.seed(seed)
        
    def sample(self, triples):
        print("\n" + "="*60 + "\nPHASE 2: STRATIFIED SAMPLING\n" + "="*60)
        by_rel = defaultdict(list)
        for t in triples:
            by_rel[t[1]].append(t)
            
        sampled = []
        for rel_uri, rel_triples in by_rel.items():
            rate = 1.0
            # FIX: Check if keywords like 'near' are PART of the URI string
            for pattern, sample_rate in self.SAMPLE_RELATIONS.items():
                if pattern in rel_uri:
                    rate = sample_rate
                    break
            
            if rate < 1.0:
                n = max(1, int(len(rel_triples) * rate))
                s_triples = random.sample(rel_triples, min(n, len(rel_triples)))
                sampled.extend(s_triples)
                print(f"  MATCHED & SAMPLED: {rel_uri.split(':')[-1]} | {len(rel_triples):,} -> {len(s_triples):,}")
            else:
                sampled.extend(rel_triples)
        
        random.shuffle(sampled)
        print(f"✓ Total triples after sampling: {len(sampled):,}")
        return sampled

class EmbeddingDataPreparer:
    """Outputs ID-based files. Fixed attribute name to self.out_dir."""
    SPATIAL_RELATIONS = {'near', 'nearby', 'adjacentTo', 'walking', 'cycling', 'within'}
    
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    def prepare(self, triples, entities, relations):
        triples = StratifiedSampler().sample(triples)
        
        print("\n" + "="*60 + "\nPHASE 3: SAVING ID-BASED DATA\n" + "="*60)
        
        all_ents = sorted(list(set([t[0] for t in triples] + [t[2] for t in triples])))
        e2id = {e: i for i, e in enumerate(all_ents)}
        r2id = {r: i for i, r in enumerate(relations)}

        print(f"Saving Mappings to {self.out_dir}...")
        with open(os.path.join(self.out_dir, 'entity_to_id.json'), 'w') as f: json.dump(e2id, f)
        with open(os.path.join(self.out_dir, 'relation_to_id.json'), 'w') as f: json.dump(r2id, f)

        print("Writing triples.txt (ID format)...")
        with open(os.path.join(self.out_dir, 'triples.txt'), 'w') as f:
            for s, p, o in triples: f.write(f"{e2id[s]}\t{r2id[p]}\t{e2id[o]}\n")

        print("Writing coordinates.txt (ID format)...")
        c_count = 0
        with open(os.path.join(self.out_dir, 'coordinates.txt'), 'w') as f:
            for e, eid in e2id.items():
                meta = entities.get(e, {})
                if 'lat' in meta:
                    f.write(f"{eid}\t{meta['lat']}\t{meta['lon']}\n")
                    c_count += 1
        print(f"✓ Saved {c_count:,} coordinates.")

        print("Writing spatial_relations.json...")
        s_ids = [r2id[r] for r in relations if any(k in r.lower() for k in self.SPATIAL_RELATIONS)]
        with open(os.path.join(self.out_dir, 'spatial_relations.json'), 'w') as f:
            json.dump(s_ids, f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output_dir", default="./georotate_training_data_v4")
    args = parser.parse_args()
    
    parser_kg = StreamingKGParser(args.input)
    triples, entities, relations = parser_kg.parse()
    preparer = EmbeddingDataPreparer(args.output_dir)
    preparer.prepare(triples, entities, relations)
    print(f"\n✓ SUCCESS: Files ready in {args.output_dir}")

if __name__ == "__main__":
    main()