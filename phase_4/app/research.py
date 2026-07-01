import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from loguru import logger
from backend.app.config import GROQ_API_KEYS, DB_PATH
import sqlite3

# Define the 7 Core Research Questions
RESEARCH_QUESTIONS = {
    "RQ1": {
        "title": "Music Discovery Friction",
        "question": "What are the primary barriers users face when trying to find and discover new music on Spotify?"
    },
    "RQ2": {
        "title": "Algorithmic Repetition & Looping",
        "question": "To what extent do users experience repetition (looping of the same 5-10 songs) in automated mixes like Smart Shuffle and Daily Mixes?"
    },
    "RQ3": {
        "title": "Recommendation Algorithm Sentiment",
        "question": "What is the overall user sentiment toward Spotify's recommendation algorithms, and what drives dissatisfaction (e.g., echo chambers, mainstream bias)?"
    },
    "RQ4": {
        "title": "User Discovery Methods & Behaviors",
        "question": "What approaches and pathways (e.g., manual search, custom playlists, Discover Weekly, AI DJ) do users employ to discover new music?"
    },
    "RQ5": {
        "title": "Feature-Specific Performance",
        "question": "How do specific discovery features (Discover Weekly, Release Radar, Smart Shuffle, AI DJ) perform in terms of user satisfaction, and what are their primary complaints?"
    },
    "RQ6": {
        "title": "Physical Listening Contexts",
        "question": "How do physical environments (e.g., Car/Driving, Smart Home/Sonos casting, Gym, Commuting) impact the usability and effectiveness of Spotify's discovery features?"
    },
    "RQ7": {
        "title": "Monetization & Feature Access",
        "question": "How do free-tier restrictions and premium upselling influence the user's music discovery experience and overall satisfaction?"
    }
}

