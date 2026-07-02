import os
import sys
import requests
from loguru import logger

def main():
    backend_url = os.environ.get("BACKEND_API_URL")
    trigger_secret = os.environ.get("PIPELINE_TRIGGER_SECRET")
    
    if not backend_url:
        logger.error("BACKEND_API_URL environment variable is missing!")
        sys.exit(1)
        
    # Ensure correct URL format
    url = f"{backend_url.rstrip('/')}/api/run-pipeline"
    
    # Configure required cron scrape parameters (Discovery Engine only)
    params = {
        "limit_google_play": 800,
        "limit_reddit": 200,
        "limit_youtube": 100,
        "limit_spotify_community": 100,
        "limit_app_store": 0,
        "run_type": "cumulative"
    }
    
    headers = {}
    if trigger_secret:
        headers["X-Pipeline-Secret"] = trigger_secret
        logger.info("Security secret key detected; configuring header authorization.")
        
    logger.info(f"Triggering scheduled bi-weekly ingestion pipeline at: {url}")
    logger.info(f"Configured limits: GP={params['limit_google_play']}, Reddit={params['limit_reddit']}, YT={params['limit_youtube']}, Forums={params['limit_spotify_community']}")
    
    try:
        response = requests.post(url, params=params, headers=headers, timeout=45)
        if response.status_code == 200:
            logger.info("Pipeline execution successfully scheduled on the production backend!")
            logger.info(f"Server response: {response.json()}")
        else:
            logger.error(f"Failed to schedule pipeline. HTTP Status Code: {response.status_code}")
            logger.error(f"Server error details: {response.text}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to connect to the backend server at {url}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
