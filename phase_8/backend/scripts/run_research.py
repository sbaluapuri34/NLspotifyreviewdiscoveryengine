import os
import sys
import json
import time
import sqlite3
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.research import ResearchEngine, RESEARCH_QUESTIONS
from backend.app.config import DB_PATH

def load_previous_answers() -> dict:
    """Loads previous answers from database if they exist."""
    prev = {}
    try:
        if Path(DB_PATH).exists():
            conn = sqlite3.connect(DB_PATH)
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

def main():
    logger.info("Starting Phase 4: Level 3 LLM Research Engine Execution...")
    start_time = time.time()

    packages_path = Path(project_root) / "backend" / "scripts" / "compiled_evidence_packages.json"
    if not packages_path.exists():
        logger.error(f"Evidence packages file not found at {packages_path}. Please run Phase 3 first.")
        return

    with open(packages_path, "r", encoding="utf-8") as f:
        packages = json.load(f)

    # 1. Initialize Research Engine
    engine = ResearchEngine()
    if not engine.api_keys:
        logger.error("GROQ_API_KEYS is not set. Please provide it before running.")
        return

    # 2. Route Clusters
    logger.info("Routing clusters to the 7 Core Research Questions...")
    routed_clusters = engine.route_clusters_to_rqs(packages)
    for rq_id, pkgs in routed_clusters.items():
        logger.info(f"  - {rq_id}: {len(pkgs)} relevant clusters.")

    # 3. Load previous answers for refinement
    prev_answers = load_previous_answers()

    # 4. Synthesize answers
    final_answers = {}
    for rq_id, pkgs in routed_clusters.items():
        if not pkgs:
            logger.warning(f"No relevant clusters for {rq_id}. Skipping synthesis.")
            continue
            
        logger.info(f"Synthesizing answer for {rq_id}: {RESEARCH_QUESTIONS[rq_id]['title']}...")
        prev_summary = prev_answers.get(rq_id)
        
        # Call the engine
        answer_data = engine.synthesize_rq_answer(rq_id, pkgs, prev_summary)
        final_answers[rq_id] = answer_data
        
        # Sleep to prevent rate limit (Groq TPM limits are strict)
        time.sleep(15.0)

    # 5. Save answers
    if final_answers:
        # Save to JSON
        answers_json_path = Path(project_root) / "backend" / "scripts" / "research_question_answers.json"
        with open(answers_json_path, "w", encoding="utf-8") as f:
            json.dump(final_answers, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved research answers to {answers_json_path}")
        
        # Save to SQLite
        engine.save_answers_to_db(final_answers)
        
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
    main()
