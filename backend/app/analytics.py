import re
import json
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger
from backend.app.config import INDIAN_LOCATIONS

# ---------------------------------------------------------
# 1. Semantic Anchor Projection (SAP)
# ---------------------------------------------------------

ANCHOR_PHRASES = {
    "goal_play_music": "play music listen to songs streaming audio",
    "goal_discover": "discover new music find new artists recommendations",
    "method_playlist": "my playlist custom playlist curation song list",
    "method_algorithmic": "discover weekly release radar smart shuffle daily mix ai dj autoplay recommendation",
    "method_search": "search bar find song search artist manual search type song",
    "context_car": "driving carplay android auto bluetooth car in the car road trip vehicle steering wheel",
    "context_home": "smart speaker alexa google home sonos casting tv smart home chromecast speaker",
    "context_gym": "workout gym running exercise training lifting fitness treadmill cardio",
    "context_work": "focus studying working office concentration coding writing thinking study",
    "context_commute": "bus train metro subway walking commuting transit travel passenger",
    "emotion_anger": "terrible worst garbage trash hate useless irritating annoying broken laggy crash freeze",
    "emotion_joy": "amazing love perfect great best awesome excellent happy wonderful beautiful smooth",
    "frustration_ads": "ads every two songs unskippable ads commercial interruption too many ads advertising",
    "frustration_repetition": "repetition same songs repeating loop shuffle playing same tracks over and over",
    "frustration_bugs": "crashes keeps stopping buggy update glitch frozen error loading offline",
    "workaround_reinstall": "clear cache reinstall restart uninstall login logout downgrade version",
    "feature_request_playlist": "playlist limit increase folders sorting custom cover playlist description",
    "churn_indicator": "uninstalling canceling subscription switching to youtube going to apple music quitting leaving",
    "competitor_youtube": "youtube music yt music premium adblock",
    "competitor_apple": "apple music amzn music prime wynk jiosaavn"
}

class SemanticAnchorProjector:
    def __init__(self, embedder, custom_anchors: Optional[Dict[str, str]] = None):
        """Initializes the projector by pre-embedding the semantic anchors."""
        self.embedder = embedder
        self.anchors = {}
        logger.info("SemanticAnchorProjector: Pre-embedding semantic anchors...")
        
        # Embed all anchors
        target_anchors = custom_anchors or ANCHOR_PHRASES
        names = list(target_anchors.keys())
        phrases = list(target_anchors.values())
        vectors = self.embedder.embed_batch(phrases)
        
        for name, vec in zip(names, vectors):
            self.anchors[name] = np.array(vec, dtype=np.float32)
        logger.info(f"SemanticAnchorProjector: Embedded {len(self.anchors)} anchors successfully.")

    def project(self, vector: List[float], threshold: float = 0.35) -> List[str]:
        """
        Projects a review vector against the anchor matrix.
        Returns a list of tags that exceed the similarity threshold.
        """
        v_arr = np.array(vector, dtype=np.float32)
        norm = np.linalg.norm(v_arr)
        if norm > 0:
            v_arr = v_arr / norm
            
        tags = []
        for name, anchor_vec in self.anchors.items():
            sim = float(np.dot(v_arr, anchor_vec))
            if sim >= threshold:
                tags.append(name)
        return tags


# ---------------------------------------------------------
# 2. c-TF-IDF Theme Extractor
# ---------------------------------------------------------

