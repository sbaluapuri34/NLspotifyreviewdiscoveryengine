import json
import sqlite3
from pathlib import Path
from backend.app.vectors.cluster import LeaderFollowerClustering

db_path = Path(__file__).resolve().parent.parent / "spotify_research.db"

def main():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, vector FROM embeddings")
    rows = cursor.fetchall()
    embeddings = {row[0]: json.loads(row[1]) for row in rows}
    conn.close()
    
    print(f"Loaded {len(embeddings)} embeddings. Sweeping thresholds...")
    
    for thresh in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        clustering = LeaderFollowerClustering(dimension=384, threshold=thresh)
        for rid, vec in embeddings.items():
            clustering.add_review(rid, vec)
            
        stats = clustering.get_cluster_stats()
        avg_size = len(embeddings) / len(stats) if stats else 0
        largest = stats[0]["size"] if stats else 0
        print(f"Threshold: {thresh:.2f} -> Clusters: {len(stats)}, Avg Size: {avg_size:.2f}, Largest: {largest}")

if __name__ == "__main__":
    main()
