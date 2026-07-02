import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger
from backend.app.config import DB_PATH

def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Returns a connection to the SQLite database with WAL enabled and row factory."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Log (WAL) mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db(db_path: Optional[str] = None):
    """Initializes the SQLite database schema and creates indexes."""
    import zipfile
    from pathlib import Path
    
    path = db_path or DB_PATH
    db_file = Path(path)
    zip_file = Path(str(path) + ".zip")
    if not zip_file.exists():
        # Fallback to backend code root directory (where zip is committed in Git)
        zip_file = Path(__file__).resolve().parent.parent / "spotify_research.db.zip"
        
    logger.info(f"--- DB DIAGNOSTICS ---")
    logger.info(f"Target DB Path: {path}")
    logger.info(f"Target DB Exists: {db_file.exists()}")
    if db_file.exists():
        logger.info(f"Target DB Size: {db_file.stat().st_size} bytes")
    logger.info(f"Source Zip Path: {zip_file}")
    logger.info(f"Source Zip Exists: {zip_file.exists()}")
    logger.info(f"----------------------")
        
    # Auto-extract database zip file on startup if DB file is missing or empty (<100KB)
    if (not db_file.exists() or db_file.stat().st_size < 100 * 1024) and zip_file.exists():
        logger.info(f"Database file not found or is empty (<100KB) at {path}. Zipped database detected at {zip_file}. Extracting...")
        try:
            if db_file.exists():
                db_file.unlink() # Delete empty placeholder file to avoid collision
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(db_file.parent)
            logger.info("Successfully extracted database.")
        except Exception as unzip_err:
            logger.error(f"Error unzipping database file: {unzip_err}")
            
    logger.info(f"Initializing database at: {path}")
    conn = get_db_connection(path)
    try:
        # Reviews table (updated with scraped_at, analysed, last_run_id, detected_language)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                raw_text TEXT NOT NULL,
                translated_text TEXT,
                rating INTEGER,
                source TEXT NOT NULL,
                country TEXT,
                sentiment REAL,
                location TEXT,
                published_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                analysed INTEGER DEFAULT 0,
                last_run_id TEXT,
                detected_language TEXT
            )
        """)
        
        # Run migrations to add analysed, last_run_id, and detected_language if table already exists
        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN scraped_at TEXT;")
            logger.info("Migration: Added scraped_at column to reviews table.")
        except sqlite3.OperationalError:
            pass
            
        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN analysed INTEGER DEFAULT 0;")
            logger.info("Migration: Added analysed column to reviews table.")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN last_run_id TEXT;")
            logger.info("Migration: Added last_run_id column to reviews table.")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN detected_language TEXT;")
            logger.info("Migration: Added detected_language column to reviews table.")
        except sqlite3.OperationalError:
            pass
        
        # Pipeline runs table for persisting per-run statistics
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                fetched_json TEXT,
                analysed_json TEXT
            )
        """)
        
        # LLM cache table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Theme configurations table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS theme_configurations (
                theme_slug TEXT PRIMARY KEY,
                theme_name TEXT NOT NULL,
                configuration_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Composite index to optimize dynamic dashboard filtering
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_date_source ON reviews(published_at, source);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_scraped ON reviews(scraped_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_last_run ON reviews(last_run_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_filters ON reviews(source, country, detected_language);")
        conn.commit()
    finally:
        conn.close()
    logger.info("Database initialized successfully.")

def save_review(review: Dict[str, Any], run_id: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    """
    Saves a single review to the database.
    Returns True if inserted/updated, False otherwise.
    """
    review_copy = dict(review)
    review_copy["run_id"] = run_id
    review_copy["detected_language"] = review.get("detected_language")
    
    query = """
        INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, sentiment, location, published_at, scraped_at, analysed, last_run_id, detected_language)
        VALUES (:id, :raw_text, :translated_text, :rating, :source, :country, :sentiment, :location, :published_at, CURRENT_TIMESTAMP, 0, :run_id, :detected_language)
        ON CONFLICT(id) DO UPDATE SET
            raw_text = excluded.raw_text,
            translated_text = excluded.translated_text,
            rating = excluded.rating,
            sentiment = excluded.sentiment,
            location = excluded.location,
            published_at = excluded.published_at,
            scraped_at = CURRENT_TIMESTAMP,
            analysed = 0,
            last_run_id = excluded.last_run_id,
            detected_language = excluded.detected_language
    """
    try:
        with get_db_connection(db_path) as conn:
            conn.execute(query, review_copy)
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving review {review.get('id')}: {e}")
        return False

def save_reviews_batch(reviews: List[Dict[str, Any]], run_id: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """
    Saves a batch of reviews efficiently.
    Returns the count of successfully saved reviews.
    """
    reviews_copied = []
    for rev in reviews:
        rev_copy = dict(rev)
        rev_copy["run_id"] = run_id
        rev_copy["detected_language"] = rev.get("detected_language")
        reviews_copied.append(rev_copy)
        
    query = """
        INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, sentiment, location, published_at, scraped_at, analysed, last_run_id, detected_language)
        VALUES (:id, :raw_text, :translated_text, :rating, :source, :country, :sentiment, :location, :published_at, CURRENT_TIMESTAMP, 0, :run_id, :detected_language)
        ON CONFLICT(id) DO UPDATE SET
            raw_text = excluded.raw_text,
            translated_text = excluded.translated_text,
            rating = excluded.rating,
            sentiment = excluded.sentiment,
            location = excluded.location,
            published_at = excluded.published_at,
            scraped_at = CURRENT_TIMESTAMP,
            analysed = 0,
            last_run_id = excluded.last_run_id,
            detected_language = excluded.detected_language
    """
    saved_count = 0
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(query, reviews_copied)
            conn.commit()
            saved_count = cursor.rowcount
        return saved_count
    except Exception as e:
        logger.error(f"Error saving batch of reviews: {e}")
        # Fallback to individual inserts to maximize success
        for rev in reviews:
            if save_review(rev, run_id, db_path):
                saved_count += 1
        return saved_count

def get_reviews(
    sources: Optional[List[str]] = None,
    min_rating: Optional[int] = None,
    max_rating: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieves reviews filtered by various criteria."""
    query = "SELECT * FROM reviews WHERE 1=1"
    params = []

    if sources:
        placeholders = ",".join(["?" for _ in sources])
        query += f" AND source IN ({placeholders})"
        params.extend(sources)

    if min_rating is not None:
        query += " AND rating >= ?"
        params.append(min_rating)

    if max_rating is not None:
        query += " AND rating <= ?"
        params.append(max_rating)

    if from_date:
        query += " AND published_at >= ?"
        params.append(from_date)

    if to_date:
        query += " AND published_at <= ?"
        params.append(to_date)

    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error retrieving reviews: {e}")
        return []

def save_theme_config(theme_slug: str, theme_name: str, config_json: str, db_path: Optional[str] = None) -> bool:
    """Saves or updates a theme configuration in the database."""
    query = """
        INSERT INTO theme_configurations (theme_slug, theme_name, configuration_json, created_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(theme_slug) DO UPDATE SET
            theme_name = excluded.theme_name,
            configuration_json = excluded.configuration_json,
            created_at = datetime('now')
    """
    try:
        with get_db_connection(db_path) as conn:
            conn.execute(query, (theme_slug, theme_name, config_json))
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving theme config for {theme_slug}: {e}")
        return False

def get_theme_config(theme_slug: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a theme configuration from the database."""
    query = "SELECT configuration_json FROM theme_configurations WHERE theme_slug = ?"
    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(query, (theme_slug,))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
    except Exception as e:
        logger.error(f"Error retrieving theme config for {theme_slug}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def init_theme_db(theme_slug: str) -> str:
    """Initializes the isolated theme-specific database."""
    import os
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent.parent
    path = str(base_dir / f"spotify_research_{theme_slug}.db")
    init_db(path)
    return path

