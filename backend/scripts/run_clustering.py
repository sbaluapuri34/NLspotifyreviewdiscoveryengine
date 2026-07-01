from typing import Optional
import asyncio
import hashlib
import os
import sys
import json
import time
import numpy as np
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root))

from backend.app.database import get_db_connection
from backend.app.cleaning import TextCleaner
from backend.app.vectors import VectorEmbedder, LeaderFollowerClustering

def run_migrations():
    """Applies necessary schema migrations without deleting any existing data."""
    logger.info("Running database migrations...")
    with get_db_connection() as conn:
        # 1. Add missing columns to reviews table
        for col_name, col_type in [("cleaned_text", "TEXT"), ("metadata", "TEXT"), ("cluster_id", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE reviews ADD COLUMN {col_name} {col_type};")
                logger.info(f"Added column '{col_name}' to 'reviews' table.")
            except Exception:
                pass

        # 2. Create embeddings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                vector TEXT NOT NULL,
                FOREIGN KEY(id) REFERENCES reviews(id)
            )
        """)

        # 3. Create clusters table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clusters (
                id TEXT PRIMARY KEY,
                centroid TEXT NOT NULL,
                size INTEGER NOT NULL,
                mean_similarity REAL NOT NULL,
                variance REAL NOT NULL,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    logger.info("Database migrations completed successfully.")

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

    logger.info("Starting Phase 2: Dual-Path Embedding & Clustering Execution...")
    
    # 1. Run migrations
    run_migrations()

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

    # 2. Initialize Text Cleaner & Embedder
    cleaner = TextCleaner()
    embedder = VectorEmbedder()

    # 3. Fetch all reviews
    logger.info("Fetching reviews from database...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, raw_text, cleaned_text, translated_text, published_at FROM reviews ORDER BY published_at ASC")
        reviews = [dict(row) for row in cursor.fetchall()]
    
    total_reviews = len(reviews)
    logger.info(f"Retrieved {total_reviews} reviews to process.")
    if total_reviews == 0:
        logger.warning("No reviews found in database. Exiting.")
        return

    # 4. Clean text if missing
    logger.info("Ensuring cleaned_text is populated for all reviews...")
    cleaned_count = 0
    with get_db_connection() as conn:
        for r in reviews:
            if not r.get("cleaned_text"):
                txt = r.get("translated_text") or r.get("raw_text")
                cleaned = cleaner.filter_pii_and_noise(cleaner.clean_text_preserve_negations(txt))
                r["cleaned_text"] = cleaned
                conn.execute("UPDATE reviews SET cleaned_text = ? WHERE id = ?", (cleaned, r["id"]))
                cleaned_count += 1
        if cleaned_count > 0:
            conn.commit()
            logger.info(f"Populated cleaned_text for {cleaned_count} reviews.")

    # 5. Dual-Path Classification: Discovery vs. Unrelated
    discovery_keywords = ["discover", "recommend", "shuffle", "playlist", "algorithm", "repeat", "find", "search", "weekly", "radar", "mix", "autoplay", "repetition", "loop", "dj"]
    
    discovery_reviews = []
    unrelated_reviews = []
    
    for r in reviews:
        txt = (r["cleaned_text"] or r["translated_text"] or r["raw_text"] or "").lower()
        # In Theme Exploration mode, bypass partition and route all reviews to detailed semantic clustering
        is_discovery = True if theme_config else any(kw in txt for kw in discovery_keywords)
        if is_discovery:
            discovery_reviews.append(r)
        else:
            unrelated_reviews.append(r)
            
    logger.info(f"Dual-Path Partition: {len(discovery_reviews)} Discovery reviews (Detailed), {len(unrelated_reviews)} Unrelated reviews (Surface-level)")

    # 6. Process Unrelated Reviews (Surface-level Rule-based Grouping)
    logger.info("Processing unrelated reviews into surface-level categories...")
    unrelated_assignments = {}
    for r in unrelated_reviews:
        txt = (r["cleaned_text"] or r["translated_text"] or r["raw_text"] or "").lower()
        if "ad" in txt or "ads" in txt or "advertisement" in txt:
            unrelated_assignments[r["id"]] = "unrelated_ads"
        elif any(kw in txt for kw in ["crash", "freeze", "bug", "error", "slow", "lag", "stop", "offline"]):
            unrelated_assignments[r["id"]] = "unrelated_bugs"
        elif "widget" in txt:
            unrelated_assignments[r["id"]] = "unrelated_widgets"
        else:
            unrelated_assignments[r["id"]] = "unrelated_general"
            
    # Mark all unrelated reviews as analysed since they are completed
    with get_db_connection() as conn:
        for rid in unrelated_assignments.keys():
            conn.execute("UPDATE reviews SET analysed = 1 WHERE id = ?", (rid,))
        conn.commit()

    # 7. Process Discovery Reviews (Detailed Semantic Clustering)
    # In Theme Exploration mode, use the dynamic volume-based adaptive threshold strategy.
    # In Discovery Mode, use the standard fixed threshold of 0.70.
    if theme_config:
        clustering = LeaderFollowerClustering(dimension=embedder.dimension, threshold=None, dataset_size=len(discovery_reviews))
    else:
        clustering = LeaderFollowerClustering(dimension=embedder.dimension, threshold=0.70)
    
    logger.info("Loading or generating embeddings for discovery reviews...")
    embeddings_dict = {}
    
    # Load existing
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, vector FROM embeddings")
        for row in cursor.fetchall():
            embeddings_dict[row[0]] = json.loads(row[1])
            
    # Mark already embedded discovery reviews as analysed
    existing_discovery_ids = [r["id"] for r in discovery_reviews if r["id"] in embeddings_dict]
    if existing_discovery_ids:
        logger.info(f"Marking {len(existing_discovery_ids)} already embedded discovery reviews as analysed...")
        with get_db_connection() as conn:
            for i in range(0, len(existing_discovery_ids), 100):
                batch_ids = existing_discovery_ids[i:i+100]
                conn.execute(f"UPDATE reviews SET analysed = 1 WHERE id IN ({','.join(['?']*len(batch_ids))})", batch_ids)
            conn.commit()
            
    # Identify missing among discovery reviews
    missing_discovery = [r for r in discovery_reviews if r["id"] not in embeddings_dict]
    if missing_discovery:
        logger.info(f"Generating embeddings for {len(missing_discovery)} discovery reviews...")
        batch_size = 64
        start_time = time.time()
        for i in range(0, len(missing_discovery), batch_size):
            batch = missing_discovery[i:i+batch_size]
            texts = [r["cleaned_text"] for r in batch]
            vectors = embedder.embed_batch(texts)
            
            with get_db_connection() as conn:
                for r, vec in zip(batch, vectors):
                    embeddings_dict[r["id"]] = vec
                    conn.execute("INSERT OR REPLACE INTO embeddings (id, vector) VALUES (?, ?)", (r["id"], json.dumps(vec)))
                    # Mark these newly embedded reviews as analysed
                    conn.execute("UPDATE reviews SET analysed = 1 WHERE id = ?", (r["id"],))
                conn.commit()
            
            elapsed = time.time() - start_time
            processed = min(i + batch_size, len(missing_discovery))
            rps = processed / elapsed if elapsed > 0 else 0
            logger.info(f"Generated embeddings: {processed}/{len(missing_discovery)} ({rps:.2f} reviews/sec)")

    # Run Leader-Follower on discovery reviews
    logger.info("Running Leader-Follower Clustering on discovery reviews...")
    start_time = time.time()
    for r in discovery_reviews:
        vec = embeddings_dict[r["id"]]
        clustering.add_review(r["id"], vec)
    clustering_time = time.time() - start_time
    logger.info(f"Semantic clustering completed in {clustering_time:.2f} seconds.")

    # 8. Persist All Assignments & Centroids
    logger.info("Persisting all cluster assignments and centroids to database...")
    with get_db_connection() as conn:
        # Save detailed discovery cluster assignments
        for cid, members in clustering.cluster_members.items():
            for rid in members:
                conn.execute("UPDATE reviews SET cluster_id = ? WHERE id = ?", (cid, rid))
                
        # Save surface-level unrelated assignments
        for rid, cid in unrelated_assignments.items():
            conn.execute("UPDATE reviews SET cluster_id = ? WHERE id = ?", (cid, rid))
            
        # Reset clusters table to store fresh centroids
        conn.execute("DELETE FROM clusters")
        
        # Save centroids for detailed discovery clusters
        for cdata in clustering.get_cluster_stats():
            conn.execute(
                "INSERT INTO clusters (id, centroid, size, mean_similarity, variance) VALUES (?, ?, ?, ?, ?)",
                (cdata["cluster_id"], json.dumps(cdata["centroid"]), cdata["size"], cdata["mean_similarity"], cdata["variance"])
            )
            
        # Save dummy/mean centroids for surface-level clusters so the analytics engine doesn't break
        for cid in ["unrelated_ads", "unrelated_bugs", "unrelated_widgets", "unrelated_general"]:
            member_rids = [rid for rid, assigned_cid in unrelated_assignments.items() if assigned_cid == cid]
            size = len(member_rids)
            if size > 0:
                # Find vectors for these members (if any are embedded)
                member_vecs = [embeddings_dict[rid] for rid in member_rids if rid in embeddings_dict]
                if member_vecs:
                    centroid = np.mean(member_vecs, axis=0)
                    centroid = centroid / np.linalg.norm(centroid)
                else:
                    # Fallback unit vector
                    centroid = np.zeros(embedder.dimension)
                    centroid[0] = 1.0
                    
                conn.execute(
                    "INSERT INTO clusters (id, centroid, size, mean_similarity, variance) VALUES (?, ?, ?, ?, ?)",
                    (cid, json.dumps(centroid.tolist()), size, 0.50, 0.10)
                )
        conn.commit()

    # 9. Print Summaries
    stats = clustering.get_cluster_stats()
    logger.info("==================================================")
    logger.info("Dual-Path Clustering Summary Report")
    logger.info("==================================================")
    logger.info(f"Total Reviews Processed      : {total_reviews}")
    logger.info(f"Discovery Reviews (Detailed) : {len(discovery_reviews)}")
    logger.info(f"Unrelated Reviews (Surface)  : {len(unrelated_reviews)}")
    logger.info(f"Detailed Clusters Created    : {len(stats)}")
    logger.info(f"Average Discovery Cluster Size: {len(discovery_reviews) / len(stats):.2f}" if stats else "0.00")
    
    logger.info("Surface-Level Categories:")
    for cid in ["unrelated_ads", "unrelated_bugs", "unrelated_widgets", "unrelated_general"]:
        count = sum(1 for v in unrelated_assignments.values() if v == cid)
        logger.info(f"  - {cid.ljust(18)}: Size={count}")
        
    logger.info("Top 5 Largest Detailed Discovery Clusters:")
    for i, c in enumerate(stats[:5]):
        logger.info(f"  {i+1}. {c['cluster_id'].ljust(12)}: Size={c['size']}, Mean Sim={c['mean_similarity']:.3f}, Var={c['variance']:.4f}")
    logger.info("==================================================")

    print(f"\nSUCCESS: Dual-Path clustering completed. {total_reviews} reviews successfully partitioned and clustered.")

if __name__ == "__main__":
    main()


async def run_clustering_pipeline(db_path: Optional[str] = None, theme_config_path: Optional[str] = None):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: main(db_path, theme_config_path))
