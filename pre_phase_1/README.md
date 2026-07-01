# Pre-Phase 1: Theme Bootstrapping & LLM Configuration Generator

This folder contains the standalone snapshot of **Pre-Phase 1**, which introduces the **Theme Bootstrapping Engine** to the Spotify Product Research pipeline.

## Overview
Pre-Phase 1 is executed before scraping or analysis. When a user inputs a custom Spotify theme $X$ (e.g. Podcasts, AI DJ, Premium), the engine uses `gemini-1.5-pro` via the Gemini REST API to dynamically construct a JSON configuration schema. This schema contains:
1. Target subreddits and search queries for the scraping workers.
2. Ingestion-level priority keywords (for Level 0 routing).
3. Theme-specific semantic anchors (for Level 2 SAP behavior tagging).
4. Tailored product research questions (TRQ1-TRQ4) to replace the 7 core Music Discovery questions.

Configurations are saved and retrieved from the `theme_configurations` SQLite table to ensure fast, cost-free caching. A local keyword-based fallback engine generates config schemas on timeouts or missing API keys.

## Snapshot Files
* `app/bootstrapping.py`: The `ThemeBootstrappingEngine` and local fallback generator.
* `app/database.py`: Updated SQLite tables and caching helpers.
* `app/main.py`: Updated API router adding the `POST /api/exploration/bootstrap` endpoint.
* `tests/test_bootstrapping.py`: Comprehensive test suite containing mocked LLM calls and endpoint checks.

## How to Test
Run the tests using the virtual environment python interpreter from the root directory:
```bash
backend\venv\Scripts\python.exe -m pytest backend/tests/test_bootstrapping.py
```
