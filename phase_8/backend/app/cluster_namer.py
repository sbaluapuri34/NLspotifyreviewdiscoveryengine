import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from loguru import logger
from backend.app.config import GROQ_API_KEYS

class BatchClusterNamer:
    def __init__(self, api_keys: Optional[List[str]] = None):
        self.api_keys = api_keys or GROQ_API_KEYS or [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.current_key_idx = 0
        self.model_name = "llama-3.3-70b-versatile"

    def _rotate_key(self):
        if len(self.api_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
            logger.info(f"BatchClusterNamer: Rotated to API key index {self.current_key_idx}")

    def name_batch(self, batch_data: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Names a batch of clusters (up to 25) in a single LLM call to optimize speed and cost.
        """
        if not self.api_keys:
            logger.warning("BatchClusterNamer: No Groq API keys configured. Returning empty mapping.")
            return {}

        prompt = f"""
You are an expert AI Product Researcher analyzing Spotify user feedback.
For each of the following feedback clusters, analyze its key themes and representative reviews, and:
1. Generate a short, descriptive, professional name/title (max 4-6 words) specific to the core issue (e.g., "Smart Shuffle Loop on Sonos").
2. Formulate the core Job-To-Be-Done (JTBD) user desire using a situation-motivation-outcome format.
3. Identify specific user workarounds.
4. Extract 1 to 2 broad behavior/context categories as "sub_themes".
5. Decompose the cluster into 2-3 specific "sub_issues", mapping each back to a parent sub-theme using an `associated_theme_id`.

You MUST respond with a JSON object mapping each cluster_id to its structured results:
{{
  "cluster_id": {{
    "name": "Cluster Name",
    "jtbd": {{
      "situation": "string",
      "motivation": "string",
      "outcome": "string"
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
        "frequency_percentage": float
      }}
    ]
  }}
}}

Do not include any markdown formatting, backticks, or text outside the JSON object.

Clusters to analyze:
{json.dumps(batch_data, indent=2)}
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
                "temperature": 0.1
            }

            try:
                logger.info(f"BatchClusterNamer: Calling Groq (Key Index {self.current_key_idx}) for batch of {len(batch_data)} clusters...")
                response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
                
                if response.status_code == 429:
                    logger.warning(f"Groq API Key rate limited (HTTP 429). Rotating...")
                    time.sleep(5.0)
                    self._rotate_key()
                    continue
                elif response.status_code != 200:
                    logger.error(f"Groq API returned status {response.status_code}: {response.text}. Rotating...")
                    self._rotate_key()
                    continue
                    
                res_json = response.json()
                text_response = res_json['choices'][0]['message']['content']
                
                # Parse mapping
                mapping = json.loads(text_response.strip())
                logger.info(f"BatchClusterNamer: Successfully named {len(mapping)} clusters.")
                return mapping
                
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Attempt {attempt+1} failed with error: {e}. Rotating...")
                self._rotate_key()
                
        return {}
