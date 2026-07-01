import asyncio
import os
import sys
import time
from pathlib import Path
from loguru import logger
from datetime import datetime, timezone

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.database import init_db, save_reviews_batch, get_db_connection
from backend.app.ingestion import (
    PlayStoreScraper,
    AppStoreScraper,
    SpotifyForumsScraper,
    YouTubeCommentsScraper,
    RedditScraper
)
from backend.app.pipeline import TextPipeline, ALLOWED_LANGS, HINGLISH_KEYWORDS
from deep_translator import GoogleTranslator

# Configs
SPOTIFY_VIDEO_IDS = [
    "9ZVCJoq76-M",  # Spotify AI DJ Official Overview
    "ozF85QOz6Dg",  # Meet the voice behind Spotify AI DJ
    "KMfVciFsc38",  # Spotify's New AI DJ @Waveform
    "y5rNcdqDRTk",  # Spotify's most underrated feature
    "IVAeoXbE9ZY",  # Inside the Making of the DJ
    "pGntmcy_HX8",  # How to Use Spotify AI DJ
    "3699aBnI0wg",  # How to Use Spotify Smart Shuffle
    "h7o_WSQUFnE",  # How to Disable Smart Shuffle
    "7ag3qjpuB3I",  # How Spotify's Algorithm Works
    "F6Gj8MPlNAM"   # Spotify Trending Songs Algorithm
]

# Limits for maximum collection
PLAY_STORE_LIMIT = 15000
APP_STORE_LIMIT = 500
REDDIT_LIMIT = 300
FORUM_LIMIT = 300
YOUTUBE_LIMIT = 300

# Queues for concurrent pipeline
raw_queue = asyncio.Queue(maxsize=1000)
translation_queue = asyncio.Queue(maxsize=200)
db_queue = asyncio.Queue(maxsize=500)

# Statistics tracking
stats = {
    "start_time": 0.0,
    "end_time": 0.0,
    "scraped": {},
    "processed": {},
    "saved": {},
    "rejected_lang": 0,
    "rejected_dup": 0,
    "rejected_short": 0,
    "translation_calls": 0,
    "translated_count": 0,
    "db_batches": 0,
}

# ---------------------------------------------------------
# Source Workers
# ---------------------------------------------------------

async def google_play_worker():
    logger.info("Google Play Worker started.")
    try:
        scraper = PlayStoreScraper()
        await scraper.scrape(raw_queue, limit=PLAY_STORE_LIMIT)
        logger.info("Google Play Worker finished.")
    except Exception as e:
        logger.error(f"Google Play Worker failed: {e}")

async def apple_worker():
    logger.info("Apple App Store Worker started.")
    try:
        scraper = AppStoreScraper()
        await scraper.scrape(raw_queue, limit=APP_STORE_LIMIT)
        logger.info("Apple App Store Worker finished.")
    except Exception as e:
        logger.error(f"Apple App Store Worker failed: {e}")

async def reddit_worker():
    logger.info("Reddit Worker started.")
    try:
        scraper = RedditScraper()
        subreddits = ["truespotify", "spotify", "spotifyplaylist", "musicsuggestions"]
        await scraper.scrape(raw_queue, subreddits=subreddits, limit=REDDIT_LIMIT)
        logger.info("Reddit Worker finished.")
    except Exception as e:
        logger.error(f"Reddit Worker failed: {e}")

async def forum_worker():
    logger.info("Spotify Forums Worker started.")
    try:
        scraper = SpotifyForumsScraper()
        queries = ["recommendation", "discover weekly", "discover", "release radar", "shuffle", "autoplay", "algorithm", "ai dj"]
        for q in queries:
            await scraper.scrape(raw_queue, query=q, limit=FORUM_LIMIT // len(queries))
        logger.info("Spotify Forums Worker finished.")
    except Exception as e:
        logger.error(f"Spotify Forums Worker failed: {e}")

async def youtube_worker():
    logger.info("YouTube Comments Worker started.")
    try:
        scraper = YouTubeCommentsScraper()
        await scraper.scrape(raw_queue, video_ids=SPOTIFY_VIDEO_IDS, limit=YOUTUBE_LIMIT)
        logger.info("YouTube Comments Worker finished.")
    except Exception as e:
        logger.error(f"YouTube Comments Worker failed: {e}")

# ---------------------------------------------------------
# Batch Translation Worker
# ---------------------------------------------------------

async def batch_translation_worker():
    logger.info("Batch Translation Worker started.")
    while True:
        # Wait for at least one item
        item = await translation_queue.get()
        if item is None:
            translation_queue.task_done()
            break
            
        batch = [item]
        # Drain queue up to batch size of 20 or wait 100ms
        start = time.time()
        while len(batch) < 20 and (time.time() - start) < 0.1:
            try:
                val = translation_queue.get_nowait()
                if val is None:
                    # Put sentinel back to let the loop exit next iteration
                    await translation_queue.put(None)
                    break
                batch.append(val)
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.02)
                
        # Group batch by source language
        by_lang = {}
        for text, lang, fut in batch:
            by_lang.setdefault(lang, []).append((text, fut))
            
        stats["translation_calls"] += len(by_lang)
        
        # Execute translations
        for lang, items in by_lang.items():
            texts = [it[0] for it in items]
            futures = [it[1] for it in items]
            
            # Map Hinglish to Hindi translator
            src_lang = "hi" if "hinglish" in lang else lang
            
            try:
                loop = asyncio.get_running_loop()
                translator = GoogleTranslator(source=src_lang, target="en")
                # Run synchronous translation in executor
                translated = await loop.run_in_executor(
                    None,
                    lambda: translator.translate_batch(texts)
                )
                stats["translated_count"] += len(translated)
                for fut, trans_txt in zip(futures, translated):
                    fut.set_result(trans_txt)
            except Exception as te:
                logger.warning(f"Batch translation failed for lang {lang}: {te}. Returning original texts.")
                for fut, orig_txt in zip(futures, texts):
                    fut.set_result(orig_txt)
                    
        for _ in range(len(batch)):
            translation_queue.task_done()
            
    logger.info("Batch Translation Worker finished.")

