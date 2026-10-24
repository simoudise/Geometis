#################################################################
#
#    Purpose: Prepare the data in the knowledge graph to be used  
#    by the SE-KGE model to generate goespatial embeddings.
#
#    Synapse Partners, LLC 
#################################################################

import rdflib
from rdflib.namespace import RDF
import os
import re
import argparse
import time

# Define the namespaces used in your knowledge graph
UKO = rdflib.Namespace("urn:urban-kg:")
GEO = rdflib.Namespace("http://www.opengis.net/ont/geosparql#")
RDFS = rdflib.namespace.RDFS

def prepare_embedding_data(kg_path: str, output_dir: str = "embedding_training_data"):
    """
    Loads the knowledge graph and extracts the necessary files for training a KGE model.

    Args:
        kg_path (str): The path to the input .ttl knowledge graph file.
        output_dir (str): The directory where the output files will be saved.
    """
    if not os.path.exists(kg_path):
        print(f"Error: Knowledge graph file not found at '{kg_path}'")
        return

    print(f"Loading knowledge graph from: {kg_path}...")
    start_time = time.time()
    graph = rdflib.Graph()
    graph.parse(kg_path, format="turtle")
    load_time = time.time() - start_time
    print(f"✓ Knowledge graph loaded in {load_time:.2f} seconds ({len(graph):,} triples).")

    os.makedirs(output_dir, exist_ok=True)
    
    triples_path = os.path.join(output_dir, "triples.txt")
    coords_path = os.path.join(output_dir, "coordinates.txt")

    # --- 1. Extract Triples ---
    print(f"Extracting triples to '{triples_path}'...")
    num_triples = 0
    with open(triples_path, 'w', encoding='utf-8') as f:
        # We only want triples where the subject, predicate, and object are all URIs.
        # This extracts the core relational structure of the graph.
        for s, p, o in graph:
            if isinstance(s, rdflib.URIRef) and isinstance(p, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
                f.write(f"{s}\t{p}\t{o}\n")
                num_triples += 1
    print(f"✓ Extracted {num_triples:,} relational triples.")

    # --- 2. Extract Coordinates ---
    print(f"Extracting entity coordinates to '{coords_path}'...")
    
    # We use a SPARQL query to efficiently get the lat/lon for all entities.
    query = """
        PREFIX uko: <urn:urban-kg:>
        SELECT ?entity ?lat ?lon
        WHERE {
            ?entity uko:latitude ?lat ;
                    uko:longitude ?lon .
        }
    """
    
    results = graph.query(query)
    num_coords = 0
    with open(coords_path, 'w', encoding='utf-8') as f:
        for row in results:
            entity_uri = str(row.entity)
            lat = str(row.lat)
            lon = str(row.lon)
            f.write(f"{entity_uri}\t{lat}\t{lon}\n")
            num_coords += 1
    print(f"✓ Extracted coordinates for {num_coords:,} entities.")
    
    print("\n--- Data Preparation Complete ---")
    print(f"Output directory: '{output_dir}'")
    print(f"Next step: Run generate_embeddings_using_geoTransE.py on the files in this directory.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prepare Contra Costa KG data for embedding model training."
    )
    parser.add_argument(
        "--kg_file", 
        default="contracosta_kg_enhanced.ttl", 
        help="Path to the input knowledge graph .ttl file."
    )
    parser.add_argument(
        "--output_dir", 
        default="embedding_training_data", 
        help="Directory to save the output training files."
    )
    args = parser.parse_args()
    
    prepare_embedding_data(args.kg_file, args.output_dir)
