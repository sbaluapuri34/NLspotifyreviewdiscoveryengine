import numpy as np
from typing import List, Tuple, Dict, Any

class NumpyVectorIndex:
    def __init__(self, dimension: int):
        self.dimension = dimension
        self.ids: List[str] = []
        self.vectors: List[np.ndarray] = []
        # Mapping from ID to index in the list
        self.id_to_idx: Dict[str, int] = {}

    def add_item(self, item_id: str, vector: List[float]):
        """Adds a single vector to the index."""
        if item_id in self.id_to_idx:
            # Update existing
            idx = self.id_to_idx[item_id]
            self.vectors[idx] = np.array(vector, dtype=np.float32)
        else:
            self.id_to_idx[item_id] = len(self.ids)
            self.ids.append(item_id)
            self.vectors.append(np.array(vector, dtype=np.float32))

    def get_vector(self, item_id: str) -> List[float]:
        """Retrieves a vector by its ID."""
        if item_id not in self.id_to_idx:
            raise KeyError(f"ID {item_id} not found in index.")
        idx = self.id_to_idx[item_id]
        return self.vectors[idx].tolist()

    def knn_query(self, query_vector: List[float], k: int = 1) -> Tuple[List[str], List[float]]:
        """
        Performs a k-nearest neighbor search using cosine similarity.
        Returns a tuple of (nearest_ids, similarities).
        """
        if not self.ids:
            return [], []

        q_vec = np.array(query_vector, dtype=np.float32)
        # Normalize query vector if it isn't already
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        # Stack all vectors into a matrix: shape (N, D)
        matrix = np.vstack(self.vectors)
        
        # Compute dot products (since vectors are L2-normalized, this is cosine similarity)
        # shape (N,)
        similarities = np.dot(matrix, q_vec)

        # Get top K indices
        k = min(k, len(self.ids))
        top_k_indices = np.argsort(similarities)[::-1][:k]

        nearest_ids = [self.ids[idx] for idx in top_k_indices]
        nearest_sims = [float(similarities[idx]) for idx in top_k_indices]

        return nearest_ids, nearest_sims

    def size(self) -> int:
        """Returns the number of items in the index."""
        return len(self.ids)

    def clear(self):
        """Clears the index."""
        self.ids = []
        self.vectors = []
        self.id_to_idx = {}
