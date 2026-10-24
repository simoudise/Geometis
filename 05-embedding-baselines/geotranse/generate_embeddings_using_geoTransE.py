import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
import os
import argparse
import time
import random
from math import radians, cos, sin, asin, sqrt
import copy
import json

class KnowledgeGraphDataset:
    """Loads, splits, and prepares the pre-processed KG data for training and evaluation."""
    def __init__(self, data_dir: str, split_ratios: tuple = (0.8, 0.1, 0.1)):
        self.data_dir = data_dir
        self.triples = []
        self.coordinates = {}
        self.entities = set()
        self.relations = set()
        self.spatial_relation_uris = set()
        
        self.entity_to_id = {}
        self.relation_to_id = {}
        
        self._load_data()
        self._create_mappings()
        self._identify_spatial_relations()
        self._split_data(split_ratios)

    def _load_data(self):
        """Loads triples and coordinates from the pre-processed text files."""
        triples_path = os.path.join(self.data_dir, "triples.txt")
        coords_path = os.path.join(self.data_dir, "coordinates.txt")

        print("Loading pre-processed data...")
        with open(triples_path, 'r', encoding='utf-8') as f:
            for line in f:
                h, p, o = line.strip().split('\t')
                h, p, o = h.strip('<>'), p.strip('<>'), o.strip('<>')
                self.triples.append((h, p, o))
                self.entities.add(h); self.entities.add(o); self.relations.add(p)
        
        with open(coords_path, 'r', encoding='utf-8') as f:
            for line in f:
                uri, lat, lon = line.strip().split('\t')
                self.coordinates[uri.strip('<>')] = (float(lat), float(lon))
        
        print(f"✓ Loaded {len(self.triples):,} triples and {len(self.coordinates):,} coordinates.")

    def _create_mappings(self):
        """Creates URI to integer ID mappings."""
        sorted_entities = sorted(list(self.entities))
        sorted_relations = sorted(list(self.relations))
        self.entity_to_id = {uri: i for i, uri in enumerate(sorted_entities)}
        self.relation_to_id = {uri: i for i, uri in enumerate(sorted_relations)}
        self.id_to_entity = {i: uri for uri, i in self.entity_to_id.items()}
        self.id_to_relation = {i: uri for uri, i in self.relation_to_id.items()}

    def _identify_spatial_relations(self):
        """Identifies relation URIs that imply a spatial relationship."""
        spatial_keywords = ['near', 'adjacent', 'walkingdistance', 'accessiblevia']
        for uri in self.relations:
            if any(keyword in uri.lower() for keyword in spatial_keywords):
                self.spatial_relation_uris.add(uri)
        self.spatial_relation_ids = {self.relation_to_id[uri] for uri in self.spatial_relation_uris}
        print(f"✓ Identified {len(self.spatial_relation_ids)} spatial relation types.")

    def _split_data(self, ratios: tuple):
        """Splits the triples into training, validation, and test sets."""
        print("Splitting data into training, validation, and test sets...")
        numeric_triples = self._get_numeric_triples(self.triples)
        np.random.shuffle(numeric_triples)
        train_size, valid_size, _ = ratios
        total_size = len(numeric_triples)
        train_end = int(train_size * total_size)
        valid_end = int((train_size + valid_size) * total_size)
        
        self.train_set = numeric_triples[:train_end]
        self.valid_set = numeric_triples[train_end:valid_end]
        self.test_set = numeric_triples[valid_end:]
        
        print(f"✓ Data split complete:")
        print(f"  - Training set:   {len(self.train_set):,} triples")
        print(f"  - Validation set: {len(self.valid_set):,} triples")
        print(f"  - Test set:       {len(self.test_set):,} triples")

    def _get_numeric_triples(self, triples_to_convert: list) -> np.ndarray:
        """Converts URI triples to their numeric ID representation."""
        numeric_triples = []
        for h, p, o in triples_to_convert:
            h_id = self.entity_to_id.get(h)
            p_id = self.relation_to_id.get(p)
            o_id = self.entity_to_id.get(o)
            if all(v is not None for v in [h_id, p_id, o_id]):
                numeric_triples.append([h_id, p_id, o_id])
        return np.array(numeric_triples, dtype=np.int64)

