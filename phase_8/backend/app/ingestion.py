import asyncio
import time
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.app.config import (
    PLAY_STORE_PACKAGE,
    APP_STORE_ID,
    COUNTRY_IN,
    YOUTUBE_API_KEY,
    APIFY_API_TOKEN,
    APIFY_API_TOKENS,
    TARGET_REDDIT_POSTS,
    TARGET_FORUM_POSTS,
    TARGET_YOUTUBE_COMMENTS
)
# Global list to track active Apify runs for graceful cleanup on termination
active_apify_runs = []

class BaseScraper:
    def _generate_id(self, source: str, text: str, timestamp_str: str) -> str:
        """Generates a deterministic SHA-256 hash for the review to avoid duplicates."""
        hasher = hashlib.sha256()
        hasher.update(f"{source}:{text}:{timestamp_str}".encode('utf-8'))
        return hasher.hexdigest()

    def _parse_iso_date(self, date_val: Any) -> str:
        """Helper to parse various date formats into ISO 8601 string."""
        if isinstance(date_val, datetime):
            if date_val.tzinfo is None:
                date_val = date_val.replace(tzinfo=timezone.utc)
            return date_val.isoformat()
        try:
            # Try parsing string
            dt = datetime.fromisoformat(str(date_val).replace('Z', '+00:00'))
            return dt.isoformat()
        except ValueError:
            return datetime.now(timezone.utc).isoformat()


class PlayStoreScraper(BaseScraper):
    """Scrapes reviews from Google Play Store for Spotify and streams them to a queue."""
    async def scrape(self, queue: asyncio.Queue, limit: int = 100) -> None:
        logger.info(f"Scraping Google Play Store reviews (limit={limit})...")
        try:
            from google_play_scraper import reviews, Sort
            
            # Since google-play-scraper is synchronous, run it in an executor
            loop = asyncio.get_running_loop()
            result, _ = await loop.run_in_executor(
                None,
                lambda: reviews(
                    PLAY_STORE_PACKAGE,
                    lang='en',
                    country=COUNTRY_IN,
                    sort=Sort.NEWEST,
                    count=limit
                )
            )
            
            count = 0
            for r in result:
                pub_date = self._parse_iso_date(r.get('at'))
                raw_text = r.get('content', '')
                review = {
                    "id": r.get('reviewId') or self._generate_id("google_play", raw_text, pub_date),
                    "raw_text": raw_text,
                    "rating": r.get('score'),
                    "source": "google_play",
                    "country": COUNTRY_IN,
                    "published_at": pub_date
                }
                await queue.put(review)
                count += 1
            logger.info(f"Successfully scraped and streamed {count} reviews from Google Play Store.")
        except Exception as e:
            logger.error(f"Error scraping Google Play Store: {e}")


