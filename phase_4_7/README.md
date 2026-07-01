# Phase 4.7: Level 3.7 Advanced Analytics & Metric Compilation Engine

This directory defines the architecture and design of the **Advanced Analytics & Metric Compilation Engine**. 

---

## 📋 Objective
To compile a comprehensive, multidimensional analytical dataset from all previous phases (ingestion, clustering, sub-issues, research synthesis, and thematic refinement). It aggregates, calculates, and formats quantitative metrics and percentages under distinct analytical heads, saving them in SQLite to feed the Phase 5 dashboard.

---

## 🛠️ Key Architectural Tasks

1.  **Split-Ratio Calculation**:
    *   Query the database to calculate the exact percentage of discovery-related issues vs. non-discovery-related issues (general, ads, bugs, widgets) out of the entire cumulative database (11,766 reviews).
2.  **Research Question Share of Voice (SoV)**:
    *   Compute the percentage distribution of discovery reviews mapped to each of the 7 Core Research Questions.
    *   Calculate the average rating and sentiment score for each RQ.
3.  **Cluster Priority Matrix**:
    *   Sort and rank all 951 clusters based on a weighted **Priority Score**:
        $$\text{Priority Score} = w_1 \cdot \text{Size} + w_2 \cdot (5 - \text{Avg Rating}) + w_3 \cdot \text{Source Diversity}$$
4.  **Sub-Issue Share Aggregation**:
    *   Parse all decomposed sub-issues (from Phase 3.5) across all clusters and compile a global frequency matrix (e.g., showing that *Smart Shuffle looping* represents X% of all repetition issues globally).
5.  **Cross-Tabulation (Source vs. Category)**:
    *   Compute the volume and average rating for each category broken down by source (Google Play, Reddit, YouTube, Forums, App Store) to highlight channel-specific friction.
6.  **Double-Pass Verification Analytics**:
    *   Calculate the proposal vs. verification rates for each refined sub-theme (from Phase 4.5), documenting the percentage of rejected wrong mappings.
7.  **State Persistence**:
    *   Store the compiled metrics in a structured JSON schema in a new SQLite table `compiled_analytics_report` for instant, low-latency querying by the Phase 5 dashboard.
