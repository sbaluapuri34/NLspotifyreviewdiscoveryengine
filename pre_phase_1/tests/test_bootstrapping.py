import os
# Set DATABASE_PATH env var before importing app modules to force consistent test DB usage
os.environ["DATABASE_PATH"] = "backend/tests/test_bootstrap.db"

import pytest
import sqlite3
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.database import save_theme_config, get_theme_config, init_db
from backend.app.bootstrapping import ThemeBootstrappingEngine
from backend.app.main import app

client = TestClient(app)
TEST_DB_PATH = "backend/tests/test_bootstrap.db"

@pytest.fixture(autouse=True)
def setup_test_db():
    # Initialize the test database schema
    init_db(TEST_DB_PATH)
    yield
    # Cleanup after test
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

def test_slugify():
    engine = ThemeBootstrappingEngine()
    assert engine.slugify("AI DJ") == "ai_dj"
    assert engine.slugify("Podcasts & Audio") == "podcasts_audio"
    assert engine.slugify("  Shuffle-Loops  ") == "shuffle_loops"

def test_fallback_config():
    engine = ThemeBootstrappingEngine()
    config = engine.generate_fallback_config("AI DJ")
    
    assert config["theme"] == "AI DJ"
    assert config["theme_slug"] == "ai_dj"
    assert "scraping_elements" in config
    assert config["scraping_elements"]["reddit_subreddits"] == ["spotify", "truespotify", "spotifyplaylist"]
    assert "level_0_config" in config
    assert "semantic_anchors" in config
    assert "research_questions" in config
    assert "ai dj" in config["level_0_config"]["priority_routing_keywords"]
    assert "TRQ1" in config["research_questions"]

def test_database_helpers():
    theme_slug = "test_theme"
    theme_name = "Test Theme"
    config_data = {"test_key": "test_value"}
    
    # Save config
    saved = save_theme_config(theme_slug, theme_name, json.dumps(config_data), TEST_DB_PATH)
    assert saved is True
    
    # Retrieve config
    retrieved = get_theme_config(theme_slug, TEST_DB_PATH)
    assert retrieved == config_data
    
    # Non-existent slug should return None
    assert get_theme_config("non_existent", TEST_DB_PATH) is None

@patch("httpx.post")
def test_bootstrap_engine_live_mock(mock_post):
    # Mock a successful Gemini API response
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    mock_config = {
        "theme": "Podcasts",
        "theme_slug": "podcasts",
        "scraping_elements": {
            "reddit_subreddits": ["spotify", "truespotify", "spotifyplaylist"],
            "reddit_search_queries": ["podcasts"],
            "youtube_search_queries": ["podcasts"],
            "spotify_community_keywords": ["podcasts"]
        },
        "level_0_config": {
            "priority_routing_keywords": ["podcast"]
        },
        "semantic_anchors": {
            "goal_listen": "listen to podcasts",
            "goal_discover": "discover podcasts",
            "context_car": "car podcasts",
            "context_home": "home podcasts",
            "frustration_playback": "playback podcasts",
            "frustration_ads": "ads podcasts",
            "frustration_navigation": "nav podcasts",
            "churn_indicator": "churn podcasts"
        },
        "research_questions": {
            "TRQ1": {"title": "T1", "question": "Q1"},
            "TRQ2": {"title": "T2", "question": "Q2"},
            "TRQ3": {"title": "T3", "question": "Q3"},
            "TRQ4": {"title": "T4", "question": "Q4"}
        }
    }
    
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": json.dumps(mock_config)}
                    ]
                }
            }
        ]
    }
    mock_post.return_value = mock_response
    
    # Force use of a dummy key to trigger API path
    engine = ThemeBootstrappingEngine(api_key="dummy_api_key")
    result = engine.bootstrap_theme("Podcasts")
    
    assert result == mock_config
    mock_post.assert_called_once()

@patch("backend.app.main.save_theme_config")
@patch("backend.app.main.get_theme_config")
@patch("backend.app.bootstrapping.ThemeBootstrappingEngine.bootstrap_theme")
def test_api_endpoint_fallback(mock_bootstrap, mock_get_config, mock_save_config):
    mock_get_config.return_value = None
    mock_config = {
        "theme": "Playlists",
        "theme_slug": "playlists",
        "scraping_elements": {},
        "level_0_config": {},
        "semantic_anchors": {},
        "research_questions": {
            "TRQ1": {"title": "Playlist Discoverability", "question": "Question 1"}
        }
    }
    mock_bootstrap.return_value = mock_config

    response = client.post("/api/exploration/bootstrap", json={"theme": "Playlists"})
    assert response.status_code == 200
    
    data = response.json()
    assert data["theme"] == "Playlists"
    assert data["theme_slug"] == "playlists"
    assert "TRQ1" in data["research_questions"]
    
    mock_save_config.assert_called_once()

@patch("backend.app.main.get_theme_config")
@patch("backend.app.bootstrapping.ThemeBootstrappingEngine.bootstrap_theme")
def test_api_endpoint_cached(mock_bootstrap, mock_get_config):
    # Setup mock config
    mock_config = {"theme": "Ads", "theme_slug": "ads", "cached": True}
    mock_get_config.return_value = mock_config
    
    # Call endpoint
    response = client.post("/api/exploration/bootstrap", json={"theme": "Ads"})
    assert response.status_code == 200
    
    data = response.json()
    assert data == mock_config
    
    # bootstrap_theme should NOT have been called because it was cached
    mock_bootstrap.assert_not_called()