class AppStoreScraper(BaseScraper):
    """Scrapes reviews from Apple App Store for Spotify using Apify and streams them."""
    async def scrape(self, queue: asyncio.Queue, limit: int = 100) -> None:
        logger.info(f"Scraping Apple App Store reviews via Apify (limit={limit})...")
        if not APIFY_API_TOKEN:
            logger.warning("APIFY_API_TOKEN not found in environment. Skipping App Store scraping.")
            return
            
        try:
            from apify_client import ApifyClient
            client = ApifyClient(APIFY_API_TOKEN)
            
            run_input = {
                "appId": str(APP_STORE_ID),
                "country": COUNTRY_IN,
                "limit": limit
            }
            
            loop = asyncio.get_running_loop()
            
            # Start the actor asynchronously (prevents log streaming thread timeout)
            logger.info("Starting Apify App Store actor...")
            run = await loop.run_in_executor(
                None,
                lambda: client.actor("automation-lab/apple-app-store-reviews-scraper").start(run_input=run_input)
            )
            run_id = run["id"] if isinstance(run, dict) else run.id
            active_apify_runs.append((client, run_id))
            
            # Poll for completion (max 60 seconds)
            dataset_items = []
            poll_start = time.time()
            completed = False
            while time.time() - poll_start < 60:
                run_info = await loop.run_in_executor(None, lambda: client.run(run_id).get())
                if isinstance(run_info, dict):
                    status = run_info.get("status")
                    default_dataset_id = run_info.get("defaultDatasetId") or run_info.get("default_dataset_id")
                else:
                    status = getattr(run_info, "status", None)
                    default_dataset_id = getattr(run_info, "default_dataset_id", None) or getattr(run_info, "defaultDatasetId", None)
                
                logger.info(f"Apify App Store actor status: {status}")
                if status == "SUCCEEDED":
                    dataset = await loop.run_in_executor(None, lambda: client.dataset(default_dataset_id).list_items())
                    dataset_items = getattr(dataset, "items", []) if not isinstance(dataset, dict) else dataset.get("items", [])
                    completed = True
                    break
                elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                    break
                await asyncio.sleep(2)
            
            # If not completed, abort the run to save Apify credits
            if not completed:
                logger.warning(f"Apify App Store actor did not complete in time. Aborting run {run_id}...")
                await loop.run_in_executor(None, lambda: client.run(run_id).abort())
            
            logger.info(f"Apify App Store Scraper finished. Retrieved {len(dataset_items)} items. Streaming to queue...")
            
            count = 0
            for item in dataset_items:
                title = item.get("title", "")
                review_text = item.get("review", "")
                full_text = f"{title}\n{review_text}".strip()
                if not full_text:
                    continue
                    
                pub_date = self._parse_iso_date(item.get("date"))
                review_id = item.get("id") or self._generate_id("app_store", full_text, pub_date)
                
                review = {
                    "id": review_id,
                    "raw_text": full_text,
                    "rating": item.get("rating"),
                    "source": "app_store",
                    "country": COUNTRY_IN,
                    "published_at": pub_date
                }
                await queue.put(review)
                count += 1
            logger.info(f"Successfully processed and streamed {count} reviews from Apple App Store.")
        except Exception as e:
            logger.error(f"Error scraping Apple App Store via Apify: {e}")


