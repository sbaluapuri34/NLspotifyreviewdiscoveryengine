import json
import sqlite3
from pathlib import Path

db_path = Path(__file__).resolve().parent.parent / "spotify_research.db"

def main():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Fetch top 20 largest clusters
    clusters = conn.execute("""
        SELECT id, size, mean_similarity, variance 
        FROM clusters 
        ORDER BY size DESC 
        LIMIT 20
    """).fetchall()
    
    print(f"Loaded {len(clusters)} clusters for inspection.\n")
    
    for idx, c in enumerate(clusters):
        cid = c["id"]
        size = c["size"]
        mean_sim = c["mean_similarity"]
        var = c["variance"]
        
        print(f"=== {idx+1}. Cluster: {cid} (Size: {size}, Mean Sim: {mean_sim:.3f}, Var: {var:.4f}) ===")
        
        # Get 3 representative reviews from this cluster
        # In a real system, we'd rank by cosine similarity to the centroid, 
        # but here we can just fetch the first 3 reviews for inspection.
        reviews = conn.execute("""
            SELECT raw_text, cleaned_text 
            FROM reviews 
            WHERE cluster_id = ? 
            LIMIT 3
        """, (cid,)).fetchall()
        
        for r_idx, r in enumerate(reviews):
            text = r["raw_text"].replace("\n", " ").strip()
            # Safe ASCII encoding to prevent Windows terminal UnicodeEncodeError
            text = text.encode("ascii", "ignore").decode("ascii")
            # Truncate text if too long
            if len(text) > 150:
                text = text[:147] + "..."
            print(f"  [{r_idx+1}] {text}")
        print()
        
    conn.close()

if __name__ == "__main__":
    main()
