import re
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Set, Tuple, Optional
from loguru import logger
import numpy as np

# Try importing langdetect and deep-translator, with fallbacks
try:
    from langdetect import detect
except ImportError:
    logger.warning("langdetect not installed. Defaulting to English.")
    def detect(text): return "en"

try:
    from deep_translator import GoogleTranslator
except ImportError:
    logger.warning("deep-translator not installed. Translation will be skipped.")
    class GoogleTranslator:
        def __init__(self, source, target): pass
        def translate(self, text): return text

from backend.app.config import (
    MIN_WORD_COUNT,
    LSH_NUM_PERM,
    LSH_THRESHOLD,
    PRIORITY_ROUTING_KEYWORDS,
    INDIAN_LOCATIONS
)
from backend.app.cleaning import TextCleaner

# Allowed languages under our policy (English, Hindi, and Indian regional languages)
ALLOWED_LANGS = {"en", "hi", "bn", "gu", "kn", "ml", "mr", "pa", "ta", "te", "ur"}

# Broad set of common Hinglish vocabulary and stopwords
HINGLISH_KEYWORDS = {
    "hai", "h", "bhai", "achha", "acha", "bohot", "bahut", "ke", "ki", "ko", "se", "ka", 
    "yaar", "aap", "tum", "ho", "na", "hi", "bhi", "toh", "tha", "rha", "raha", "rhi", 
    "gaya", "ab", "kar", "kr", "kya", "karna", "karke", "likha", "sath", "saath", "aur", 
    "ya", "lekin", "par", "pe", "hota", "hote", "baje", "gaye", "diya", "liya", "kuch",
    "nahin", "nahi", "nahe", "aa", "rahe", "krta", "karta", "karti", "karte", "lagta", 
    "lagti", "lagte", "badhiya", "badiya", "mast", "bekar", "bakwas", "worse", "ads", 
    "song", "songs", "chal", "chala", "chalata", "chalati", "chalate", "hata", "do", 
    "de", "di", "sahi", "saza", "kam", "jyada", "zyada", "bhaut", "he", "hu", "hoon", 
    "thi", "the", "kro", "karo", "kyu", "kyon", "apna", "apni", "apne", "mera", "meri", 
    "mere", "mujhe", "mujhse", "humein", "hum", "sab", "log", "bro", "sir", "please", 
    "pls", "plz", "bhia", "hiii", "heee"
}

