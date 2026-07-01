import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from loguru import logger
from backend.app.config import GROQ_API_KEYS

class ClusterIntelligenceEngine:
    def __init__(self, api_keys: Optional[List[str]] = None):
        # Load keys from config or environment
        self.api_keys = api_keys if api_keys is not None else (GROQ_API_KEYS or [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()])
        self.current_key_idx = 0
        self.model_name = "llama-3.3-70b-versatile"  # Groq's active high-capacity Llama 3.3 model
        
    def decompose_cluster(self, cluster_id: str, themes: List[str], reviews: List[str]) -> Dict[str, Any]:
        """
        Calls the Groq API to decompose a cluster of reviews into 3-5 distinct sub-issues.
        Supports automatic rotation across multiple API keys in case of rate limits or failures.
        """
        if not self.api_keys:
            logger.warning("ClusterIntelligenceEngine: No GROQ API keys configured. Returning empty sub-issues.")
            return {"sub_issues": []}

        # Format the reviews for the prompt (limit to top 30 reviews to stay within context/token budgets)
        reviews_formatted = "\n".join([f"- {r}" for r in reviews[:30]])
        themes_formatted = ", ".join(themes)

        prompt = f"""
You are an expert AI Product Researcher analyzing user feedback for Spotify.
Your task is to analyze a semantic cluster of user reviews and:
1. Generate a short, descriptive, professional name/title for the cluster (e.g., "Smart Shuffle Loop on Sonos" or "Discover Weekly Recommendation Stale"). Max 5-7 words.
2. Decompose the cluster into 3 to 5 distinct, granular sub-issues.

Cluster ID: {cluster_id}
Key Themes: {themes_formatted}

User Reviews:
{reviews_formatted}

Analyze these reviews and group them into 3 to 5 highly specific sub-issues.
For each sub-issue, provide:
1. A concise, descriptive name (e.g., "Smart Shuffle playing deleted songs").
2. A brief description of the issue.
3. The estimated frequency percentage of this sub-issue within this cluster (must sum to approximately 100% across all sub-issues).
4. Up to 2 exact representative quotes from the reviews provided above.

You MUST respond with a JSON object matching this schema:
{{
  "cluster_name": "string",
  "sub_issues": [
    {{
      "name": "string",
      "description": "string",
      "frequency_percentage": float,
      "representative_quotes": ["string"]
    }}
  ]
}}
Do not include any markdown formatting, backticks, or text outside the JSON object.
"""

        url = "https://api.groq.com/openai/v1/chat/completions"
        max_attempts = len(self.api_keys)
        
        for attempt in range(max_attempts):
            api_key = self.api_keys[self.current_key_idx]
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
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
                logger.info(f"ClusterIntelligenceEngine: Calling Groq (Key Index {self.current_key_idx}) for {cluster_id}...")
                response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
                
                # Check for rate limit (429) or other server errors
                if response.status_code == 429:
                    logger.warning(f"Groq API Key index {self.current_key_idx} rate limited (HTTP 429). Sleeping 10s before retry...")
                    time.sleep(10.0)
                    self._rotate_key()
                    continue
                elif response.status_code != 200:
                    logger.error(f"Groq API returned status code {response.status_code}: {response.text}. Rotating key...")
                    self._rotate_key()
                    continue
                    
                res_json = response.json()
                text_response = res_json['choices'][0]['message']['content']
                
                # Parse response
                data = json.loads(text_response.strip())
                logger.info(f"ClusterIntelligenceEngine: Successfully decomposed {cluster_id} into {len(data.get('sub_issues', []))} sub-issues.")
                return data
                
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Attempt {attempt+1} failed with error: {e}. Rotating key...")
                self._rotate_key()
                
        logger.error("ClusterIntelligenceEngine: All configured Groq API keys failed or were rate limited.")
        return {"sub_issues": []}

    def _rotate_key(self):
        """Rotates to the next API key in the list."""
        if len(self.api_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
            logger.info(f"ClusterIntelligenceEngine: Rotated to API key index {self.current_key_idx}")
