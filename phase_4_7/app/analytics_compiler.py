import os
import json
import sqlite3
from typing import List, Dict, Any
from loguru import logger
from backend.app.config import DB_PATH

class AnalyticsCompiler:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_device_column()
        
    def _ensure_device_column(self):
        """Alters the reviews table to add the device_type column if it doesn't exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(reviews)")
            columns = [row[1] for row in cursor.fetchall()]
            if "device_type" not in columns:
                logger.info("AnalyticsCompiler: Adding device_type column to reviews table...")
                cursor.execute("ALTER TABLE reviews ADD COLUMN device_type TEXT DEFAULT 'mobile'")
                conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error ensuring device_type column: {e}")

    def classify_device(self, text: str) -> str:
        """Classifies the device type based on keywords in the review text."""
        text_lower = text.lower()
        
        # Car / Android Auto
        if any(w in text_lower for w in ["car", "android auto", "driving", "dash", "carplay", "vehicle", "infotainment"]):
            return "car"
        # TV / Smart TV
        if any(w in text_lower for w in ["tv", "smart tv", "android tv", "firestick", "television", "chromecast"]):
            return "tv"
        # Tablet
        if any(w in text_lower for w in ["tablet", "ipad", "galaxy tab", "tab s"]):
            return "tablet"
        # PC / Laptop
        if any(w in text_lower for w in ["pc", "laptop", "chromebook", "desktop", "computer", "windows", "mac"]):
            return "pc"
        # Wearable / Smartwatch
        if any(w in text_lower for w in ["watch", "wearos", "wear os", "galaxy watch", "pixel watch"]):
            return "wearable"
            
        return "mobile"

    def run_device_classification(self):
        """Scans all reviews in the database, classifies their device type, and updates SQLite."""
        logger.info("AnalyticsCompiler: Running device classification on all reviews...")
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Fetch all reviews
            cursor.execute("SELECT id, translated_text, raw_text FROM reviews")
            rows = cursor.fetchall()
            
            updates = []
            for rid, trans, raw in rows:
                text = trans or raw or ""
                device = self.classify_device(text)
                updates.append((device, rid))
                
            # Batch update
            cursor.executemany("UPDATE reviews SET device_type = ? WHERE id = ?", updates)
            conn.commit()
            conn.close()
            logger.info(f"AnalyticsCompiler: Successfully classified and updated {len(updates)} reviews.")
        except Exception as e:
            logger.error(f"Error running device classification: {e}")

    def compile_metrics(self) -> Dict[str, Any]:
        """Compiles all quantitative metrics and percentages from the database."""
        logger.info("AnalyticsCompiler: Compiling advanced metrics...")
        metrics = {}
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. Split-Ratio Calculation
            cursor.execute("SELECT COUNT(*) FROM reviews")
            total_reviews = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM reviews WHERE cluster_id IS NOT NULL AND cluster_id NOT LIKE 'unrelated_%'")
            discovery_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT cluster_id, COUNT(*) FROM reviews WHERE cluster_id LIKE 'unrelated_%' GROUP BY cluster_id")
            unrelated_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            metrics["split_ratio"] = {
                "total_reviews": total_reviews,
                "discovery_related": {
                    "count": discovery_count,
                    "percentage": round((discovery_count / total_reviews) * 100, 2) if total_reviews else 0
                },
                "operational_unrelated": {
                    "count": total_reviews - discovery_count,
                    "percentage": round(((total_reviews - discovery_count) / total_reviews) * 100, 2) if total_reviews else 0,
                    "breakdown": {
                        "general": unrelated_counts.get("unrelated_general", 0),
                        "ads": unrelated_counts.get("unrelated_ads", 0),
                        "bugs": unrelated_counts.get("unrelated_bugs", 0),
                        "widgets": unrelated_counts.get("unrelated_widgets", 0)
                    }
                }
            }
            
            # 2. Device Type Distribution (Global and Discovery-specific)
            cursor.execute("SELECT device_type, COUNT(*), AVG(rating) FROM reviews GROUP BY device_type")
            device_global = []
            for row in cursor.fetchall():
                device_global.append({
                    "device": row[0],
                    "count": row[1],
                    "percentage": round((row[1] / total_reviews) * 100, 2) if total_reviews else 0,
                    "avg_rating": round(row[2], 2) if row[2] else 0.0
                })
                
            cursor.execute("""
                SELECT device_type, COUNT(*), AVG(rating) 
                FROM reviews 
                WHERE cluster_id IS NOT NULL AND cluster_id NOT LIKE 'unrelated_%'
                GROUP BY device_type
            """)
            device_discovery = []
            for row in cursor.fetchall():
                device_discovery.append({
                    "device": row[0],
                    "count": row[1],
                    "percentage": round((row[1] / discovery_count) * 100, 2) if discovery_count else 0,
                    "avg_rating": round(row[2], 2) if row[2] else 0.0
                })
                
            metrics["device_distribution"] = {
                "global": device_global,
                "discovery": device_discovery
            }
            
            # 3. Source Distribution
            cursor.execute("SELECT source, COUNT(*), AVG(rating) FROM reviews GROUP BY source")
            source_dist = []
            for row in cursor.fetchall():
                source_dist.append({
                    "source": row[0],
                    "count": row[1],
                    "percentage": round((row[1] / total_reviews) * 100, 2) if total_reviews else 0,
                    "avg_rating": round(row[2], 2) if row[2] else 0.0
                })
            metrics["source_distribution"] = source_dist
            
            # 4. Research Questions (RQ) Share of Voice
            # Since the mapping is stored in JSON/Python, we will load from the database
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='research_answers'")
            rq_list = []
            if cursor.fetchone():
                cursor.execute("SELECT rq_id, title, confidence_score, content FROM research_answers")
                for row in cursor.fetchall():
                    rq_id, title, conf, content_json = row
                    content = json.loads(content_json)
                    # We count clusters routed to this RQ
                    rq_list.append({
                        "rq_id": rq_id,
                        "title": title,
                        "confidence_score": conf,
                        "findings_count": len(content.get("key_findings", [])),
                        "opportunities_count": len(content.get("actionable_opportunities", []))
                    })
            metrics["research_questions"] = rq_list
            
            # 5. Verified Refined Themes Verification Rates
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decomposed_themes'")
            themes_list = []
            if cursor.fetchone():
                cursor.execute("SELECT theme_id, name, category FROM decomposed_themes")
                for row in cursor.fetchall():
                    tid, name, cat = row
                    cursor.execute("SELECT COUNT(*) FROM theme_reviews WHERE theme_id = ?", (tid,))
                    count = cursor.fetchone()[0]
                    themes_list.append({
                        "theme_id": tid,
                        "name": name,
                        "category": cat,
                        "verified_reviews_count": count
                    })
            metrics["refined_themes"] = themes_list
            
            conn.close()
            
            # Save compiled report to SQLite
            self.save_report_to_db(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error compiling metrics: {e}")
            return {}

    def save_report_to_db(self, report: Dict[str, Any]):
        """Saves the compiled metrics report to a dedicated SQLite table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compiled_analytics_report (
                    id TEXT PRIMARY KEY,
                    report_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT INTO compiled_analytics_report (id, report_json, updated_at)
                VALUES ('latest', ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    report_json = excluded.report_json,
                    updated_at = datetime('now')
            """, (json.dumps(report),))
            conn.commit()
            conn.close()
            logger.info("AnalyticsCompiler: Saved compiled analytics report to SQLite.")
        except Exception as e:
            logger.error(f"Error saving compiled report to database: {e}")
