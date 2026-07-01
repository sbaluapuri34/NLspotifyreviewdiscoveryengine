from typing import Optional
import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys_path = str(project_root)
if sys_path not in os.sys.path:
    os.sys.path.append(sys_path)

from backend.app.analytics_compiler import AnalyticsCompiler

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

    logger.info("Starting Phase 4.7: Advanced Analytics & Metric Compilation Engine...")
    start_time = time.time()

    # 1. Initialize Compiler
    compiler = AnalyticsCompiler(db_path=db_path) if db_path else AnalyticsCompiler()

    # 2. Run Device Classification
    compiler.run_device_classification()

    # 3. Compile Metrics
    metrics = compiler.compile_metrics()
    if not metrics:
        logger.error("Failed to compile metrics.")
        return

    # 4. Print Detailed Analytical Report
    print("\n" + "="*65)
    print("PHASE 4.7: ADVANCED ANALYTICS & METRICS COMPILATION REPORT")
    print("="*65)

    # Ingestion Split
    split = metrics["split_ratio"]
    print(f"\n[1] DATA INGESTION & ISSUE CLASSIFICATION")
    print(f"Total Reviews Ingested   : {split['total_reviews']}")
    print(f"Discovery-Related (Detailed) : {split['discovery_related']['count']} ({split['discovery_related']['percentage']}%)")
    print(f"Operational (Surface Path)   : {split['operational_unrelated']['count']} ({split['operational_unrelated']['percentage']}%)")
    print("Operational Breakdown:")
    for k, v in split['operational_unrelated']['breakdown'].items():
        print(f"  - {k.capitalize():<10} : {v} reviews")

    # Device Distribution
    devices = metrics["device_distribution"]
    print(f"\n[2] DEVICE TYPE DISTRIBUTION (COMPRESSED ANALYSIS)")
    print("Global Device Share:")
    for dev in devices["global"]:
        print(f"  - {dev['device']:<10} : {dev['count']:<5} reviews ({dev['percentage']:>5}%) | Avg Rating: {dev['avg_rating']} stars")
    print("\nDiscovery-Specific Device Share:")
    for dev in devices["discovery"]:
        print(f"  - {dev['device']:<10} : {dev['count']:<5} reviews ({dev['percentage']:>5}%) | Avg Rating: {dev['avg_rating']} stars")

    # Source Distribution
    sources = metrics["source_distribution"]
    print(f"\n[3] DATA SOURCE CHANNEL DISTRIBUTION")
    for src in sources:
        print(f"  - {src['source']:<20} : {src['count']:<5} reviews ({src['percentage']:>5}%) | Avg Rating: {src['avg_rating']} stars")

    # Research Questions
    rqs = metrics["research_questions"]
    print(f"\n[4] 7 CORE RESEARCH QUESTIONS STATUS")
    for rq in rqs:
        print(f"  - [{rq['rq_id']}] {rq['title']:<40} | Conf: {rq['confidence_score']:.2f} | Findings: {rq['findings_count']} | Opps: {rq['opportunities_count']}")

    # Refined Themes
    themes = metrics["refined_themes"]
    print(f"\n[5] PHASE 4.5 DEEP THEMATIC REFINEMENT VERIFICATION")
    for th in themes:
        print(f"  - [{th['theme_id']}] {th['name']:<40} | Category: {th['category']:<30} | Verified: {th['verified_reviews_count']}")

    print("\n" + "="*65)
    elapsed = time.time() - start_time
    logger.info(f"Phase 4.7 completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()


async def run_analytics_compiler_pipeline(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: main(db_path, theme_config_path))