class SpatiallyAwareKGEModel(nn.Module):
    """SE-KGE model with a hybrid scoring function for spatial and semantic relations."""
    def __init__(self, num_entities, num_relations, embedding_dim, dataset, device):
        super(SpatiallyAwareKGEModel, self).__init__()
        self.num_entities = num_entities
        self.embedding_dim = embedding_dim
        self.device = device
        self.entity_embeddings = nn.Embedding(num_entities, embedding_dim)
        self.relation_embeddings = nn.Embedding(num_relations, embedding_dim)
        self.entity_coord_tensor = self._create_coord_tensor(num_entities, dataset)
        self.spatial_relation_ids = torch.tensor(list(dataset.spatial_relation_ids), dtype=torch.long).to(device)
        self.spatial_weight = nn.Parameter(torch.tensor([0.5]))
        nn.init.xavier_uniform_(self.entity_embeddings.weight.data)
        nn.init.xavier_uniform_(self.relation_embeddings.weight.data)

    def _create_coord_tensor(self, num_entities, dataset):
        """Create a tensor of all entity coordinates for fast GPU lookups."""
        coord_tensor = torch.zeros(num_entities, 2, dtype=torch.float32)
        for uri, (lat, lon) in dataset.coordinates.items():
            if uri in dataset.entity_to_id:
                entity_id = dataset.entity_to_id[uri]
                coord_tensor[entity_id] = torch.tensor([lat, lon])
        return coord_tensor.to(self.device)

    def forward(self, h, r, t):
        h_emb = self.entity_embeddings(h)
        r_emb = self.relation_embeddings(r)
        t_emb = self.entity_embeddings(t)
        semantic_score = torch.norm(h_emb + r_emb - t_emb, p=2, dim=-1)
        is_spatial_mask = torch.isin(r, self.spatial_relation_ids)
        spatial_score = torch.zeros_like(semantic_score)
        if torch.any(is_spatial_mask):
            h_coords = self.entity_coord_tensor[h[is_spatial_mask]]
            t_coords = self.entity_coord_tensor[t[is_spatial_mask]]
            geo_dist = self.haversine_distance(h_coords[:, 0], h_coords[:, 1], t_coords[:, 0], t_coords[:, 1])
            normalized_geo_dist = torch.tanh(geo_dist / 10000)
            spatial_score[is_spatial_mask] = normalized_geo_dist
        final_score = (1.0 - self.spatial_weight) * semantic_score + self.spatial_weight * spatial_score
        return final_score

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """GPU-accelerated Haversine distance calculation."""
        lat1, lon1, lat2, lon2 = map(torch.deg2rad, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1; dlon = lon2 - lon1
        a = torch.sin(dlat / 2)**2 + torch.cos(lat1) * torch.cos(lat2) * torch.sin(dlon / 2)**2
        c = 2 * torch.asin(torch.sqrt(a)); r = 6371000
        return c * r

def evaluate(model, data_loader, device):
    """Evaluates the model on a given dataset using link prediction metrics."""
    model.eval()
    hits_at_10 = 0; mrr = 0.0
    with torch.no_grad():
        for i, batch in enumerate(data_loader):
            if (i + 1) % 50000 == 0:
                print(f"  ... validating triple {i+1}/{len(data_loader)}...")
            h, r, t = batch[0]
            h, r, t = h.to(device), r.to(device), t.to(device)
            all_entities = torch.arange(model.num_entities).to(device)
            h_repeated = h.repeat(model.num_entities)
            r_repeated = r.repeat(model.num_entities)
            scores = model(h_repeated, r_repeated, all_entities)
            rank = (scores < scores[t]).sum().item() + 1
            if rank <= 10: hits_at_10 += 1
            mrr += 1.0 / rank
    return mrr / len(data_loader), hits_at_10 / len(data_loader)

def train(model, dataset, epochs, batch_size, learning_rate, device, patience: int = 3, output_dir: str = "."):
    """Main training loop with your custom validation schedule and early stopping."""
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    criterion = nn.MarginRankingLoss(margin=1.0)
    train_data = dataset.train_set
    valid_data_loader = torch.utils.data.DataLoader(dataset.valid_set, batch_size=1)
    num_entities = len(dataset.entity_to_id)
    
    best_mrr = 0.0
    best_model_state = None
    best_epoch = 0

    print("\n--- Starting Model Training (Custom Schedule) ---")
    
    for epoch in range(1, epochs + 1):
        model.train()
        epoch_loss = 0.0
        start_time = time.time()
        np.random.shuffle(train_data)
        
        for i in range(0, len(train_data), batch_size):
            batch = train_data[i : i + batch_size]
            positive_batch = torch.tensor(batch, dtype=torch.long).to(device)
            corrupted_tails = torch.randint(0, num_entities, (len(batch),)).to(device)
            negative_batch = positive_batch.clone(); negative_batch[:, 2] = corrupted_tails
            optimizer.zero_grad()
            pos_scores = model(positive_batch[:, 0], positive_batch[:, 1], positive_batch[:, 2])
            neg_scores = model(negative_batch[:, 0], negative_batch[:, 1], negative_batch[:, 2])
            target = torch.tensor([-1], dtype=torch.float, device=device)
            loss = criterion(pos_scores, neg_scores, target)
            loss.backward(); optimizer.step()
            epoch_loss += loss.item()
        
        epoch_time = time.time() - start_time
        avg_loss = epoch_loss / (len(train_data) / batch_size)
        
        print(f"Epoch {epoch}/{epochs} | Loss: {avg_loss:.4f} | Time: {epoch_time:.2f}s")
        
        # --- YOUR CUSTOM VALIDATION AND SAVING LOGIC ---
        # This condition now clearly implements your requested 4-step schedule.
        if epoch >= 25:
            print(f"\n--- Running Validation for Epoch {epoch} ---")
            mrr, hits10 = evaluate(model, valid_data_loader, device)
            print(f"--- Validation Metrics -> MRR: {mrr:.4f} | Hits@10: {hits10:.4f} ---")
            
            if mrr > best_mrr:
                best_mrr = mrr
                best_epoch = epoch
                best_model_state = copy.deepcopy(model.state_dict())
                print(f"  *** New best model found at epoch {epoch} with MRR: {best_mrr:.4f} ***")

            # STEP 3: Save the safety checkpoint ONLY at epoch 25.
            if epoch == 25:
                print(f"\n--- Saving Intermediate Embeddings from Epoch {epoch} as a safety checkpoint ---")
                save_results(model, dataset, output_dir, suffix=f"_epoch_{epoch}")

            # STEP 4: Apply early stopping logic based on epoch count since best was found.
            # This check is only active after the first validation has run.
            if best_epoch > 0 and (epoch - best_epoch) >= patience:
                print(f"\n--- Early stopping triggered. No improvement in {patience} epochs since epoch {best_epoch}. ---")
                break
    # --- END OF CUSTOM LOGIC ---

    print("\n--- Training Complete ---")
    
    if best_model_state:
        print(f"\nLoading best model from epoch {best_epoch} with MRR {best_mrr:.4f}")
        model.load_state_dict(best_model_state)
    
    return model

def save_results(model, dataset, output_dir, suffix=""):
    """Saves the learned embeddings and mappings, with an optional filename suffix."""
    embeddings_path = os.path.join(output_dir, f"entity_embeddings{suffix}.csv")
    mappings_path = os.path.join(output_dir, f"id_to_entity{suffix}.json")
    
    print(f"Saving entity embeddings to '{embeddings_path}'...")
    embeddings = model.entity_embeddings.weight.data.cpu().numpy()
    df = pd.DataFrame(embeddings); df.insert(0, 'uri', df.index.map(dataset.id_to_entity.get))
    
    # Create descriptive column names
    df.columns = ['uri'] + [f'dim_{i}' for i in range(df.shape[1] - 1)]
    
    df.to_csv(embeddings_path, index_label='id')
    
    print(f"Saving ID-to-URI mappings to '{mappings_path}'...")
    with open(mappings_path, 'w', encoding='utf-8') as f:
        json.dump(dataset.id_to_entity, f, indent=4)
    print("✓ Embeddings and mappings saved successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train a Spatially-Aware KGE model with a custom schedule.")
    parser.add_argument("--data_dir", default="embedding_training_data", help="Directory with pre-processed data.")
    parser.add_argument("--embedding_dim", type=int, default=64, help="Dimensionality of embeddings.")
    parser.add_argument("--epochs", type=int, default=50, help="Total number of training epochs to run.")
    parser.add_argument("--batch_size", type=int, default=2048, help="Batch size for training.")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate.")
    parser.add_argument("--patience", type=int, default=3, help="Number of epochs to wait for improvement before stopping.")
    
    args = parser.parse_args()
    
    device = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    print(f"Using device: {device}")
    
    dataset = KnowledgeGraphDataset(args.data_dir)
    model = SpatiallyAwareKGEModel(
        num_entities=len(dataset.entity_to_id),
        num_relations=len(dataset.relation_to_id),
        embedding_dim=args.embedding_dim,
        dataset=dataset,
        device=device
    ).to(device)
    
    trained_model = train(model, dataset, args.epochs, args.batch_size, args.lr, device, args.patience, args.data_dir)
    
    print("\n--- Evaluating on Final Test Set using Best Model ---")
    test_loader = torch.utils.data.DataLoader(dataset.test_set, batch_size=1)
    test_mrr, test_hits10 = evaluate(trained_model, test_loader, device)
    print(f"Final Test Metrics -> MRR: {test_mrr:.4f}, Hits@10: {test_hits10:.4f}")
    
    print("\n--- Saving Final Embeddings from Best Model ---")
    save_results(trained_model, dataset, args.data_dir)

