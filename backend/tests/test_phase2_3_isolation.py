import os
import json
import sqlite3
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from backend.app.database import init_db
from backend.app.vectors.cluster import LeaderFollowerClustering
from backend.scripts.run_clustering import main as run_clustering_main
from backend.scripts.run_analytics import main as run_analytics_main

@pytest.fixture
def temp_env_and_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    # Initialize the database schema
    init_db(db_path)
    
    # Pre-apply migrations for columns added by run_clustering
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN cleaned_text TEXT;")
        conn.execute("ALTER TABLE reviews ADD COLUMN metadata TEXT;")
        conn.execute("ALTER TABLE reviews ADD COLUMN cluster_id TEXT;")
    except Exception:
        pass
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            vector TEXT NOT NULL,
            FOREIGN KEY(id) REFERENCES reviews(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            id TEXT PRIMARY KEY,
            centroid TEXT NOT NULL,
            size INTEGER NOT NULL,
            mean_similarity REAL NOT NULL,
            variance REAL NOT NULL,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Insert some mock reviews
    conn.execute("""
        INSERT INTO reviews (id, raw_text, rating, source, country, published_at, scraped_at, analysed)
        VALUES 
        ('r1', 'Loved the smart shuffle recommendation loop dj', 5, 'google_play', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0),
        ('r2', 'Podcast feature offline speed control is bad', 2, 'google_play', 'us', '2026-07-01T12:00:00', '2026-07-01T12:05:00', 0)
    """)
    conn.commit()
    conn.close()
    
    # Setup temporary theme config file
    theme_config = {
        "theme": "Podcasts Exploration",
        "theme_slug": "podcasts",
        "level_0_config": {
            "priority_routing_keywords": ["podcast", "offline"]
        },
        "semantic_anchors": {
            "frustration_playback": "playback error buffering offline sync speed control skip seconds",
            "frustration_ads": "host-read ads premium ads unskippable sponsored segments"
        }
    }
    fd_cfg, cfg_path = tempfile.mkstemp(suffix=".json")
    os.close(fd_cfg)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(theme_config, f)
        
    yield db_path, cfg_path
    
    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except OSError:
            pass
    if os.path.exists(cfg_path):
        try:
            os.unlink(cfg_path)
        except OSError:
            pass

def test_adaptive_threshold_logic():
    # Verify that LeaderFollowerClustering computes adaptive threshold when threshold is None
    clustering = LeaderFollowerClustering(dimension=384, threshold=None, dataset_size=200)
    assert clustering.threshold == 0.80 # N < 500
    
    clustering_large = LeaderFollowerClustering(dimension=384, threshold=None, dataset_size=5000)
    assert clustering_large.threshold == 0.65 # 4000 <= N < 8000

@patch("backend.scripts.run_clustering.get_db_connection")
@patch("backend.scripts.run_clustering.VectorEmbedder")
def test_run_clustering_isolation(mock_embedder_class, mock_get_conn, temp_env_and_db):
    db_path, cfg_path = temp_env_and_db
    
    # Set up mock embedder
    mock_embedder = mock_embedder_class.return_value
    mock_embedder.dimension = 384
    mock_embedder.embed_batch.return_value = [[0.1] * 384, [0.2] * 384]
    
    # Set up database connection mock (needs sqlite3.Row row factory)
    def get_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    mock_get_conn.side_effect = get_conn
    
    # 1. Test Discovery Mode (no theme configuration)
    with patch.dict(os.environ, {"DATABASE_PATH": db_path}, clear=True):
        if "THEME_CONFIG_PATH" in os.environ:
            del os.environ["THEME_CONFIG_PATH"]
            
        run_clustering_main()
        
        # Verify that only review 1 (containing 'shuffle', 'loop') is classified as discovery
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, cluster_id FROM reviews ORDER BY id")
        rows = cursor.fetchall()
        conn.close()
        
        # r1 gets detailed cluster, r2 (podcast bad) goes to unrelated_ads because of 'ad' in 'bad'
        assert rows[0][0] == 'r1'
        assert rows[0][1].startswith('cluster_')
        assert rows[1] == ('r2', 'unrelated_ads')
        
    # Reset database review analytics states
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE reviews SET cluster_id = NULL, analysed = 0")
    conn.commit()
    conn.close()

    # 2. Test Theme Exploration Mode (theme configuration loaded)
    with patch.dict(os.environ, {"DATABASE_PATH": db_path, "THEME_CONFIG_PATH": cfg_path}):
        run_clustering_main()
        
        # Verify that BOTH reviews are routed to detailed clustering (cluster_1, cluster_2, etc.)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, cluster_id FROM reviews ORDER BY id")
        rows = cursor.fetchall()
        conn.close()
        
        # Both should be assigned detailed semantic clusters (which start with 'cluster_')
        assert rows[0][1].startswith('cluster_')
        assert rows[1][1].startswith('cluster_')

@patch("backend.scripts.run_analytics.get_db_connection")
@patch("backend.scripts.run_analytics.VectorEmbedder")
def test_run_analytics_isolation(mock_embedder_class, mock_get_conn, temp_env_and_db):
    db_path, cfg_path = temp_env_and_db
    
    # Mock database centroids
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE reviews SET cluster_id = 'cluster_1'")
    conn.execute("INSERT INTO clusters (id, centroid, size, mean_similarity, variance) VALUES ('cluster_1', ?, 2, 0.8, 0.1)", (json.dumps([0.1]*384),))
    conn.execute("INSERT OR REPLACE INTO embeddings (id, vector) VALUES ('r1', ?), ('r2', ?)", (json.dumps([0.1]*384), json.dumps([0.2]*384)))
    conn.commit()
    conn.close()

    # Set up mock embedder
    mock_embedder = mock_embedder_class.return_value
    mock_embedder.dimension = 384
    mock_embedder.embed_batch.return_value = [[0.1] * 384, [0.2] * 384]
    
    # Set up database connection mock
    def get_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    mock_get_conn.side_effect = get_conn
    
    # Run analytics in Theme Mode
    with patch.dict(os.environ, {"DATABASE_PATH": db_path, "THEME_CONFIG_PATH": cfg_path}):
        run_analytics_main()
        
        # Verify compiled evidence packages output file exists
        out_file = Path(__file__).resolve().parent.parent / "scripts" / "compiled_evidence_packages.json"
        assert out_file.exists()
