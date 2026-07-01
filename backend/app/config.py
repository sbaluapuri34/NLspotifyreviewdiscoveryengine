import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from backend/.env or parent .env
base_dir = Path(__file__).resolve().parent.parent
load_dotenv(base_dir / ".env")
load_dotenv(base_dir.parent / ".env")

# API Keys
GEMINI_API_KEY = os.getenv("THEME_X_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEYS = [k.strip() for k in (os.getenv("THEME_X_GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEYS", "")).split(",") if k.strip()]
if not GEMINI_API_KEYS and GEMINI_API_KEY:
    GEMINI_API_KEYS = [GEMINI_API_KEY]
YOUTUBE_API_KEY = os.getenv("THEME_X_YOUTUBE_API_KEY") or os.getenv("YOUTUBE_API_KEY", "")
APIFY_API_TOKEN = os.getenv("THEME_X_APIFY_API_TOKEN") or os.getenv("APIFY_API_TOKEN", "")
APIFY_API_TOKENS = [t.strip() for t in (os.getenv("THEME_X_APIFY_API_TOKENS") or os.getenv("APIFY_API_TOKENS", "")).split(",") if t.strip()]
if not APIFY_API_TOKENS and APIFY_API_TOKEN:
    APIFY_API_TOKENS = [APIFY_API_TOKEN]
GROQ_API_KEYS = [k.strip() for k in (os.getenv("THEME_X_GROQ_API_KEYS") or os.getenv("GROQ_API_KEYS", "")).split(",") if k.strip()]
if not GROQ_API_KEYS and os.getenv("GROQ_API_KEY"):
    GROQ_API_KEYS = [os.getenv("GROQ_API_KEY")]

# Ingestion Config
PLAY_STORE_PACKAGE = "com.spotify.music"
APP_STORE_ID = 324684580
COUNTRY_IN = "in"

TARGET_PLAY_STORE_REVIEWS = 6000
TARGET_APP_STORE_REVIEWS = 4000
TARGET_REDDIT_POSTS = 1000
TARGET_FORUM_POSTS = 500
TARGET_YOUTUBE_COMMENTS = 1000
TIME_HORIZON_DAYS = 180

# Database Config
DB_PATH = os.getenv("DATABASE_PATH", str(base_dir / "spotify_research.db"))

# Adaptive Clustering Config
# Format: (dataset_size_upper_bound_exclusive, similarity_threshold)
ADAPTIVE_THRESHOLDS = [
    (500, 0.80),
    (1500, 0.75),
    (4000, 0.70),
    (8000, 0.65),
    (float('inf'), 0.60)
]

# Pipeline Config
MIN_WORD_COUNT = 3
LSH_NUM_PERM = 128
LSH_THRESHOLD = 0.80

PRIORITY_ROUTING_KEYWORDS = [
    "discover weekly",
    "discover",
    "release radar",
    "smart shuffle",
    "daily mix",
    "recommendations",
    "recommend",
    "home feed",
    "ai dj",
    "algorithmic",
    "shuffle"
]

# Indian Location Gazetteer (States, Union Territories, and Major Cities)
INDIAN_LOCATIONS = {
    # States & UTs
    "andhra pradesh": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "odisha": "Odisha",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamil nadu": "Tamil Nadu",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "west bengal": "West Bengal",
    "delhi": "Delhi NCR",
    "new delhi": "Delhi NCR",
    "ncr": "Delhi NCR",
    "jammu": "Jammu & Kashmir",
    "kashmir": "Jammu & Kashmir",
    "ladakh": "Ladakh",
    "puducherry": "Puducherry",
    "pondicherry": "Puducherry",
    "chandigarh": "Chandigarh",
    
    # Cities (Tier 1 & Major Tier 2/3)
    "mumbai": "Mumbai",
    "bombay": "Mumbai",
    "pune": "Pune",
    "nagpur": "Maharashtra",
    "thane": "Mumbai",
    "navi mumbai": "Mumbai",
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "mysore": "Karnataka",
    "hubli": "Karnataka",
    "mangalore": "Karnataka",
    "chennai": "Chennai",
    "madras": "Chennai",
    "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu",
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "warangal": "Telangana",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "darjeeling": "West Bengal",
    "ahmedabad": "Gujarat",
    "surat": "Gujarat",
    "vadodara": "Gujarat",
    "baroda": "Gujarat",
    "rajkot": "Gujarat",
    "jaipur": "Rajasthan",
    "jodhpur": "Rajasthan",
    "udaipur": "Rajasthan",
    "lucknow": "Uttar Pradesh",
    "kanpur": "Uttar Pradesh",
    "noida": "Delhi NCR",
    "greater noida": "Delhi NCR",
    "ghaziabad": "Delhi NCR",
    "gurugram": "Delhi NCR",
    "gurgaon": "Delhi NCR",
    "faridabad": "Delhi NCR",
    "patna": "Bihar",
    "ranchi": "Jharkhand",
    "jamshedpur": "Jharkhand",
    "bhopal": "Madhya Pradesh",
    "indore": "Madhya Pradesh",
    "gwalior": "Madhya Pradesh",
    "jabalpur": "Madhya Pradesh",
    "raipur": "Chhattisgarh",
    "bhubaneswar": "Odisha",
    "cuttack": "Odisha",
    "guwahati": "Assam",
    "amritsar": "Punjab",
    "ludhiana": "Punjab",
    "jalandhar": "Punjab",
    "kochi": "Kerala",
    "cochin": "Kerala",
    "trivandrum": "Kerala",
    "thiruvananthapuram": "Kerala",
    "visakhapatnam": "Andhra Pradesh",
    "vizag": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh",
    "guntur": "Andhra Pradesh",
    "dehradun": "Uttarakhand",
    "shimla": "Himachal Pradesh",
    "srinagar": "Jammu & Kashmir",
}
