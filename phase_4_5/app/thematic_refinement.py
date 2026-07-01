import os
import json
import time
import httpx
import numpy as np
from typing import List, Dict, Any, Optional
from loguru import logger
from backend.app.config import GROQ_API_KEYS, DB_PATH
from backend.app.vectors.embedder import VectorEmbedder

class ThematicRefinementEngine:
    def __init__(self, api_keys: Optional[List[str]] = None):
        # Load keys
        keys = api_keys or GROQ_API_KEYS or [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.api_keys = keys
        
        # Use the second key if available (api_key_2), otherwise fallback to the first
        if len(self.api_keys) > 1:
            self.api_key = self.api_keys[1]
            logger.info("ThematicRefinementEngine: Initialized with GROQ_API_KEY_2 (Index 1)")
        elif len(self.api_keys) == 1:
            self.api_key = self.api_keys[0]
            logger.warning("ThematicRefinementEngine: Only 1 Groq key found. Falling back to GROQ_API_KEY_1 (Index 0)")
        else:
            self.api_key = ""
            logger.warning("ThematicRefinementEngine: No Groq API keys found.")
            
        self.model_name = "llama-3.3-70b-versatile"
        self.embedder = VectorEmbedder()
        
    def extract_sub_themes(self, research_answers: List[Dict[str, Any]], reviews_pool: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calls Groq to analyze the Phase 4 research answers and propose granular sub-themes,
        mapping them to candidate review IDs.
        """
        if not self.api_key:
            logger.error("ThematicRefinementEngine: Groq API key is missing.")
            return {"refined_themes": []}

        # Format the research answers and review pool for the prompt
        answers_str = json.dumps(research_answers, indent=2)
        reviews_str = "\n".join([f"- [{r['id']}] {r['text']}" for r in reviews_pool[:50]])

        prompt = f"""
You are a Principal Product Researcher performing deep thematic refinement on Spotify user feedback.
Your task is to take the synthesized research answers and a pool of user reviews, and extract highly granular, niche sub-themes.

Research Answers (Phase 4):
{answers_str}

Candidate Reviews:
{reviews_str}

Please extract 3 to 6 highly specific, granular sub-themes.
For each sub-theme, provide:
1. A unique theme_id (e.g., "theme_1").
2. A descriptive name (e.g., "Smart Shuffle loops on Sonos casting").
3. A detailed description of the sub-theme.
4. The high-level Research Question category it belongs to (e.g., "Algorithmic Repetition & Looping").
5. A list of proposed_review_ids from the Candidate Reviews that belong to this sub-theme.

You MUST respond with a JSON object matching this schema:
{{
  "refined_themes": [
    {{
      "theme_id": "string",
      "name": "string",
      "description": "string",
      "category": "string",
      "proposed_review_ids": ["string"]
    }}
  ]
}}
Do not include any markdown formatting, backticks, or text outside the JSON object.
"""

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2
        }

        try:
            logger.info("ThematicRefinementEngine: Calling Groq to propose sub-themes...")
            response = httpx.post(url, json=payload, headers=headers, timeout=45.0)
            
            if response.status_code != 200:
                logger.error(f"Groq API returned status code {response.status_code}: {response.text}")
                return {"refined_themes": []}
                
            res_json = response.json()
            text_response = res_json['choices'][0]['message']['content']
            
            data = json.loads(text_response.strip())
            logger.info(f"ThematicRefinementEngine: Proposed {len(data.get('refined_themes', []))} sub-themes.")
            return data
        except Exception as e:
            logger.error(f"Error proposing sub-themes: {e}")
            return {"refined_themes": []}

    def validate_mappings(self, refined_themes: List[Dict[str, Any]], review_vectors: Dict[str, List[float]]) -> List[Dict[str, Any]]:
        """
        Double-Pass Validation Protocol:
        Embeds each sub-theme's description and calculates the cosine similarity against the
        vectors of the proposed reviews. Filters out any mappings with similarity < 0.60.
        """
        validated_themes = []
        
        for theme in refined_themes:
            theme_name = theme.get("name", "")
            theme_desc = theme.get("description", "")
            theme_text = f"{theme_name}: {theme_desc}"
            
            # Generate embedding for the theme
            theme_vector = np.array(self.embedder.embed_text(theme_text))
            theme_vector = theme_vector / np.linalg.norm(theme_vector)  # Normalize
            
            proposed_ids = theme.get("proposed_review_ids", [])
            verified_ids = []
            
            logger.info(f"ThematicRefinementEngine: Validating mappings for theme '{theme_name}'...")
            
            for rid in proposed_ids:
                if rid not in review_vectors:
                    logger.warning(f"  - Review ID {rid} vector not found. Skipping.")
                    continue
                    
                rev_vector = np.array(review_vectors[rid])
                rev_vector = rev_vector / np.linalg.norm(rev_vector)  # Normalize
                
                # Calculate cosine similarity
                similarity = float(np.dot(theme_vector, rev_vector))
                
                if similarity >= 0.60:
                    verified_ids.append(rid)
                    logger.debug(f"  - Review {rid}: VERIFIED (Sim: {similarity:.3f})")
                else:
                    logger.warning(f"  - Review {rid}: REJECTED (Sim: {similarity:.3f} < 0.60)")
                    
            theme["verified_review_ids"] = verified_ids
            validated_themes.append(theme)
            
        return validated_themes
