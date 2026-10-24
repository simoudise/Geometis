"""
GeoRotatE Training Script

Train the GeoRotatE model on prepared knowledge graph data.

Usage:
    python train_georotate.py --data_dir georotate_training_data --epochs 100

Copyright (c) 2025 Synapse Partners, LLC
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import ReduceLROnPlateau
import numpy as np
import pandas as pd
import os
import argparse
import time
import json
import copy
from typing import Dict, Optional
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.georotate import GeoRotatE
from data.dataset import GeoRotatEDataModule, GeoRotatEConfig


class GeoRotatETrainer:
    """Trainer for GeoRotatE model."""
    
    def __init__(self, model, data_module, learning_rate=0.001, 
                 adversarial_temperature=1.0, regularization=0.0,
                 device=None, output_dir="georotate_output"):
        self.model = model
        self.data_module = data_module
        self.device = device or torch.device('cpu')
        self.output_dir = output_dir
        self.model.to(self.device)
        
        self.optimizer = optim.Adam(model.parameters(), lr=learning_rate)
        self.scheduler = ReduceLROnPlateau(self.optimizer, mode='max', factor=0.5, patience=5)
        self.adversarial_temperature = adversarial_temperature
        self.regularization = regularization
        self.best_mrr = 0.0
        self.best_epoch = 0
        self.best_model_state = None
        os.makedirs(output_dir, exist_ok=True)
    
    def train(self, epochs=100, validate_every=5, patience=10, save_checkpoints=True):
        """Main training loop."""
        print("\n" + "="*60)
        print("GeoRotatE Training")
        print("="*60)
        
        train_loader = self.data_module.get_train_dataloader()
        history = {'train_loss': [], 'valid_mrr': [], 'valid_hits10': []}
        epochs_without_improvement = 0
        
        for epoch in range(1, epochs + 1):
            train_loss = self._train_epoch(train_loader, epoch)
            history['train_loss'].append(train_loss)
            
            if epoch % validate_every == 0:
                print(f"\n--- Validation at Epoch {epoch} ---")
                metrics = self._validate()
                history['valid_mrr'].append(metrics['mrr'])
                history['valid_hits10'].append(metrics['hits@10'])
                print(f"MRR: {metrics['mrr']:.4f} | Hits@1: {metrics['hits@1']:.4f} | "
                      f"Hits@10: {metrics['hits@10']:.4f} | Mean Rank: {metrics['mean_rank']:.1f}")
                
                self.scheduler.step(metrics['mrr'])
                
                if metrics['mrr'] > self.best_mrr:
                    self.best_mrr = metrics['mrr']
                    self.best_epoch = epoch
                    self.best_model_state = copy.deepcopy(self.model.state_dict())
                    epochs_without_improvement = 0
                    print(f"*** New best model! ***")
                    if save_checkpoints:
                        self._save_checkpoint(epoch, metrics)
                else:
                    epochs_without_improvement += validate_every
                
                if epochs_without_improvement >= patience * validate_every:
                    print(f"\n--- Early stopping at epoch {epoch} ---")
                    break
        
        if self.best_model_state:
            print(f"\nLoading best model from epoch {self.best_epoch}")
            self.model.load_state_dict(self.best_model_state)
        
        return history
    
    def _train_epoch(self, train_loader, epoch):
        """Train for one epoch."""
        self.model.train()
        total_loss = 0.0
        num_batches = 0
        start_time = time.time()
        
        for batch_idx, batch in enumerate(train_loader):
            loss = self._train_step(batch)
            total_loss += loss
            num_batches += 1
            
            if (batch_idx + 1) % 100 == 0:
                print(f"  Epoch {epoch} | Batch {batch_idx + 1}/{len(train_loader)} | "
                      f"Loss: {total_loss / num_batches:.4f}")
        
        print(f"Epoch {epoch} | Loss: {total_loss / num_batches:.4f} | "
              f"Time: {time.time() - start_time:.1f}s")
        return total_loss / num_batches
    
    def _train_step(self, batch):
        """Single training step."""
        self.optimizer.zero_grad()
        
        head = batch['head'].to(self.device)
        relation = batch['relation'].to(self.device)
        tail = batch['tail'].to(self.device)
        negative_tails = batch['negative_tails'].to(self.device)
        
        head_coords = batch.get('head_coords')
        tail_coords = batch.get('tail_coords')
        head_topo = batch.get('head_topo')
        tail_topo = batch.get('tail_topo')
        
        if head_coords is not None:
            head_coords = head_coords.to(self.device)
            tail_coords = tail_coords.to(self.device)
        if head_topo is not None:
            head_topo = head_topo.to(self.device)
            tail_topo = tail_topo.to(self.device)
        
        # Positive scores
        positive_score = self.model(head, relation, tail,
                                   head_coords=head_coords, tail_coords=tail_coords,
                                   head_topo=head_topo, tail_topo=tail_topo, mode='single')
        
        # Negative scores
        batch_size = head.shape[0]
        num_neg = negative_tails.shape[1]
        
        head_exp = head.unsqueeze(1).expand(-1, num_neg).reshape(-1)
        rel_exp = relation.unsqueeze(1).expand(-1, num_neg).reshape(-1)
        neg_tails_flat = negative_tails.reshape(-1)
        
        neg_coords = neg_topo = None
        head_coords_exp = head_topo_exp = None
        
        # Move indices to CPU for indexing, then move result to device
        neg_tails_cpu = neg_tails_flat.cpu()
        
        if head_coords is not None:
            neg_coords = self.data_module.coordinates[neg_tails_cpu].to(self.device)
            head_coords_exp = head_coords.unsqueeze(1).expand(-1, num_neg, -1).reshape(-1, 2)
        if head_topo is not None:
            neg_topo = self.data_module.topo_features[neg_tails_cpu].to(self.device)
            head_topo_exp = head_topo.unsqueeze(1).expand(-1, num_neg, -1).reshape(-1, head_topo.shape[-1])
        
        negative_score = self.model(head_exp, rel_exp, neg_tails_flat,
                                   head_coords=head_coords_exp, tail_coords=neg_coords,
                                   head_topo=head_topo_exp, tail_topo=neg_topo,
                                   mode='single').view(batch_size, num_neg)
        
        # Loss
        neg_weights = torch.softmax(negative_score * self.adversarial_temperature, dim=-1).detach()
        pos_loss = -torch.log(torch.sigmoid(positive_score) + 1e-10).mean()
        neg_loss = -(neg_weights * torch.log(torch.sigmoid(-negative_score) + 1e-10)).sum(dim=-1).mean()
        loss = (pos_loss + neg_loss) / 2
        
        if self.regularization > 0:
            reg = (self.model.entity_embedding_real.weight.norm(p=2) +
                   self.model.entity_embedding_imag.weight.norm(p=2) +
                   self.model.relation_embedding.weight.norm(p=2))
            loss = loss + self.regularization * reg
        
        loss.backward()
        self.optimizer.step()
        return loss.item()
    
    def _validate(self, max_samples=5000):
        """
        Run validation with sampling for efficiency.
        
        Evaluates link prediction: given (head, relation, ?), rank the true tail
        among all possible entities.
        """
        self.model.eval()
        valid_loader = self.data_module.get_valid_dataloader()
        ranks = []
        
        num_entities = self.data_module.num_entities
        
        with torch.no_grad():
            sample_count = 0
            for batch_idx, batch in enumerate(valid_loader):
                # Get batch data
                heads = batch['head'].to(self.device)
                relations = batch['relation'].to(self.device)
                tails = batch['tail'].to(self.device)
                
                # Process each triple in the batch individually
                for i in range(len(heads)):
                    if sample_count >= max_samples:
                        break
                    
                    head = heads[i].item()  # Get scalar value
                    relation = relations[i].item()
                    tail = tails[i].item()
                    
                    # Create expanded tensors for scoring all entities
                    head_expanded = torch.full((num_entities,), head, dtype=torch.long, device=self.device)
                    relation_expanded = torch.full((num_entities,), relation, dtype=torch.long, device=self.device)
                    all_entities = torch.arange(num_entities, device=self.device)
                    
                    scores = self.model(head_expanded, relation_expanded, all_entities, mode='single')
                    
                    # Get rank of true tail (how many entities score higher + 1)
                    true_score = scores[tail]
                    rank = (scores > true_score).sum().item() + 1
                    ranks.append(rank)
                    sample_count += 1
                
                if sample_count >= max_samples:
                    break
                
                if (batch_idx + 1) % 50 == 0:
                    print(f"  Validated {sample_count}/{max_samples} samples...")
        
        # Compute metrics
        mrr = np.mean([1.0/r for r in ranks])
        hits_at_1 = sum(1 for r in ranks if r <= 1) / len(ranks)
        hits_at_3 = sum(1 for r in ranks if r <= 3) / len(ranks)
        hits_at_10 = sum(1 for r in ranks if r <= 10) / len(ranks)
        mean_rank = np.mean(ranks)
        
        return {
            'mrr': mrr, 
            'hits@1': hits_at_1,
            'hits@3': hits_at_3,
            'hits@10': hits_at_10,
            'mean_rank': mean_rank
        }
    
    def _save_checkpoint(self, epoch, metrics):
        """Save checkpoint."""
        path = os.path.join(self.output_dir, f"checkpoint_epoch_{epoch}.pt")
        torch.save({'epoch': epoch, 'model_state_dict': self.model.state_dict(),
                   'metrics': metrics}, path)
        print(f"  Saved: {path}")
    
    def save_embeddings(self, output_path=None):
        """Save embeddings."""
        if output_path is None:
            output_path = os.path.join(self.output_dir, "entity_embeddings.pt")
        
        self.model.eval()
        embeddings = self.model.get_entity_embeddings().cpu()
        
        torch.save({'embeddings': embeddings, 
                   'id_to_entity': self.data_module.id_to_entity}, output_path)
        print(f"Saved embeddings to: {output_path}")
        
        # CSV version
        csv_path = output_path.replace('.pt', '.csv')
        df = pd.DataFrame(embeddings.detach().numpy())
        df.insert(0, 'entity_id', range(len(df)))
        df.insert(1, 'entity_uri', [self.data_module.id_to_entity.get(i, '') for i in range(len(df))])
        df.columns = ['entity_id', 'entity_uri'] + [f'dim_{i}' for i in range(embeddings.shape[1])]
        df.to_csv(csv_path, index=False)
        print(f"Saved CSV to: {csv_path}")
    
    def test(self, max_samples=10000):
        """Final test evaluation."""
        print("\n" + "="*60 + "\nFinal Test Evaluation\n" + "="*60)
        
        self.model.eval()
        test_loader = self.data_module.get_test_dataloader()
        ranks = []
        
        num_entities = self.data_module.num_entities
        
        with torch.no_grad():
            sample_count = 0
            for batch_idx, batch in enumerate(test_loader):
                # Get batch data
                heads = batch['head'].to(self.device)
                relations = batch['relation'].to(self.device)
                tails = batch['tail'].to(self.device)
                
                # Process each triple in the batch individually
                for i in range(len(heads)):
                    if sample_count >= max_samples:
                        break
                    
                    head = heads[i].item()  # Get scalar value
                    relation = relations[i].item()
                    tail = tails[i].item()
                    
                    # Create expanded tensors for scoring all entities
                    head_expanded = torch.full((num_entities,), head, dtype=torch.long, device=self.device)
                    relation_expanded = torch.full((num_entities,), relation, dtype=torch.long, device=self.device)
                    all_entities = torch.arange(num_entities, device=self.device)
                    
                    scores = self.model(head_expanded, relation_expanded, all_entities, mode='single')
                    
                    # Get rank of true tail
                    true_score = scores[tail]
                    rank = (scores > true_score).sum().item() + 1
                    ranks.append(rank)
                    sample_count += 1
                
                if sample_count >= max_samples:
                    break
                
                if (batch_idx + 1) % 50 == 0:
                    print(f"  Tested {sample_count}/{max_samples} samples...")
        
        n = len(ranks)
        metrics = {
            'mrr': np.mean([1.0/r for r in ranks]),
            'hits@1': sum(1 for r in ranks if r <= 1) / n,
            'hits@3': sum(1 for r in ranks if r <= 3) / n,
            'hits@10': sum(1 for r in ranks if r <= 10) / n,
            'mean_rank': np.mean(ranks)
        }
        
        print(f"\nTest Results:")
        print(f"  MRR:       {metrics['mrr']:.4f}")
        print(f"  Hits@1:    {metrics['hits@1']:.4f}")
        print(f"  Hits@3:    {metrics['hits@3']:.4f}")
        print(f"  Hits@10:   {metrics['hits@10']:.4f}")
        print(f"  Mean Rank: {metrics['mean_rank']:.1f}")
        
        with open(os.path.join(self.output_dir, "test_results.json"), 'w') as f:
            json.dump(metrics, f, indent=2)
        
        return metrics


def main():
    parser = argparse.ArgumentParser(description="Train GeoRotatE model")
    parser.add_argument('--data_dir', type=str, default='georotate_training_data')
    parser.add_argument('--output_dir', type=str, default='georotate_output')
    parser.add_argument('--embedding_dim', type=int, default=256)
    parser.add_argument('--location_dim', type=int, default=64)
    parser.add_argument('--topo_dim', type=int, default=64)
    parser.add_argument('--gamma', type=float, default=12.0)
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--batch_size', type=int, default=2048)
    parser.add_argument('--lr', type=float, default=0.001)
    parser.add_argument('--negative_samples', type=int, default=256)
    parser.add_argument('--validate_every', type=int, default=5)
    parser.add_argument('--patience', type=int, default=2)
    parser.add_argument('--no_coordinates', action='store_true')
    parser.add_argument('--no_topology', action='store_true')
    parser.add_argument('--max_val_samples', type=int, default=5000,
                       help='Max samples for validation (default: 5000)')
    parser.add_argument('--max_test_samples', type=int, default=10000,
                       help='Max samples for testing (default: 10000)')
    args = parser.parse_args()
    
    device = torch.device('cuda' if torch.cuda.is_available() else 
                         'mps' if torch.backends.mps.is_available() else 'cpu')
    print(f"Using device: {device}")
    
    config = GeoRotatEConfig(data_dir=args.data_dir, batch_size=args.batch_size,
                            negative_sample_size=args.negative_samples,
                            use_coordinates=not args.no_coordinates,
                            use_topology=not args.no_topology)
    data_module = GeoRotatEDataModule(config)
    
    model = GeoRotatE(num_entities=data_module.num_entities,
                     num_relations=data_module.num_relations,
                     embedding_dim=args.embedding_dim,
                     location_dim=args.location_dim,
                     topo_dim=args.topo_dim,
                     gamma=args.gamma,
                     spatial_relation_ids=data_module.spatial_relation_ids,
                     device=device)
    
    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")
    
    trainer = GeoRotatETrainer(model, data_module, learning_rate=args.lr,
                              device=device, output_dir=args.output_dir)
    
    trainer.train(epochs=args.epochs, validate_every=args.validate_every, patience=args.patience)
    trainer.test(max_samples=args.max_test_samples)
    trainer.save_embeddings()
    
    print(f"\nTraining Complete! Best MRR: {trainer.best_mrr:.4f}")


if __name__ == "__main__":
    main()
