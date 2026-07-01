import pytest
from fastapi.testclient import TestClient
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

def test_trigger_scrape():
    response = client.post("/api/scrape?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data

def test_trigger_analyze():
    response = client.post("/api/analyze")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data

def test_stream_headers():
    # Only verify the initial connection and headers to prevent hanging
    with client.stream("GET", "/api/stream") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
