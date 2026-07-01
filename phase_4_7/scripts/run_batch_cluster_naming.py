import os
import sys
import json
import time
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.cluster_namer import BatchClusterNamer

def main():
    logger.info("Starting Batch Cluster Naming Engine (Highly Cost & Time Efficient)...")
    start_time = time.time()

    packages_path = Path(project_root) / "backend" / "scripts" / "compiled_evidence_packages.json"
    if not packages_path.exists():
        logger.error(f"Evidence packages file not found at {packages_path}.")
        return

    with open(packages_path, "r", encoding="utf-8") as f:
        packages = json.load(f)

    # 1. Filter target clusters of size >= 3 (114 clusters)
    target_clusters = [p for p in packages if p.get("size", 0) >= 3 and not p["cluster_id"].startswith("unrelated_")]
    logger.info(f"Preparing batch naming for {len(target_clusters)} clusters...")

    # 2. Format surface-level data (Themes + 2 short truncated reviews)
    formatted_clusters = []
    for pkg in target_clusters:
        cid = pkg["cluster_id"]
        themes = [t[0] for t in pkg.get("themes", [])[:5]]
        
        # Gather only top 2 reviews
        reviews = []
        for key in ["medoids", "outliers"]:
            for r in pkg.get(key, []):
                text = r.get("translated_text") or r.get("raw_text")
                if text and text not in reviews:
                    # Truncate to 120 characters to minimize token usage
                    truncated = text[:120] + "..." if len(text) > 120 else text
                    reviews.append(truncated)
            if len(reviews) >= 2:
                break
                
        formatted_clusters.append({
            "cluster_id": cid,
            "themes": themes,
            "reviews": reviews[:2] # Strictly limit to 2
        })

    # 3. Batch naming (25 clusters per LLM call)
    namer = BatchClusterNamer()
    batch_size = 25
    all_names = {}

    for i in range(0, len(formatted_clusters), batch_size):
        batch = formatted_clusters[i:i+batch_size]
        mapping = namer.name_batch(batch)
        all_names.update(mapping)
        # Gentle rate limit sleep
        time.sleep(1.5)

    # 4. Save names back to packages
    named_count = 0
    for pkg in packages:
        cid = pkg["cluster_id"]
        if cid in all_names:
            pkg["cluster_name"] = all_names[cid]
            named_count += 1

    if named_count > 0:
        with open(packages_path, "w", encoding="utf-8") as f:
            json.dump(packages, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully named and saved {named_count} clusters in {packages_path}")
    else:
        logger.warning("No clusters were successfully named.")

    # Print summary
    print("\n" + "="*50)
    print("LLM BATCH CLUSTER NAMING COMPLETE")
    print("="*50)
    for cid, name in list(all_names.items())[:15]:
        print(f" - {cid:<12} -> {name}")
    if len(all_names) > 15:
        print(f" ... and {len(all_names) - 15} more clusters.")
    print("="*50)

    elapsed = time.time() - start_time
    logger.info(f"Naming process completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()
