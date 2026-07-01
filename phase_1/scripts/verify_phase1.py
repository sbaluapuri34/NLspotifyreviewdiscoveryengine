import asyncio
import os
import sys
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

# Reconfigure stdout to use UTF-8 on Windows consoles to prevent encoding errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.database import init_db, get_reviews, save_reviews_batch
from backend.app.ingestion import PlayStoreScraper
from backend.app.pipeline import TextPipeline

async def main():
    logger.info("Starting Phase 1 end-to-end integration verification...")
    
    # 1. Initialize database
    init_db()
    
    # 2. Scrape a few reviews from Google Play Store (live)
    scraper = PlayStoreScraper()
    raw_reviews = await scraper.scrape(limit=5)
    
    if not raw_reviews:
        logger.error("No reviews scraped. Check internet connection.")
        return
        
    logger.info(f"Scraped {len(raw_reviews)} raw reviews. Processing through pipeline...")
    
    # 3. Process reviews
    pipeline = TextPipeline()
    processed_reviews = []
    for r in raw_reviews:
        processed = pipeline.process_review(r)
        if processed:
            processed_reviews.append(processed)
            
    logger.info(f"Processed {len(processed_reviews)} reviews (filtered out duplicates/short reviews).")
    
    # 4. Save to database
    if processed_reviews:
        saved_count = save_reviews_batch(processed_reviews)
        logger.info(f"Saved {saved_count} reviews to the SQLite database.")
        
        # 5. Retrieve and print
        db_reviews = get_reviews(limit=5)
        print("\n--- Last 5 Saved Reviews in Database ---")
        for i, r in enumerate(db_reviews, 1):
            print(f"\n[{i}] Source: {r['source']} | Rating: {r['rating']} | Location: {r['location']}")
            print(f"    Raw Text: {r['raw_text'][:100]}...")
            if r['translated_text']:
                print(f"    Translated/Sanitized: {r['translated_text'][:100]}...")
            print(f"    Published At: {r['published_at']}")
        print("----------------------------------------\n")
    else:
        logger.warning("No reviews were saved (they might have been filtered out as duplicates or too short).")
        
    logger.info("Verification complete!")

if __name__ == "__main__":
    asyncio.run(main())