# ---------------------------------------------------------
# Parallel Preprocessing Workers
# ---------------------------------------------------------

async def preprocessing_worker(worker_id: int, pipeline: TextPipeline, existing_ids: set):
    logger.info(f"Preprocessing Worker {worker_id} started.")
    while True:
        review = await raw_queue.get()
        if review is None:
            raw_queue.task_done()
            break
            
        review_id = review.get("id")
        source = review.get("source", "unknown")
        
        # Track raw scraped count
        stats["scraped"][source] = stats["scraped"].get(source, 0) + 1
        
        if review_id and review_id in existing_ids:
            raw_queue.task_done()
            continue
            
        source = review.get("source", "unknown")
        raw_text = review.get("raw_text", "").strip()
        
        if not raw_text:
            raw_queue.task_done()
            continue
            
        # 1. Clean Text
        cleaned = pipeline.clean_text_preserve_negations(raw_text)
        
        # 2. Early Language Filtering
        lang = pipeline.detect_language(cleaned)
        is_target = False
        if lang in ALLOWED_LANGS:
            is_target = True
        else:
            words = set(cleaned.lower().split())
            if words.intersection(HINGLISH_KEYWORDS):
                is_target = True
                lang = "hinglish"
                
        if not is_target:
            stats["rejected_lang"] += 1
            raw_queue.task_done()
            continue
            
        # 3. Translate if necessary (delegate to batch translation worker)
        translated = cleaned
        if lang != "en":
            fut = asyncio.get_running_loop().create_future()
            await translation_queue.put((cleaned, lang, fut))
            translated = await fut
            
        # 4. Filter PII & Emojis
        sanitized = pipeline.filter_pii_and_noise(translated)
        
        # 5. Extract location
        location = pipeline.extract_location(raw_text) or pipeline.extract_location(sanitized)
        
        # 6. Length Filter
        meaningful_count = pipeline.get_meaningful_word_count(sanitized)
        is_priority = pipeline.matches_priority_keywords(sanitized)
        
        if meaningful_count < 3 and not is_priority:
            stats["rejected_short"] += 1
            raw_queue.task_done()
            continue
            
        # 7. Deduplicate (LSH)
        if pipeline.is_duplicate_lsh(review_id, sanitized):
            stats["rejected_dup"] += 1
            raw_queue.task_done()
            continue
            
        # 8. Compress if extremely long
        words = sanitized.split()
        if len(words) > 150:
            compressed = pipeline.compress_text_textrank(sanitized, num_sentences=3)
            sanitized = compressed
            
        processed_review = {
            "id": review_id,
            "raw_text": raw_text,
            "translated_text": sanitized if lang != "en" else None,
            "rating": review.get("rating"),
            "source": source,
            "country": review.get("country"),
            "sentiment": None,
            "location": location,
            "published_at": review.get("published_at")
        }
        
        await db_queue.put(processed_review)
        stats["processed"][source] = stats["processed"].get(source, 0) + 1
        raw_queue.task_done()
        
    logger.info(f"Preprocessing Worker {worker_id} finished.")

# ---------------------------------------------------------
# Batch Database Writer
# ---------------------------------------------------------

