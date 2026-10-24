#!/bin/bash
#################################################################
#
#    GeoRotatE Training Script for Apple Silicon (M1/M2/M3)
#    Optimized settings for MacBook Air with 8-16GB unified memory
#
#    Synapse Partners, LLC 
#################################################################

# ============================================
# PHASE 3: Prepare Data for Embeddings
# ============================================
echo "=========================================="
echo "PHASE 3: Preparing data for GeoRotatE..."
echo "=========================================="

python georotate_kge/data/prepare_georotate_data.py \
    --kg_file contracosta_kg_enhanced.ttl \
    --output_dir georotate_training_data

# ============================================
# PHASE 4: Train GeoRotatE Model
# ============================================
echo ""
echo "=========================================="
echo "PHASE 4: Training GeoRotatE model..."
echo "=========================================="

# Settings optimized for M3 MacBook Air:
# - embedding_dim 256: Good balance of quality vs memory
# - batch_size 1024: Reduced from 2048 for memory efficiency
# - negative_samples 128: Reduced from 256 for faster training
# - validate_every 5: Check progress every 5 epochs
# - patience 2: Stop if no improvement for 2 validations (10 epochs)

python georotate_kge/train_georotate.py \
    --data_dir georotate_training_data \
    --output_dir georotate_output \
    --embedding_dim 256 \
    --batch_size 1024 \
    --negative_samples 128 \
    --epochs 100 \
    --validate_every 5 \
    --patience 2 \
    --lr 0.001

echo ""
echo "=========================================="
echo "Training Complete!"
echo "=========================================="
echo "Embeddings saved to: georotate_output/"
echo ""
echo "To query embeddings, use:"
echo "  python -c \"from georotate_kge.inference.similarity import GeoRotatESimilaritySearch; ...\""
