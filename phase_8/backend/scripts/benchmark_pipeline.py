import os
import sys
import json
import sqlite3
import time
from pathlib import Path
from loguru import logger
from datetime import datetime

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.database import get_db_connection
from backend.app.pipeline import TextPipeline, ALLOWED_LANGS, HINGLISH_KEYWORDS

def run_db_queries():
    """Queries the database for statistics."""
    logger.info("Querying database for final statistics...")
    stats = {}
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. Total records
        cursor.execute("SELECT COUNT(*) FROM reviews")
        stats["total_records"] = cursor.fetchone()[0]
        
        # 2. Counts per source
        cursor.execute("SELECT source, COUNT(*) as count FROM reviews GROUP BY source")
        stats["source_counts"] = {row["source"]: row["count"] for row in cursor.fetchall()}
        
        # 3. Date range
        cursor.execute("SELECT MIN(published_at), MAX(published_at) FROM reviews")
        row = cursor.fetchone()
        stats["earliest_date"] = row[0]
        stats["latest_date"] = row[1]
        
        # 4. Extract language distribution (by running detection on all reviews in DB)
        logger.info("Calculating language distribution of stored reviews...")
        cursor.execute("SELECT raw_text FROM reviews")
        raw_texts = [row["raw_text"] for row in cursor.fetchall()]
        
    pipeline = TextPipeline()
    lang_dist = {}
    for text in raw_texts:
        cleaned = pipeline.clean_text_preserve_negations(text)
        lang = pipeline.detect_language(cleaned)
        if lang in ALLOWED_LANGS:
            pass
        else:
            words = set(cleaned.lower().split())
            if words.intersection(HINGLISH_KEYWORDS):
                lang = "hinglish"
        lang_dist[lang] = lang_dist.get(lang, 0) + 1
        
    stats["language_distribution"] = lang_dist
    return stats

def load_measured_stats():
    """Loads the real measured execution metrics from the ingestion run."""
    stats_file_path = project_root / "backend" / "scripts" / "ingestion_stats.json"
    if not stats_file_path.exists():
        logger.warning(f"Ingestion stats file not found at {stats_file_path}. Please run run_production_ingestion.py first.")
        return None
        
    with open(stats_file_path, "r") as f:
        return json.load(f)

def main():
    logger.info("Starting Pipeline Benchmarking...")
    
    db_stats = run_db_queries()
    measured = load_measured_stats()
    
    if not measured:
        logger.error("No measured stats available. Cannot run benchmark.")
        return
        
    total_runtime = measured["total_runtime"]
    total_scraped = measured["total_scraped"]
    total_saved = measured["total_saved"]
    
    # Calculate real, measured throughputs
    processing_rps = total_scraped / total_runtime if total_runtime > 0 else 0
    saving_rps = total_saved / total_runtime if total_runtime > 0 else 0
    
    # Language rejection and duplicate rates from the actual run
    lang_rejection_rate = measured["rejected_lang"] / total_scraped if total_scraped > 0 else 0
    duplicate_rate = measured["rejected_dup"] / total_scraped if total_scraped > 0 else 0
    
    # Preprocessing latency is estimated from total runtime divided by total items processed,
    # which represents the overall end-to-end processing time per review (including network I/O).
    latency_ms = (total_runtime / total_scraped) * 1000 if total_scraped > 0 else 0
    
    # Previous pipeline performance: 65 mins (3900s) for 8000 reviews = 2.05 reviews/sec
    prev_rps = 2.05
    perf_improvement = (processing_rps / prev_rps) * 100 if prev_rps > 0 else 0
    
    print("\n" + "="*60)
    print(" PIPELINE BENCHMARK REPORT (REAL MEASURED METRICS)")
    print("="*60)
    print(f"Total Processed Records in DB : {db_stats['total_records']}")
    print(f"Earliest Review Date          : {db_stats['earliest_date']}")
    print(f"Latest Review Date            : {db_stats['latest_date']}")
    print(f"Total Runtime of Ingestion    : {total_runtime:.2f} seconds")
    print(f"Total Records Scraped in Run  : {total_scraped}")
    print(f"Total Records Saved in Run    : {total_saved}")
    print("-"*60)
    print("Review Counts by Source in DB:")
    for src, count in db_stats["source_counts"].items():
        print(f"  - {src.ljust(20)}: {count}")
    print("-"*60)
    print("Language Distribution in DB:")
    for lang, count in db_stats["language_distribution"].items():
        print(f"  - {lang.ljust(20)}: {count}")
    print("-"*60)
    print("Real Measured Performance Metrics:")
    print(f"  - Avg End-to-End Latency     : {latency_ms:.2f} ms/review (including scraping & I/O)")
    print(f"  - Language Rejection Rate   : {lang_rejection_rate*100:.1f}%")
    print(f"  - Duplicate Detection Rate  : {duplicate_rate*100:.1f}%")
    print(f"  - Ingestion Throughput (RPS): {processing_rps:.2f} reviews/sec (scraped & processed)")
    print(f"  - Database Save Rate        : {saving_rps:.2f} reviews/sec (inserted to DB)")
    print(f"  - Translation Throughput    : {measured['translated_count'] / total_runtime:.2f} translations/sec")
    print(f"  - Overall Speedup           : {perf_improvement:.1f}% of legacy pipeline performance")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
