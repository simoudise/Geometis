#!/usr/bin/env python3
"""
Extract Embeddings from GeoRotatE Checkpoint

This script extracts entity and relation embeddings from a training checkpoint
and saves them in the format expected by the query test suite.

Usage:
    python extract_embeddings_from_checkpoint.py \
        --checkpoint ./georotate_output_v3/checkpoint_epoch_20.pt \
        --data_dir ./georotate_training_data_v3 \
        --output_dir ./georotate_output_v3

Copyright (c) 2025 Synapse Partners, LLC
"""

import os
import json
import argparse
import torch
import numpy as np


def extract_embeddings(checkpoint_path: str, data_dir: str, output_dir: str):
    """
    Extract embeddings from checkpoint and save in usable format.
    """
    print("="*60)
    print("EXTRACTING EMBEDDINGS FROM CHECKPOINT")
    print("="*60)
    
    # Load checkpoint
    print(f"\nLoading checkpoint: {checkpoint_path}")
    # Note: weights_only=False is safe here since we created this checkpoint ourselves
    # PyTorch 2.6+ defaults to weights_only=True for security
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=False)
    
    print(f"Checkpoint keys: {list(checkpoint.keys())}")
    
    # Get model state dict
    if 'model_state_dict' in checkpoint:
        state_dict = checkpoint['model_state_dict']
    elif 'state_dict' in checkpoint:
        state_dict = checkpoint['state_dict']
    else:
        # Maybe the checkpoint IS the state dict
        state_dict = checkpoint
    
    print(f"\nModel state dict keys:")
    for key in state_dict.keys():
        shape = state_dict[key].shape if hasattr(state_dict[key], 'shape') else 'N/A'
        print(f"  {key}: {shape}")
    
    # Find entity embeddings (try various common names)
    entity_emb = None
    entity_keys = ['entity_embeddings.weight', 'ent_embeddings.weight', 
                   'entity_embedding.weight', 'ent_emb.weight',
                   'entities.weight', 'entity_emb']
    
    for key in entity_keys:
        if key in state_dict:
            entity_emb = state_dict[key]
            print(f"\n✓ Found entity embeddings: {key} with shape {entity_emb.shape}")
            break
    
    # Try partial match if exact match fails
    if entity_emb is None:
        for key in state_dict.keys():
            if 'entity' in key.lower() and 'embed' in key.lower():
                entity_emb = state_dict[key]
                print(f"\n✓ Found entity embeddings: {key} with shape {entity_emb.shape}")
                break
    
    if entity_emb is None:
        print("\n✗ Could not find entity embeddings!")
        print("Available keys:", list(state_dict.keys()))
        return False
    
    # Find relation embeddings
    relation_emb = None
    relation_keys = ['relation_embeddings.weight', 'rel_embeddings.weight',
                     'relation_embedding.weight', 'rel_emb.weight',
                     'relations.weight', 'rel_emb']
    
    for key in relation_keys:
        if key in state_dict:
            relation_emb = state_dict[key]
            print(f"✓ Found relation embeddings: {key} with shape {relation_emb.shape}")
            break
    
    # Try partial match
    if relation_emb is None:
        for key in state_dict.keys():
            if 'relation' in key.lower() and 'embed' in key.lower():
                relation_emb = state_dict[key]
                print(f"✓ Found relation embeddings: {key} with shape {relation_emb.shape}")
                break
            elif 'rel' in key.lower() and 'embed' in key.lower():
                relation_emb = state_dict[key]
                print(f"✓ Found relation embeddings: {key} with shape {relation_emb.shape}")
                break
    
    # Find phase embeddings (specific to RotatE/GeoRotatE)
    phase_emb = None
    for key in state_dict.keys():
        if 'phase' in key.lower():
            phase_emb = state_dict[key]
            print(f"✓ Found phase embeddings: {key} with shape {phase_emb.shape}")
            break
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Load id_to_entity mapping from data_dir
    id_to_entity = {}
    entity_to_id_path = os.path.join(data_dir, 'entity_to_id.json')
    if os.path.exists(entity_to_id_path):
        with open(entity_to_id_path, 'r') as f:
            entity_to_id = json.load(f)
            id_to_entity = {int(v): k for k, v in entity_to_id.items()}
        print(f"✓ Loaded entity mappings: {len(id_to_entity)} entities")
    else:
        print(f"⚠ entity_to_id.json not found in {data_dir}")
    
    # Save entity embeddings in the format expected by query_test_suite
    # The test suite expects: {'embeddings': tensor, 'id_to_entity': dict}
    embeddings_data = {
        'embeddings': entity_emb,
        'id_to_entity': id_to_entity,
    }
    
    entity_emb_path = os.path.join(output_dir, 'entity_embeddings.pt')
    torch.save(embeddings_data, entity_emb_path)
    print(f"\n✓ Saved entity embeddings to: {entity_emb_path}")
    print(f"  Format: dict with 'embeddings' ({entity_emb.shape}) and 'id_to_entity' ({len(id_to_entity)} mappings)")
    
    # Also save raw embeddings as numpy for other uses
    entity_emb_np_path = os.path.join(output_dir, 'entity_embeddings.npy')
    np.save(entity_emb_np_path, entity_emb.numpy())
    print(f"✓ Saved entity embeddings (numpy) to: {entity_emb_np_path}")
    
    # Save relation embeddings
    if relation_emb is not None:
        relation_emb_path = os.path.join(output_dir, 'relation_embeddings.pt')
        torch.save(relation_emb, relation_emb_path)
        print(f"✓ Saved relation embeddings to: {relation_emb_path}")
        
        relation_emb_np_path = os.path.join(output_dir, 'relation_embeddings.npy')
        np.save(relation_emb_np_path, relation_emb.numpy())
        print(f"✓ Saved relation embeddings (numpy) to: {relation_emb_np_path}")
    
    # Save phase embeddings if present
    if phase_emb is not None:
        phase_emb_path = os.path.join(output_dir, 'phase_embeddings.pt')
        torch.save(phase_emb, phase_emb_path)
        print(f"✓ Saved phase embeddings to: {phase_emb_path}")
    
    # Copy mapping files from data_dir if they exist
    mapping_files = ['entity_to_id.json', 'relation_to_id.json', 
                     'spatial_relations.json', 'dataset_stats.json']
    
    print(f"\nCopying mapping files from {data_dir}...")
    for fname in mapping_files:
        src = os.path.join(data_dir, fname)
        dst = os.path.join(output_dir, fname)
        if os.path.exists(src):
            import shutil
            shutil.copy(src, dst)
            print(f"✓ Copied {fname}")
        else:
            print(f"  {fname} not found in data_dir")
    
    # Create config file with embedding info
    config = {
        'entity_embedding_dim': entity_emb.shape[1],
        'num_entities': entity_emb.shape[0],
        'num_relations': relation_emb.shape[0] if relation_emb is not None else None,
        'relation_embedding_dim': relation_emb.shape[1] if relation_emb is not None else None,
        'checkpoint_source': os.path.basename(checkpoint_path),
        'has_phase_embeddings': phase_emb is not None,
    }
    
    # Add training info if available
    if 'epoch' in checkpoint:
        config['trained_epochs'] = checkpoint['epoch']
    if 'best_mrr' in checkpoint:
        config['best_mrr'] = float(checkpoint['best_mrr'])
    if 'metrics' in checkpoint:
        config['final_metrics'] = checkpoint['metrics']
    
    config_path = os.path.join(output_dir, 'config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"✓ Saved config to: {config_path}")
    
    # Print summary
    print("\n" + "="*60)
    print("EXTRACTION COMPLETE")
    print("="*60)
    print(f"\nOutput directory: {output_dir}")
    print(f"\nFiles created:")
    for f in os.listdir(output_dir):
        size = os.path.getsize(os.path.join(output_dir, f))
        print(f"  {f}: {size/1024/1024:.2f} MB")
    
    print(f"\nEmbedding dimensions:")
    print(f"  Entities: {entity_emb.shape[0]:,} x {entity_emb.shape[1]}")
    if relation_emb is not None:
        print(f"  Relations: {relation_emb.shape[0]:,} x {relation_emb.shape[1]}")
    
    print(f"\nYou can now run the test queries with:")
    print(f"  python query_test_suite_v3.py \\")
    print(f"      --kg_file contracosta_kg_final_with_safety_enhanced.nt \\")
    print(f"      --embeddings_dir {output_dir}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Extract embeddings from GeoRotatE checkpoint"
    )
    parser.add_argument(
        "--checkpoint",
        required=True,
        help="Path to checkpoint file (e.g., checkpoint_epoch_20.pt)"
    )
    parser.add_argument(
        "--data_dir",
        required=True,
        help="Path to training data directory (for mapping files)"
    )
    parser.add_argument(
        "--output_dir",
        required=True,
        help="Path to output directory for extracted embeddings"
    )
    
    args = parser.parse_args()
    
    success = extract_embeddings(
        checkpoint_path=args.checkpoint,
        data_dir=args.data_dir,
        output_dir=args.output_dir
    )
    
    if not success:
        exit(1)


if __name__ == "__main__":
    main()
