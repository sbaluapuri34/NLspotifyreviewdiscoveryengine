import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger
from backend.app.vectors.index import NumpyVectorIndex

class LeaderFollowerClustering:
    def __init__(self, dimension: int, threshold: Optional[float] = None, dataset_size: Optional[int] = None):
        """
        Initializes the clustering engine.
        - dimension: Dimension of the embedding vectors.
        - threshold: Optional fixed cosine similarity threshold. If None, calculates dynamically.
        - dataset_size: Size of the dataset, used for adaptive thresholding if threshold is None.
        """
        self.dimension = dimension
        
        if threshold is not None:
            self.threshold = threshold
            logger.info(f"LeaderFollowerClustering: Using fixed similarity threshold = {self.threshold:.2f}")
        else:
            self.threshold = self.calculate_adaptive_threshold(dataset_size or 0)
            logger.info(f"LeaderFollowerClustering: Calculated adaptive similarity threshold = {self.threshold:.2f} for N = {dataset_size or 0}")
        
        # Centroid index for O(log K) equivalent matching
        self.centroid_index = NumpyVectorIndex(dimension)
        
        # Cluster metadata: maps cluster_id -> dict
        # { "centroid": np.ndarray, "count": int, "mean_sim": float, "M2": float, "variance": float }
        # M2 is used for Welford's algorithm to track running variance.
        self.clusters: Dict[str, Dict[str, Any]] = {}
        
        # Track cluster members and their vectors in memory to support local splitting
        self.cluster_members: Dict[str, List[str]] = {}  # cluster_id -> list of review_ids
        self.review_vectors: Dict[str, np.ndarray] = {}  # review_id -> normalized vector

    @staticmethod
    def calculate_adaptive_threshold(dataset_size: int) -> float:
        """Calculates the similarity threshold dynamically based on the dataset size."""
        from backend.app.config import ADAPTIVE_THRESHOLDS
        for limit, thresh in ADAPTIVE_THRESHOLDS:
            if dataset_size < limit:
                return thresh
        return 0.60  # Default fallback for very large datasets
        
    def add_review(self, review_id: str, vector: List[float]) -> str:
        """
        Clusters a single review vector.
        Returns the cluster_id assigned to the review (either merged or newly spawned).
        """
        v_arr = np.array(vector, dtype=np.float32)
        # Ensure L2 normalized
        norm = np.linalg.norm(v_arr)
        if norm > 0:
            v_arr = v_arr / norm
            
        # 1. Query nearest centroid
        if self.centroid_index.size() == 0:
            # First cluster
            cluster_id = "cluster_1"
            self._create_cluster(cluster_id, review_id, v_arr)
            return cluster_id

        nearest_ids, similarities = self.centroid_index.knn_query(v_arr.tolist(), k=1)
        best_cluster_id = nearest_ids[0]
        similarity = similarities[0]

        # 2. Threshold Evaluation
        if similarity >= self.threshold:
            # Case A: Merge into existing cluster
            self._merge_into_cluster(best_cluster_id, review_id, v_arr, similarity)
            
            # Retrieve the possibly updated/split cluster ID for this review
            # (If a split occurred, the review might be in a new sub-cluster)
            for cid, members in self.cluster_members.items():
                if review_id in members:
                    return cid
            return best_cluster_id
        else:
            # Case B: Spawn a new cluster
            new_cluster_idx = len(self.clusters) + 1
            # Ensure unique ID even if some clusters were deleted during splits
            while f"cluster_{new_cluster_idx}" in self.clusters:
                new_cluster_idx += 1
            new_cluster_id = f"cluster_{new_cluster_idx}"
            self._create_cluster(new_cluster_id, review_id, v_arr)
            return new_cluster_id

    def _create_cluster(self, cluster_id: str, review_id: str, vector: np.ndarray):
        """Spawns a new cluster with the given vector as the initial centroid."""
        self.clusters[cluster_id] = {
            "centroid": vector.copy(),
            "count": 1,
            "mean_sim": 1.0,  # Similarity of first element to its own centroid is 1.0
            "M2": 0.0,        # Welford's M2 parameter
            "variance": 0.0
        }
        self.cluster_members[cluster_id] = [review_id]
        self.review_vectors[review_id] = vector
        self.centroid_index.add_item(cluster_id, vector.tolist())
        logger.debug(f"Spawned new cluster: {cluster_id}")

    def _merge_into_cluster(self, cluster_id: str, review_id: str, vector: np.ndarray, similarity: float):
        """Merges a vector into an existing cluster and updates its centroid and variance."""
        c_data = self.clusters[cluster_id]
        old_centroid = c_data["centroid"]
        old_count = c_data["count"]
        new_count = old_count + 1
        
        # 1. Update Centroid (Normalized Moving Average)
        new_centroid = (old_centroid * old_count + vector) / new_count
        new_centroid_norm = np.linalg.norm(new_centroid)
        if new_centroid_norm > 0:
            new_centroid = new_centroid / new_centroid_norm
            
        c_data["centroid"] = new_centroid
        c_data["count"] = new_count
        
        self.cluster_members[cluster_id].append(review_id)
        self.review_vectors[review_id] = vector
        
        # Update in centroid index
        self.centroid_index.add_item(cluster_id, new_centroid.tolist())
        
        # 2. Update Variance using Welford's Online Algorithm
        # We track the variance of the cosine similarities of elements to the running centroid.
        old_mean = c_data["mean_sim"]
        delta = similarity - old_mean
        new_mean = old_mean + delta / new_count
        delta2 = similarity - new_mean
        new_M2 = c_data["M2"] + delta * delta2
        
        c_data["mean_sim"] = new_mean
        c_data["M2"] = new_M2
        c_data["variance"] = new_M2 / new_count if new_count > 1 else 0.0
        
        logger.debug(f"Merged review into {cluster_id} (New Size={new_count}, Similarity={similarity:.3f}, Variance={c_data['variance']:.4f})")

        # 3. Drift Split Trigger
        # If variance exceeds 0.25 (equivalent to mean similarity dropping below 0.75) and size >= 30, split it.
        if c_data["variance"] > 0.25 and new_count >= 30:
            self._split_cluster(cluster_id)

    def _split_cluster(self, cluster_id: str):
        """Splits a drifted cluster into two new sub-clusters using a local 2-Means algorithm."""
        c_data = self.clusters[cluster_id]
        members = self.cluster_members[cluster_id]
        logger.info(f"LeaderFollowerClustering: Drift detected in {cluster_id} (Size={len(members)}, Variance={c_data['variance']:.4f}). Triggering split...")
        
        vectors = np.array([self.review_vectors[rid] for rid in members])
        
        # Initialize two centroids (K=2)
        # c1 is the first vector, c2 is the vector furthest from c1 (maximum cosine distance)
        c1 = vectors[0]
        distances = 1.0 - np.dot(vectors, c1)
        c2 = vectors[np.argmax(distances)]
        
        # Run 2-Means iterations
        labels = np.zeros(len(vectors), dtype=bool)
        for iteration in range(10):
            sims1 = np.dot(vectors, c1)
            sims2 = np.dot(vectors, c2)
            
            new_labels = sims1 < sims2  # True if closer to c2
            
            # Check convergence
            if np.array_equal(labels, new_labels):
                break
            labels = new_labels
            
            # Update centroids
            v1 = vectors[~labels]
            v2 = vectors[labels]
            
            if len(v1) == 0 or len(v2) == 0:
                break
                
            c1 = np.mean(v1, axis=0)
            c2 = np.mean(v2, axis=0)
            
            c1_norm = np.linalg.norm(c1)
            c2_norm = np.linalg.norm(c2)
            
            if c1_norm > 0:
                c1 = c1 / c1_norm
            if c2_norm > 0:
                c2 = c2 / c2_norm

        # Allocate new cluster IDs
        c_idx = len(self.clusters) + 1
        while f"cluster_{c_idx}" in self.clusters:
            c_idx += 1
        cid1 = f"cluster_{c_idx}"
        cid2 = f"cluster_{c_idx + 1}"
        
        # Split members
        members1 = [members[i] for i in range(len(members)) if not labels[i]]
        members2 = [members[i] for i in range(len(members)) if labels[i]]
        
        # Clean up old cluster
        self.centroid_index.remove_item(cluster_id)
        if cluster_id in self.clusters:
            del self.clusters[cluster_id]
        if cluster_id in self.cluster_members:
            del self.cluster_members[cluster_id]
            
        # Register new clusters
        self._register_new_split_cluster(cid1, c1, members1)
        self._register_new_split_cluster(cid2, c2, members2)

    def _register_new_split_cluster(self, cluster_id: str, centroid: np.ndarray, members: List[str]):
        """Helper to register a new sub-cluster after a split."""
        similarities = []
        for rid in members:
            vec = self.review_vectors[rid]
            sim = float(np.dot(vec, centroid))
            similarities.append(sim)
            
        mean_sim = np.mean(similarities) if similarities else 1.0
        variance = np.var(similarities) if similarities else 0.0
        
        self.clusters[cluster_id] = {
            "centroid": centroid,
            "count": len(members),
            "mean_sim": mean_sim,
            "M2": variance * len(members),
            "variance": variance
        }
        self.cluster_members[cluster_id] = members
        self.centroid_index.add_item(cluster_id, centroid.tolist())
        logger.info(f"LeaderFollowerClustering: Split created {cluster_id} (Size={len(members)}, Mean Sim={mean_sim:.3f}, Var={variance:.4f})")

    def get_cluster_stats(self) -> List[Dict[str, Any]]:
        """Returns statistical summaries for all active clusters."""
        summaries = []
        for cid, cdata in self.clusters.items():
            summaries.append({
                "cluster_id": cid,
                "size": cdata["count"],
                "mean_similarity": float(cdata["mean_sim"]),
                "variance": float(cdata["variance"]),
                "centroid": cdata["centroid"].tolist()
            })
        # Sort by size descending
        return sorted(summaries, key=lambda x: x["size"], reverse=True)
