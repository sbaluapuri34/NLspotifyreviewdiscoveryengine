import os
import json
import time
import httpx
import sqlite3
from typing import List, Dict, Any, Optional
from loguru import logger
from pathlib import Path
from backend.app.config import GROQ_API_KEYS, DB_PATH

class ResearchValidator:
    def __init__(self, api_keys: Optional[List[str]] = None, db_path: str = DB_PATH):
        self.api_keys = api_keys or GROQ_API_KEYS or [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.current_key_idx = 0
        self.model_name = "llama-3.3-70b-versatile"
        self.db_path = db_path
        
        # Load dynamic theme config if it exists
        self.theme_config = None
        theme_config_path = os.environ.get("THEME_CONFIG_PATH")
        if theme_config_path and Path(theme_config_path).exists():
            try:
                with open(theme_config_path, "r", encoding="utf-8") as f:
                    self.theme_config = json.load(f)
                logger.info(f"ResearchValidator: Loaded dynamic theme configuration for: {self.theme_config.get('theme')}")
            except Exception as e:
                logger.error(f"ResearchValidator: Error loading theme configuration JSON: {e}")

    def _rotate_key(self):
        if len(self.api_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
            logger.info(f"ResearchValidator: Rotated to API key index {self.current_key_idx}")

    def validate_and_synthesize(self) -> Dict[str, Any]:
        """
        Consumes:
        1. Aggregated Analytics Metrics (from compiled_analytics_report table)
        2. Evidence Packages (from compiled_evidence_packages.json)
        3. Cluster Intelligence (from decomposed_themes or sqlite)
        4. Research Question Answers (from research_answers table)
        
        Runs the LLM to validate the research and generate executive insights.
        """
        if not self.api_keys:
            logger.warning("ResearchValidator: No GROQ API keys configured. Skipping LLM validation.")
            return {}

        # 1. Load data from DB / Files
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Load metrics
        metrics = {}
        cursor.execute("SELECT report_json FROM compiled_analytics_report WHERE id = 'latest'")
        row = cursor.fetchone()
        if row:
            metrics = json.loads(row["report_json"])

        # Load RQs
        rq_answers = []
        cursor.execute("SELECT rq_id, title, content, confidence_score FROM research_answers")
        for r in cursor.fetchall():
            content = json.loads(r["content"])
            rq_answers.append({
                "rq_id": r["rq_id"],
                "title": r["title"],
                "confidence_score": r["confidence_score"],
                "executive_summary": content.get("executive_summary", ""),
                "key_findings": content.get("key_findings", []),
                "actionable_opportunities": content.get("actionable_opportunities", [])
            })

        # Load Evidence Packages
        theme_slug = self.theme_config.get("theme_slug") if self.theme_config else None
        suffix = f"_{theme_slug}" if theme_slug else ""
        evidence_packages = []
        packages_filename = f"compiled_evidence_packages{suffix}.json"
        packages_path = Path(self.db_path).parent / "scripts" / packages_filename
        if packages_path.exists():
            try:
                with open(packages_path, "r", encoding="utf-8") as f:
                    evidence_packages = json.load(f)
            except Exception as e:
                logger.warning(f"ResearchValidator: Could not load {packages_filename}: {e}")

        conn.close()

        # Compile a compact representation for the LLM to stay within token limits
        metrics_summary = {
            "total_reviews": metrics.get("split_ratio", {}).get("total_reviews", 0),
            "discovery_related_count": metrics.get("split_ratio", {}).get("discovery_related", {}).get("count", 0),
            "discovery_related_percentage": metrics.get("split_ratio", {}).get("discovery_related", {}).get("percentage", 0),
            "device_distribution_global": metrics.get("device_distribution", {}).get("global", []),
            "device_distribution_discovery": metrics.get("device_distribution", {}).get("discovery", []),
            "source_distribution": metrics.get("source_distribution", [])
        }

        # Clusters summary
        clusters_summary = []
        for pkg in evidence_packages[:10]: # Top 10 clusters
            clusters_summary.append({
                "cluster_id": pkg.get("cluster_id"),
                "cluster_name": pkg.get("cluster_name") or pkg.get("cluster_id"),
                "size": pkg.get("size"),
                "average_rating": pkg.get("average_rating"),
                "csss": pkg.get("csss"),
                "opportunity_score": pkg.get("opportunity_score"),
                "themes": [t[0] for t in pkg.get("themes", [])[:5]],
                "jtbd": pkg.get("jtbd", {}),
                "workarounds": pkg.get("workarounds", [])
            })

        # Prompt
        prompt = f"""
You are a Lead Research Validator and Executive Insight Generator analyzing Spotify user feedback.
Your goal is to perform high-level research validation and synthesis based on the compiled metrics, cluster intelligence (including Jobs-to-be-Done and workarounds), and research question answers.

CRITICAL ANTI-HALLUCINATION RULES:
1. Strict Grounding: Every claim, executive summary sentence, PM prioritized backlog item, PM recommendation, and future research direction must be directly derived from and supported by the provided INPUTS. Do not make up generic Spotify features, user issues, or business recommendations that are not directly related to the input cluster intelligence.
2. Backlog Action Items: The prioritized backlog items must solve the specific unmet needs and workarounds explicitly mentioned in the inputs. Do not suggest generic features (e.g. "add equalizers", "redesign library UI") if they are not represented in the input clusters.
3. Unsupported Claims: You must actively populate the `unsupported_claims_or_overgeneralisations` array with any claims in the Research Question answers that go beyond the actual cluster evidence provided, enforcing database sanity.

DO NOT calculate any counts, percentages, or statistics. Focus entirely on qualitative validation, synthesis, and strategic product recommendations.

INPUTS:

1. AGGREGATED ANALYTICS METRICS:
{json.dumps(metrics_summary, indent=2)}

2. TOP CLUSTER INTELLIGENCE & EVIDENCE (Including JTBD & Workarounds):
{json.dumps(clusters_summary, indent=2)}

3. RESEARCH QUESTION ANSWERS:
{json.dumps(rq_answers, indent=2)}

Please analyze these inputs and generate a comprehensive research validation and synthesis report.
Your response MUST be a JSON object matching this schema:
{{
  "executive_summary": "string (A concise, high-level executive summary of the key findings across all research questions)",
  "overall_research_confidence_score": float,
  "evidence_coverage": [
    {{
      "rq_id": "string",
      "coverage_level": "High" | "Medium" | "Low",
      "critique": "string"
    }}
  ],
  "supported_conclusions_validation": [
    {{
      "conclusion": "string",
      "is_supported": boolean,
      "validation_details": "string"
    }}
  ],
  "contradictions_and_conflicts": [
    {{
      "conflict": "string",
      "description": "string"
    }}
  ],
  "unsupported_claims_or_overgeneralisations": [
    {{
      "claim": "string",
      "alternative_interpretation": "string"
    }}
  ],
  "cross_source_validation": [
    {{
      "finding": "string",
      "corroborated_sources": ["string"],
      "details": "string"
    }}
  ],
  "missing_evidence_or_gaps": [
    {{
      "gap": "string",
      "impact": "string"
    }}
  ],
  "pm_recommendations": [
    {{
      "priority": 1 | 2 | 3 | 4 | 5,
      "recommendation": "string",
      "strategic_rationale": "string",
      "action_items": ["string"]
    }}
  ],
  "pm_prioritized_backlog": [
    {{
      "feature_name": "string",
      "unmet_need": "string",
      "user_workarounds_resolved": ["string"],
      "priority_level": "High" | "Medium" | "Low",
      "pm_action_items": ["string"]
    }}
  ],
  "deep_inquiry_questions": [
    {{
      "question": "string",
      "rationale": "string",
      "priority": "High" | "Medium" | "Low"
    }}
  ],
  "future_research_directions": [
    {{
      "direction": "string",
      "rationale": "string"
    }}
  ]
}}
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
                logger.info(f"ResearchValidator: Calling Groq (Key Index {self.current_key_idx}) for validation...")
                response = httpx.post(url, json=payload, headers=headers, timeout=60.0)
                
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
                
                # Parse and validate JSON
                data = json.loads(text_response.strip())
                logger.info(f"ResearchValidator: Successfully validated research and generated insights (Confidence: {data.get('overall_research_confidence_score')}).")
                
                # Save to DB
                self.save_insights_to_db(data)
                
                # Save to JSON for file-based fallback compatibility
                try:
                    theme_slug = self.theme_config.get("theme_slug") if self.theme_config else None
                    suffix = f"_{theme_slug}" if theme_slug else ""
                    json_path = Path(self.db_path).parent / "scripts" / f"executive_insights{suffix}.json"
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    logger.info(f"ResearchValidator: Saved executive insights JSON file to: {json_path}")
                    
                    # Save a copy to persistent metadata cache
                    cache_path = Path(self.db_path).parent / "scripts" / f"executive_insights_cache{suffix}.json"
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    logger.info(f"ResearchValidator: Saved executive insights cache file to: {cache_path}")
                except Exception as json_save_err:
                    logger.error(f"ResearchValidator: Error saving insights JSON/cache files: {json_save_err}")
                    
                return data
                
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"Attempt {attempt+1} failed with error: {e}. Rotating key...")
                self._rotate_key()
                
        logger.error("ResearchValidator: All configured Groq API keys failed or were rate limited.")
        
        # Fallback: Try to load the previously saved insights from the database to prevent pipeline failure
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.conn.cursor() if hasattr(conn, "conn") else conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='executive_insights'")
            if cursor.fetchone():
                cursor.execute("SELECT insights_json FROM executive_insights WHERE id = 'latest'")
                row = cursor.fetchone()
                if row:
                    logger.warning("ResearchValidator: Falling back to previously saved insights from database to prevent pipeline crash.")
                    conn.close()
                    return json.loads(row["insights_json"])
            conn.close()
        except Exception as fb_err:
            logger.error(f"ResearchValidator: Fallback loading failed: {fb_err}")
            
        return {}

    def save_insights_to_db(self, insights: Dict[str, Any]):
        """Saves the generated executive insights to the SQLite database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executive_insights (
                    id TEXT PRIMARY KEY,
                    insights_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT INTO executive_insights (id, insights_json, updated_at)
                VALUES ('latest', ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    insights_json = excluded.insights_json,
                    updated_at = datetime('now')
            """, (json.dumps(insights),))
            conn.commit()
            conn.close()
            logger.info("ResearchValidator: Saved executive insights to SQLite database.")
        except Exception as e:
            logger.error(f"ResearchValidator: Error saving insights to database: {e}")
