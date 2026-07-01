import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from backend.app.main import app

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    # Should serve our HTML
    assert "html" in response.headers["content-type"]

def test_get_clusters():
    response = client.get("/api/clusters")
    assert response.status_code == 200
    data = response.json()
    assert "clusters" in data
    # Verify cluster keys if clusters exist
    if data["clusters"]:
        first = data["clusters"][0]
        assert "cluster_id" in first
        assert "size" in first
        assert "avg_rating" in first
        assert "x" in first
        assert "y" in first

def test_get_research():
    response = client.get("/api/research")
    assert response.status_code == 200
    data = response.json()
    assert "answers" in data
    if data["answers"]:
        first = data["answers"][0]
        assert "rq_id" in first
        assert "title" in first
        assert "executive_summary" in first

def test_get_thematic_refinement():
    response = client.get("/api/thematic-refinement")
    assert response.status_code == 200
    data = response.json()
    assert "themes" in data
    if data["themes"]:
        first = data["themes"][0]
        assert "theme_id" in first
        assert "name" in first
        assert "description" in first

def test_get_source_counts():
    response = client.get("/api/source-counts")
    assert response.status_code == 200
    data = response.json()
    assert "sources" in data
    assert "total" in data

def test_get_operational_friction():
    response = client.get("/api/operational-friction")
    assert response.status_code == 200
    data = response.json()
    assert "categories" in data
    if data["categories"]:
        first = data["categories"][0]
        assert "category_id" in first
        assert "category_name" in first
        assert "count" in first
        assert "percentage" in first

def test_trigger_pipeline():
    # Mock BackgroundTasks.add_task to prevent the long-running pipeline from executing during the unit test
    with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
        response = client.post("/api/run-pipeline?limit_google_play=5&limit_reddit=5")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        mock_add_task.assert_called_once()
