import math
import json
from typing import Dict, Any, Optional

class DataNormalizer:
    @staticmethod
    def calculate_engagement_weight(source: str, metadata: Dict[str, Any]) -> float:
        """
        Calculates the logarithmic user engagement weight (W_r) for a review/comment.
        Prevents viral posts from drowning out other reviews while reflecting endorsement.
        """
        if not metadata:
            return 1.0

        if source in ("google_play", "app_store"):
            thumbs_up = metadata.get("thumbs_up_count", metadata.get("thumbsUpCount", 0))
            return 1.0 + math.log1p(max(0, thumbs_up))

        elif source == "youtube":
            likes = metadata.get("like_count", metadata.get("likeCount", 0))
            return 1.0 + math.log1p(max(0, likes))

        elif source == "reddit":
            upvotes = metadata.get("upvotes", metadata.get("score", 0))
            # Determine if it's a post or a comment
            is_post = metadata.get("is_post", True)
            base_multiplier = 1.5 if is_post else 1.0
            return base_multiplier * (1.0 + math.log1p(max(0, upvotes)))

        elif source == "spotify_community":
            kudos = metadata.get("kudos_count", metadata.get("kudos", 0))
            return 1.0 + math.log1p(max(0, kudos))

        return 1.0

    @staticmethod
    def normalize_rating(source: str, raw_rating: Optional[int], metadata: Dict[str, Any]) -> Optional[int]:
        """
        Normalizes ratings from different platforms to a standard 1-5 scale.
        Returns None if no rating exists and cannot be inferred.
        """
        if raw_rating is not None:
            # Clamp between 1 and 5
            return max(1, min(5, int(raw_rating)))
            
        # For platforms without native ratings (YouTube, Reddit, Forums),
        # we can optionally infer a rating from sentiment or keep it as None.
        return None

    @staticmethod
    def standardize_review(raw_review: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizes a raw review dict from any source into the standardized SQLite schema.
        """
        source = raw_review.get("source", "unknown")
        raw_text = raw_review.get("raw_text", raw_review.get("text", ""))
        
        # Extract metadata
        metadata = raw_review.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
                
        # Calculate rating and weight
        raw_rating = raw_review.get("rating", raw_review.get("score"))
        rating = DataNormalizer.normalize_rating(source, raw_rating, metadata)
        weight = DataNormalizer.calculate_engagement_weight(source, metadata)
        
        # Ensure metadata has the weight stored
        metadata["engagement_weight"] = weight

        return {
            "id": raw_review.get("id"),
            "source": source,
            "raw_text": raw_text,
            "cleaned_text": raw_review.get("cleaned_text", ""),
            "translated_text": raw_review.get("translated_text", ""),
            "rating": rating,
            "sentiment": raw_review.get("sentiment", "neutral"),
            "location": raw_review.get("location"),
            "published_at": raw_review.get("published_at"),
            "metadata": json.dumps(metadata)
        }
