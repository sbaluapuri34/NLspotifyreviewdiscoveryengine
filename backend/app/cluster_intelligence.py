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
        self.model_name = "llama-3.1-8b-instant"  # Groq's active fast Llama 3.1 8B model
        
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
2. Formulate the core Job-To-Be-Done (JTBD) user desire represented by this cluster using a structured situation-motivation-outcome format.
3. Identify specific user workarounds employed to bypass the friction points.
4. Extract 2 to 3 broad behavior/context categories as "sub_themes" (e.g., "Sonos casting", "playlist playback variety").
5. Decompose the feedback into 3 to 5 granular complaints/defects as "sub_issues", mapping each back to a parent sub-theme using an `associated_theme_id`.

Cluster ID: {cluster_id}
Key Themes: {themes_formatted}

User Reviews:
{reviews_formatted}

Analyze these reviews and group them into structured themes and granular sub-issues.
For each sub-theme, provide:
1. A unique `theme_id` (e.g., "theme_casting").
2. A descriptive `name` (e.g., "Multi-device Casting context").
3. A brief `description`.

For each sub-issue, provide:
1. A concise, descriptive `name` (e.g., "Smart Shuffle playing deleted songs").
2. The `associated_theme_id` matching one of your sub-themes.
3. A brief `description` of the issue.
4. The estimated `frequency_percentage` of this sub-issue within this cluster (must sum to approximately 100% across all sub-issues).
5. Up to 2 exact representative quotes from the reviews provided above.

You MUST respond with a JSON object matching this schema:
{{
  "cluster_name": "string",
  "jtbd": {{
    "situation": "string (e.g., When I am casting music to my speaker system for a social gathering)",
    "motivation": "string (e.g., I want to have a seamless, hands-free variety of recommended music)",
    "outcome": "string (e.g., so that I can enjoy the music without constantly checking my phone)"
  }},
  "workarounds": ["string"],
  "sub_themes": [
    {{
      "theme_id": "string",
      "name": "string",
      "description": "string"
    }}
  ],
  "sub_issues": [
    {{
      "name": "string",
      "associated_theme_id": "string",
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
