import asyncio
import os
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.ingestion import RedditScraper, YouTubeCommentsScraper

async def main():
    print("Verifying provided API credentials...")
    
    # 1. Test Reddit Scraper (Apify)
    reddit = RedditScraper()
    print("Testing Reddit scraper (Apify)...")
    try:
        reddit_results = await reddit.scrape(["truespotify"], limit=2)
        print(f"✅ Reddit Scraper Success! Scraped {len(reddit_results)} posts.")
        if reddit_results:
            print(f"   Sample: {reddit_results[0]['raw_text'][:100]}...")
    except Exception as e:
        print(f"❌ Reddit Scraper Failed: {e}")
        
    # 2. Test YouTube Comments Scraper
    yt = YouTubeCommentsScraper()
    print("\nTesting YouTube Comments scraper...")
    try:
        # Using a well-known video ID (e.g. YouTube official video or popular music video)
        yt_results = await yt.scrape(["dQw4w9WgXcQ"], limit=2)
        print(f"✅ YouTube Scraper Success! Scraped {len(yt_results)} comments.")
        if yt_results:
            print(f"   Sample: {yt_results[0]['raw_text'][:100]}...")
    except Exception as e:
        print(f"❌ YouTube Scraper Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
