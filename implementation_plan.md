# Implementation Plan: Spotify AI Product Research Engine (Music Discovery & Context Focus)

This document outlines the step-by-step implementation plan for building the **Spotify AI Product Research Engine** optimized for the **Indian market** and focused on **music discovery behaviors, playlist-based discovery friction, and physical listening contexts**. The development is structured to build and verify each layer of the four-level intelligence architecture.

---

## User Review Required

> [!IMPORTANT]
> **API Key Requirements**: The LLM reasoning layer (Level 3) requires a Gemini API key. The YouTube Comments Scraper and Reddit Scraper require a YouTube Data API Key and an Apify API Token, respectively. All keys must be stored in the local `.env` file.
> 
> **Translation Dependencies**: We will use `deep-translator` (a lightweight Python library) to handle the translation of Hindi and other regional Indian languages into English during the preprocessing stage.
> 
> **Scraping Configuration**: Play Store and App Store scrapers will be initialized with `country="in"` and targeted to fetch a combined **10,000 reviews** (allocated as 6,000 Play Store and 4,000 App Store reviews based on Indian market share) spanning the **last 6 months up to today**.
> 
> **Interactive Filtering & Cache**: All reviews, vectors, and LLM-generated research answers will be cached in SQLite. The dashboard will allow users to filter the analysis on-the-fly by Date (`From/End`), Ingestion Sources, and Max Review Volume without triggering new LLM calls.

---

## Proposed Changes

We will create a structured monorepo containing a `backend` (FastAPI) and a `frontend` (React + Vite).

```
spotify/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI Entrypoint & SSE Streamer
│   │   ├── config.py          # Configuration, Thresholds & Location Gazetteers
│   │   ├── database.py        # SQLite Persistence & Cache Manager
│   │   ├── ingestion.py       # Scraper Workers (Play Store, App Store, Forums, YouTube, Reddit)
│   │   ├── pipeline.py        # Level 0: LangDetect, Translator, PII Remover, Sanitizer, LSH, Router, Compressor
│   │   ├── vectors.py         # Level 1: ONNX Embeddings & HNSW Index
│   │   ├── analytics.py       # Level 2: c-TF-IDF, SAP, Regional Classifier, CSSS, Opportunity Scoring, Filter Engine
│   │   └── research.py        # Level 2.5/3: Cluster Intelligence & LLM Research Engine & Refinement Loop
│   ├── requirements.txt
│   └── tests/
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── Dashboard.jsx
    │   │   ├── ResearchQuestionCard.jsx
    │   │   ├── OpportunityMatrix.jsx
    │   │   └── SourceDistribution.jsx
    │   ├── App.jsx
    │   ├── main.jsx
    │   └── index.css          # Premium Glassmorphism styling
    ├── package.json
    └── vite.config.js
```

---

## Technical Implementation Steps

### Phase 1: Level 0 Data Engine & Ingestion (Local)
* **Objective**: Establish the raw data ingestion pipelines, configuration, text translation, PII/noise removal, text sanitization, deduplication, and initial routing.
* **Tasks**:
  1. Set up a `.env` file in the root directory containing:
     - `YOUTUBE_API_KEY` (for YouTube comments scraping).
     - `GEMINI_API_KEY` (for Level 3 LLM synthesis).
     - `APIFY_API_TOKEN` (for Reddit scraping).
  2. Implement `ingestion.py` with:
     - **Google Play Store Scraper**: Fetches 6,000 reviews for `com.spotify.music` with `country="in"` spanning the **last 6 months up to today**.
     - **Apple App Store Scraper**: Fetches 4,000 reviews for App ID `324684580` with `country="in"` spanning the **last 6 months up to today**.
     - **Spotify Community Forums Scraper**: Queries search results for `"recommendation"`, `"discover weekly"`, `"discover"`, and `"release radar"` on the search page, parsing threads specifically from the *Idea Exchange*, *Android/iOS Support*, and *Music Chat* boards using `BeautifulSoup`.
     - **YouTube Comments Scraper**: Queries comments from Spotify-specific video URLs (official announcements, AI DJ reviews) using the YouTube Data API v3 `commentThreads.list` endpoint.
     - **Reddit Scraper**: An async worker that uses the **Apify API** with the `APIFY_API_TOKEN` to fetch posts and comments from Spotify-specific subreddits: `r/truespotify`, `r/spotify`, `r/spotifyplaylist`, `r/SpotifyPlaylists`, and `r/musicsuggestions` spanning the last 6 months, and falls back to invoking the local **Agent-Reach** codebase if the Apify quota is exhausted.
     - **Ingestion Queue**: Pushes all fetched data into a unified async queue.
  3. Implement the **Language Detector & Translation Pipeline**: Use `langdetect` to identify non-English reviews (e.g., Hindi, Tamil, Telugu) and translate them to English using `deep-translator` before downstream processing.
  4. Implement **PII & Noise Preprocessing**: Build regex and heuristic filters in `pipeline.py` to:
     - Strip emails, phone numbers, URLs, and social media usernames (`@handle` or `u/username`).
     - Strip emojis.
     - Identify and exclude promotional/spam-only content.
     - Discard any review containing **fewer than 3 meaningful words** (excluding stop words and punctuation) from semantic analysis.
  5. Create the **Text Sanitizer** to clean text while preserving negations (`not`, `never`, `don't`) and comparative words.
  6. Build the **Near-Duplicate Detector** using MinHash and LSH.
  7. Build the **Review Classifier** to route reviews to `Ignore`, `Statistics Only`, `Semantic Analysis`, or `Deep AI Analysis`. Integrate the **Recommendation Feature Detection & Priority Routing** rule to automatically upgrade any review containing core recommendation terms (`"Discover Weekly"`, `"Release Radar"`, `"Smart Shuffle"`, `"Daily Mix"`, `"AI DJ"`, etc.) to `Semantic Analysis` or higher. (This is strictly an ingestion gate; downstream semantic clustering remains unbiased).
  8. Build the **Semantic Compressor** using a local extractive TextRank algorithm for long-form reviews.
  9. Create the SQLite database schema in `database.py` to store raw reviews, hashes, embeddings, and classification results. Create composite B-Tree indexes on `(published_at, source)` to optimize multi-dimensional dashboard queries.

