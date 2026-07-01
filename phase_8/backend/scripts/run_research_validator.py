import os
import sys
import time
from pathlib import Path
from loguru import logger

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent.parent
sys_path = str(project_root)
if sys_path not in os.sys.path:
    os.sys.path.append(sys_path)

from backend.app.research_validator import ResearchValidator

def main():
    logger.info("Starting Phase 4.8: LLM Research Validation & Executive Insights Synthesis...")
    start_time = time.time()

    # 1. Initialize Validator
    validator = ResearchValidator()

    # 2. Run Validation & Synthesis
    insights = validator.validate_and_synthesize()
    if not insights:
        logger.error("Failed to generate research validation insights.")
        return

    # 3. Print Summary
    print("\n" + "="*65)
    print("PHASE 4.8: LLM RESEARCH VALIDATION & EXECUTIVE INSIGHTS")
    print("="*65)
    print(f"\n[1] EXECUTIVE SUMMARY:")
    print(insights.get("executive_summary", "N/A"))
    
    print(f"\n[2] OVERALL RESEARCH CONFIDENCE: {insights.get('overall_research_confidence_score', 0.0):.2f}")
    
    print("\n[3] TOP PM RECOMMENDATIONS:")
    for rec in insights.get("pm_recommendations", [])[:3]:
        print(f"  - [Priority {rec.get('priority')}] {rec.get('recommendation')}")
        print(f"    Rationale: {rec.get('strategic_rationale')}")
        
    print("\n" + "="*65)
    elapsed = time.time() - start_time
    logger.info(f"Research Validator completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()
