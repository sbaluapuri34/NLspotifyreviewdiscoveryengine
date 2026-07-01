# Implementation Plan: Isolated Dynamic Theme Exploration Engine

This plan describes the implementation steps to add **Theme Exploration Mode** (Mode 2) to the Spotify Product Research Engine, enabling research on any user-defined Spotify theme $X$ (e.g., Podcasts, Ads, Premium, Playlists) fully isolated from the core **Music Discovery** pipeline.

---

## User Review Required

> [!IMPORTANT]
> **Key Architectural Elements to Review:**
> 1. **Dynamic Database Isolation**: A completely new SQLite database (`spotify_research_{theme}.db`) and centroid index will be instantiated for every custom theme, ensuring 100% data safety.
> 2. **Shared Raw Replica Store**: The primary database (`spotify_research.db`) will remain strictly isolated and read-only. Storefront reviews (Google Play/App Store) are copied to a temp `spotify_raw_shared_replica.db` staging database for custom pipelines to filter locally.
> 3. **Environment Configurations**: Requires the user to add named credentials (`THEME_X_APIFY_API_TOKEN`, `THEME_X_YOUTUBE_API_KEY`, `THEME_X_GEMINI_API_KEY`, `THEME_X_GROQ_API_KEYS`) in [backend/.env](file:///C:/Users/pc/Favorites/spotify%20-2/backend/.env) to separate API quotas in production.
> 4. **SAP Dynamic Rebuilding**: Dynamic Semantic Anchor Projection (SAP) will be completely rebuilt from scratch per theme, discarding all music discovery anchors.
> 5. **Dashboard Transition Flow**: The frontend remains fully interactive and displays current discovery data during the exploration run. A completion nudge appears upon pipeline completion, offering a dynamic swap to the custom theme view.

---

## Proposed Changes

We will modify the core backend files to accept dynamically passed parameters (such as database paths, routing keywords, SAP anchors, and research questions) instead of relying on hardcoded constants.

### 1. Database & Config Layers

#### [MODIFY] [database.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/database.py)
* Refactor `get_db_connection()` to accept an optional `db_path` parameter, defaulting to `DB_PATH`.
* Update `init_db()` to support dynamically initializing target database schemas (reviews, pipeline_runs, llm_cache, research_answers, theme_reviews, decomposed_themes) for any file path.

#### [MODIFY] [config.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/config.py)
* Read environment variables for custom theme runs: `THEME_X_APIFY_API_TOKEN`, `THEME_X_YOUTUBE_API_KEY`, `THEME_X_GEMINI_API_KEY`, and `THEME_X_GROQ_API_KEYS`, falling back to standard keys if not provided.

---

### 2. Core Pipeline Modification

#### [MODIFY] [pipeline.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/pipeline.py)
* Update `TextPipeline` constructor to accept custom `priority_keywords` and `allowed_langs`.
* Modify `process_review` to use custom keywords for Level 0 priority routing.

#### [MODIFY] [analytics.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/analytics.py)
* Update `SemanticAnchorProjector` to accept a custom dictionary of anchor phrases at initialization rather than using the hardcoded `ANCHOR_PHRASES`.
* Update `ClusterTfidfExtractor` to accept custom priority words.
* Refactor `DynamicFilterEngine` to dynamically look up embeddings and clusters using the database path assigned to the active theme.

#### [MODIFY] [research.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/research.py)
* Refactor `ResearchEngine` to accept a custom research questions dictionary at initialization (rather than using the hardcoded `RESEARCH_QUESTIONS`).
* Update `route_clusters_to_rqs` and `synthesize_rq_answer` to route and synthesize based on the custom RQs.

#### [MODIFY] [ingestion.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/ingestion.py)
* Refactor scrapers (`PlayStoreScraper`, `AppStoreScraper`, `SpotifyForumsScraper`, `YouTubeCommentsScraper`, `RedditScraper`) to read their credentials, limits, and keywords dynamically from a config dictionary passed at runtime.

---

### 3. API & Orchestration Layer

#### [MODIFY] [main.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/app/main.py)
* **Bootstrapping Endpoint**: Add `POST /api/exploration/bootstrap` which receives a theme string $X$, calls Gemini to generate the custom JSON configuration (scraping keywords, subreddits, priority keywords, SAP anchors, and RQs), and caches it in a master config table.
* **Replica Staging**: Before executing the scraping phase of custom exploration, copy the raw reviews table (Google Play and App Store records) from `spotify_research.db` into `spotify_raw_shared_replica.db`.
* **Dynamic Router**: Refactor dashboard endpoints to accept a prefix `/api/exploration/{theme_slug}/...` (e.g., clusters, research, operational-friction). These endpoints will dynamically map database paths to `spotify_research_{theme}.db`.
* **Asynchronous Runner**: Implement `run_exploration_pipeline_task()` that:
  - Connects to the dynamic DB file.
  - Feeds custom configuration metrics (keywords, anchors, RQs) into the modified pipeline executors.
  - Broadcasts progress via dynamic SSE logs `/api/stream?mode=exploration&theme={theme}`.

---

### 4. Frontend Presentation Layer

#### [MODIFY] [index.html](file:///C:/Users/pc/Favorites/spotify%20-2/frontend/index.html)
* Add a header toggle element with custom description text: *"The default dashboard is optimized strictly for Music Discovery. Toggle to explore custom Spotify themes without affecting the discovery dataset."*
* Add an input field for writing the custom Spotify theme and a "Run Exploration" button.
* Create a **Nudge Transition Modal** in HTML: *"New analysis for theme [X] is ready. Would you like to view the analysis?"* with "Show Analysis" and "Keep Current" buttons.
* Ensure progress overlays and logging terminals are visible during active runs.

#### [MODIFY] [app.js](file:///C:/Users/pc/Favorites/spotify%20-2/frontend/app.js)
* Maintain a local state variable `activeTheme` (defaulting to `"discovery"`).
* Update API call functions to dynamically inject the `activeTheme` path prefix.
* Implement the toggle handler: when exploration is clicked, show the theme input.
* Implement the custom run handler: trigger the bootstrapping & pipeline run, but keep rendering all core discovery tabs (acting as an interactive placeholder).
* Map the SSE stream endpoint to the selected theme mode to display background run logs.
* Listen for execution completion messages via SSE. When completed, display the **Nudge Transition Modal**.
* Implement the swap handler: upon confirming the nudge, update `activeTheme` to the new custom theme, refresh the active tab elements, and reload the cluster visuals.

---

## Verification Plan

### Automated Tests
Create a new test file: [test_theme_exploration.py](file:///C:/Users/pc/Favorites/spotify%20-2/backend/tests/test_theme_exploration.py)
* **Verify Bootstrapping**: Test that `POST /api/exploration/bootstrap` calls Gemini, returns the correct schema (RQs, SAP anchors, scraping elements), and saves it.
* **Verify Replica Copying**: Test that the raw Play/App Store reviews table is cloned to `spotify_raw_shared_replica.db` without reading secondary columns or touching the live DB.
* **Verify Pipeline Customization**: Test that the pipeline runs correctly using custom keywords, custom SAP anchors (wiped and rebuilt), and dynamic RQs, writing outputs to `spotify_research_test_theme.db`.
* **Verify API Routing**: Test that `/api/exploration/test_theme/clusters` retrieves data exclusively from the dynamic SQLite database.

### Manual Verification
1. Open the updated dashboard. Verify that the mode toggle displays the explanatory label.
2. Select a custom theme (e.g., "Podcasts") and click "Run Exploration".
3. Verify that the dashboard remains fully interactive, showing the core Music Discovery data during the run.
4. Verify that the terminal logs background progress updates in real-time.
5. Verify that upon pipeline completion, a toast modal appears asking: *"New analysis for theme [Podcasts] is ready. Want to view it?"*
6. Click "Show Analysis" and verify that all tabs, clusters, and research questions immediately refresh to display the Podcast exploration metrics.
