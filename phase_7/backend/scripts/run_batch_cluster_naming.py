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
    cache_path = Path(project_root) / "backend" / "scripts" / "cluster_metadata_cache.json"
    
    if not packages_path.exists():
        logger.error(f"Evidence packages file not found at {packages_path}.")
        return

    with open(packages_path, "r", encoding="utf-8") as f:
        packages = json.load(f)

    # Load persistent metadata cache
    cache = {}
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            logger.info(f"Loaded {len(cache)} cached cluster definitions from {cache_path.name}.")
        except Exception as e:
            logger.warning(f"Could not load metadata cache: {e}")

    # 1. Filter target clusters of size >= 3
    target_clusters = [p for p in packages if p.get("size", 0) >= 3 and not p["cluster_id"].startswith("unrelated_")]
    logger.info(f"Analyzing {len(target_clusters)} active clusters...")

    # 2. Separate new clusters from cached ones
    clusters_to_name = []
    cached_count = 0
    
    for pkg in target_clusters:
        cid = pkg["cluster_id"]
        if cid in cache:
            # Reuse cached name, sub-issues, and new strategic intelligence fields
            pkg["cluster_name"] = cache[cid]["cluster_name"]
            pkg["sub_issues"] = cache[cid]["sub_issues"]
            pkg["sub_themes"] = cache[cid].get("sub_themes", [])
            pkg["jtbd"] = cache[cid].get("jtbd", {})
            pkg["workarounds"] = cache[cid].get("workarounds", [])
            cached_count += 1
        else:
            clusters_to_name.append(pkg)

    logger.info(f"Reuse Cache: {cached_count} clusters. LLM Naming Required: {len(clusters_to_name)} clusters.")

    # 3. Format surface-level data for new clusters only
    formatted_clusters = []
    for pkg in clusters_to_name:
        cid = pkg["cluster_id"]
        themes = [t[0] for t in pkg.get("themes", [])[:5]]
        
        # Gather only top 2 reviews
        reviews = []
        for key in ["medoids", "outliers"]:
            for r in pkg.get(key, []):
                text = r.get("translated_text") or r.get("raw_text")
                if text and text not in reviews:
                    truncated = text[:120] + "..." if len(text) > 120 else text
                    reviews.append(truncated)
            if len(reviews) >= 2:
                break
                
        formatted_clusters.append({
            "cluster_id": cid,
            "themes": themes,
            "reviews": reviews[:2]
        })

    # 4. Batch naming for new clusters (25 clusters per LLM call)
    if formatted_clusters:
        namer = BatchClusterNamer()
        batch_size = 25
        new_names_mapping = {}

        for i in range(0, len(formatted_clusters), batch_size):
            batch = formatted_clusters[i:i+batch_size]
            mapping = namer.name_batch(batch)
            new_names_mapping.update(mapping)
            time.sleep(1.5)

        # Update packages and cache with new LLM results
        for pkg in packages:
            cid = pkg["cluster_id"]
            if cid in new_names_mapping:
                res = new_names_mapping[cid]
                if isinstance(res, dict):
                    name = res.get("name", "Unnamed Cluster")
                    sub_issues = res.get("sub_issues", [])
                    sub_themes = res.get("sub_themes", [])
                    jtbd = res.get("jtbd", {})
                    workarounds = res.get("workarounds", [])
                else:
                    name = res
                    sub_issues = []
                    sub_themes = []
                    jtbd = {}
                    workarounds = []
                
                # Save to package
                pkg["cluster_name"] = name
                pkg["sub_issues"] = sub_issues
                pkg["sub_themes"] = sub_themes
                pkg["jtbd"] = jtbd
                pkg["workarounds"] = workarounds
                
                # Save to persistent cache
                cache[cid] = {
                    "cluster_name": name,
                    "sub_issues": sub_issues,
                    "sub_themes": sub_themes,
                    "jtbd": jtbd,
                    "workarounds": workarounds
                }

        # Save updated cache back to disk
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated metadata cache at {cache_path.name}.")
        except Exception as e:
            logger.error(f"Error saving metadata cache: {e}")

    # 5. Save updated packages
    with open(packages_path, "w", encoding="utf-8") as f:
        json.dump(packages, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved compiled evidence packages to {packages_path.name}.")

    # Print summary
    print("\n" + "="*50)
    print("LLM BATCH CLUSTER NAMING COMPLETE")
    print("="*50)
    print(f"Total Clusters   : {len(target_clusters)}")
    print(f"Reused from Cache: {cached_count}")
    print(f"Newly Named (LLM): {len(formatted_clusters)}")
    print("="*50)

    elapsed = time.time() - start_time
    logger.info(f"Naming process completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()
