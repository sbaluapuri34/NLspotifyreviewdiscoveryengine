import numpy as np
from typing import List, Optional
from loguru import logger

class VectorEmbedder:
    """A fully local vector embedding generator using the SentenceTransformer 'all-MiniLM-L6-v2' model."""
    def __init__(self, corpus: Optional[List[str]] = None, mode: str = "local"):
        """Initializes the local SentenceTransformer embedder."""
        self.dimension = 384
        self.model = None
        self.mode = mode
        logger.info(f"VectorEmbedder: Initializing fully local SentenceTransformer ('all-MiniLM-L6-v2') on CPU (mode={mode}).")

    def embed_text(self, text: str) -> List[float]:
        """Generates a single embedding vector for a given text."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generates a batch of embedding vectors for a list of texts."""
        if not texts:
            return []

        cleaned_texts = [t.strip() if t.strip() else "empty review" for t in texts]

        # Lazy load the model to save memory if not called immediately
        if not self.model:
            from sentence_transformers import SentenceTransformer
            logger.info("VectorEmbedder: Loading local SentenceTransformer ('all-MiniLM-L6-v2') on CPU...")
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Generate embeddings
        embeddings = self.model.encode(cleaned_texts, convert_to_numpy=True)
        
        # L2 Normalize vectors
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normalized = embeddings / norms
        
        return normalized.tolist()
