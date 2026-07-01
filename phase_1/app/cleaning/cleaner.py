import re
from typing import Set

class TextCleaner:
    def __init__(self):
        # Precompiled regexes for PII and noise
        self.email_regex = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
        self.phone_regex = re.compile(r"\+?\d{1,4}[-.\s]?\(?\d{1,3}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}")
        self.url_regex = re.compile(r"https?://\S+|www\.\S+")
        self.username_regex = re.compile(r"@[a-zA-Z0-9_]+|u/[a-zA-Z0-9_-]+")
        self.emoji_regex = re.compile(r"[\U00010000-\U0010ffff]+", flags=re.UNICODE)
        
        # Stop words for length filtering
        self.stop_words = {
            "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", 
            "to", "for", "of", "in", "on", "at", "by", "this", "that", "it", 
            "with", "as", "i", "you", "he", "she", "they", "we", "my", "your"
        }

    def filter_pii_and_noise(self, text: str) -> str:
        """Removes emails, phone numbers, URLs, usernames, and emojis."""
        if not text:
            return ""
        text = self.email_regex.sub("", text)
        text = self.phone_regex.sub("", text)
        text = self.url_regex.sub("", text)
        text = self.username_regex.sub("", text)
        text = self.emoji_regex.sub("", text)
        # Clean up excess whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def clean_text_preserve_negations(self, text: str) -> str:
        """Sanitizes text but preserves negations and punctuation relevant to sentiment."""
        if not text:
            return ""
        # Strip HTML tags (common in Spotify Community Forum scrapes)
        text = re.sub(r"<[^>]*>", "", text)
        # Replace curly quotes with straight quotes
        text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
        return text

    def get_meaningful_word_count(self, text: str) -> int:
        """Calculates the number of words that are not stop words or punctuation."""
        if not text:
            return 0
        words = re.findall(r"\b\w+\b", text.lower())
        meaningful_words = [w for w in words if w not in self.stop_words]
        return len(meaningful_words)
