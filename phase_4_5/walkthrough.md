# Walkthrough - Ingestion, Clustering, and LLM Research Engine

This document summarizes the changes and run results for the entire Spotify Product Research Engine, spanning Ingestion (Phase 1), Clustering (Phase 2), Analytics (Phase 3), Cluster Intelligence (Phase 3.5), Research Engine (Phase 4), and Deep Thematic Refinement (Phase 4.5).

---

## 1. Data Ingestion & Database Audit (Phase 1 & 1.5)
* **Total Audited & Kept**: English and Indian regional language reviews were audited and deduplicated.
* **Two-Phase Ingestion**: Ran targeted scrapers to ingest 372 new highly-focused discovery reviews from Reddit, Spotify Community, and YouTube comments.
* **Final Database Count**: **11,766 total reviews** in SQLite (`spotify_research.db`).
  - *Google Play Store*: 10,026 reviews
  - *Reddit*: 977 posts/comments
  - *Spotify Community Forums*: 349 posts
  - *YouTube Comments*: 337 comments
  - *Apple App Store*: 77 reviews

---

## 2. Dual-Path Clustering & Analytics (Phase 2 & 3)
* **Dual-Path Strategy**: 
  - Unrelated reviews (ads, bugs, widgets) were routed to a surface-level path (9,374 reviews).
  - Discovery-related reviews (2,392 reviews) were routed to a detailed path using dense embeddings.
* **Clustering Result**: Generated **951 highly specific, granular clusters** using Leader-Follower clustering with a similarity threshold of `0.70`.

---

## 3. Phase 3.5: Level 2.5 Cluster Intelligence (Groq Llama 3.3 70B)
To capture maximum granular feedback, the LLM trigger threshold was set to **$\ge 3$ reviews**.
* **Clusters Decomposed**: **114 clusters** met this threshold and were sent to Groq (`llama-3.3-70b-versatile`).
* **Decomposition Output**: Decomposed each cluster into 3–5 granular sub-issues (e.g., *looping same 5 songs*, *autoplay genre mismatch*, *AI DJ voice transition lag*), saved in `compiled_evidence_packages.json`.

---

## 4. Phase 4: Level 3 LLM Research Engine (Groq Llama 3.3 70B)
* **Objective**: Synthesize data-backed answers for the **7 Core Research Questions**.
* **Synthesis Scope**: Dynamically routed all discovery clusters and fed the top 15 most relevant clusters per question into the LLM.
* **Execution**: Ran with a 15-second inter-request delay and 30-second 429 backoff to prevent rate limits.
* **Results**:
  - **RQ1: Music Discovery Friction** (Confidence: 0.95)
  - **RQ2: Algorithmic Repetition & Looping** (Confidence: 0.92)
  - **RQ3: Recommendation Algorithm Sentiment** (Confidence: 0.90)
  - **RQ4: User Discovery Methods & Behaviors** (Confidence: 0.95)
  - **RQ5: Feature-Specific Performance** (Confidence: 0.92)
  - **RQ6: Physical Listening Contexts** (Confidence: 0.88)
  - **RQ7: Monetization & Feature Access** (Confidence: 0.90)
* All answers, key findings, and opportunities were saved to SQLite and `research_question_answers.json`.

---

## 5. Phase 4.5: Level 3.5 Deep Thematic Refinement (Groq Key 2)
* **Objective**: Extract fine-grained sub-themes and map them back to specific review and cluster IDs with strict validation using **`GROQ_API_KEY_2`** for quota isolation.
* **Double-Pass Validation Protocol**:
  - *Pass 1*: The LLM proposed 5 sub-themes and mapped them to candidate reviews.
  - *Pass 2*: The engine ran local **cosine similarity** validation (using local ONNX embeddings) between the sub-theme description and the review vectors. Mappings with similarity $< 0.60$ were rejected.
* **Run Results**:
  1. **[theme_1] Smart Shuffle Sonos Looping** (Algorithmic Repetition)
     - *Description*: Smart Shuffle looping when casting to Sonos smart home speakers.
     - *Verification*: **5 Verified, 0 Rejected** (100.0% Verification Rate)
  2. **[theme_2] Ad-Related Frustrations** (Monetization & Feature Access)
     - *Description*: Intrusiveness and frequency of ads interrupting music playback.
     - *Verification*: **0 Verified, 4 Rejected** (0.0% Verification Rate — *accurately caught and rejected wrong mappings!*)
  3. **[theme_3] Playlist Management Issues** (User Discovery Behaviors)
     - *Description*: Problems managing playlists (disappearing songs, inability to add/remove tracks).
     - *Verification*: **2 Verified, 1 Rejected** (66.7% Verification Rate)
  4. **[theme_4] Search and Discovery Limitations** (User Discovery Behaviors)
     - *Description*: Difficulties searching for specific songs or artists, restricting discovery.
     - *Verification*: **1 Verified, 1 Rejected** (50.0% Verification Rate)
  5. **[theme_5] Premium and Free Version Disparities** (Monetization & Feature Access)
     - *Description*: Free tier limitations (skip limits, forced shuffle) degrading discovery.
     - *Verification*: **1 Verified, 2 Rejected** (33.3% Verification Rate)
* **Persistence**: Saved the refined sub-themes and verified mappings to the `decomposed_themes` and `theme_reviews` SQLite tables, and saved the JSON output to `decomposed_themes.json`.
