import os
import sys
import sqlite3
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.database import get_db_connection
from backend.app.pipeline import TextPipeline

# Common Hinglish stopwords
HINGLISH_KEYWORDS = {
    "hai", "h", "bhai", "achha", "acha", "bohot", "bahut", "ke", "ki", "ko", "se", "ka", 
    "yaar", "aap", "tum", "ho", "na", "hi", "bhi", "toh", "tha", "rha", "raha", "rhi", 
    "gaya", "ab", "kar", "kr", "kya", "karna", "karke", "likha", "sath", "saath", "aur", 
    "ya", "lekin", "par", "pe", "hota", "hote", "baje", "gaye", "diya", "liya", "kuch"
}

ALLOWED_LANGS = {"en", "hi", "bn", "gu", "kn", "ml", "mr", "pa", "ta", "te", "ur"}
MISIDENTIFIED_HINGLISH_LANGS = {"so", "tl", "af", "et", "ro", "cy", "sl", "no"}

def is_target_language(text: str, pipeline: TextPipeline) -> tuple[bool, str]:
    """
    Checks if the text is in one of the target languages:
    English, Hindi, Hinglish, or Indian regional languages.
    Returns (is_target, detected_lang).
    """
    cleaned = pipeline.clean_text_preserve_negations(text)
    if not cleaned:
        return False, "unknown"
        
    lang = pipeline.detect_language(cleaned)
    
    # 1. Direct match with allowed languages
    if lang in ALLOWED_LANGS:
        return True, lang
        
    # 2. Hinglish heuristic for commonly misidentified languages
    if lang in MISIDENTIFIED_HINGLISH_LANGS:
        words = set(cleaned.lower().split())
        if words.intersection(HINGLISH_KEYWORDS):
            return True, f"hinglish ({lang})"
            
    return False, lang

def main():
    logger.info("Starting database audit...")
    pipeline = TextPipeline()
    
    db_path = project_root / "backend" / "spotify_research.db"
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        return
        
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Fetch all reviews
        cursor.execute("SELECT id, raw_text, source FROM reviews")
        reviews = cursor.fetchall()
        logger.info(f"Total reviews in database to audit: {len(reviews)}")
        
        to_delete = []
        kept_counts = {}
        rejected_counts = {}
        
        for idx, r in enumerate(reviews, 1):
            review_id = r["id"]
            text = r["raw_text"]
            source = r["source"]
            
            is_target, lang = is_target_language(text, pipeline)
            
            if is_target:
                kept_counts[lang] = kept_counts.get(lang, 0) + 1
            else:
                to_delete.append(review_id)
                rejected_counts[lang] = rejected_counts.get(lang, 0) + 1
                logger.debug(f"Rejecting review [{review_id}] from source [{source}] (detected: {lang}): {text[:60]}...")
                
            if idx % 1000 == 0:
                logger.info(f"Audited {idx}/{len(reviews)} reviews...")
                
        logger.info(f"Audit complete. Kept: {sum(kept_counts.values())}, Rejected: {len(to_delete)}")
        logger.info(f"Kept language distribution: {kept_counts}")
        logger.info(f"Rejected language distribution: {rejected_counts}")
        
        if to_delete:
            logger.info(f"Deleting {len(to_delete)} non-target language reviews from database...")
            # Delete in batches
            batch_size = 500
            for i in range(0, len(to_delete), batch_size):
                batch = to_delete[i:i+batch_size]
                cursor.execute(
                    f"DELETE FROM reviews WHERE id IN ({','.join(['?'] * len(batch))})",
                    batch
                )
            conn.commit()
            logger.info("Successfully pruned the database.")
        else:
            logger.info("No reviews needed to be deleted.")

if __name__ == "__main__":
    main()
