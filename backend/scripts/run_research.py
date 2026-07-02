import hashlib
import os
import sys
import json
import time
import sqlite3
from typing import Optional
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.research import ResearchEngine, RESEARCH_QUESTIONS
from backend.app.config import DB_PATH

import asyncio

def load_previous_answers(db_path: Optional[str] = None) -> dict:
    """Loads previous answers from database if they exist."""
    prev = {}
    try:
        target_db = db_path or os.environ.get("DATABASE_PATH") or DB_PATH
        if Path(target_db).exists():
            conn = sqlite3.connect(target_db)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='research_answers'")
            if cursor.fetchone():
                cursor.execute("SELECT rq_id, content FROM research_answers")
                for row in cursor.fetchall():
                    prev[row[0]] = json.loads(row[1]).get("executive_summary")
            conn.close()
    except Exception as e:
        logger.warning(f"Could not load previous answers: {e}")
    return prev

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

def compute_rq_hash(rq_id: str, question_text: str, packages: list, prev_summary: Optional[str] = None) -> str:
    pkg_hashes = [compute_package_hash(p) for p in packages]
    pkg_hashes.sort()
    combined = f"rq_id:{rq_id}|q:{question_text}|pkgs:{','.join(pkg_hashes)}|prev:{prev_summary or ''}"
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

    logger.info("Starting Phase 4: Level 3 LLM Research Engine Execution...")
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

    packages_filename = f"compiled_evidence_packages{suffix}.json"
    packages_path = Path(project_root) / "backend" / "scripts" / packages_filename
    if not packages_path.exists():
        logger.error(f"Evidence packages file not found at {packages_path}. Please run Phase 3 first.")
        return

    with open(packages_path, "r", encoding="utf-8") as f:
        packages = json.load(f)

    # 1. Initialize Research Engine
    custom_rqs = theme_config.get("research_questions") if theme_config else None
    engine = ResearchEngine(research_questions=custom_rqs)
    if not engine.api_keys:
        logger.error("GROQ_API_KEYS is not set. Please provide it before running.")
        return

    # 2. Route Clusters
    logger.info("Routing clusters to Research Questions...")
    routed_clusters = engine.route_clusters_to_rqs(packages)
    for rq_id, pkgs in routed_clusters.items():
        logger.info(f"  - {rq_id}: {len(pkgs)} relevant clusters.")

    # 3. Load previous answers for refinement
    target_db_path = os.environ.get("DATABASE_PATH")
    prev_answers = load_previous_answers(target_db_path)

    # 4. Synthesize answers concurrently in parallel
    final_answers = {}
    active_rqs = custom_rqs or RESEARCH_QUESTIONS
    tasks = []

    # Limit active API calls to the number of available keys
    sem = asyncio.Semaphore(len(engine.api_keys)) if engine.api_keys else None

    async def run_rq_task(idx: int, rq_id: str, pkgs: list, delay: float = 0.0):
        if not pkgs:
            logger.warning(f"No relevant clusters for {rq_id}. Skipping synthesis.")
            return None
            
        logger.info(f"Synthesizing answer for {rq_id}: {active_rqs.get(rq_id, {}).get('title')}...")
        prev_summary = prev_answers.get(rq_id)
        
        # Check Cache
        rq_info = active_rqs[rq_id]
        rq_hash = compute_rq_hash(rq_id, rq_info.get("question", ""), pkgs, prev_summary)
        cache_key = f"rq_answer_hash_{rq_hash}"
        cached_str = get_cached_val(cache_key, target_db_path)
        if cached_str:
            try:
                cached_result = json.loads(cached_str)
                logger.info(f"ResearchEngine: Cache hit for research question {rq_id}.")
                return rq_id, cached_result, True
            except Exception as ce:
                logger.warning(f"Failed to parse cache value for {rq_id}: {ce}")

        # Proactive Rate-Limiting Delay for cache misses
        if delay > 0.0:
            logger.info(f"ResearchEngine: Cache miss for {rq_id}. Applying proactive rate-limit delay of {delay:.1f}s...")
            await asyncio.sleep(delay)

        # Instantiate a ResearchEngine for this task with a unique key index offset
        engine_instance = ResearchEngine(api_keys=engine.api_keys, research_questions=custom_rqs)
        engine_instance.current_key_idx = idx % len(engine.api_keys)
        
        loop = asyncio.get_running_loop()
        
        if sem:
            async with sem:
                answer_data = await loop.run_in_executor(
                    None,
                    lambda: engine_instance.synthesize_rq_answer(rq_id, pkgs, prev_summary)
                )
        else:
            answer_data = await loop.run_in_executor(
                None,
                lambda: engine_instance.synthesize_rq_answer(rq_id, pkgs, prev_summary)
            )

        if answer_data and answer_data.get("executive_summary") != "Failed to synthesize answer.":
            save_cached_val(cache_key, json.dumps(answer_data), target_db_path)

        return rq_id, answer_data, False

    # Check cache state beforehand to assign progressive delays for LLM calls
    uncached_idx = 0
    for idx, (rq_id, pkgs) in enumerate(routed_clusters.items()):
        if pkgs:
            prev_summary = prev_answers.get(rq_id)
            rq_info = active_rqs[rq_id]
            rq_hash = compute_rq_hash(rq_id, rq_info.get("question", ""), pkgs, prev_summary)
            cache_key = f"rq_answer_hash_{rq_hash}"
            cached_str = get_cached_val(cache_key, target_db_path)
            if cached_str:
                tasks.append(run_rq_task(idx, rq_id, pkgs, delay=0.0))
            else:
                delay = uncached_idx * 10.0  # 10s delay between parallel dispatches
                uncached_idx += 1
                tasks.append(run_rq_task(idx, rq_id, pkgs, delay=delay))

    if tasks:
        logger.info(f"Dispatching {len(tasks)} Research Question synthesis tasks concurrently...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Error in RQ synthesis task: {res}")
            elif res:
                rq_id, answer_data, is_cache_hit = res
                final_answers[rq_id] = answer_data
                msg_prefix = "[CACHE HIT]" if is_cache_hit else "[LLM GENERATED]"
                logger.info(f"{msg_prefix} Synthesized answer for {rq_id} (Confidence: {answer_data.get('confidence_score')}).")

    # 5. Save answers
    if final_answers:
        # Save to JSON
        answers_json_filename = f"research_question_answers{suffix}.json"
        answers_json_path = Path(project_root) / "backend" / "scripts" / answers_json_filename
        with open(answers_json_path, "w", encoding="utf-8") as f:
            json.dump(final_answers, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved research answers to {answers_json_path}")
        
        # Save a copy to persistent metadata cache
        cache_json_filename = f"research_question_answers_cache{suffix}.json"
        cache_json_path = Path(project_root) / "backend" / "scripts" / cache_json_filename
        try:
            with open(cache_json_path, "w", encoding="utf-8") as f:
                json.dump(final_answers, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved research answers cache to {cache_json_path}")
        except Exception as ce:
            logger.warning(f"Error saving research answers cache: {ce}")
        
        # Save to SQLite
        engine.save_answers_to_db(final_answers, db_path=target_db_path)
        
        # Print summary report
        print("\n" + "="*50)
        print("LEVEL 3 RESEARCH ENGINE SUMMARY REPORT")
        print("="*50)
        for rq_id, data in final_answers.items():
            print(f"\n[{rq_id}] {data.get('title')} (Confidence: {data.get('confidence_score'):.2f})")
            print(f"Summary: {data.get('executive_summary')[:200]}...")
            print(f"Key Findings: {len(data.get('key_findings', []))} identified.")
            print(f"Actionable Opportunities: {len(data.get('actionable_opportunities', []))} identified.")
        print("\n" + "="*50)
    else:
        logger.warning("No research answers were synthesized.")

    elapsed = time.time() - start_time
    logger.info(f"Phase 4 completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())


async def run_research_pipeline(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    await main(db_path, theme_config_path)
