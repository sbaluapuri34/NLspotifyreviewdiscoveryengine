import pytest
import numpy as np
from backend.app.vectors import VectorEmbedder, NumpyVectorIndex, LeaderFollowerClustering

def test_numpy_vector_index():
    """Tests the NumpyVectorIndex for insertion and KNN cosine queries."""
    index = NumpyVectorIndex(dimension=4)
    
    # Add L2 normalized vectors
    # v1 and v2 are very similar, v3 is orthogonal
    v1 = [1.0, 0.0, 0.0, 0.0]
    v2 = [0.9, 0.1, 0.0, 0.0]
    v3 = [0.0, 0.0, 1.0, 0.0]
    
    index.add_item("v1", v1)
    index.add_item("v2", v2)
    index.add_item("v3", v3)
    
    assert index.size() == 3
    
    # Query with v1, should return v1 as closest, then v2
    nearest_ids, similarities = index.knn_query(v1, k=3)
    assert nearest_ids[0] == "v1"
    assert nearest_ids[1] == "v2"
    assert nearest_ids[2] == "v3"
    assert similarities[0] == pytest.approx(1.0, rel=1e-3)
    assert similarities[1] > 0.8
    assert similarities[2] == pytest.approx(0.0, rel=1e-3)

def test_vector_embedder_mock():
    """Tests the VectorEmbedder in mock mode."""
    embedder = VectorEmbedder(mode="mock")
    assert embedder.dimension == 384
    
    vec = embedder.embed_text("test review")
    assert len(vec) == 384
    # Check L2 normalized
    assert np.linalg.norm(vec) == pytest.approx(1.0, rel=1e-3)
    
    # Test batch embedding
    batch = ["first review", "second review", "third"]
    vectors = embedder.embed_batch(batch)
    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 384
        assert np.linalg.norm(v) == pytest.approx(1.0, rel=1e-3)

def test_leader_follower_clustering():
    """Tests the LeaderFollowerClustering logic for merging and spawning clusters."""
    # Use dimension 4, threshold 0.80
    clustering = LeaderFollowerClustering(dimension=4, threshold=0.80)
    
    v1 = [1.0, 0.0, 0.0, 0.0]
    v2 = [0.99, 0.01, 0.0, 0.0] # Extremely close to v1 (should merge)
    v3 = [0.0, 1.0, 0.0, 0.0]    # Orthogonal (should spawn new cluster)
    
    # 1. Add first review -> should spawn cluster_1
    c1 = clustering.add_review("r1", v1)
    assert c1 == "cluster_1"
    assert len(clustering.get_cluster_stats()) == 1
    
    # 2. Add second review (close to v1) -> should merge into cluster_1
    c2 = clustering.add_review("r2", v2)
    assert c2 == "cluster_1"
    stats = clustering.get_cluster_stats()
    assert len(stats) == 1
    assert stats[0]["size"] == 2
    assert stats[0]["variance"] > 0.0  # Variance should be updated
    
    # 3. Add third review (orthogonal) -> should spawn cluster_2
    c3 = clustering.add_review("r3", v3)
    assert c3 == "cluster_2"
    stats = clustering.get_cluster_stats()
    assert len(stats) == 2
    assert stats[0]["cluster_id"] == "cluster_1"
    assert stats[1]["cluster_id"] == "cluster_2"
    assert stats[0]["size"] == 2
    assert stats[1]["size"] == 1
