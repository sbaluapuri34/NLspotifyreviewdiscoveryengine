from typing import Optional
import hashlib
import os
import sys
import json
import time
import asyncio
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.cluster_intelligence import ClusterIntelligenceEngine

def compute_package_hash(pkg: dict) -> str:
    themes = sorted([t[0] for t in pkg.get("themes", [])])
    reviews_data = []
    for key in ["medoids", "outliers", "anomalies"]:
        for r in pkg.get(key, []):
            text = r.get("translated_text") or r.get("raw_text") or ""
            rid = r.get("id", "")
            rating = str(r.get("rating", ""))
            reviews_data.append(f"{rid}:{text}:{rating}")
    reviews_data.sort()
    combined = f"themes:{','.join(themes)}|reviews:{'|'.join(reviews_data)}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()

def get_cached_val(key: str, db_path: Optional[str] = None) -> Optional[str]:
    try:
        from backend.app.database import get_db_connection
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM llm_cache WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return row[0]
    except Exception as e:
        logger.warning(f"Error reading from llm_cache: {e}")
    return None

def save_cached_val(key: str, value: str, db_path: Optional[str] = None):
    try:
        from backend.app.database import get_db_connection
        with get_db_connection(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (key, value)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Error writing to llm_cache: {e}")

async def main(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
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

    logger.info("Starting Phase 3.5: Level 2.5 Cluster Intelligence Execution...")
    start_time = time.time()

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

    theme_slug = theme_config.get("theme_slug") if theme_config else None
    suffix = f"_{theme_slug}" if theme_slug else ""

    packages_path = Path(project_root) / "backend" / "scripts" / f"compiled_evidence_packages{suffix}.json"
    if not packages_path.exists():
        logger.error(f"Evidence packages file not found at {packages_path}. Please run Phase 3 first.")
        return

    with open(packages_path, "r", encoding="utf-8") as f:
        packages = json.load(f)

    # 1. Initialize Gemini Engine
    engine = ClusterIntelligenceEngine()
    if not engine.api_keys:
        logger.error("GROQ_API_KEYS is not set in the environment or config. Please provide it before running.")
        print("\n[ERROR] GROQ_API_KEYS is missing. Please set it in your environment or .env file.")
        return

    # 2. Filter clusters with size >= 3
    target_clusters = [p for p in packages if p.get("size", 0) >= 3 and not p["cluster_id"].startswith("unrelated_")]
    logger.info(f"Found {len(target_clusters)} clusters meeting the size >= 3 threshold.")

    # 3. Process each cluster concurrently in parallel
    decomposed_count = 0
    tasks = []

    # Limit active API calls to the number of available keys
    sem = asyncio.Semaphore(len(engine.api_keys)) if engine.api_keys else None

    async def process_cluster(idx: int, pkg: dict):
        cid = pkg["cluster_id"]
        themes = [t[0] for t in pkg.get("themes", [])]
        
        # Collect raw texts from medoids and outliers
        reviews = []
        for key in ["medoids", "outliers", "anomalies"]:
            for r in pkg.get(key, []):
                text = r.get("translated_text") or r.get("raw_text")
                if text and text not in reviews:
                    reviews.append(text)
                    
        if not reviews:
            logger.warning(f"No reviews found for cluster {cid}. Skipping.")
            return None

        # Check Cache
        pkg_hash = compute_package_hash(pkg)
        cache_key = f"cluster_intel_hash_{pkg_hash}"
        cached_str = get_cached_val(cache_key, db_path)
        if cached_str:
            try:
                cached_result = json.loads(cached_str)
                logger.info(f"ClusterIntelligenceEngine: Cache hit for cluster {cid}.")
                return pkg, cached_result, True
            except Exception as ce:
                logger.warning(f"Failed to parse cache value for {cid}: {ce}")

        # Instantiate a separate engine for this task to offset starting key index
        engine_instance = ClusterIntelligenceEngine(api_keys=engine.api_keys)
        engine_instance.current_key_idx = idx % len(engine.api_keys)

        loop = asyncio.get_running_loop()
        
        if sem:
            async with sem:
                result = await loop.run_in_executor(
                    None,
                    lambda: engine_instance.decompose_cluster(cid, themes, reviews)
                )
        else:
            result = await loop.run_in_executor(
                None,
                lambda: engine_instance.decompose_cluster(cid, themes, reviews)
            )

        if result and result.get("sub_issues"):
            save_cached_val(cache_key, json.dumps(result), db_path)
            
        return pkg, result, False

    for idx, pkg in enumerate(target_clusters):
        tasks.append(process_cluster(idx, pkg))

    if tasks:
        logger.info(f"Dispatching {len(tasks)} cluster intelligence decomposition tasks concurrently...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Error in cluster intelligence decomposition task: {res}")
            elif res:
                pkg, result, is_cache_hit = res
                if result and "sub_issues" in result:
                    pkg["sub_issues"] = result["sub_issues"]
                    pkg["sub_themes"] = result.get("sub_themes", [])
                    pkg["jtbd"] = result.get("jtbd", {})
                    pkg["workarounds"] = result.get("workarounds", [])
                    if "cluster_name" in result:
                        pkg["cluster_name"] = result["cluster_name"]
                    decomposed_count += 1
                    
                    # Print a quick summary
                    msg_prefix = "[CACHE HIT]" if is_cache_hit else "[LLM GENERATED]"
                    logger.info(f"{msg_prefix} Decomposed {pkg['cluster_id']} ({pkg.get('cluster_name', 'No Name')}):")
                    for sub in result["sub_issues"]:
                        logger.info(f"  - [{sub['frequency_percentage']}%] {sub['name']}")
                else:
                    logger.warning(f"Failed to decompose cluster {pkg.get('cluster_id')}.")

    # 4. Save enriched packages back to JSON
    if decomposed_count > 0:
        with open(packages_path, "w", encoding="utf-8") as f:
            json.dump(packages, f, indent=2, ensure_ascii=False)
        logger.info(f"Enriched and saved {decomposed_count} clusters in {packages_path}")
    else:
        logger.warning("No clusters were successfully decomposed.")

    elapsed = time.time() - start_time
    logger.info(f"Phase 3.5 completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())


async def run_cluster_intelligence_pipeline(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    await main(db_path, theme_config_path)
