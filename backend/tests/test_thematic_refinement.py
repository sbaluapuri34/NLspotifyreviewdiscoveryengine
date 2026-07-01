import pytest
import json
import numpy as np
from unittest.mock import MagicMock
from backend.app.thematic_refinement import ThematicRefinementEngine

def test_engine_key_selection():
    # Only one key
    engine1 = ThematicRefinementEngine(api_keys=["key1"])
    assert engine1.api_key == "key1"
    
    # Multiple keys
    engine2 = ThematicRefinementEngine(api_keys=["key1", "key2", "key3"])
    assert engine2.api_key == "key2"  # Should pick GROQ_API_KEY_2 (Index 1)

def test_extract_sub_themes_mock_api(monkeypatch):
    engine = ThematicRefinementEngine(api_keys=["mock_key1", "mock_key2"])
    
    mock_response_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "refined_themes": [
                            {
                                "theme_id": "theme_1",
                                "name": "Smart Shuffle loops on Sonos casting",
                                "description": "Repetition in Smart Shuffle when casting to Sonos smart home speakers.",
                                "category": "Algorithmic Repetition & Looping",
                                "proposed_review_ids": ["r_1", "r_2"]
                            }
                        ]
                    })
                }
            }
        ]
    }
    
    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = mock_response_data
    monkeypatch.setattr("httpx.post", mock_post)
    
    result = engine.extract_sub_themes(
        research_answers=[{"rq_id": "RQ2", "executive_summary": "looping issues"}],
        reviews_pool=[{"id": "r_1", "text": "smart shuffle is looping on sonos"}]
    )
    
    assert len(result["refined_themes"]) == 1
    assert result["refined_themes"][0]["theme_id"] == "theme_1"
    assert "r_1" in result["refined_themes"][0]["proposed_review_ids"]

def test_validate_mappings():
    engine = ThematicRefinementEngine(api_keys=["mock_key"])
    
    # Mock the ONNX embedder's embed_text method to return a deterministic vector
    # We will mock it to return a 3-dimensional vector [1.0, 0.0, 0.0] for the theme
    engine.embedder.embed_text = MagicMock(return_value=[1.0, 0.0, 0.0])
    
    refined_themes = [
        {
            "theme_id": "theme_1",
            "name": "Sonos Smart Shuffle Loops",
            "description": "Smart Shuffle looping when casting to Sonos speakers.",
            "category": "Algorithmic Repetition & Looping",
            "proposed_review_ids": ["r_1", "r_2", "r_3"]
        }
    ]
    
    # Mock review vectors:
    # r_1: Vector is [0.95, 0.1, 0.0] (Very close, similarity = 0.95 >= 0.60 -> VERIFIED)
    # r_2: Vector is [0.70, 0.71, 0.0] (Close, similarity = 0.70 >= 0.60 -> VERIFIED)
    # r_3: Vector is [0.20, 0.98, 0.0] (Far, similarity = 0.20 < 0.60 -> REJECTED)
    review_vectors = {
        "r_1": [0.95, 0.1, 0.0],
        "r_2": [0.70, 0.71, 0.0],
        "r_3": [0.20, 0.98, 0.0]
    }
    
    validated = engine.validate_mappings(refined_themes, review_vectors)
    
    assert len(validated) == 1
    verified_ids = validated[0]["verified_review_ids"]
    
    assert "r_1" in verified_ids
    assert "r_2" in verified_ids
    assert "r_3" not in verified_ids  # Should be filtered out by validation gate!