class SpotifyForumsScraper(BaseScraper):
    """Scrapes Spotify Community Forums using HTTPX + BeautifulSoup and streams them."""
    async def scrape(self, queue: asyncio.Queue, query: str = "recommendation", limit: int = TARGET_FORUM_POSTS) -> None:
        logger.info(f"Scraping Spotify Community Forums for query '{query}' (limit={limit})...")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            count = 0
            page = 1
            max_pages = max(1, (limit // 15) + 2) # Est. 15 items per page
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                while count < limit and page <= max_pages:
                    url = f"https://community.spotify.com/t5/forums/searchpage/tab/message?q={query}&sort_by=-topicPostDate&page={page}"
                    logger.info(f"Scraping Spotify Forums page {page} for query '{query}'...")
                    response = await client.get(url, headers=headers)
                    if response.status_code != 200:
                        logger.warning(f"Forums returned status code {response.status_code} on page {page}")
                        break
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    items = soup.select(".lia-message-view-message-search-item, .MessageView")
                    if not items:
                        logger.info(f"No more forum posts found on page {page}. Stopping.")
                        break
                        
                    for item in items:
                        if count >= limit:
                            break
                        title_el = item.select_one(".message-subject, .lia-message-subject, a.page-link")
                        body_el = item.select_one(".lia-message-body-content, .lia-message-body")
                        date_el = item.select_one(".lia-message-post-date")
                        
                        title = title_el.text.strip() if title_el else ""
                        body = body_el.text.strip() if body_el else ""
                        full_text = f"{title}\n{body}".strip()
                        
                        if not full_text:
                            continue
                            
                        pub_date_str = date_el.text.strip() if date_el else datetime.now(timezone.utc).isoformat()
                        pub_date = self._parse_iso_date(pub_date_str)
                        
                        review = {
                            "id": self._generate_id("forum", full_text, pub_date),
                            "raw_text": full_text,
                            "rating": None,
                            "source": "spotify_community",
                            "country": "in",
                            "published_at": pub_date
                        }
                        await queue.put(review)
                        count += 1
                        
                    page += 1
            logger.info(f"Successfully scraped and streamed {count} posts from Spotify Forums for query '{query}'.")
        except Exception as e:
            logger.error(f"Error scraping Spotify Forums: {e}")


class YouTubeCommentsScraper(BaseScraper):
    """Scrapes comments from Spotify-related YouTube videos and streams them."""
    async def scrape(self, queue: asyncio.Queue, video_ids: List[str], limit: int = TARGET_YOUTUBE_COMMENTS) -> None:
        if not YOUTUBE_API_KEY:
            logger.warning("YOUTUBE_API_KEY not found in environment. Skipping YouTube scraping.")
            return
            
        logger.info(f"Scraping YouTube comments for {len(video_ids)} videos...")
        try:
            from googleapiclient.discovery import build
            loop = asyncio.get_running_loop()
            
            # Read date range from environment variables
            from_date_str = os.environ.get("FROM_DATE")
            to_date_str = os.environ.get("TO_DATE")
            
            from_date = None
            to_date = None
            
            if from_date_str:
                if len(from_date_str) == 10:
                    from_date = datetime.fromisoformat(from_date_str).replace(tzinfo=timezone.utc)
                else:
                    from_date = datetime.fromisoformat(from_date_str.replace("Z", "+00:00"))
            else:
                # Default to 6 months ago
                from_date = datetime.now(timezone.utc) - timedelta(days=180)
                
            if to_date_str:
                if len(to_date_str) == 10:
                    to_date = datetime.fromisoformat(to_date_str).replace(tzinfo=timezone.utc)
                else:
                    to_date = datetime.fromisoformat(to_date_str.replace("Z", "+00:00"))
            else:
                to_date = datetime.now(timezone.utc)
            
            def _fetch_comments_for_video(vid: str):
                youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
                results = []
                next_page_token = None
                try:
                    while len(results) < limit:
                        request = youtube.commentThreads().list(
                            part="snippet",
                            videoId=vid,
                            maxResults=min(limit - len(results), 100),
                            textFormat="plainText",
                            order="time", # Reverse chronological order (newest first)
                            pageToken=next_page_token
                        )
                        response = request.execute()
                        
                        items = response.get('items', [])
                        if not items:
                            break
                            
                        for item in items:
                            comment = item['snippet']['topLevelComment']['snippet']
                            text = comment['textDisplay']
                            pub_date_str = comment['publishedAt']
                            comment_id = item['id']
                            
                            # Parse comment publication date
                            pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                            
                            # Apply comment-date windowing
                            if to_date and pub_date > to_date:
                                # Too new, skip and keep going back in time
                                continue
                            if from_date and pub_date < from_date:
                                # Too old, stop paginating this video
                                next_page_token = None
                                break
                                
                            results.append({
                                "id": comment_id,
                                "raw_text": text,
                                "rating": None,
                                "source": "youtube",
                                "country": "in",
                                "published_at": pub_date_str
                            })
                            
                        if not next_page_token:
                            break
                        next_page_token = response.get('nextPageToken')
                except Exception as ve:
                    logger.error(f"Error fetching comments for video {vid}: {ve}")
                return results

            for vid in video_ids:
                comments = await loop.run_in_executor(None, lambda: _fetch_comments_for_video(vid))
                for c in comments:
                    await queue.put(c)
                if comments:
                    logger.info(f"Streamed {len(comments)} comments for video {vid}.")
            logger.info("YouTube Comments scraping and streaming completed.")
        except Exception as e:
            logger.error(f"Error scraping YouTube comments: {e}")


class RedditScraper(BaseScraper):
    """Scrapes Spotify-related subreddits and streams them to a queue."""
    async def scrape(self, queue: asyncio.Queue, subreddits: List[str], limit: int = TARGET_REDDIT_POSTS) -> None:
        logger.info(f"Scraping subreddits {subreddits} in batches of 200 (total limit={limit})...")
        
        # Method 1: Apify Reddit Scraper
        if APIFY_API_TOKEN or APIFY_API_TOKENS:
            try:
                # Partition subreddits into up to 3 chunks for parallel execution
                partitions = [[] for _ in range(3)]
                for idx, sub in enumerate(subreddits):
                    partitions[idx % 3].append(sub)
                partitions = [p for p in partitions if p]
                
                n_parts = len(partitions)
                limit_per_part = limit // n_parts
                limits = [limit_per_part] * n_parts
                limits[-1] += limit % n_parts
                
                async def scrape_partition(part_idx: int, subs: List[str], limit_part: int, token: str) -> None:
                    if not token:
                        logger.warning(f"[Partition {part_idx}] No Apify token available for {subs}. Skipping.")
                        return
                    
                    from apify_client import ApifyClient
                    client = ApifyClient(token)
                    loop = asyncio.get_running_loop()
                    
                    batch_size = 200
                    total_fetched = 0
                    
                    while total_fetched < limit_part:
                        current_batch_limit = min(batch_size, limit_part - total_fetched)
                        logger.info(f"[Partition {part_idx}] Starting batch fetch: {current_batch_limit} reviews for {subs} (Fetched: {total_fetched}/{limit_part})")
                        
                        run_input = {
                            "startUrls": [f"https://www.reddit.com/r/{sub}" for sub in subs],
                            "maxItems": current_batch_limit,
                            "scrollTimeout": 5, # Optimized timeout
                            "includeComments": True,
                            "maxComments": 5 # Optimized comment depth
                        }
                        
                        actors = ["automation-lab/reddit-scraper", "trdfour/reddit-scraper", "microworlds/reddit-scraper"]
                        run = None
                        active_actor = None
                        for actor_id in actors:
                            try:
                                logger.info(f"[Partition {part_idx}] Trying Apify Reddit Scraper actor: {actor_id}...")
                                run = await loop.run_in_executor(
                                    None, 
                                    lambda aid=actor_id: client.actor(aid).start(run_input=run_input)
                                )
                                run_id = run["id"] if isinstance(run, dict) else run.id
                                active_apify_runs.append((client, run_id))
                                logger.info(f"[Partition {part_idx}] Successfully started Apify actor: {actor_id}")
                                active_actor = actor_id
                                break
                            except Exception as ae:
                                logger.warning(f"[Partition {part_idx}] Apify actor {actor_id} failed or not found: {ae}")
                        
                        if not run:
                            logger.error(f"[Partition {part_idx}] All attempted Apify Reddit Scraper actors failed/were not found.")
                            break
                        
                        run_id = run["id"] if isinstance(run, dict) else run.id
                        poll_start = time.time()
                        completed = False
                        
                        last_item_count = 0
                        last_change_time = time.time()
                        
                        while time.time() - poll_start < 3600:
                            run_info = await loop.run_in_executor(None, lambda: client.run(run_id).get())
                            if isinstance(run_info, dict):
                                status = run_info.get("status")
                                default_dataset_id = run_info.get("defaultDatasetId") or run_info.get("default_dataset_id")
                            else:
                                status = getattr(run_info, "status", None)
                                default_dataset_id = getattr(run_info, "default_dataset_id", None) or getattr(run_info, "defaultDatasetId", None)
                            
                            try:
                                dataset_info = await loop.run_in_executor(
                                    None, 
                                    lambda: client.dataset(default_dataset_id).get()
                                )
                                if isinstance(dataset_info, dict):
                                    item_count = dataset_info.get("itemCount", 0)
                                else:
                                    item_count = getattr(dataset_info, "item_count", 0) or getattr(dataset_info, "itemCount", 0)
                            except Exception:
                                item_count = 0
                                
                            logger.info(f"[Partition {part_idx}] Apify Reddit actor ({active_actor}) status: {status} | Items scraped: {item_count}")
                            
                            if item_count >= current_batch_limit:
                                logger.info(f"[Partition {part_idx}] Reached required batch limit of {current_batch_limit} items. Aborting Apify run to save credits...")
                                try:
                                    await loop.run_in_executor(None, lambda: client.run(run_id).abort())
                                except Exception:
                                    pass
                                completed = True
                                break
                                
                            if status == "SUCCEEDED":
                                completed = True
                                break
                            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                                break
                                
                            # Check for stagnation
                            now = time.time()
                            if item_count > last_item_count:
                                last_item_count = item_count
                                last_change_time = now
                            else:
                                if item_count == 0 and (now - poll_start) > 90:
                                    logger.warning(f"[Partition {part_idx}] Apify Reddit actor stuck in startup for 90s. Aborting.")
                                    break
                                elif item_count > 0 and (now - last_change_time) > 60:
                                    logger.warning(f"[Partition {part_idx}] Apify Reddit actor item count stagnated at {item_count} for 60s. Aborting.")
                                    break
                                    
                            await asyncio.sleep(5) # Faster polling
                            
                        if not completed:
                            logger.warning(f"[Partition {part_idx}] Apify Reddit actor did not complete or stagnated. Aborting run {run_id}...")
                            try:
                                await loop.run_in_executor(None, lambda: client.run(run_id).abort())
                            except Exception:
                                pass
                        
                        # Fetch dataset items
                        try:
                            dataset_items_page = await loop.run_in_executor(None, lambda: client.dataset(default_dataset_id).list_items())
                            dataset_items = getattr(dataset_items_page, "items", []) if not isinstance(dataset_items_page, dict) else dataset_items_page.get("items", [])
                        except Exception as de:
                            logger.error(f"[Partition {part_idx}] Error listing dataset items: {de}")
                            dataset_items = []
                        
                        logger.info(f"[Partition {part_idx}] Apify Reddit Scraper returned {len(dataset_items)} items for this batch. Streaming to queue...")
                        
                        if not dataset_items:
                            logger.warning(f"[Partition {part_idx}] No items returned in this batch. Breaking batch loop.")
                            break
                            
                        batch_fetched_count = 0
                        for item in dataset_items:
                            item_type = item.get("type") or ""
                            is_comment = item_type == "comment" or "comment" in item.get("url", "")
                            
                            if is_comment:
                                text = item.get("body", "").strip()
                                if not text:
                                    continue
                                pub_date = self._parse_iso_date(item.get("createdAt") or item.get("created"))
                                post_id = item.get("id") or self._generate_id("reddit_comment", text, pub_date)
                                review = {
                                    "id": post_id,
                                    "raw_text": text,
                                    "rating": None,
                                    "source": "reddit",
                                    "country": "in",
                                    "published_at": pub_date
                                }
                                await queue.put(review)
                                batch_fetched_count += 1
                            else:
                                title = item.get("title", "")
                                body = item.get("body", "") or item.get("selfText", "")
                                full_text = f"{title}\n{body}".strip()
                                
                                if full_text:
                                    pub_date = self._parse_iso_date(item.get("createdAt") or item.get("created"))
                                    post_id = item.get("id") or self._generate_id("reddit", full_text, pub_date)
                                    review = {
                                        "id": post_id,
                                        "raw_text": full_text,
                                        "rating": None,
                                        "source": "reddit",
                                        "country": "in",
                                        "published_at": pub_date
                                    }
                                    await queue.put(review)
                                    batch_fetched_count += 1
                                    
                                comments = item.get("comments", [])
                                if isinstance(comments, list):
                                    for c in comments:
                                        if isinstance(c, dict):
                                            c_text = c.get("body", "").strip()
                                            if c_text:
                                                c_date = self._parse_iso_date(c.get("createdAt") or c.get("created"))
                                                comment_review = {
                                                    "id": c.get("id") or self._generate_id("reddit_comment", c_text, c_date),
                                                    "raw_text": c_text,
                                                    "rating": None,
                                                    "source": "reddit",
                                                    "country": "in",
                                                    "published_at": c_date
                                                }
                                                await queue.put(comment_review)
                                                batch_fetched_count += 1
                                                
                        total_fetched += batch_fetched_count
                        logger.info(f"[Partition {part_idx}] Completed batch. Scraped in this batch: {batch_fetched_count}. Total progress: {total_fetched}/{limit_part}")
                        
                        if batch_fetched_count == 0:
                            break
                
                # Launch all partition scrapers in parallel
                tasks = []
                for p_idx, partition in enumerate(partitions):
                    # Assign a key from APIFY_API_TOKENS (or fallback to APIFY_API_TOKEN)
                    token = APIFY_API_TOKENS[p_idx % len(APIFY_API_TOKENS)] if APIFY_API_TOKENS else APIFY_API_TOKEN
                    tasks.append(scrape_partition(p_idx, partition, limits[p_idx], token))
                
                await asyncio.gather(*tasks)
                return
            except Exception as e:
                logger.error(f"Apify Reddit Scraper failed: {e}. Falling back to Agent-Reach CLI...")

        # Method 2: Fallback to Agent-Reach CLI (OpenCLI or rdt-cli)
        opencli_path = shutil.which("opencli")
        rdt_path = shutil.which("rdt")
        
        if opencli_path:
            logger.info("Falling back to Agent-Reach: Using OpenCLI...")
            try:
                count = 0
                for sub in subreddits:
                    cmd = [opencli_path, "reddit", "subreddit", sub, "hot", "--limit", str(limit // len(subreddits) + 1), "--json"]
                    loop = asyncio.get_running_loop()
                    proc_result = await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(cmd, capture_output=True, text=True, errors="replace")
                    )
                    
                    if proc_result.returncode == 0 and proc_result.stdout.strip():
                        data = json.loads(proc_result.stdout)
                        if isinstance(data, list):
                            for post in data:
                                title = post.get("title", "")
                                body = post.get("selftext", "") or post.get("body", "")
                                full_text = f"{title}\n{body}".strip()
                                pub_date = self._parse_iso_date(post.get("created_utc") or post.get("created"))
                                review = {
                                    "id": post.get("id") or self._generate_id("reddit", full_text, pub_date),
                                    "raw_text": full_text,
                                    "rating": None,
                                    "source": "reddit",
                                    "country": "in",
                                    "published_at": pub_date
                                }
                                await queue.put(review)
                                count += 1
                logger.info(f"Successfully scraped and streamed {count} posts from Reddit via OpenCLI.")
                return
            except Exception as e:
                logger.error(f"OpenCLI fallback failed: {e}")

        if rdt_path:
            logger.info("Falling back to Agent-Reach: Using rdt-cli...")
            try:
                count = 0
                for sub in subreddits:
                    cmd = [rdt_path, "subreddit", sub, "--limit", str(limit // len(subreddits) + 1), "--json"]
                    loop = asyncio.get_running_loop()
                    proc_result = await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(cmd, capture_output=True, text=True, errors="replace")
                    )
                    
                    if proc_result.returncode == 0 and proc_result.stdout.strip():
                        data = json.loads(proc_result.stdout)
                        if isinstance(data, dict) and "posts" in data:
                            posts = data["posts"]
                        elif isinstance(data, list):
                            posts = data
                        else:
                            posts = []
                            
                        for post in posts:
                            title = post.get("title", "")
                            body = post.get("selftext", "") or post.get("body", "")
                            full_text = f"{title}\n{body}".strip()
                            pub_date = self._parse_iso_date(post.get("created_utc") or post.get("created"))
                            review = {
                                "id": post.get("id") or self._generate_id("reddit", full_text, pub_date),
                                "raw_text": full_text,
                                "rating": None,
                                "source": "reddit",
                                "country": "in",
                                "published_at": pub_date
                            }
                            await queue.put(review)
                            count += 1
                logger.info(f"Successfully scraped and streamed {count} posts from Reddit via rdt-cli.")
                return
            except Exception as e:
                logger.error(f"rdt-cli fallback failed: {e}")
                
        logger.warning("No working Reddit scraping backend available (Apify, OpenCLI, and rdt-cli all failed/missing).")
