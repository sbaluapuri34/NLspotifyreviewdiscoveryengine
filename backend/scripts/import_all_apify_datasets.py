import os
import sys
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger
from apify_client import ApifyClient

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys_path = str(project_root)
if sys_path not in os.sys.path:
    os.sys.path.append(sys_path)

from backend.app.config import DB_PATH
from backend.app.pipeline import TextPipeline

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN") or os.environ.get("APIFY_TOKEN") or ""
DATASET_IDS = ["9MGzkOidq9acifZA2", "l6nTH42i6DdaD98ll", "kQhS4CQPPTj1IWtIb"]

def parse_iso_date(date_str):
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        # Standardize timezone offset for SQLite comparison
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()

def generate_id(source_type, text, date_str):
    import hashlib
    hash_input = f"{source_type}_{text[:50]}_{date_str}"
    return hashlib.md5(hash_input.encode("utf-8")).hexdigest()

async def main():
    logger.info("Starting bulk import of all past Apify datasets...")
    client = ApifyClient(APIFY_TOKEN)
    pipeline = TextPipeline()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    imported_count = 0
    duplicate_count = 0
    filtered_count = 0
    
    # 1. Fetch and process all items from datasets
    for ds_id in DATASET_IDS:
        logger.info(f"Fetching items from dataset {ds_id}...")
        try:
            dataset = client.dataset(ds_id).list_items()
            items = dataset.items
            logger.info(f"Found {len(items)} items in dataset {ds_id}.")
            
            for item in items:
                # Extract text
                text = ""
                if item.get("type") == "comment":
                    text = item.get("body", "").strip()
                else:
                    title = item.get("title", "")
                    body = item.get("body", "") or item.get("selfText", "")
                    text = f"{title}\n{body}".strip()
                
                if not text:
                    continue
                
                pub_date = parse_iso_date(item.get("createdAt") or item.get("created"))
                post_id = item.get("id") or generate_id("reddit", text, pub_date)
                
                raw_review = {
                    "id": post_id,
                    "raw_text": text,
                    "rating": None,
                    "source": "reddit",
                    "country": "in",
                    "published_at": pub_date
                }
                
                # Run through the pipeline (cleaning, translation, LSH deduplication, etc.)
                processed = pipeline.process_review(raw_review)
                if not processed:
                    filtered_count += 1
                    continue
                
                # Save to database
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO reviews (id, raw_text, translated_text, rating, source, country, published_at, scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        processed["id"],
                        processed["raw_text"],
                        processed["translated_text"],
                        processed["rating"],
                        processed["source"],
                        processed["country"],
                        processed["published_at"],
                        datetime.now(timezone.utc).isoformat()
                    ))
                    if cursor.rowcount > 0:
                        imported_count += 1
                    else:
                        duplicate_count += 1
                except Exception as db_err:
                    logger.error(f"Failed to insert review {post_id}: {db_err}")
                    
        except Exception as e:
            logger.error(f"Error processing dataset {ds_id}: {e}")
            
    conn.commit()
    conn.close()
    
    logger.info(f"Import complete! Saved {imported_count} new reviews, ignored {duplicate_count} duplicates, filtered {filtered_count} due to noise/length/language.")
    
    if imported_count > 0:
        logger.info("New reviews imported. Rerunning clustering and LLM analytics...")
        
        # 2. Run Clustering
        logger.info("Step 1: Running Clustering...")
        import subprocess
        subprocess.run([sys.executable, str(project_root / "backend" / "scripts" / "run_clustering.py")])
        
        # 3. Run LLM Analytics
        logger.info("Step 2: Running LLM Analytics...")
        subprocess.run([sys.executable, str(project_root / "backend" / "scripts" / "run_analytics.py")])
        
        logger.info("All steps completed successfully! Dashboard data is fully updated.")
    else:
        logger.info("No new reviews imported, skipping clustering/analytics rerun.")

if __name__ == "__main__":
    asyncio.run(main())
