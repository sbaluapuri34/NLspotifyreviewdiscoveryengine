import os
import sqlite3
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app, create_raw_replica, run_level_0_bridge
from backend.app.database import init_db

@pytest.fixture
def temp_dbs():
    # Create temporary database files for testing
    fd1, db1 = tempfile.mkstemp(suffix=".db")
    fd2, db2 = tempfile.mkstemp(suffix=".db")
    fd3, db3 = tempfile.mkstemp(suffix=".db")
    os.close(fd1)
    os.close(fd2)
    os.close(fd3)
    
    yield db1, db2, db3
    
    for db in [db1, db2, db3]:
        if os.path.exists(db):
            os.unlink(db)

def test_create_raw_replica(temp_dbs):
    db_primary, db_replica, _ = temp_dbs
    
    # 1. Initialize primary DB and save some reviews
    init_db(db_primary)
    
    conn = sqlite3.connect(db_primary)
    conn.execute("""
        INSERT INTO reviews (id, raw_text, rating, source, country, published_at, scraped_at, analysed)
        VALUES 
        ('gp_1', 'Loved the smart shuffle recommendation', 5, 'google_play', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0),
        ('as_1', 'Podcast feature is bad', 2, 'app_store', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0),
        ('rd_1', 'Reddit comments about Spotify design', 4, 'reddit', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0)
    """)
    conn.commit()
    conn.close()
    
    # 2. Run create_raw_replica
    create_raw_replica(db_primary, db_replica)
    
    # 3. Verify that only GP and AS reviews are copied to replica
    conn = sqlite3.connect(db_replica)
    cursor = conn.cursor()
    cursor.execute("SELECT id, source FROM reviews ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 2
    assert rows[0] == ('as_1', 'app_store')
    assert rows[1] == ('gp_1', 'google_play')

def test_run_level_0_bridge(temp_dbs):
    _, db_replica, db_theme = temp_dbs
    
    # Initialize replica DB and save some reviews
    init_db(db_replica)
    conn = sqlite3.connect(db_replica)
    conn.execute("""
        INSERT INTO reviews (id, raw_text, rating, source, country, published_at, scraped_at, analysed)
        VALUES 
        ('gp_1', 'Loved the smart shuffle recommendation', 5, 'google_play', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0),
        ('gp_2', 'Podcast feature is bad', 2, 'google_play', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0),
        ('as_1', 'UI is slow', 3, 'app_store', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0)
    """)
    conn.commit()
    conn.close()
    
    # Initialize theme DB
    init_db(db_theme)
    
    # Define a theme config with priority keywords
    theme_config = {
        "theme": "Podcasts Exploration",
        "level_0_config": {
            "priority_routing_keywords": ["podcast", "smart shuffle"]
        }
    }
    
    # Run Level 0 bridge
    run_level_0_bridge("podcasts", theme_config, db_replica, db_theme)
    
    # Verify that only matching reviews are copied to the theme database
    conn = sqlite3.connect(db_theme)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reviews ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 2
    assert rows[0] == ('gp_1',) # Matches "smart shuffle"
    assert rows[1] == ('gp_2',) # Matches "podcast"
    # 'as_1' does not match, so it should not be in the theme database.

def test_run_pipeline_route():
    client = TestClient(app)
    
    # Mock get_theme_config to return None for non-existent theme
    with patch("backend.app.main.get_theme_config") as mock_get:
        mock_get.return_value = None
        
        # Test 400 response for non-existent theme
        response = client.post("/api/exploration/unknown_theme/run-pipeline")
        assert response.status_code == 400
        assert "is not bootstrapped" in response.json()["error"]
        
        # Test 202 response for discovery mode (default)
        # Mock background_tasks.add_task
        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/run-pipeline")
            assert response.status_code == 202
            assert "started" in response.json()["status"]
            mock_add_task.assert_called_once()
            
        # Test 202 response for theme mode
        mock_get.return_value = {"theme": "podcasts"}
        with patch("fastapi.BackgroundTasks.add_task") as mock_add_task:
            response = client.post("/api/exploration/podcasts/run-pipeline")
            assert response.status_code == 202
            assert "started" in response.json()["status"]
            mock_add_task.assert_called_once()

def test_google_play_scraper_regional_parameters():
    from backend.app.ingestion import PlayStoreScraper
    import asyncio
    
    scraper = PlayStoreScraper()
    queue = asyncio.Queue()
    
    with patch("google_play_scraper.reviews") as mock_reviews:
        mock_reviews.return_value = ([], None)
        
        # Run scraping task
        asyncio.run(scraper.scrape(queue, limit=10, lang='hi', country='in'))
        
        # Verify reviews was called with our target parameters
        mock_reviews.assert_called_once()
        args, kwargs = mock_reviews.call_args
        assert kwargs.get('lang') == 'hi'
        assert kwargs.get('country') == 'in'
        assert kwargs.get('count') == 10