class ClusterTfidfExtractor:
    def __init__(self, stop_words: Optional[set] = None, priority_words: Optional[set] = None):
        self.stop_words = stop_words or {
            "the", "and", "a", "of", "to", "is", "in", "it", "i", "you", "that", "this", "on", "for", "with", 
            "as", "at", "by", "an", "be", "this", "my", "have", "with", "but", "not", "they", "was", "are"
        }
        # Seed keywords to prioritize recommendation terms
        self.priority_words = priority_words or {
            "shuffle", "recommendation", "recommendations", "recommend", "playlist", "playlists", 
            "discover", "weekly", "radar", "mix", "dj", "ads", "premium", "song", "songs", "music"
        }

    def extract_themes(
        self, 
        cluster_reviews: List[str], 
        all_clusters_reviews: List[List[str]], 
        top_k: int = 10,
        precomputed_df: Optional[Dict[str, int]] = None,
        precomputed_avg_words: Optional[float] = None
    ) -> List[Tuple[str, float]]:
        """
        Calculates c-TF-IDF weights for terms in a target cluster.
        Returns the top_k terms with their weights.
        """
        import re
        from collections import Counter
        
        def tokenize(text):
            return re.findall(r'\b[a-z]{3,15}\b', text.lower())

        # Count term frequencies in the target cluster
        target_tokens = []
        for r in cluster_reviews:
            target_tokens.extend(tokenize(r))
        
        target_tf = Counter([t for t in target_tokens if t not in self.stop_words])
        if not target_tf:
            return []

        # Count document (cluster) frequencies across all clusters
        if precomputed_df is not None:
            cluster_df = precomputed_df
            avg_words_per_cluster = precomputed_avg_words or 1.0
        else:
            cluster_df = Counter()
            for c_revs in all_clusters_reviews:
                unique_words = set()
                for r in c_revs:
                    unique_words.update(tokenize(r))
                for w in unique_words:
                    if w not in self.stop_words:
                        cluster_df[w] += 1
            avg_words_per_cluster = np.mean([sum(len(tokenize(r)) for r in c_revs) for c_revs in all_clusters_reviews]) or 1.0

        # Calculate c-TF-IDF
        themes = []
        for term, tf in target_tf.items():
            df_val = cluster_df.get(term, 1)
            # c-TF-IDF formula
            idf = np.log(1 + (avg_words_per_cluster / df_val))
            score = tf * idf
            
            # Boost priority words
            if term in self.priority_words:
                score *= 1.5
                
            themes.append((term, float(score)))

        # Sort by score descending
        return sorted(themes, key=lambda x: x[1], reverse=True)[:top_k]


# ---------------------------------------------------------
# 3. Location & Text Extraction Helpers
# ---------------------------------------------------------

def extract_indian_locations(text: str) -> List[str]:
    """Extracts Indian states/cities mentioned in the text using the gazetteer."""
    text_lower = text.lower()
    matched = []
    for keyword, standard_name in INDIAN_LOCATIONS.items():
        # Match word boundaries to avoid partial matches
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            matched.append(standard_name)
    return list(set(matched))


# ---------------------------------------------------------
# 4. Evidence Package Compiler & Prioritization
# ---------------------------------------------------------

