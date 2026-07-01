import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger
from backend.app.config import DB_PATH

def get_db_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database with WAL enabled and row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Log (WAL) mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    """Initializes the SQLite database schema and creates indexes."""
    logger.info(f"Initializing database at: {DB_PATH}")
    with get_db_connection() as conn:
        # Reviews table (updated with scraped_at, analysed, last_run_id)
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
                last_run_id TEXT
            )
        """)
        
        # Run migrations to add analysed and last_run_id if table already exists
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
        
        # Composite index to optimize dynamic dashboard filtering
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_date_source ON reviews(published_at, source);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_scraped ON reviews(scraped_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_last_run ON reviews(last_run_id);")
        conn.commit()
    logger.info("Database initialized successfully.")

def save_review(review: Dict[str, Any], run_id: Optional[str] = None) -> bool:
    """
    Saves a single review to the database.
    Returns True if inserted/updated, False otherwise.
    """
    review_copy = dict(review)
    review_copy["run_id"] = run_id
    
    query = """
        INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, sentiment, location, published_at, scraped_at, analysed, last_run_id)
        VALUES (:id, :raw_text, :translated_text, :rating, :source, :country, :sentiment, :location, :published_at, CURRENT_TIMESTAMP, 0, :run_id)
        ON CONFLICT(id) DO UPDATE SET
            raw_text = excluded.raw_text,
            translated_text = excluded.translated_text,
            rating = excluded.rating,
            sentiment = excluded.sentiment,
            location = excluded.location,
            published_at = excluded.published_at,
            scraped_at = CURRENT_TIMESTAMP,
            analysed = 0,
            last_run_id = excluded.last_run_id
    """
    try:
        with get_db_connection() as conn:
            conn.execute(query, review_copy)
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving review {review.get('id')}: {e}")
        return False

def save_reviews_batch(reviews: List[Dict[str, Any]], run_id: Optional[str] = None) -> int:
    """
    Saves a batch of reviews efficiently.
    Returns the count of successfully saved reviews.
    """
    reviews_copied = []
    for rev in reviews:
        rev_copy = dict(rev)
        rev_copy["run_id"] = run_id
        reviews_copied.append(rev_copy)
        
    query = """
        INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, sentiment, location, published_at, scraped_at, analysed, last_run_id)
        VALUES (:id, :raw_text, :translated_text, :rating, :source, :country, :sentiment, :location, :published_at, CURRENT_TIMESTAMP, 0, :run_id)
        ON CONFLICT(id) DO UPDATE SET
            raw_text = excluded.raw_text,
            translated_text = excluded.translated_text,
            rating = excluded.rating,
            sentiment = excluded.sentiment,
            location = excluded.location,
            published_at = excluded.published_at,
            scraped_at = CURRENT_TIMESTAMP,
            analysed = 0,
            last_run_id = excluded.last_run_id
    """
    saved_count = 0
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, reviews_copied)
            conn.commit()
            saved_count = cursor.rowcount
        return saved_count
    except Exception as e:
        logger.error(f"Error saving batch of reviews: {e}")
        # Fallback to individual inserts to maximize success
        for rev in reviews:
            if save_review(rev, run_id):
                saved_count += 1
        return saved_count

def get_reviews(
    sources: Optional[List[str]] = None,
    min_rating: Optional[int] = None,
    max_rating: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
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
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error retrieving reviews: {e}")
        return []