class TextPipeline:
    def __init__(self, priority_keywords: Optional[List[str]] = None):
        # LSH parameters: 16 bands of 8 rows = 128 permutations
        self.num_perm = LSH_NUM_PERM
        self.threshold = LSH_THRESHOLD
        self.num_bands = 16
        self.rows_per_band = 8
        assert self.num_bands * self.rows_per_band == self.num_perm
        
        # Save custom priority keywords
        self.priority_keywords = priority_keywords or PRIORITY_ROUTING_KEYWORDS
        
        # LSH tables: list of dicts, one dict per band
        # Each dict maps a band hash (string) to a list of (review_id, shingle_set)
        self.lsh_tables: List[Dict[str, List[Tuple[str, Set[str]]]]] = [{} for _ in range(self.num_bands)]
        
        # Delegate text cleaning tasks to the dedicated TextCleaner module
        self.cleaner = TextCleaner()
        
        # Stop words for summarization
        self.stop_words = {
            "the", "and", "a", "of", "to", "is", "in", "it", "i", "you", "that", "this", "on", "for", "with", 
            "as", "at", "by", "an", "be", "this", "my", "have", "with", "but", "not", "they", "was", "are"
        }

    def detect_language(self, text: str) -> str:
        """Detects the language of the text. Returns 'en' if detection fails."""
        if not text.strip():
            return "en"
        try:
            return detect(text)
        except Exception:
            return "en"

    def translate_to_english(self, text: str, source_lang: str) -> str:
        """Translates non-English text to English."""
        if source_lang == "en" or not text.strip():
            return text
        try:
            # For Hinglish, use 'hi' (Hindi) as the source, which Google Translate handles well in Latin script
            src = "hi" if "hinglish" in source_lang else source_lang
            translator = GoogleTranslator(source=src, target="en")
            translated = translator.translate(text)
            logger.debug(f"Translated [{source_lang} -> en]: {text[:30]}... -> {translated[:30]}...")
            return translated
        except Exception as e:
            logger.warning(f"Translation failed: {e}. Using original text.")
            return text

    def filter_pii_and_noise(self, text: str) -> str:
        """Removes emails, phone numbers, URLs, usernames, and emojis."""
        return self.cleaner.filter_pii_and_noise(text)

    def clean_text_preserve_negations(self, text: str) -> str:
        """Sanitizes text but preserves negations and punctuation relevant to sentiment."""
        return self.cleaner.clean_text_preserve_negations(text)

    def get_meaningful_word_count(self, text: str) -> int:
        """Calculates the number of words that are not stop words or punctuation."""
        return self.cleaner.get_meaningful_word_count(text)

    def matches_priority_keywords(self, text: str) -> bool:
        """Checks if the text contains any priority recommendation keywords."""
        lower_text = text.lower()
        for kw in self.priority_keywords:
            if kw in lower_text:
                return True
        return False

    def is_duplicate_lsh(self, review_id: str, text: str) -> bool:
        """
        Uses MinHash + LSH to detect if the text is a near-duplicate of an existing review.
        If it's NOT a duplicate, it indexes the review and returns False.
        If it IS a duplicate, it returns True.
        """
        # 1. Tokenize into 3-character shingles
        shingles = self._get_shingles(text)
        if not shingles:
            return False
            
        # 2. Compute MinHash signature (128 hash values)
        sig = self._compute_minhash_sig(shingles)
        
        # 3. Query LSH bands
        is_dup = False
        matching_id = None
        
        for band_idx in range(self.num_bands):
            start = band_idx * self.rows_per_band
            end = start + self.rows_per_band
            band_slice = tuple(sig[start:end])
            
            # Hash the band slice to a string key
            band_hash = hashlib.md5(str(band_slice).encode('utf-8')).hexdigest()
            
            # Check for collision in this band
            if band_hash in self.lsh_tables[band_idx]:
                for existing_id, existing_shingles in self.lsh_tables[band_idx][band_hash]:
                    # Verify using Jaccard Similarity
                    jaccard = len(shingles.intersection(existing_shingles)) / len(shingles.union(existing_shingles))
                    if jaccard >= self.threshold:
                        is_dup = True
                        matching_id = existing_id
                        break
            if is_dup:
                break
                
        # 4. If it's a duplicate, we don't index it
        if is_dup:
            logger.debug(f"Review {review_id} is a near-duplicate of {matching_id} (Jaccard >= {self.threshold})")
            return True
            
        # 5. If it's not a duplicate, index it in all bands
        for band_idx in range(self.num_bands):
            start = band_idx * self.rows_per_band
            end = start + self.rows_per_band
            band_slice = tuple(sig[start:end])
            band_hash = hashlib.md5(str(band_slice).encode('utf-8')).hexdigest()
            
            if band_hash not in self.lsh_tables[band_idx]:
                self.lsh_tables[band_idx][band_hash] = []
            self.lsh_tables[band_idx][band_hash].append((review_id, shingles))
            
        return False

    def _get_shingles(self, text: str, k: int = 3) -> Set[str]:
        """Generates k-character shingles from text."""
        clean = re.sub(r"\s+", "", text.lower())
        if len(clean) < k:
            return set()
        return {clean[i:i+k] for i in range(len(clean) - k + 1)}

    def _compute_minhash_sig(self, shingles: Set[str]) -> List[int]:
        """Computes the 128-integer MinHash signature for a set of shingles."""
        sig = [float('inf')] * self.num_perm
        for shingle in shingles:
            # We generate 128 hash values for this shingle using md5 + salting
            shingle_bytes = shingle.encode('utf-8')
            for i in range(self.num_perm):
                # Simple salting: hash(shingle + i)
                h = int(hashlib.md5(shingle_bytes + bytes([i])).hexdigest(), 16)
                if h < sig[i]:
                    sig[i] = h
        return sig

    def extract_location(self, text: str) -> Optional[str]:
        """Matches text against the Indian locations gazetteer, prioritizing cities over states."""
        lower_text = text.lower()
        
        states = {
            "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", 
            "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka", 
            "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", 
            "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", 
            "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal", 
            "jammu", "kashmir", "ladakh", "puducherry", "pondicherry", "chandigarh"
        }
        
        # Sort keys: cities first (not in states), then states.
        # Within each group, sort by length descending.
        sorted_keys = sorted(
            INDIAN_LOCATIONS.keys(),
            key=lambda k: (0 if k not in states else 1, -len(k))
        )
        
        for loc_key in sorted_keys:
            pattern = r"\b" + re.escape(loc_key) + r"\b"
            if re.search(pattern, lower_text):
                return INDIAN_LOCATIONS[loc_key]
        return None

    def compress_text_textrank(self, text: str, num_sentences: int = 3) -> str:
        """
        Extractive summarizer using a simple self-contained TextRank algorithm.
        Fits within 50 lines, no external heavy libraries required.
        """
        # Split text into sentences using simple punctuation splitting
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) <= num_sentences:
            return text
            
        # 1. Tokenize sentences and compute TF-IDF proxy (word frequencies)
        sentence_words = []
        all_words = []
        for s in sentences:
            words = re.findall(r"\b\w+\b", s.lower())
            words = [w for w in words if w not in self.stop_words]
            sentence_words.append(words)
            all_words.extend(words)
            
        vocab = list(set(all_words))
        if not vocab:
            return " ".join(sentences[:num_sentences])
            
        # 2. Build simple TF vectors
        vectors = []
        for words in sentence_words:
            vec = np.zeros(len(vocab))
            for w in words:
                vec[vocab.index(w)] += 1
            vectors.append(vec)
            
        # 3. Build cosine similarity matrix
        n = len(sentences)
        similarity_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                norm_i = np.linalg.norm(vectors[i])
                norm_j = np.linalg.norm(vectors[j])
                if norm_i > 0 and norm_j > 0:
                    similarity_matrix[i][j] = np.dot(vectors[i], vectors[j]) / (norm_i * norm_j)
                    
        # 4. Run PageRank power iteration (15 iterations, d=0.85)
        d = 0.85
        scores = np.ones(n)
        for _ in range(15):
            new_scores = np.zeros(n)
            for i in range(n):
                sum_link_weights = 0
                for j in range(n):
                    if j == i:
                        continue
                    # Outgoing links from j to i (symmetric in undirected graph)
                    total_j_out = np.sum(similarity_matrix[j])
                    if total_j_out > 0:
                        sum_link_weights += (similarity_matrix[j][i] / total_j_out) * scores[j]
                new_scores[i] = (1 - d) + d * sum_link_weights
            scores = new_scores
            
        # 5. Sort by score and pick top sentences, but keep original order
        top_indices = np.argsort(scores)[-num_sentences:]
        top_indices = sorted(top_indices)
        
        summary = " ".join([sentences[idx] for idx in top_indices])
        return summary

    def process_review(self, review: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Runs a review through the preprocessing pipeline:
        0. Date-filter (must be within 6 months / 180 days).
        1. Clean text (remove HTML, unicode quotes).
        2. Early Language Detection & Filtering (English, Hindi, Hinglish, Indian regional languages only).
        3. Translate to English if needed (Hindi/Hinglish/Indian regional languages).
        4. Remove PII & Emojis.
        5. Extract location.
        6. Length-filter (allow bypass if priority keywords match).
        7. Deduplicate (LSH).
        8. Compress if extremely long.
        
        Returns the processed review dict, or None if it was filtered out.
        """
        raw_text = review.get("raw_text", "").strip()
        if not raw_text:
            return None
            
        # 0. Date Filter (within 6 months / 180 days)
        pub_at_str = review.get("published_at")
        if pub_at_str:
            try:
                dt = datetime.fromisoformat(pub_at_str.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                diff = now - dt
                if diff.days > 180:
                    logger.debug(f"Review {review.get('id')} filtered out because it is older than 6 months ({diff.days} days old)")
                    return None
            except Exception as de:
                logger.warning(f"Error parsing date {pub_at_str} for 6-month filter: {de}")
            
        # 1. Clean Text
        cleaned = self.clean_text_preserve_negations(raw_text)
        
        # 2. Early Language Detection & Filtering
        lang = self.detect_language(cleaned)
        is_target = False
        if lang in ALLOWED_LANGS:
            is_target = True
        else:
            # Hinglish heuristic: check if any non-target language contains Hinglish keywords
            words = set(cleaned.lower().split())
            if words.intersection(HINGLISH_KEYWORDS):
                is_target = True
                lang = "hinglish"
                
        if not is_target:
            logger.debug(f"Review filtered out due to language policy ({lang}): {cleaned[:50]}")
            return None
            
        # 3. Translate if necessary
        translated = cleaned
        if lang != "en":
            translated = self.translate_to_english(cleaned, lang)
        
        # 4. Remove PII & Emojis
        sanitized = self.filter_pii_and_noise(translated)
        
        # 5. Extract location from the original and translated text
        location = self.extract_location(raw_text) or self.extract_location(sanitized)
        
        # 6. Length Filter & Priority Keyword Routing
        meaningful_count = self.get_meaningful_word_count(sanitized)
        is_priority = self.matches_priority_keywords(sanitized)
        
        if meaningful_count < MIN_WORD_COUNT and not is_priority:
            logger.debug(f"Review filtered out due to short length ({meaningful_count} words): {sanitized[:30]}")
            return None
            
        # 7. Deduplicate (LSH)
        review_id = review.get("id")
        if self.is_duplicate_lsh(review_id, sanitized):
            return None
            
        # 8. Compress if extremely long (e.g., > 150 words)
        words = sanitized.split()
        if len(words) > 150:
            compressed = self.compress_text_textrank(sanitized, num_sentences=3)
            logger.debug(f"Compressed long review ({len(words)} words) to: {compressed[:50]}...")
            sanitized = compressed
            
        return {
            "id": review_id,
            "raw_text": raw_text,
            "translated_text": sanitized if lang != "en" else None,
            "rating": review.get("rating"),
            "source": review.get("source"),
            "country": review.get("country"),
            "sentiment": None, # Will be computed in Level 2/3
            "location": location,
            "published_at": review.get("published_at"),
            "detected_language": lang
        }