class ResearchEngine:
    def __init__(self, api_keys: Optional[List[str]] = None):
        self.api_keys = api_keys or GROQ_API_KEYS or [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.current_key_idx = 0
        self.model_name = "llama-3.3-70b-versatile"
        
    def route_clusters_to_rqs(self, evidence_packages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Routes each evidence package to the relevant Research Questions based on themes,
        explicit mentions, and behavioral tags.
        """
        routed = {rq_id: [] for rq_id in RESEARCH_QUESTIONS}
        
        for pkg in evidence_packages:
            cid = pkg.get("cluster_id", "")
            themes = [t[0].lower() for t in pkg.get("themes", [])]
            intents = [i.lower() for i in pkg.get("intents", [])]
            
            # Map to RQ1 (Discovery Friction)
            if any(x in themes or x in cid for x in ["discover", "find", "search", "stale", "slow", "freeze", "crash"]):
                routed["RQ1"].append(pkg)
                
            # Map to RQ2 (Repetition & Looping)
            if any(x in themes or x in cid for x in ["repeat", "repetition", "loop", "same", "shuffle", "shuffled"]):
                routed["RQ2"].append(pkg)
                
            # Map to RQ3 (Algorithm Sentiment)
            if any(x in themes or x in cid for x in ["algorithm", "recommend", "recommendation", "bias", "push"]):
                routed["RQ3"].append(pkg)
                
            # Map to RQ4 (Discovery Methods)
            if any(x in themes or x in cid for x in ["playlist", "search", "weekly", "dj", "autoplay"]):
                routed["RQ4"].append(pkg)
                
            # Map to RQ5 (Feature-Specific)
            if any(x in themes or x in cid for x in ["weekly", "radar", "shuffle", "dj", "daily"]):
                routed["RQ5"].append(pkg)
                
            # Map to RQ6 (Listening Contexts)
            if any(x in themes or x in cid for x in ["car", "driving", "home", "sonos", "casting", "gym", "workout", "offline"]):
                routed["RQ6"].append(pkg)
                
            # Map to RQ7 (Monetization)
            if any(x in themes or x in cid for x in ["premium", "free", "ad", "ads", "subscription", "pay"]):
                routed["RQ7"].append(pkg)
                
        return routed

    def synthesize_rq_answer(self, rq_id: str, relevant_packages: List[Dict[str, Any]], previous_answer: Optional[str] = None) -> Dict[str, Any]:
        """
        Calls Groq to synthesize or refine the answer to a specific Research Question
        using the routed evidence packages.
        """
        if not self.api_keys:
            logger.warning("ResearchEngine: No GROQ API keys configured. Returning empty answer.")
            return {"answer": "No API keys configured.", "confidence_score": 0.0}

        rq_info = RESEARCH_QUESTIONS[rq_id]
        
        # Serialize the evidence packages to a clean YAML-like string to save tokens
        evidence_str = ""
        for pkg in relevant_packages[:6]:  # Limit to top 6 most relevant clusters to save tokens to prevent rate limits
            evidence_str += f"- Cluster: {pkg.get('cluster_id')} (Size: {pkg.get('size')}, Avg Rating: {pkg.get('avg_rating')})\n"
            themes = [t[0] for t in pkg.get("themes", [])]
            evidence_str += f"  Themes: {', '.join(themes[:5])}\n"
            
            if "sub_issues" in pkg:
                evidence_str += "  Decomposed Sub-Issues:\n"
                for sub in pkg["sub_issues"]:
                    evidence_str += f"    * [{sub['frequency_percentage']}%] {sub['name']}\n"
                    
            # Include top 2 medoid quotes
            medoids = pkg.get("medoids", [])
            if medoids:
                evidence_str += "  Key Quotes:\n"
                for m in medoids[:2]:
                    quote = m.get("translated_text") or m.get("raw_text") or ""
                    evidence_str += f"    * \"{quote[:150]}...\"\n"
            evidence_str += "\n"

        refinement_context = ""
        if previous_answer:
            refinement_context = f"\nPREVIOUS ANSWER STATE:\n{previous_answer}\n\nPlease refine and update the previous answer based on the new evidence above. Do not discard valid historical synthesis unless the new evidence directly contradicts it.\n"

        prompt = f"""
You are a Principal Product Researcher analyzing Spotify user feedback.
Your goal is to synthesize a comprehensive, data-backed answer to a core Research Question.

RESEARCH QUESTION {rq_id}: {rq_info['title']}
{rq_info['question']}

EVIDENCE PACKAGES:
{evidence_str}
{refinement_context}

Please synthesize a highly professional, structured research answer.
Your response MUST be a JSON object matching this schema:
{{
  "rq_id": "string",
  "title": "string",
  "executive_summary": "string",
  "key_findings": [
    {{
      "finding": "string",
      "supporting_evidence": "string",
      "impact_rating": "High" | "Medium" | "Low"
    }}
  ],
  "actionable_opportunities": [
    {{
      "opportunity": "string",
      "unmet_need": "string",
      "proposed_feature": "string"
    }}
  ],
  "confidence_score": float
}}
Ensure the confidence_score is a float between 0.0 and 1.0, reflecting the volume and coherence of the supporting evidence.
Do not include any markdown formatting, backticks, or text outside the JSON object.
"""

        url = "https://api.groq.com/openai/v1/chat/completions"
        max_attempts = max(5, len(self.api_keys))
        
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
                logger.info(f"ResearchEngine: Calling Groq (Key Index {self.current_key_idx}) for {rq_id}...")
                response = httpx.post(url, json=payload, headers=headers, timeout=45.0)
                
                if response.status_code == 429:
                    logger.warning(f"Groq API Key index {self.current_key_idx} rate limited (HTTP 429). Sleeping 30s before retry...")
                    time.sleep(30.0)
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
                logger.info(f"ResearchEngine: Successfully synthesized answer for {rq_id} (Confidence: {data.get('confidence_score')}).")
                return data
                
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Attempt {attempt+1} failed with error: {e}. Rotating key...")
                self._rotate_key()
                
        logger.error(f"ResearchEngine: All configured Groq API keys failed or were rate limited for {rq_id}.")
        return {"rq_id": rq_id, "title": rq_info['title'], "executive_summary": "Failed to synthesize answer.", "key_findings": [], "actionable_opportunities": [], "confidence_score": 0.0}

    def _rotate_key(self):
        if len(self.api_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
            logger.info(f"ResearchEngine: Rotated to API key index {self.current_key_idx}")
            
    def save_answers_to_db(self, answers: Dict[str, Any]):
        """Saves or updates the synthesized research answers in the SQLite database."""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS research_answers (
                    rq_id TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    confidence_score REAL,
                    updated_at TEXT
                )
            """)
            
            for rq_id, data in answers.items():
                cursor.execute("""
                    INSERT INTO research_answers (rq_id, title, content, confidence_score, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(rq_id) DO UPDATE SET
                        title=excluded.title,
                        content=excluded.content,
                        confidence_score=excluded.confidence_score,
                        updated_at=datetime('now')
                """, (rq_id, data.get("title"), json.dumps(data), data.get("confidence_score", 0.0)))
                
            conn.commit()
            conn.close()
            logger.info("ResearchEngine: Successfully saved research answers to SQLite database.")
        except Exception as e:
            logger.error(f"ResearchEngine: Error saving research answers to database: {e}")