class EvidencePackageCompiler:
    @staticmethod
    def calculate_csss(sources_counts: Dict[str, int], mean_similarity: float) -> float:
        """
        Calculates the Cross-Source Synergy Score (CSSS).
        CSSS = Normalized Source Entropy * Mean Similarity
        """
        total = sum(sources_counts.values())
        if total == 0:
            return 0.0
            
        entropy = 0.0
        for count in sources_counts.values():
            if count > 0:
                p = count / total
                entropy -= p * np.log2(p)
                
        # Normalize by maximum possible entropy (log2 of active sources)
        active_sources = sum(1 for count in sources_counts.values() if count > 0)
        if active_sources <= 1:
            return 0.0
            
        max_entropy = np.log2(active_sources)
        normalized_entropy = entropy / max_entropy
        
        return float(normalized_entropy * mean_similarity)

    @staticmethod
    def calculate_opportunity_score(
        size: int,
        total_reviews: int,
        avg_rating: float,
        csss: float,
        churn_ratio: float,
        premium_ratio: float
    ) -> float:
        """
        Calculates the Opportunity Prioritization Score.
        Score = Severity * Frequency * CSSS * Business Impact
        """
        if total_reviews == 0:
            return 0.0
            
        frequency = size / total_reviews
        
        # Severity: lower ratings mean higher severity (scale 0.1 to 1.0)
        severity = (5.0 - avg_rating) / 4.0
        severity = max(0.1, min(1.0, severity))
        
        # Business Impact: higher if churn mentions or premium users are affected
        business_impact = 1.0 + (0.5 * churn_ratio) + (0.5 * premium_ratio)
        
        score = severity * frequency * csss * business_impact
        # Scale to 0-100 range for readability
        return float(score * 100)

    @staticmethod
    def compile_package(
        cluster_id: str,
        cluster_data: Dict[str, Any],
        reviews: List[Dict[str, Any]],
        embeddings: Dict[str, List[float]],
        all_clusters_reviews: List[List[str]],
        projector: SemanticAnchorProjector,
        tfidf_extractor: ClusterTfidfExtractor,
        total_reviews_in_db: int,
        precomputed_df: Optional[Dict[str, int]] = None,
        precomputed_avg_words: Optional[float] = None
    ) -> Dict[str, Any]:
        """Compiles the complete Level 2 Evidence Package for a cluster."""
        size = len(reviews)
        if size == 0:
            return {}

        # 1. Basic Stats
        ratings = [r["rating"] for r in reviews if r.get("rating") is not None]
        avg_rating = np.mean(ratings) if ratings else 3.0
        
        sources = [r["source"] for r in reviews]
        source_counts = {s: sources.count(s) for s in set(sources)}
        
        # 2. Extract Location Mentions
        locations = []
        for r in reviews:
            locations.extend(extract_indian_locations(r["translated_text"] or r["raw_text"]))
        location_counts = {loc: locations.count(loc) for loc in set(locations)}

        # 3. Project Vectors & Aggregate Tags (SAP)
        tag_counts = {}
        premium_count = 0
        for r in reviews:
            # Check if premium user (heuristic or explicit metadata)
            meta = r.get("metadata")
            is_premium = False
            if meta:
                try:
                    meta_dict = json.loads(meta) if isinstance(meta, str) else meta
                    if meta_dict.get("is_premium") or "premium" in str(meta_dict).lower():
                        is_premium = True
                except Exception:
                    pass
            if "premium" in (r["translated_text"] or r["raw_text"]).lower():
                is_premium = True
            if is_premium:
                premium_count += 1

            vec = embeddings.get(r["id"])
            if vec:
                tags = projector.project(vec)
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        tag_ratios = {tag: count / size for tag, count in tag_counts.items()}
        churn_ratio = tag_ratios.get("churn_indicator", 0.0)
        premium_ratio = premium_count / size

        # 4. Calculate Scores
        mean_sim = cluster_data.get("mean_similarity", 0.80)
        csss = EvidencePackageCompiler.calculate_csss(source_counts, mean_sim)
        opp_score = EvidencePackageCompiler.calculate_opportunity_score(
            size, total_reviews_in_db, avg_rating, csss, churn_ratio, premium_ratio
        )

        # 5. Extract Themes (c-TF-IDF)
        cluster_texts = [r["cleaned_text"] or r["translated_text"] or r["raw_text"] for r in reviews]
        themes = tfidf_extractor.extract_themes(
            cluster_texts, 
            all_clusters_reviews, 
            precomputed_df=precomputed_df, 
            precomputed_avg_words=precomputed_avg_words
        )

        # 6. Select Medoid and Outliers
        centroid = np.array(cluster_data["centroid"], dtype=np.float32)
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm > 0:
            centroid = centroid / centroid_norm

        review_similarities = []
        for r in reviews:
            vec = embeddings.get(r["id"])
            if vec:
                v_arr = np.array(vec, dtype=np.float32)
                v_norm = np.linalg.norm(v_arr)
                if v_norm > 0:
                    v_arr = v_arr / v_norm
                sim = float(np.dot(v_arr, centroid))
                review_similarities.append((r, sim))

        # Sort by similarity descending
        sorted_reviews = sorted(review_similarities, key=lambda x: x[1], reverse=True)
        
        medoids = [x[0] for x in sorted_reviews[:5]]
        outliers = [x[0] for x in sorted_reviews[-3:]] if len(sorted_reviews) >= 3 else []
        
        # Identify anomalies: reviews in this cluster with rating = 5 but average rating is low,
        # or rating = 1 but average rating is high (opposite sentiment)
        anomalies = []
        for r, sim in sorted_reviews:
            rating = r.get("rating")
            if rating is not None:
                if avg_rating >= 4.0 and rating <= 2:
                    anomalies.append(r)
                elif avg_rating <= 2.5 and rating >= 4:
                    anomalies.append(r)
        
        return {
            "cluster_id": cluster_id,
            "size": size,
            "average_rating": float(avg_rating),
            "mean_similarity": float(mean_sim),
            "variance": float(cluster_data.get("variance", 0.0)),
            "csss": csss,
            "opportunity_score": opp_score,
            "source_distribution": source_counts,
            "location_distribution": location_counts,
            "tag_distribution": tag_counts,
            "premium_ratio": premium_ratio,
            "themes": themes,
            "medoids": medoids,
            "outliers": outliers,
            "anomalies": anomalies[:3]
        }


# ---------------------------------------------------------
# 5. Dynamic Filter Query Engine
# ---------------------------------------------------------

