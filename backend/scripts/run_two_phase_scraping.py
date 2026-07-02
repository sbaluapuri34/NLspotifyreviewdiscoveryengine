import os
import sys
import json
import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.database import get_db_connection, init_db
from backend.app.pipeline import TextPipeline
from backend.app.ingestion import (
    RedditScraper,
    SpotifyForumsScraper,
    YouTubeCommentsScraper,
    PlayStoreScraper,
    AppStoreScraper,
    active_apify_runs
)
from backend.app.config import APIFY_API_TOKEN, YOUTUBE_API_KEY

async def main():
    logger.info("Starting Two-Phase Ingestion & Scraping Pipeline...")
    start_time = time.time()
    
    # Ensure database is initialized and migrated before scraping
    init_db()
    
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

    priority_keywords = None
    if theme_config:
        priority_keywords = theme_config.get("level_0_config", {}).get("priority_routing_keywords")

    pipeline = TextPipeline(priority_keywords=priority_keywords)
    queue = asyncio.Queue()
    
    # Read scraping limits from environment variables (passed by FastAPI)
    limit_gp = int(os.environ.get("LIMIT_GOOGLE_PLAY", "100"))
    limit_reddit = int(os.environ.get("LIMIT_REDDIT", "100"))
    limit_forums = int(os.environ.get("LIMIT_SPOTIFY_COMMUNITY", "50"))
    limit_youtube = int(os.environ.get("LIMIT_YOUTUBE", "50"))
    limit_app_store = int(os.environ.get("LIMIT_APP_STORE", "50"))
    
    logger.info(f"Active Scraping Limits: GP={limit_gp}, RD={limit_reddit}, SC={limit_forums}, YT={limit_youtube}, AS={limit_app_store}")
    
    # ---------------------------------------------------------
    # PHASE 1: Random/Baseline Ingestion (Non-Targeted)
    # ---------------------------------------------------------
    logger.info("=== PHASE 1: Running Random/Baseline Ingestion ===")
    
    tasks = []
    
    # 1. Google Play Store
    if limit_gp > 0:
        logger.info(f"Preparing Google Play Store scraper (limit={limit_gp})...")
        play_scraper = PlayStoreScraper()
        gp_lang = os.environ.get("PLAY_STORE_LANG") or 'en'
        gp_country = os.environ.get("PLAY_STORE_COUNTRY") or 'in'
        tasks.append(play_scraper.scrape(queue, limit=limit_gp, lang=gp_lang, country=gp_country))
    
    # 2. Reddit (Hot/New feed - no query)
    if limit_reddit > 0:
        logger.info(f"Preparing Reddit scraper (limit={limit_reddit})...")
        reddit_scraper = RedditScraper()
        subs = theme_config.get("scraping_elements", {}).get("reddit_subreddits") if theme_config else ["spotify", "truespotify", "musicsuggestions", "spotifyplaylist"]
        tasks.append(reddit_scraper.scrape(queue, subreddits=subs, limit=limit_reddit))
    
    # 3. Spotify Forums
    if limit_forums > 0:
        logger.info(f"Preparing Spotify Forums scraper (limit={limit_forums})...")
        forum_scraper = SpotifyForumsScraper()
        query_forum = theme_config.get("scraping_elements", {}).get("spotify_community_keywords", ["spotify"])[0] if theme_config else "spotify"
        tasks.append(forum_scraper.scrape(queue, query=query_forum, limit=limit_forums))
    
    # 4. YouTube Comments
    if limit_youtube > 0:
        logger.info(f"Preparing YouTube Comments scraper (limit={limit_youtube})...")
        yt_scraper = YouTubeCommentsScraper()
        if theme_config:
            general_video_ids = []
            if YOUTUBE_API_KEY:
                try:
                    from googleapiclient.discovery import build
                    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
                    kw = theme_config.get("scraping_elements", {}).get("youtube_search_queries", ["spotify"])[0]
                    req = youtube.search().list(q=kw, part="snippet", type="video", maxResults=1)
                    res = req.execute()
                    for item in res.get("items", []):
                        general_video_ids.append(item["id"]["videoId"])
                except Exception as e:
                    logger.warning(f"YouTube search failed in phase 1: {e}")
            if not general_video_ids:
                general_video_ids = ["ozF85QOz6Dg"]
        else:
            general_video_ids = ["ozF85QOz6Dg", "KMfVciFsc38"] # General reviews
        tasks.append(yt_scraper.scrape(queue, video_ids=general_video_ids, limit=limit_youtube))
            
    # 5. App Store Reviews (via Apify)
    if limit_app_store > 0:
        logger.info(f"Preparing Apple App Store scraper (limit={limit_app_store})...")
        app_store_scraper = AppStoreScraper()
        tasks.append(app_store_scraper.scrape(queue, limit=limit_app_store))
        
    if tasks:
        logger.info(f"Launching {len(tasks)} scrapers simultaneously in parallel...")
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("All concurrent scrapers completed.")
    
    # ---------------------------------------------------------
    # PHASE 2: Targeted Ingestion (Discovery & Algorithm Focused)
    # ---------------------------------------------------------
    disable_keywords = os.environ.get("DISABLE_KEYWORDS", "false").lower() == "true"
    if disable_keywords:
        logger.info("=== PHASE 2: Skipped (Disable Keyword Filtering is active) ===")
    else:
        logger.info("=== PHASE 2: Running Targeted Ingestion ===")
        if theme_config:
            target_keywords = list(set(
                theme_config.get("scraping_elements", {}).get("reddit_search_queries", []) +
                theme_config.get("scraping_elements", {}).get("youtube_search_queries", []) +
                theme_config.get("scraping_elements", {}).get("spotify_community_keywords", [])
            ))
        else:
            target_keywords = [
                "discover weekly", 
                "smart shuffle", 
                "rap caviar", 
                "rapcaviar", 
                "song repetition", 
                "algorithm", 
                "autoplay", 
                "recommendation", 
                "spotify issues",
                "spotify song recommendation",
                "spotify music listening",
                "spotify problems",
                "spotify music suggestion",
                "spotify playlist"
            ]
    
    # 1. Reddit Targeted Search
    if not disable_keywords and limit_reddit > 0 and APIFY_API_TOKEN:
        try:
            from apify_client import ApifyClient
            client = ApifyClient(APIFY_API_TOKEN)
            
            # Construct search URLs for targeted keywords
            search_urls = []
            subs = theme_config.get("scraping_elements", {}).get("reddit_subreddits") if theme_config else ["spotify", "truespotify", "musicmarketing"]
            for sub in subs:
                for kw in target_keywords:
                    query_encoded = kw.replace(" ", "+")
                    search_urls.append(f"https://www.reddit.com/r/{sub}/search/?q={query_encoded}&restrict_sr=1&sort=new")
            
            logger.info(f"Triggering Apify Reddit Scraper for {len(search_urls)} targeted search URLs...")
            run_input = {
                "startUrls": search_urls[:10], # Limit to first 10
                "maxItems": max(20, limit_reddit),
                "scrollTimeout": 10,
                "includeComments": True,
                "maxComments": 5
            }
            
            loop = asyncio.get_running_loop()
            
            # Start the actor asynchronously (prevents log streaming thread timeout)
            logger.info("Starting Apify Reddit search actor...")
            run = await loop.run_in_executor(
                None, 
                lambda: client.actor("trdfour/reddit-scraper").start(run_input=run_input)
            )
            run_id = run["id"]
            active_apify_runs.append((client, run_id))
            
            # Set Apify timeout to 1 hour always
            timeout_seconds = 3600
            logger.info(f"Setting Apify Reddit scraper polling timeout to {timeout_seconds} seconds (1 hour)...")
            
            # Poll for completion
            dataset_items = []
            poll_start = time.time()
            completed = False
            while time.time() - poll_start < timeout_seconds:
                run_info = await loop.run_in_executor(None, lambda: client.run(run_id).get())
                status = run_info.get("status")
                
                # Fetch current item count from dataset
                try:
                    dataset_info = await loop.run_in_executor(
                        None, 
                        lambda: client.dataset(run_info["defaultDatasetId"]).get()
                    )
                    item_count = dataset_info.get("itemCount", 0)
                except Exception:
                    item_count = 0
                
                logger.info(f"Apify Reddit actor status: {status} | Items scraped: {item_count}")
                
                if item_count >= limit_reddit:
                    logger.info(f"Reached required limit of {limit_reddit} items. Aborting Apify run to save credits...")
                    await loop.run_in_executor(None, lambda: client.run(run_id).abort())
                    dataset = await loop.run_in_executor(None, lambda: client.dataset(run_info["defaultDatasetId"]).list_items())
                    dataset_items = dataset.items
                    completed = True
                    break
                
                if status == "SUCCEEDED":
                    dataset = await loop.run_in_executor(None, lambda: client.dataset(run_info["defaultDatasetId"]).list_items())
                    dataset_items = dataset.items
                    completed = True
                    break
                elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                    break
                await asyncio.sleep(10)
            
            # If not completed, abort the run to save Apify credits
            if not completed:
                logger.warning(f"Apify Reddit actor did not complete in time. Aborting run {run_id}...")
                await loop.run_in_executor(None, lambda: client.run(run_id).abort())
            
            logger.info(f"Apify Reddit Scraper finished. Retrieved {len(dataset_items)} targeted items.")
            
            reddit_scraper = RedditScraper()
            for item in dataset_items:
                text = item.get("body", "").strip() or item.get("selfText", "").strip() or item.get("title", "").strip()
                if not text:
                    continue
                pub_date = reddit_scraper._parse_iso_date(item.get("createdAt") or item.get("created"))
                review = {
                    "id": item.get("id") or reddit_scraper._generate_id("reddit_targeted", text, pub_date),
                    "raw_text": text,
                    "rating": None,
                    "source": "reddit",
                    "country": "in",
                    "published_at": pub_date
                }
                await queue.put(review)
        except Exception as e:
            logger.error(f"Targeted Reddit scrape failed: {e}")
            
    # 2. Spotify Forums Targeted Search
    if not disable_keywords and limit_forums > 0:
        try:
            forum_scraper = SpotifyForumsScraper()
            for kw in target_keywords[:3]: # Run search for top 3 keywords
                await forum_scraper.scrape(queue, query=kw, limit=min(10, limit_forums))
        except Exception as e:
            logger.error(f"Targeted Spotify Forums scrape failed: {e}")
        
    # 3. YouTube Targeted Comments
    if not disable_keywords and limit_youtube > 0 and YOUTUBE_API_KEY:
        try:
            from googleapiclient.discovery import build
            youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
            
            video_ids = []
            # We search for both popular (relevance) and recent (date) videos for each keyword
            yt_queries = theme_config.get("scraping_elements", {}).get("youtube_search_queries") if theme_config else [
                "Spotify Discover Weekly", 
                "Spotify Smart Shuffle", 
                "Spotify Algorithm",
                "Spotify song recommendation",
                "Spotify music listening",
                "Spotify problems",
                "Spotify Music suggestion",
                "Spotify playlist",
                "Spotify issues"
            ]
            for kw in yt_queries:
                # 1. Search by relevance (Popularity & Relevance)
                try:
                    req_rel = youtube.search().list(
                        q=kw,
                        part="snippet",
                        type="video",
                        maxResults=2,
                        order="relevance"
                    )
                    res_rel = req_rel.execute()
                    for item in res_rel.get("items", []):
                        vid = item["id"]["videoId"]
                        if vid not in video_ids:
                            video_ids.append(vid)
                except Exception as e:
                    logger.warning(f"YouTube relevance search failed for '{kw}': {e}")
                    
                # 2. Search by date (Recency)
                try:
                    req_date = youtube.search().list(
                        q=kw,
                        part="snippet",
                        type="video",
                        maxResults=2,
                        order="date"
                    )
                    res_date = req_date.execute()
                    for item in res_date.get("items", []):
                        vid = item["id"]["videoId"]
                        if vid not in video_ids:
                            video_ids.append(vid)
                except Exception as e:
                    logger.warning(f"YouTube date search failed for '{kw}': {e}")
            
            logger.info(f"Found {len(video_ids)} targeted YouTube videos. Scraping comments...")
            yt_scraper = YouTubeCommentsScraper()
            await yt_scraper.scrape(queue, video_ids=video_ids, limit=min(15, limit_youtube))
        except Exception as e:
            logger.error(f"Targeted YouTube search/scrape failed: {e}")

    # ---------------------------------------------------------
    # PROCESSING & PERSISTENCE (with Date-Range Mismatch Gating)
    # ---------------------------------------------------------
    logger.info("Processing and separating scraped reviews by date range...")
    
    # Read date range from env to verify
    from_date_str = os.environ.get("FROM_DATE")
    to_date_str = os.environ.get("TO_DATE")
    
    from_date = None
    to_date = None
    if from_date_str:
        from_date = datetime.fromisoformat(from_date_str).replace(tzinfo=timezone.utc) if len(from_date_str) == 10 else datetime.fromisoformat(from_date_str.replace("Z", "+00:00"))
    if to_date_str:
        to_date = datetime.fromisoformat(to_date_str).replace(tzinfo=timezone.utc) if len(to_date_str) == 10 else datetime.fromisoformat(to_date_str.replace("Z", "+00:00"))
        
    in_range_reviews = []
    out_of_range_reviews = []
    duplicate_count = 0
    
    # Process reviews from queue
    seen_ids = set()
    while not queue.empty():
        raw_review = await queue.get()
        processed = pipeline.process_review(raw_review)
        
        if processed:
            rid = processed["id"]
            if rid in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(rid)
            
            # Check if within date range
            is_in_range = True
            if processed.get("published_at"):
                try:
                    pub_date = datetime.fromisoformat(processed["published_at"].replace("Z", "+00:00"))
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                    if from_date and pub_date < from_date:
                        is_in_range = False
                    if to_date and pub_date > to_date:
                        is_in_range = False
                except Exception:
                    pass
            
            if is_in_range:
                in_range_reviews.append(processed)
            else:
                out_of_range_reviews.append(processed)
        else:
            duplicate_count += 1

    total_limit = limit_gp + limit_reddit + limit_youtube + limit_forums + limit_app_store
    has_mismatch = (from_date or to_date) and len(in_range_reviews) < total_limit and len(out_of_range_reviews) > 0
    
    theme_slug = theme_config.get("theme_slug") if theme_config else None
    suffix = f"_{theme_slug}" if theme_slug else ""
    status_path = Path(project_root) / "backend" / "scripts" / f"pipeline_status{suffix}.json"
    temp_reviews_path = Path(project_root) / "backend" / "scripts" / f"scraped_reviews_temp{suffix}.json"
    
    if has_mismatch:
        logger.warning(f"Date-range mismatch detected: Found only {len(in_range_reviews)} reviews in range, but {len(out_of_range_reviews)} reviews are out of range. Total requested: {total_limit}.")
        
        # Save temp reviews
        temp_data = {
            "in_range": in_range_reviews,
            "out_of_range": out_of_range_reviews
        }
        with open(temp_reviews_path, "w", encoding="utf-8") as f:
            json.dump(temp_data, f, indent=2)
            
        # Write status file for backend to pause and prompt user
        status_data = {
            "status": "AWAITING_DECISION",
            "in_range_count": len(in_range_reviews),
            "total_count": len(in_range_reviews) + len(out_of_range_reviews),
            "requested_limit": total_limit
        }
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
            
        # Save stats
        stats = {
            "fetched": len(in_range_reviews) + len(out_of_range_reviews) + duplicate_count,
            "saved": len(in_range_reviews), # Default to saving in-range if aborted/fallback
            "filtered": duplicate_count
        }
        stats_path = Path(project_root) / "backend" / "scripts" / f"ingestion_stats{suffix}.json"
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
            
    else:
        # Save directly to database
        logger.info(f"Saving {len(in_range_reviews) + len(out_of_range_reviews)} reviews directly to database...")
        run_id = os.environ.get("RUN_ID", f"run_{int(time.time())}")
        conn = get_db_connection()
        saved_count = 0
        all_reviews = in_range_reviews + out_of_range_reviews
        for processed in all_reviews:
            try:
                conn.execute(
                    """
                    INSERT INTO reviews (id, raw_text, translated_text, rating, source, country, published_at, scraped_at, analysed, last_run_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        raw_text = excluded.raw_text,
                        translated_text = excluded.translated_text,
                        rating = excluded.rating,
                        published_at = excluded.published_at,
                        scraped_at = CURRENT_TIMESTAMP,
                        analysed = 0,
                        last_run_id = excluded.last_run_id
                    """,
                    (
                        processed["id"],
                        processed["raw_text"],
                        processed.get("translated_text"),
                        processed["rating"],
                        processed["source"],
                        processed["country"],
                        processed["published_at"],
                        run_id
                    )
                )
                saved_count += 1
            except Exception as db_err:
                logger.error(f"DB Error: {db_err}")
        conn.commit()
        conn.close()
        
        # Write completed status
        status_data = {
            "status": "COMPLETED",
            "in_range_count": len(in_range_reviews),
            "total_count": len(in_range_reviews) + len(out_of_range_reviews)
        }
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
            
        # Save stats
        stats = {
            "fetched": len(all_reviews) + duplicate_count,
            "saved": saved_count,
            "filtered": duplicate_count
        }
        stats_path = Path(project_root) / "backend" / "scripts" / f"ingestion_stats{suffix}.json"
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
            
    elapsed = time.time() - start_time
    logger.info(f"Ingestion completed. Added/Updated {len(in_range_reviews)} in-range and {len(out_of_range_reviews)} out-of-range reviews.")
    logger.info(f"Two-Phase Ingestion Completed in {time.time() - start_time:.2f} seconds.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        if active_apify_runs:
            import time
            from loguru import logger
            logger.warning(f"Script terminating. Aborting {len(active_apify_runs)} active Apify runs to prevent token exhaustion...")
            for client, run_id in active_apify_runs:
                try:
                    logger.info(f"Aborting Apify run: {run_id}")
                    client.run(run_id).abort()
                except Exception as e:
                    logger.error(f"Failed to abort Apify run {run_id}: {e}")