### Phase 2: Level 1 Vector Engine & Clustering (Local)
* **Objective**: Generate dense embeddings and cluster reviews semantically in real-time.
* **Tasks**:
  1. Set up `vectors.py` using `onnxruntime` to run the `all-MiniLM-L6-v2` embedding model locally.
  2. Implement the local HNSW vector index for individual reviews using `hnswlib`.
  3. Implement the **HNSW Centroid Indexing** algorithm: Index centroids in a separate `HNSW_centroids` index and perform $O(\log C)$ nearest centroid lookups.
  4. Implement the **Adaptive Clustering Threshold Strategy** in `cluster.py`:
     - Automatically adjust the similarity threshold $\theta_{\text{match}}(N)$ based on the dataset size $N$:
       - $N < 500 \implies \theta_{\text{match}} = 0.80$
       - $500 \le N < 1500 \implies \theta_{\text{match}} = 0.75$
       - $1500 \le N < 4000 \implies \theta_{\text{match}} = 0.70$
       - $4000 \le N < 8000 \implies \theta_{\text{match}} = 0.65$
       - $N \ge 8000 \implies \theta_{\text{match}} = 0.60$
     - Make this adaptive behavior fully configurable and overridable by a fixed user-specified threshold.
  5. Implement the **Incremental Leader-Follower Clustering** lifecycle: Evaluate the calculated/overridden similarity threshold to merge reviews or spawn new clusters.
  6. Write the centroid update logic (unit-length normalized moving average) and implement Welford's algorithm to track running variance ($\sigma^2_k$) for drift detection.

### Phase 3: Level 2 Evidence Engine & Analytics (Local)
* **Objective**: Calculate cluster statistics, extract semantic themes, intents, emotions, listening contexts, compile the rich Evidence Package, and compute opportunity scores.
* **Tasks**:
  1. Implement the **Cross-Source Synergy Score (CSSS)** based on Shannon source entropy and semantic coherence.
  2. Implement the **Opportunity Prioritization Score** based on Severity, Frequency, CSSS, and Business Impact.
  3. Build the background **Drift Monitor & Splitter**: Detect when running variance $\sigma^2_k > 0.25$ and size $N_k \ge 30$, execute a local **Mini-Batch 2-Means** split, and update the `HNSW_centroids` index.
  4. Write the **Medoid Selector** to extract the top 5–10 central reviews closest to the centroid.
  5. Implement the **Anomaly and Outlier Selector** to identify contradictory reviews (opposite sentiment) and fringe/outlier reviews (boundary vectors).
  6. Implement **Class-Based TF-IDF (c-TF-IDF)** to extract cluster-specific semantic n-gram themes, seeding the vocabulary to prioritize recommendation terms.
  7. Implement **Semantic Anchor Projection (SAP)**: Project review vectors against a static matrix of embedded anchors using cosine similarity to extract:
     - **User Goals**
     - **Discovery Methods** (Playlist, Algorithmic, Manual Search)
     - **Listening Contexts** (Car/Driving, Smart Home/Casting, Gym/Workout, Work/Focus, Commuting)
     - **Emotions** (Anger/Disappointment vs. Satisfaction/Joy)
     - **Frustrations**
     - **Workarounds**
     - **Feature Requests**
     - **Churn Indicators**
     - **Competitor Mentions**
  8. Implement the **Indian Regional Location Classifier**: A local gazetteer-based matcher utilizing a pre-defined dictionary of Indian states and cities (e.g., Mumbai, Delhi, Bengaluru) to extract regional tags from review text.
  9. Implement the **Dynamic Filter Query Engine** in `analytics.py`. It must accept optional filters (`from_date`, `to_date`, `sources`, `limit`), query the B-Tree indexed SQLite database, and re-calculate distributions, c-TF-IDF themes, and SAP intent/emotional tags on-the-fly for the filtered slice.
  10. Write the **Evidence Package Compiler** that serializes all metrics, distributions, recommendation product breakdowns, **listening context breakdowns**, **discovery method breakdowns**, **emotion distributions**, **regional location distributions**, and text selections into a structured JSON payload.

