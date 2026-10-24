#!/bin/bash
# =============================================================================
# GeoRotatE Training Script - Optimized for M3 MacBook Air
# =============================================================================
#
# This script runs the complete training pipeline with parameters optimized
# for Apple Silicon M3 with 16GB RAM.
#
# Expected runtime: 2.5-4 hours (with early stopping)
#
# Usage:
#   chmod +x train_m3_optimized.sh
#   ./train_m3_optimized.sh
#
# =============================================================================

set -e  # Exit on error

# Configuration
KG_FILE="contracosta_kg_enhanced.ttl"
OUTPUT_DIR="georotate_training_data"
MODEL_DIR="georotate_output"

echo "============================================================"
echo "GeoRotatE Training Pipeline - M3 Optimized"
echo "============================================================"
echo ""
echo "Knowledge Graph: $KG_FILE"
echo "Training Data:   $OUTPUT_DIR"
echo "Model Output:    $MODEL_DIR"
echo ""

# Check if virtual environment is active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "⚠ Virtual environment not active. Activating..."
    source georotate_env/bin/activate
fi

# Verify PyTorch and MPS
echo "Checking PyTorch and MPS availability..."
python3 -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'MPS available: {torch.backends.mps.is_available()}')
if torch.backends.mps.is_available():
    print('✓ M3 GPU acceleration enabled')
else:
    print('⚠ MPS not available, will use CPU')
"
echo ""

# =============================================================================
# Phase 3: Data Preparation with Stratified Sampling
# =============================================================================
echo "============================================================"
echo "PHASE 3: Data Preparation"
echo "============================================================"
echo ""

if [ -f "$OUTPUT_DIR/triples.txt" ]; then
    echo "Training data already exists in $OUTPUT_DIR"
    read -p "Regenerate? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$OUTPUT_DIR"
    else
        echo "Skipping data preparation..."
    fi
fi

if [ ! -f "$OUTPUT_DIR/triples.txt" ]; then
    echo "Running data preparation with stratified sampling..."
    echo "  - Proximity relations sampled at 5%"
    echo "  - All infrastructure/transit/connectivity relations kept"
    echo ""
    
    python3 data/prepare_georotate_data.py \
        --kg_file "$KG_FILE" \
        --output_dir "$OUTPUT_DIR" \
        --proximity_sample_rate 0.05 \
        --seed 42
    
    echo ""
    echo "✓ Data preparation complete"
fi

# Show data stats
if [ -f "$OUTPUT_DIR/dataset_stats.json" ]; then
    echo ""
    echo "Dataset Statistics:"
    python3 -c "
import json
with open('$OUTPUT_DIR/dataset_stats.json') as f:
    stats = json.load(f)
print(f\"  Entities:  {stats['num_entities']:,}\")
print(f\"  Relations: {stats['num_relations']:,}\")
print(f\"  Triples:   {stats['num_triples']:,}\")
print(f\"  With coords: {stats['num_entities_with_coords']:,}\")
print(f\"  With topo:   {stats['num_entities_with_topo']:,}\")
"
fi

echo ""

# =============================================================================
# Phase 4: Model Training
# =============================================================================
echo "============================================================"
echo "PHASE 4: GeoRotatE Model Training"
echo "============================================================"
echo ""
echo "M3-Optimized Parameters:"
echo "  - Embedding dimension: 256"
echo "  - Batch size: 512"
echo "  - Learning rate: 0.0005"
echo "  - Negative samples: 64"
echo "  - Epochs: 100 (with early stopping)"
echo "  - Early stopping patience: 10"
echo ""

read -p "Start training? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Training cancelled."
    exit 0
fi

echo ""
echo "Starting training... (estimated time: 2.5-4 hours)"
echo "Progress will be validated every 5 epochs."
echo ""

# Using correct argument names from train_georotate.py
python3 train_georotate.py \
    --data_dir "$OUTPUT_DIR" \
    --output_dir "$MODEL_DIR" \
    --embedding_dim 256 \
    --batch_size 512 \
    --lr 0.0005 \
    --negative_samples 64 \
    --epochs 100 \
    --patience 10 \
    --validate_every 5

echo ""
echo "============================================================"
echo "Training Complete!"
echo "============================================================"
echo ""
echo "Model outputs saved to: $MODEL_DIR"
echo ""
echo "Files created:"
ls -la "$MODEL_DIR"
echo ""
echo "Next steps:"
echo "  1. Review training results in $MODEL_DIR"
echo "  2. Use inference/similarity.py for similarity queries"
echo "  3. Optionally run llm_augmentation/area_discovery.py to add neighborhoods"
