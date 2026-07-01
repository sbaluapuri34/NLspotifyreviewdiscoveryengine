import os
import sys
import json
import time
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.cluster_intelligence import ClusterIntelligenceEngine

def main():
    logger.info("Starting Phase 3.5: Level 2.5 Cluster Intelligence Execution...")
    start_time = time.time()

    packages_path = Path(project_root) / "backend" / "scripts" / "compiled_evidence_packages.json"
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

    # 3. Process each cluster
    decomposed_count = 0
    for pkg in target_clusters:
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
            continue

        # Run decomposition
        result = engine.decompose_cluster(cid, themes, reviews)
        if result and "sub_issues" in result:
            pkg["sub_issues"] = result["sub_issues"]
            decomposed_count += 1
            
            # Print a quick summary
            logger.info(f"Decomposed {cid}:")
            for sub in result["sub_issues"]:
                logger.info(f"  - [{sub['frequency_percentage']}%] {sub['name']}")
        else:
            logger.warning(f"Failed to decompose cluster {cid}.")

        # Rate limit prevention sleep (Groq Free Tier has strict TPM/RPM limits)
        time.sleep(2.0)

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
    main()