class DynamicFilterEngine:
    def __init__(self, db_conn, embedder, custom_anchors: Optional[Dict[str, str]] = None, priority_words: Optional[set] = None):
        self.conn = db_conn
        self.embedder = embedder
        self.projector = SemanticAnchorProjector(embedder, custom_anchors)
        self.tfidf_extractor = ClusterTfidfExtractor(priority_words=priority_words)

    def get_filtered_analytics(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        sources: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Queries reviews matching filters, groups them by their assigned cluster_id,
        and re-calculates all Evidence Packages on-the-fly.
        """
        # 1. Build Query
        query = "SELECT * FROM reviews WHERE cluster_id IS NOT NULL"
        params = {}
        
        if from_date:
            query += " AND published_at >= :from_date"
            params["from_date"] = from_date
        if to_date:
            query += " AND published_at <= :to_date"
            params["to_date"] = to_date
        if sources:
            placeholders = [f":source_{i}" for i in range(len(sources))]
            query += f" AND source IN ({', '.join(placeholders)})"
            for i, src in enumerate(sources):
                params[f"source_{i}"] = src
                
        query += " ORDER BY published_at DESC"
        
        if limit:
            query += " LIMIT :limit"
            params["limit"] = limit

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        reviews = [dict(row) for row in cursor.fetchall()]
        
        if not reviews:
            return []

        total_reviews = len(reviews)

        # 2. Fetch Embeddings
        review_ids = [r["id"] for r in reviews]
        embeddings = {}
        # Query in chunks to avoid SQLite parameter limits
        chunk_size = 999
        for i in range(0, len(review_ids), chunk_size):
            chunk = review_ids[i:i+chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            emb_cursor = self.conn.cursor()
            emb_cursor.execute(f"SELECT id, vector FROM embeddings WHERE id IN ({placeholders})", chunk)
            for row in emb_cursor.fetchall():
                embeddings[row[0]] = json.loads(row[1])

        # 3. Group reviews by cluster_id
        cluster_groups = {}
        for r in reviews:
            cid = r["cluster_id"]
            if cid not in cluster_groups:
                cluster_groups[cid] = []
            cluster_groups[cid].append(r)

        # 4. Load Cluster Centroids and Metadata
        cluster_metadata = {}
        meta_cursor = self.conn.cursor()
        meta_cursor.execute("SELECT id, centroid, mean_similarity, variance FROM clusters")
        for row in meta_cursor.fetchall():
            cluster_metadata[row[0]] = {
                "centroid": json.loads(row[1]),
                "mean_similarity": row[2],
                "variance": row[3]
            }

        # 5. Compile all cluster reviews for c-TF-IDF background corpus
        all_clusters_texts = []
        for cid, revs in cluster_groups.items():
            all_clusters_texts.append([r["cleaned_text"] or r["translated_text"] or r["raw_text"] for r in revs])

        # Precompute c-TF-IDF document frequencies for massive speedup
        from collections import Counter
        import re
        def tokenize(text):
            return re.findall(r'\b[a-z]{3,15}\b', text.lower())
            
        precomputed_df = Counter()
        stop_words = self.tfidf_extractor.stop_words
        words_counts = []
        
        for c_revs in all_clusters_texts:
            unique_words = set()
            total_words = 0
            for r in c_revs:
                tokens = tokenize(r)
                unique_words.update(tokens)
                total_words += len(tokens)
            words_counts.append(total_words)
            for w in unique_words:
                if w not in stop_words:
                    precomputed_df[w] += 1
                    
        precomputed_avg_words = float(np.mean(words_counts)) if words_counts else 1.0

        # 6. Compile Evidence Packages
        packages = []
        for cid, revs in cluster_groups.items():
            meta = cluster_metadata.get(cid, {
                # Fallback if cluster row is missing
                "centroid": embeddings.get(revs[0]["id"], [0.0]*384),
                "mean_similarity": 0.80,
                "variance": 0.0
            })
            pkg = EvidencePackageCompiler.compile_package(
                cluster_id=cid,
                cluster_data=meta,
                reviews=revs,
                embeddings=embeddings,
                all_clusters_reviews=all_clusters_texts,
                projector=self.projector,
                tfidf_extractor=self.tfidf_extractor,
                total_reviews_in_db=total_reviews,
                precomputed_df=precomputed_df,
                precomputed_avg_words=precomputed_avg_words
            )
            if pkg:
                packages.append(pkg)

        # Sort by opportunity score descending
        return sorted(packages, key=lambda x: x["opportunity_score"], reverse=True)
