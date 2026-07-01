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
        # Reviews table (updated with scraped_at)
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
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Run migration to add scraped_at if table already exists
        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN scraped_at TEXT;")
            logger.info("Migration: Added scraped_at column to reviews table.")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
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
        conn.commit()
    logger.info("Database initialized successfully.")

def save_review(review: Dict[str, Any]) -> bool:
    """
    Saves a single review to the database.
    Returns True if inserted/updated, False otherwise.
    """
    query = """
        INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, sentiment, location, published_at, scraped_at)
        VALUES (:id, :raw_text, :translated_text, :rating, :source, :country, :sentiment, :location, :published_at, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            raw_text = excluded.raw_text,
            translated_text = excluded.translated_text,
            rating = excluded.rating,
            sentiment = excluded.sentiment,
            location = excluded.location,
            published_at = excluded.published_at,
            scraped_at = CURRENT_TIMESTAMP
    """
    try:
        with get_db_connection() as conn:
            conn.execute(query, review)
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving review {review.get('id')}: {e}")
        return False

def save_reviews_batch(reviews: List[Dict[str, Any]]) -> int:
    """
    Saves a batch of reviews efficiently.
    Returns the count of successfully saved reviews.
    """
    query = """
        INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, sentiment, location, published_at, scraped_at)
        VALUES (:id, :raw_text, :translated_text, :rating, :source, :country, :sentiment, :location, :published_at, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            raw_text = excluded.raw_text,
            translated_text = excluded.translated_text,
            rating = excluded.rating,
            sentiment = excluded.sentiment,
            location = excluded.location,
            published_at = excluded.published_at,
            scraped_at = CURRENT_TIMESTAMP
    """
    saved_count = 0
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, reviews)
            conn.commit()
            saved_count = cursor.rowcount
        return saved_count
    except Exception as e:
        logger.error(f"Error saving batch of reviews: {e}")
        # Fallback to individual inserts to maximize success
        for rev in reviews:
            if save_review(rev):
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
