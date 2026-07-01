from typing import Optional
import asyncio
import hashlib
import os
import sys
import json
import time
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.database import get_db_connection
from backend.app.vectors import VectorEmbedder
from backend.app.analytics import DynamicFilterEngine

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

    logger.info("Starting Phase 3: Level 2 Evidence Engine Execution...")
    start_time = time.time()

    # 1. Initialize DB Connection & Embedder
    conn = get_db_connection()
    embedder = VectorEmbedder()

    # 2. Initialize Dynamic Filter Engine
    # Load theme configuration from environment variables if present
    theme_config = None
    theme_config_path = os.environ.get("THEME_CONFIG_PATH")
    if theme_config_path and Path(theme_config_path).exists():
        try:
            with open(theme_config_path, "r", encoding="utf-8") as f:
                theme_config = json.load(f)
            logger.info(f"Loaded dynamic theme configuration for: {theme_config.get('theme')}")
        except Exception as e:
            logger.error(f"Error loading theme configuration JSON: {e}")
            
    custom_anchors = None
    priority_words = None
    if theme_config:
        custom_anchors = theme_config.get("semantic_anchors")
        priority_words = set(theme_config.get("level_0_config", {}).get("priority_routing_keywords", []))

    logger.info("Initializing Dynamic Filter Engine...")
    engine = DynamicFilterEngine(conn, embedder, custom_anchors=custom_anchors, priority_words=priority_words)

    # 3. Compile Evidence Packages (No filters = all reviews)
    logger.info("Compiling Evidence Packages for all clusters...")
    packages = engine.get_filtered_analytics()
    
    total_packages = len(packages)
    logger.info(f"Successfully compiled {total_packages} Evidence Packages.")

    if total_packages == 0:
        logger.warning("No clustered reviews found. Please run Phase 2 clustering first.")
        conn.close()
        return

    # 4. Save to JSON for inspection and Phase 4 use
    theme_slug = theme_config.get("theme_slug") if theme_config else None
    output_filename = f"compiled_evidence_packages_{theme_slug}.json" if theme_slug else "compiled_evidence_packages.json"
    output_path = Path(__file__).resolve().parent / output_filename
    
    # Clean packages for JSON serialization (remove review dicts or keep essential fields)
    serializable_packages = []
    for pkg in packages:
        # We make a copy and clean up reviews inside medoids/outliers/anomalies for clean JSON
        clean_pkg = pkg.copy()
        for key in ["medoids", "outliers", "anomalies"]:
            clean_pkg[key] = [
                {
                    "id": r["id"],
                    "raw_text": r["raw_text"],
                    "translated_text": r.get("translated_text"),
                    "rating": r.get("rating"),
                    "source": r["source"],
                    "published_at": r["published_at"]
                }
                for r in pkg[key]
            ]
        serializable_packages.append(clean_pkg)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable_packages, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved compiled evidence packages to {output_path}")

    # 5. Print Top 10 Opportunity Areas
    logger.info("==================================================")
    logger.info("Top 10 Opportunity Prioritization Report")
    logger.info("==================================================")
    for idx, pkg in enumerate(packages[:10]):
        themes_str = ", ".join([f"'{t[0]}'" for t in pkg["themes"][:5]])
        logger.info(f"{idx+1}. Cluster: {pkg['cluster_id'].ljust(12)} "
                    f"| Size: {str(pkg['size']).rjust(4)} "
                    f"| Opp Score: {pkg['opportunity_score']:.2f} "
                    f"| CSSS: {pkg['csss']:.2f} "
                    f"| Rating: {pkg['average_rating']:.2f}")
        logger.info(f"    Themes  : {themes_str}")
        
        # Print top locations if any
        if pkg["location_distribution"]:
            loc_str = ", ".join([f"{k} ({v})" for k, v in sorted(pkg["location_distribution"].items(), key=lambda x: x[1], reverse=True)[:3]])
            logger.info(f"    Regions : {loc_str}")
            
        # Print top tags (SAP)
        top_tags = sorted(pkg["tag_distribution"].items(), key=lambda x: x[1], reverse=True)[:3]
        if top_tags:
            tag_str = ", ".join([f"{k} ({v})" for k, v in top_tags])
            logger.info(f"    Intents : {tag_str}")
            
        # Print Medoid quote
        if pkg["medoids"]:
            medoid_text = pkg["medoids"][0]["raw_text"].replace("\n", " ").strip()
            if len(medoid_text) > 120:
                medoid_text = medoid_text[:117] + "..."
            logger.info(f"    Quote   : \"{medoid_text}\"")
        logger.info("-" * 50)

    elapsed_time = time.time() - start_time
    logger.info(f"Level 2 Evidence Engine completed in {elapsed_time:.2f} seconds.")
    conn.close()

if __name__ == "__main__":
    main()


async def run_analytics_pipeline(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: main(db_path, theme_config_path))
