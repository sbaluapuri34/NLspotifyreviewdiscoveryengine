import pytest
import json
from unittest.mock import MagicMock
from backend.app.research import ResearchEngine

def test_engine_initialization():
    engine = ResearchEngine(api_keys=["key1", "key2"])
    assert engine.api_keys == ["key1", "key2"]
    assert engine.model_name == "llama-3.3-70b-versatile"

def test_route_clusters_to_rqs():
    engine = ResearchEngine(api_keys=[])
    
    # Mock evidence packages
    packages = [
        {
            "cluster_id": "cluster_14",
            "themes": [("shuffle", 0.9), ("songs", 0.8)],
            "intents": ["method_algorithmic"]
        },
        {
            "cluster_id": "cluster_157",
            "themes": [("weekly", 0.9), ("discover", 0.8)],
            "intents": ["goal_discover"]
        }
    ]
    
    routed = engine.route_clusters_to_rqs(packages)
    
    assert "RQ1" in routed
    assert "RQ2" in routed
    assert "RQ5" in routed
    
    # cluster_14 has "shuffle", should route to RQ2 (repetition) and RQ5 (feature-specific)
    rq2_ids = [p["cluster_id"] for p in routed["RQ2"]]
    assert "cluster_14" in rq2_ids
    
    # cluster_157 has "weekly" and "discover", should route to RQ1 (friction), RQ4 (methods), and RQ5 (feature-specific)
    rq1_ids = [p["cluster_id"] for p in routed["RQ1"]]
    assert "cluster_157" in rq1_ids

def test_synthesize_rq_answer_mock_api(monkeypatch):
    engine = ResearchEngine(api_keys=["mock_key"])
    
    mock_response_data = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "rq_id": "RQ2",
                        "title": "Algorithmic Repetition & Looping",
                        "executive_summary": "Users experience significant repetition in Smart Shuffle.",
                        "key_findings": [
                            {
                                "finding": "Smart Shuffle repeating same 5 songs",
                                "supporting_evidence": "60% of cluster_14 reviews",
                                "impact_rating": "High"
                            }
                        ],
                        "actionable_opportunities": [
                            {
                                "opportunity": "Introduce a shuffle reset toggle",
                                "unmet_need": "Control over shuffle pool",
                                "proposed_feature": "Reset Shuffle Pool button"
                            }
                        ],
                        "confidence_score": 0.95
                    })
                }
            }
        ]
    }
    
    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = mock_response_data
    monkeypatch.setattr("httpx.post", mock_post)
    
    result = engine.synthesize_rq_answer("RQ2", [{"cluster_id": "cluster_14"}])
    
    assert result["rq_id"] == "RQ2"
    assert result["confidence_score"] == 0.95
    assert len(result["key_findings"]) == 1
    assert result["key_findings"][0]["impact_rating"] == "High"
    
    # Verify mock post was called
    assert mock_post.called
