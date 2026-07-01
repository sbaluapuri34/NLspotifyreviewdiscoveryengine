import os
import json
import re
import httpx
from loguru import logger
from typing import Dict, Any, Optional
from backend.app.config import GEMINI_API_KEY

class ThemeBootstrappingEngine:
    def __init__(self, api_key: Optional[str] = None):
        if api_key:
            self.api_key = api_key
        else:
            from backend.app.config import GEMINI_API_KEYS
            self.api_key = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else (os.getenv("THEME_X_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", ""))
        self.model_name = "gemini-2.5-flash"
        
    def slugify(self, text: str) -> str:
        """Converts a text string to a URL-friendly slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_-]+", "_", text)
        return text.strip("_")

    def generate_fallback_config(self, theme_name: str) -> Dict[str, Any]:
        """Generates a default theme configuration schema without any API calls."""
        slug = self.slugify(theme_name)
        # Basic keyword derivation
        kw = theme_name.lower().strip()
        kws = [kw]
        if " " in kw:
            kws.extend(kw.split())
            
        return {
            "theme": theme_name,
            "theme_slug": slug,
            "scraping_elements": {
                "reddit_subreddits": ["spotify", "truespotify", "spotifyplaylist"],
                "reddit_search_queries": [f"spotify {kw}", f"{kw} feedback", f"{kw} issue"],
                "youtube_search_queries": [f"spotify {kw} review", f"spotify {kw} update", f"spotify {kw} issues"],
                "spotify_community_keywords": [kw, f"{kw} recommendation", f"{kw} issues"]
            },
            "level_0_config": {
                "priority_routing_keywords": kws + [f"spotify {kw}", f"new {kw}", f"{kw} loop"]
            },
            "semantic_anchors": {
                "goal_listen": f"listen to play stream hear music audio tracks {kw}",
                "goal_discover": f"find new creators search recommendations playlists discover {kw}",
                "context_car": "driving carplay android auto bluetooth road trip car",
                "context_home": "smart speaker casting sonos speaker casting audio Alexa google home cast",
                "frustration_playback": f"playback error buffering offline sync speed control skip seconds crash {kw}",
                "frustration_ads": "ads premium ads unskippable sponsored segments commercial commercials free",
                "frustration_navigation": f"search library navigation button ui menu tab screen playlist {kw}",
                "churn_indicator": f"switching leaving cancel subscription apple music youtube premium pocket casts"
            },
            "research_questions": {
                "TRQ1": {
                    "title": f"{theme_name} Discoverability & Friction",
                    "question": f"How do users navigate and discover features related to {theme_name}, and what usability barriers exist?"
                },
                "TRQ2": {
                    "title": f"{theme_name} Technical Performance",
                    "question": f"What technical bugs, crashes, sync errors, or performance issues disrupt the experience for {theme_name}?"
                },
                "TRQ3": {
                    "title": f"{theme_name} User Value & Monetization",
                    "question": f"How do users feel about the cost, ad placements, and premium benefits related to {theme_name}?"
                },
                "TRQ4": {
                    "title": f"{theme_name} Platform Competitiveness & Churn",
                    "question": f"What limitations in Spotify's {theme_name} implementation prompt users to switch to competitor platforms?"
                }
            }
        }

    def bootstrap_theme(self, theme_name: str) -> Dict[str, Any]:
        """
        Calls Gemini API to generate the custom JSON configuration for a theme X.
        Falls back to generating a heuristic template if the call fails or key is missing.
        """
        if not self.api_key:
            logger.warning("ThemeBootstrappingEngine: No GEMINI_API_KEY configured. Using fallback configuration.")
            return self.generate_fallback_config(theme_name)
            
        slug = self.slugify(theme_name)
        prompt = f"""
You are a Lead AI Product Researcher. Generate a theme-specific research and scraping configuration schema for Spotify Product Research.
The user wants to explore custom feedback and reviews related to the theme: "{theme_name}".

Analyze this theme and construct a configuration JSON mapping exactly to the following structure:
1. `theme`: The original theme name (e.g., "{theme_name}").
2. `theme_slug`: The slugified lowercase identifier (e.g., "{slug}").
3. `scraping_elements`: Target search terms for data collection:
   - `reddit_search_queries`: List of exactly 3 highly theme-specific search terms to query Reddit.
   - `youtube_search_queries`: List of exactly 3 YouTube search terms for video comments. IMPORTANT: Each search term MUST start with the word 'spotify ' (e.g., 'spotify {theme_name} review').
   - `spotify_community_keywords`: List of exactly 3 keyword terms to search the Spotify Community Forums.
4. `level_0_config`: Ingestion filters:
   - `priority_routing_keywords`: List of 6-10 lowercase keywords used as a Level 0 priority routing check (if a review has any of these, it must be analyzed).
