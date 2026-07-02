import pytest
import json
from unittest.mock import MagicMock
from backend.app.cluster_intelligence import ClusterIntelligenceEngine

def test_engine_initialization():
    engine = ClusterIntelligenceEngine(api_keys=["key1", "key2"])
    assert engine.api_keys == ["key1", "key2"]
    assert engine.model_name == "llama-3.1-8b-instant"

def test_decompose_cluster_no_keys():
    engine = ClusterIntelligenceEngine(api_keys=[])
    result = engine.decompose_cluster("cluster_1", ["shuffle"], ["some review"])
    assert result == {"sub_issues": []}

def test_decompose_cluster_key_rotation(monkeypatch):
    # Initialize with 3 keys
    engine = ClusterIntelligenceEngine(api_keys=["key1", "key2", "key3"])
    
    # We want to simulate:
    # - First call (key1) -> returns HTTP 429 (Rate Limit)
    # - Second call (key2) -> returns HTTP 200 (Success)
    
    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429
    
    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "sub_issues": [
                            {
                                "name": "Smart Shuffle loops same 5 songs",
                                "description": "Repeated songs in shuffle.",
                                "frequency_percentage": 100.0,
                                "representative_quotes": ["it plays the same songs"]
                            }
                        ]
                    })
                }
            }
        ]
    }
    
    # Side effect function to return 429 first, then 200
    call_count = 0
    def mock_post(url, json, headers, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Check that it used key1
            assert headers["Authorization"] == "Bearer key1"
            return mock_response_429
        elif call_count == 2:
            # Check that it rotated to key2
            assert headers["Authorization"] == "Bearer key2"
            return mock_response_200
        return mock_response_429

    monkeypatch.setattr("httpx.post", mock_post)
    
    result = engine.decompose_cluster("cluster_14", ["shuffle"], ["review 1"])
    
    assert "sub_issues" in result
    assert len(result["sub_issues"]) == 1
    assert result["sub_issues"][0]["name"] == "Smart Shuffle loops same 5 songs"
    assert engine.current_key_idx == 1  # Should remain at index 1 (key2) after successful call
    assert call_count == 2
