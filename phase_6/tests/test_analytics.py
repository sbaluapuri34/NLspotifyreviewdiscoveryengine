import pytest
import numpy as np
from backend.app.vectors import VectorEmbedder
from backend.app.analytics import (
    SemanticAnchorProjector,
    ClusterTfidfExtractor,
    extract_indian_locations,
    EvidencePackageCompiler
)

def test_extract_indian_locations():
    text = "I am using Spotify in Mumbai and Pune, Maharashtra. The app is great."
    locations = extract_indian_locations(text)
    assert "Mumbai" in locations
    assert "Pune" in locations
    assert "Maharashtra" in locations
    
    text_no_loc = "This app is really good, I love the recommendations."
    locations_empty = extract_indian_locations(text_no_loc)
    assert len(locations_empty) == 0

def test_csss_calculation():
    # Equal distribution across 3 sources (max entropy)
    sources_equal = {"google_play": 10, "app_store": 10, "reddit": 10}
    csss_equal = EvidencePackageCompiler.calculate_csss(sources_equal, mean_similarity=0.80)
    
    # Concentrated on 1 source (zero entropy)
    sources_concentrated = {"google_play": 30, "app_store": 0, "reddit": 0}
    csss_concentrated = EvidencePackageCompiler.calculate_csss(sources_concentrated, mean_similarity=0.80)
    
    assert csss_equal > csss_concentrated
    assert csss_concentrated == 0.0

def test_opportunity_score():
    # Low rating, high size, high CSSS -> High score
    score_high = EvidencePackageCompiler.calculate_opportunity_score(
        size=100, total_reviews=1000, avg_rating=1.0, csss=0.80, churn_ratio=0.5, premium_ratio=0.5
    )
    
    # High rating, low size, low CSSS -> Low score
    score_low = EvidencePackageCompiler.calculate_opportunity_score(
        size=5, total_reviews=1000, avg_rating=5.0, csss=0.10, churn_ratio=0.0, premium_ratio=0.0
    )
    
    assert score_high > score_low

def test_tfidf_extractor():
    extractor = ClusterTfidfExtractor()
    target_cluster = [
        "The shuffle playing same tracks over and over.",
        "Smart shuffle is repeating songs in my playlist.",
        "I hate how the shuffle repeats songs."
    ]
    other_clusters = [
        ["I love the new UI update, it looks very modern and clean."],
        ["The app is crashing on my Android phone when I try to open it."]
    ]
    
    themes = extractor.extract_themes(target_cluster, [target_cluster] + other_clusters, top_k=5)
    assert len(themes) > 0
    # Check if "shuffle" or "repeating" or "songs" is in the extracted themes
    terms = [t[0] for t in themes]
    assert any(term in terms for term in ["shuffle", "repeating", "songs", "tracks"])

@pytest.mark.asyncio
async def test_semantic_anchor_projection():
    # Initialize embedder (uses Mock or local model depending on environment)
    # In tests, it will use the local SentenceTransformer
    embedder = VectorEmbedder()
    projector = SemanticAnchorProjector(embedder)
    
    # Check if anchors are embedded
    assert len(projector.anchors) > 0
    assert "context_car" in projector.anchors
    
    # Project a vector (use the embedded text of "driving a car on the road")
    vec = embedder.embed_text("I am driving my car using Android Auto bluetooth connection")
    tags = projector.project(vec, threshold=0.35)
    
    # Should project close to "context_car"
    assert "context_car" in tags
