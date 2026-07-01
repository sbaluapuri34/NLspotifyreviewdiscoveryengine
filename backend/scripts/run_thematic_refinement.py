from typing import Optional
import asyncio
import hashlib
import os
import sys
import json
import time
import sqlite3
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.thematic_refinement import ThematicRefinementEngine
from backend.app.config import DB_PATH

def main(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    if db_path:
        os.environ["DATABASE_PATH"] = db_path
        if "DB_PATH" in globals():
            globals()["DB_PATH"] = db_path
        import backend.app.config
        backend.app.config.DB_PATH = db_path
        import backend.app.database
        backend.app.database.DB_PATH = db_path
        try:
            import backend.app.research
            backend.app.research.DB_PATH = db_path
        except ImportError:
            pass
        try:
            import backend.app.research_validator
            backend.app.research_validator.DB_PATH = db_path
        except ImportError:
            pass
        try:
            import backend.app.thematic_refinement
            backend.app.thematic_refinement.DB_PATH = db_path
        except ImportError:
            pass
        try:
            import backend.app.analytics_compiler
            backend.app.analytics_compiler.DB_PATH = db_path
        except ImportError:
            pass
    if theme_config_path:
        os.environ["THEME_CONFIG_PATH"] = theme_config_path

    logger.info("Starting Phase 4.5: Level 3.5 Thematic Refinement Execution...")
    start_time = time.time()

    # Load dynamic theme config if it exists
    theme_config = None
    theme_config_path = os.environ.get("THEME_CONFIG_PATH")
    if theme_config_path and Path(theme_config_path).exists():
        try:
            with open(theme_config_path, "r", encoding="utf-8") as f:
                theme_config = json.load(f)
            logger.info(f"Loaded dynamic theme configuration for: {theme_config.get('theme')}")
        except Exception as e:
            logger.error(f"Error loading theme configuration JSON: {e}")

    theme_slug = theme_config.get("theme_slug") if theme_config else None
    suffix = f"_{theme_slug}" if theme_slug else ""

    answers_filename = f"research_question_answers{suffix}.json"
    answers_path = Path(project_root) / "backend" / "scripts" / answers_filename
    if not answers_path.exists():
        logger.error(f"Research answers file not found at {answers_path}. Please run Phase 4 first.")
        return

    with open(answers_path, "r", encoding="utf-8") as f:
        answers = json.load(f)

    # 1. Fetch reviews and their embeddings from database
    logger.info("Fetching reviews and embeddings from SQLite...")
    target_db_path = os.environ.get("DATABASE_PATH") or DB_PATH
    conn = sqlite3.connect(target_db_path)
    cursor = conn.cursor()
    
    # We only need discovery reviews to keep the pool clean and relevant
    cursor.execute("""
        SELECT r.id, r.translated_text, r.raw_text, e.vector 
        FROM reviews r 
        JOIN embeddings e ON r.id = e.id
        WHERE r.cluster_id IS NOT NULL AND r.cluster_id NOT LIKE 'unrelated_%'
    """)
    
    reviews_pool = []
    review_vectors = {}
    
    for row in cursor.fetchall():
        rid, trans, raw, vec_blob = row
        text = trans or raw
        reviews_pool.append({"id": rid, "text": text})
        
        # Deserialize vector blob (stored as JSON array in database)
        review_vectors[rid] = json.loads(vec_blob)
        
    conn.close()
    logger.info(f"Loaded {len(reviews_pool)} candidate discovery reviews.")

    if not reviews_pool:
        logger.error("No discovery reviews found in the database. Aborting.")
        return

    # 2. Initialize Thematic Refinement Engine
    engine = ThematicRefinementEngine()
    if not engine.api_key:
        logger.error("No Groq API key found. Please configure it in your environment or .env file.")
        return

    # 3. Extract sub-themes
    research_list = list(answers.values())
    raw_themes = engine.extract_sub_themes(research_list, reviews_pool)
    
    refined_themes = raw_themes.get("refined_themes", [])
    if not refined_themes:
        logger.warning("No sub-themes were proposed by the LLM.")
        return

    # 4. Double-Pass Validation
    validated_themes = engine.validate_mappings(refined_themes, review_vectors)

    # 5. Save to JSON
    output_json_filename = f"decomposed_themes{suffix}.json"
    output_json_path = Path(project_root) / "backend" / "scripts" / output_json_filename
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(validated_themes, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved refined themes to {output_json_path}")

    # Save a copy to persistent metadata cache
    cache_json_filename = f"decomposed_themes_cache{suffix}.json"
    cache_json_path = Path(project_root) / "backend" / "scripts" / cache_json_filename
    try:
        with open(cache_json_path, "w", encoding="utf-8") as f:
            json.dump(validated_themes, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved refined themes cache to {cache_json_path}")
    except Exception as ce:
        logger.warning(f"Error saving refined themes cache: {ce}")

    # 6. Save to SQLite database
    try:
        conn = sqlite3.connect(target_db_path)
        cursor = conn.cursor()
        
        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decomposed_themes (
                theme_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                category TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS theme_reviews (
                theme_id TEXT,
                review_id TEXT,
                PRIMARY KEY (theme_id, review_id),
                FOREIGN KEY (theme_id) REFERENCES decomposed_themes(theme_id),
                FOREIGN KEY (review_id) REFERENCES reviews(id)
            )
        """)
        
        # Clear old mappings
        cursor.execute("DELETE FROM theme_reviews")
        cursor.execute("DELETE FROM decomposed_themes")
        
        for theme in validated_themes:
            tid = theme.get("theme_id")
            cursor.execute("""
                INSERT INTO decomposed_themes (theme_id, name, description, category, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (tid, theme.get("name"), theme.get("description"), theme.get("category")))
            
            for rid in theme.get("verified_review_ids", []):
                cursor.execute("""
                    INSERT OR IGNORE INTO theme_reviews (theme_id, review_id)
                    VALUES (?, ?)
                """, (tid, rid))
                
        conn.commit()
        conn.close()
        logger.info("Successfully saved refined themes and mappings to SQLite.")
    except Exception as e:
        logger.error(f"Error saving refined themes to database: {e}")

    # 7. Print Summary
    print("\n" + "="*50)
    print("LEVEL 3.5 DEEP THEMATIC REFINEMENT SUMMARY")
    print("="*50)
    for theme in validated_themes:
        proposed = len(theme.get("proposed_review_ids", []))
        verified = len(theme.get("verified_review_ids", []))
        rejected = proposed - verified
        print(f"\n[{theme.get('theme_id')}] {theme.get('name')}")
        print(f"Category   : {theme.get('category')}")
        print(f"Description: {theme.get('description')}")
        print(f"Mappings   : {verified} Verified, {rejected} Rejected (Verification Rate: {verified/proposed*100:.1f}%)")
    print("\n" + "="*50)

    elapsed = time.time() - start_time
    logger.info(f"Phase 4.5 completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()


async def run_thematic_refinement_pipeline(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: main(db_path, theme_config_path))