5. `semantic_anchors`: Mapping of semantic anchor identifiers to dense search query strings (phrases or terms expressing these states specifically for "{theme_name}"):
   - `goal_listen`: Core goal of listening/streaming in relation to "{theme_name}".
   - `goal_discover`: Seeking or finding new options/features within "{theme_name}".
   - `context_car`: Physical context of driving or commuting with this theme.
   - `context_home`: Physical context of casting, smart speakers, or home casting.
   - `frustration_playback`: Technical playback issues, buffering, sync errors, or offline bugs.
   - `frustration_ads`: Frustrations related to monetization, ads, or value.
   - `frustration_navigation`: Friction in menus, UI layout, or searching.
   - `churn_indicator`: Behavioral expressions of wanting to switch apps, cancel premium, or uninstall.
6. `research_questions`: Exactly 4 target Research Questions ("TRQ1", "TRQ2", "TRQ3", "TRQ4") custom-tailored for "{theme_name}". Each question must have:
   - `title`: Short descriptive title (max 5 words).
   - `question`: Detailed product research question.

You MUST respond with a JSON object matching this schema. Do not include any text, backticks, or markdown formatting outside the JSON object. Do not generate 'reddit_subreddits' in your JSON output.

Example JSON output:
{{
  "theme": "Podcasts",
  "theme_slug": "podcasts",
  "scraping_elements": {{
    "reddit_search_queries": ["podcast player spotify", "spotify podcasts issues", "spotify podcast ads"],
    "youtube_search_queries": ["spotify podcast update", "spotify video podcasts", "spotify podcast ads"],
    "spotify_community_keywords": ["podcast offline", "podcast playback", "podcast queue"]
  }},
  "level_0_config": {{
    "priority_routing_keywords": ["podcast", "podcasts", "episode", "episodes", "show", "shows", "host", "playback speed"]
  }},
  "semantic_anchors": {{
    "goal_listen": "listen to podcasts episodes stories talk shows",
    "goal_discover": "find new shows discover creators podcast recommendations",
    "context_car": "driving carplay android auto bluetooth road trip",
    "context_home": "smart speaker casting sonos speaker casting audio Alexa",
    "frustration_playback": "playback error buffering offline sync speed control skip seconds",
    "frustration_ads": "host-read ads premium ads unskippable sponsored segments",
    "frustration_navigation": "search episodes show feed latest episode catalog library",
    "churn_indicator": "switching to Apple Podcasts Pocket Casts YouTube leaving spotify"
  }},
  "research_questions": {{
    "TRQ1": {{
      "title": "Podcast Discoverability & Feed Friction",
      "question": "How do users navigate and discover new podcast shows, and what barriers exist in the show recommendations feed?"
    }},
    "TRQ2": {{
      "title": "Audio/Video Playback Performance",
      "question": "What technical and UX issues (e.g., sync, offline downloads, speed) disrupt the playback experience for audio and video podcasts?"
    }},
    "TRQ3": {{
      "title": "Monetization and Podcast Advertising",
      "question": "How do Premium users feel about podcast-specific ads, and how does ad placement affect user retention?"
    }},
    "TRQ4": {{
      "title": "Platform Competition & Churn Triggers",
      "question": "What features drive users to switch from Spotify to dedicated podcast apps like Apple Podcasts or Pocket Casts?"
    }}
  }}
}}
"""
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2
            }
        }
        
        try:
            logger.info(f"ThemeBootstrappingEngine: Requesting Gemini ({self.model_name}) config generation for: {theme_name}...")
            # Set a 30-second timeout to prevent lockups
            response = httpx.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30.0)
            
            if response.status_code != 200:
                logger.error(f"Gemini API returned error code {response.status_code}: {response.text}. Using fallback config.")
                # Attempt to fallback to gemini-2.0-flash as a secondary measure if 2.5-flash is restricted/rate-limited
                if self.model_name == "gemini-2.5-flash":
                    logger.info("Attempting fallback call to gemini-2.0-flash...")
                    fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
                    self.model_name = "gemini-2.0-flash"
                    payload["generationConfig"]["responseMimeType"] = "application/json"
                    response = httpx.post(fallback_url, json=payload, headers={"Content-Type": "application/json"}, timeout=20.0)
                    if response.status_code == 200:
                        res_json = response.json()
                        text = res_json['candidates'][0]['content']['parts'][0]['text']
                        return json.loads(text.strip())
                return self.generate_fallback_config(theme_name)
                
            res_json = response.json()
            text = res_json['candidates'][0]['content']['parts'][0]['text']
            config_data = json.loads(text.strip())
            
            # Post-check validation to guarantee presence of core keys
            required_keys = ["theme", "theme_slug", "scraping_elements", "level_0_config", "semantic_anchors", "research_questions"]
            if all(k in config_data for k in required_keys):
                # Hardcode and inject the fixed subreddits list
                config_data["scraping_elements"]["reddit_subreddits"] = ["spotify", "truespotify", "spotifyplaylist"]
                logger.info(f"ThemeBootstrappingEngine: Successfully bootstrapped config for theme: {theme_name}")
                return config_data
            else:
                logger.warning("ThemeBootstrappingEngine: Generated JSON missed essential keys. Falling back.")
                return self.generate_fallback_config(theme_name)
                
        except Exception as e:
            logger.error(f"ThemeBootstrappingEngine: API call failed with error: {e}. Using fallback config.")
            return self.generate_fallback_config(theme_name)