async def db_writer_worker():
    logger.info("Database Writer Worker started.")
    while True:
        item = await db_queue.get()
        if item is None:
            db_queue.task_done()
            break
            
        batch = [item]
        start = time.time()
        # Drain queue up to batch size of 50 or wait 200ms
        while len(batch) < 50 and (time.time() - start) < 0.2:
            try:
                val = db_queue.get_nowait()
                if val is None:
                    await db_queue.put(None)
                    break
                batch.append(val)
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.02)
                
        # Write batch to database
        try:
            loop = asyncio.get_running_loop()
            saved_count = await loop.run_in_executor(
                None,
                lambda: save_reviews_batch(batch)
            )
            stats["db_batches"] += 1
            for r in batch[:saved_count]:
                src = r["source"]
                stats["saved"][src] = stats["saved"].get(src, 0) + 1
        except Exception as dbe:
            logger.error(f"Failed to save batch to database: {dbe}")
            
        for _ in range(len(batch)):
            db_queue.task_done()
            
    logger.info("Database Writer Worker finished.")

# ---------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------

async def get_database_count() -> int:
    try:
        with get_db_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    except Exception as e:
        logger.error(f"Error getting DB count: {e}")
        return 0

async def get_existing_ids() -> set:
    """Returns a set of all review IDs currently in the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM reviews")
            return {row[0] for row in cursor.fetchall()}
    except Exception as e:
        logger.error(f"Error getting existing IDs: {e}")
        return set()

async def main():
    logger.info("Starting concurrent production-grade ingestion refactor...")
    init_db()
    
    stats["start_time"] = time.time()
    pipeline = TextPipeline()
    
    # Load existing IDs to skip reprocessing
    existing_ids = await get_existing_ids()
    logger.info(f"Loaded {len(existing_ids)} existing review IDs from database.")
    
    # 1. Start background workers
    num_preprocessors = 4
    preprocessor_tasks = [
        asyncio.create_task(preprocessing_worker(i, pipeline, existing_ids)) 
        for i in range(num_preprocessors)
    ]
    translation_task = asyncio.create_task(batch_translation_worker())
    db_writer_task = asyncio.create_task(db_writer_worker())
    
    # 2. Start all scraping workers concurrently
    logger.info("Spawning all ingestion workers concurrently...")
    scrapers = [
        google_play_worker(),
        apple_worker(),
        reddit_worker(),
        forum_worker(),
        youtube_worker()
    ]
    await asyncio.gather(*scrapers)
    logger.info("All ingestion workers completed scraping. Waiting for queue to clear...")
    
    # 3. Stop preprocessing workers
    for _ in range(num_preprocessors):
        await raw_queue.put(None)
    await asyncio.gather(*preprocessor_tasks)
    
    # 4. Stop translation worker
    await translation_queue.put(None)
    await translation_task
    
    # 5. Stop db writer worker
    await db_queue.put(None)
    await db_writer_task
    
    stats["end_time"] = time.time()
    total_runtime = stats["end_time"] - stats["start_time"]
    
    # Write execution stats to JSON file
    import json
    stats_data = {
        "total_runtime": total_runtime,
        "total_scraped": sum(stats["scraped"].values()),
        "total_saved": sum(stats["saved"].values()),
        "scraped_by_source": stats["scraped"],
        "saved_by_source": stats["saved"],
        "rejected_lang": stats["rejected_lang"],
        "rejected_dup": stats["rejected_dup"],
        "rejected_short": stats["rejected_short"],
        "translation_batches": stats["translation_calls"],
        "translated_count": stats["translated_count"],
        "db_batches": stats["db_batches"]
    }
    try:
        stats_file_path = project_root / "backend" / "scripts" / "ingestion_stats.json"
        with open(stats_file_path, "w") as f:
            json.dump(stats_data, f, indent=4)
        logger.info(f"Successfully wrote execution stats to {stats_file_path}")
    except Exception as se:
        logger.error(f"Failed to write execution stats: {se}")
        
    # Final Summary
    final_count = await get_database_count()
    logger.info("==================================================")
    logger.info("Ingestion Refactor Run Summary")
    logger.info("==================================================")
    logger.info(f"Total Runtime: {total_runtime:.2f} seconds")
    logger.info(f"Total Scraped: {sum(stats['scraped'].values())}")
    logger.info(f"Total Saved in this run: {sum(stats['saved'].values())}")
    logger.info(f"Total Reviews in DB: {final_count}")
    logger.info(f"Scraped per source: {stats['scraped']}")
    logger.info(f"Saved per source in this run: {stats['saved']}")
    logger.info(f"Rejected: Lang={stats['rejected_lang']}, Dup={stats['rejected_dup']}, Short={stats['rejected_short']}")
    logger.info(f"Translation batches: {stats['translation_calls']}, Translated count: {stats['translated_count']}")
    logger.info(f"DB batches: {stats['db_batches']}")
    logger.info("==================================================")
    
    print(f"\n✅ SUCCESS: Ingestion pipeline finished. Total reviews in database: {final_count}")

if __name__ == "__main__":
    asyncio.run(main())
