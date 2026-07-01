import pytest
import sqlite3
import os
import json
from pathlib import Path
from unittest.mock import MagicMock
from backend.app.analytics_compiler import AnalyticsCompiler

def test_device_classification(monkeypatch):
    # Mock _ensure_device_column to prevent creating a physical DB file
    monkeypatch.setattr(AnalyticsCompiler, "_ensure_device_column", MagicMock())
    
    compiler = AnalyticsCompiler(db_path="dummy_test.db")
    
    assert compiler.classify_device("using spotify in my car with android auto") == "car"
    assert compiler.classify_device("the app works great on my ipad tablet") == "tablet"
    assert compiler.classify_device("wearos watch app is laggy") == "wearable"
    assert compiler.classify_device("installed it on my windows pc laptop") == "pc"
    assert compiler.classify_device("casting to my android tv screen") == "tv"
    assert compiler.classify_device("great songs on my samsung mobile phone") == "mobile"

def test_compile_metrics_in_memory():
    # Use a temporary file path for the test database
    db_path = "backend/tests/test_temp.db"
    
    # Clean up any leftover test db
    if Path(db_path).exists():
        try:
            os.remove(db_path)
        except Exception:
            pass
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create reviews table
        cursor.execute("""
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                raw_text TEXT,
                translated_text TEXT,
                rating INTEGER,
                source TEXT,
                country TEXT,
                sentiment REAL,
                location TEXT,
                published_at TEXT,
                cluster_id TEXT,
                device_type TEXT
            )
        """)
        
        # Insert mock reviews
        cursor.execute("""
            INSERT INTO reviews (id, raw_text, rating, source, published_at, cluster_id, device_type)
            VALUES 
            ('r1', 'repetition in car auto', 2, 'google_play', '2026-06-01', 'cluster_14', 'car'),
            ('r2', 'discover weekly is stale', 3, 'reddit', '2026-06-02', 'cluster_11', 'mobile'),
            ('r3', 'unrelated ad complaints', 1, 'google_play', '2026-06-03', 'unrelated_ads', 'mobile'),
            ('r4', 'unrelated widget crash', 2, 'app_store', '2026-06-04', 'unrelated_widgets', 'tablet')
        """)
        
        # Create embeddings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                vector TEXT
            )
        """)
        cursor.execute("""
            INSERT INTO embeddings (id, vector)
            VALUES 
            ('r1', '[0.1, 0.2]'),
            ('r2', '[0.3, 0.4]')
        """)
        
        conn.commit()
        conn.close()
        
        # Initialize compiler on the temp DB
        compiler = AnalyticsCompiler(db_path=db_path)
        
        metrics = compiler.compile_metrics()
        
        assert metrics["split_ratio"]["total_reviews"] == 4
        assert metrics["split_ratio"]["discovery_related"]["count"] == 2
        assert metrics["split_ratio"]["discovery_related"]["percentage"] == 50.0
        
        # Verify device distribution
        devices = metrics["device_distribution"]["global"]
        car_dev = next(d for d in devices if d["device"] == "car")
        assert car_dev["count"] == 1
        assert car_dev["percentage"] == 25.0
        
        # Verify source distribution
        sources = metrics["source_distribution"]
        gp_src = next(s for s in sources if s["source"] == "google_play")
        assert gp_src["count"] == 2
        assert gp_src["percentage"] == 50.0
        
    finally:
        # Always clean up the test database file
        if Path(db_path).exists():
            try:
                os.remove(db_path)
            except Exception:
                pass