### Phase 3.5: Level 2.5 Cluster Intelligence (Gemini Flash)
* **Objective**: Identify, quantify, and score distinct sub-issues within each mature cluster using a single Gemini Flash call.
* **Tasks**:
  1. Implement `extract_cluster_sub_issues` in `research.py`. Write a highly structured prompt for `gemini-1.5-flash` that reads the compiled Level 2 Evidence Package (c-TF-IDF themes, medoid reviews, intent distributions) and outputs a structured JSON list of distinct **Sub-issues** (each with a title, frequency percentage, representative quote, and confidence score).
  2. Implement the trigger logic: Run the Cluster Intelligence stage only when a cluster's size reaches maturity milestones ($N_k \ge 15$) or when a drift split occurs.
  3. Cache the extracted `cluster_intelligence` JSON in the `llm_cache` table of SQLite, linked to the cluster's current version and review count, preventing redundant API calls.
  4. Enrich the compiled Evidence Package with the `cluster_intelligence` block before serializing it for the downstream Research Engine.

### Phase 4: Level 3 LLM Research Engine (AI - Pro)
* **Objective**: Connect Enriched Evidence Packages to the 7 Core Research Questions and refine answers progressively using Gemini Pro.
* **Tasks**:
  1. Implement the **Deterministic Token Compressor**: Round floats to 3 decimal places, strip null/empty fields, truncate quotes to specific character limits, cap c-TF-IDF keywords, de-duplicate quotes, and serialize the final package to **YAML** format. Enforce the configurable `MAX_TOKEN_BUDGET` per cluster tier.
  2. Implement the **Cluster Summarizer** using `gemini-1.5-flash` to generate theme titles at logarithmic size milestones (5, 10, 20, 40...) from the compressed Evidence Package.
  3. Implement the **Research Question Router** to map Enriched Evidence Packages to the 7 target research questions.
  4. Implement the **Incremental Refinement Loop** using `gemini-1.5-pro` to update research answers using the latest Enriched Evidence Package (including the `cluster_intelligence` sub-issue breakdown) and the previous answer state. Explicitly prompt the LLM to structure and segment its findings around:
     - **How users discover new songs** via playlists vs. algorithmic autoplay/AI DJ vs. manual search.
     - **Specific problems and friction** they face as Spotify users (e.g., repetition loops, echo chamber bias, UI changes blocking discovery).
     - **Where exactly they are using Spotify** (e.g., Car/Driving, Smart Home/Sonos casting, Gym, Commuting) and how physical environment limitations compound their discovery frustrations.
     - **Pre-analyzed sub-issues and frequencies** (from the `cluster_intelligence` block).
     - **Emotional and behavioral patterns** (extracted via the SAP emotion distributions).
     - **Regional Indian variations** based on the location distribution.
  5. Cache all LLM responses in SQLite to enable instant resume and incremental learning.

### Phase 5: Live SSE Streaming & Dashboard
* **Objective**: Build the real-time presentation layer.
* **Tasks**:
  1. Set up the `/api/stream` endpoint in FastAPI using Server-Sent Events to stream delta updates.
  2. Create the React frontend and establish the `EventSource` connection.
  3. Implement the **ResearchQuestionCard** showing the current answer, supporting quotes, and a dynamic confidence progress bar.
  4. Build the **OpportunityMatrix** (an interactive scatter plot of Severity vs. Business Impact).
  5. Implement the **Data Horizon Indicator** displaying the date range of currently loaded reviews.
  6. Design the premium glassmorphism dark-mode UI in `index.css` using custom CSS variables, CSS grid layouts, and hardware-accelerated animations.
  7. Add **Date Pickers (From/End)**, **Source Selection Checkboxes**, and a **Max Reviews Input** to the UI, linking them to backend REST endpoints for dynamic filtering.
  8. Implement real-time SSE streaming updates that dynamically merge into the active view. If the user has a filter applied, the UI will filter the incoming stream locally to match the criteria.

### Phase 6: Resiliency, Verification & Testing
* **Objective**: Verify correctness, performance, and cost limits.
* **Tasks**:
  1. Write unit tests for the Text Sanitizer, Translation Pipeline, MinHash deduplication, PII/Noise Preprocessing, and clustering.
  2. Run a performance benchmark with 5,000 mock reviews to verify CPU usage, vector query times, and memory footprint.
  3. Verify that the SQLite state persistence allows stopping and restarting the backend without losing clusters or re-running LLM queries.
