import os
import json
import sqlite3
import tempfile
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app.main import app, get_db_path, DB_PATH
from backend.app.database import init_db

@pytest.fixture
def test_setup():
    # Create temp DB for default
    fd_def, db_def_path = tempfile.mkstemp(suffix=".db")
    os.close(fd_def)
    init_db(db_def_path)
    
    # Create temp DB for custom theme "testtheme"
    fd_theme, db_theme_path = tempfile.mkstemp(suffix=".db")
    os.close(fd_theme)
    init_db(db_theme_path)
    
    # Insert data in base DB
    conn = sqlite3.connect(db_def_path)
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN cluster_id TEXT;")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN cleaned_text TEXT;")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            vector TEXT NOT NULL,
            FOREIGN KEY(id) REFERENCES reviews(id)
        )
    """)
    conn.execute("INSERT INTO reviews (id, raw_text, rating, source, country, published_at, scraped_at, analysed, cluster_id) VALUES ('r_def', 'Discovery friction', 3, 'google_play', 'in', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 1, 'discovery_cluster')")
    conn.execute("INSERT INTO embeddings (id, vector) VALUES ('r_def', '[0.1, 0.2]')")
    conn.commit()
    conn.close()
    
    # Insert data in theme DB
    conn = sqlite3.connect(db_theme_path)
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN cluster_id TEXT;")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN cleaned_text TEXT;")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            vector TEXT NOT NULL,
            FOREIGN KEY(id) REFERENCES reviews(id)
        )
    """)
    conn.execute("INSERT INTO reviews (id, raw_text, rating, source, country, published_at, scraped_at, analysed, cluster_id) VALUES ('r_theme', 'Theme custom playback', 1, 'reddit', 'in', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 1, 'theme_playback')")
    conn.execute("INSERT INTO embeddings (id, vector) VALUES ('r_theme', '[0.3, 0.4]')")
    conn.commit()
    conn.close()
    
    yield db_def_path, db_theme_path
    
    for path in [db_def_path, db_theme_path]:
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

def test_theme_routing_isolation(test_setup):
    db_def_path, db_theme_path = test_setup
    
    client = TestClient(app)
    
    # Mock get_db_path in main.py
    def mock_get_db_path(theme_slug):
        if theme_slug == "testtheme":
            return db_theme_path
        return db_def_path
        
    with patch("backend.app.main.get_db_path", side_effect=mock_get_db_path), \
         patch("backend.app.main.DB_PATH", db_def_path):
         
        # 1. Test /api/clusters (Discovery mode)
        # Should query DB_PATH and get 1 cluster
        res_def = client.get("/api/clusters")
        assert res_def.status_code == 200
        data_def = res_def.json()
        assert len(data_def.get("clusters", [])) == 1
        assert data_def.get("clusters", [])[0]["cluster_id"] == "discovery_cluster"
        
        # 2. Test /api/exploration/testtheme/clusters
        # Should query custom theme DB and return custom cluster
        res_theme = client.get("/api/exploration/testtheme/clusters")
        assert res_theme.status_code == 200
        data_theme = res_theme.json()
        clusters = data_theme.get("clusters", [])
        assert len(clusters) == 1
        assert clusters[0]["cluster_id"] == "theme_playback"
        assert clusters[0]["top_reviews"][0]["id"] == "r_theme"
        assert clusters[0]["top_reviews"][0]["source"] == "reddit"
        
        # 3. Test research answers dynamic file loading path check
        with patch("pathlib.Path.exists", return_value=True), \
             patch("builtins.open", create=True) as mock_open:
             
            # Setup mock read data
            mock_open.return_value.__enter__.return_value.read.return_value = '{"RQ1": {"title": "Discovery theme", "executive_summary": "Theme answers"}}'
            
            # Hit default research
            client.get("/api/research")
            # Hit exploration research
            client.get("/api/exploration/testtheme/research")
