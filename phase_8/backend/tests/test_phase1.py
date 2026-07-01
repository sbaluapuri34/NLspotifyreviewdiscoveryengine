import os
import pytest
import tempfile
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Set up test database path before importing database module
temp_db = tempfile.NamedTuple = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_PATH"] = temp_db

from backend.app.database import init_db, save_review, get_reviews, get_db_connection
from backend.app.pipeline import TextPipeline
from backend.app.ingestion import PlayStoreScraper, AppStoreScraper, SpotifyForumsScraper

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Initializes the database before running tests and removes it after."""
    init_db()
    yield
    if os.path.exists(temp_db):
        try:
            os.remove(temp_db)
        except OSError:
            pass

def test_database_crud():
    """Tests saving and retrieving reviews from the SQLite database."""
    review = {
        "id": "test_id_123",
        "raw_text": "This is a raw review.",
        "translated_text": "This is a translated review.",
        "rating": 5,
        "source": "google_play",
        "country": "in",
        "sentiment": 0.8,
        "location": "Bengaluru",
        "published_at": "2026-06-29T12:00:00+00:00"
    }
    
    # Save review
    success = save_review(review)
    assert success is True
    
    # Retrieve review
    retrieved = get_reviews(sources=["google_play"])
    assert len(retrieved) >= 1
    saved_review = next((r for r in retrieved if r["id"] == "test_id_123"), None)
    assert saved_review is not None
    assert saved_review["raw_text"] == "This is a raw review."
    assert saved_review["rating"] == 5
    assert saved_review["location"] == "Bengaluru"
    
    # Test date filtering
    filtered = get_reviews(from_date="2026-06-29T13:00:00+00:00")
    # Should not contain test_id_123 because it was published at 12:00:00
    assert not any(r["id"] == "test_id_123" for r in filtered)


def test_pipeline_cleaning_and_pii():
    """Tests that PII, URLs, and emojis are stripped correctly."""
    pipeline = TextPipeline()
    
    dirty_text = "Hello! Contact me at test@example.com or +91 98765 43210. Visit https://spotify.com. My twitter is @spotty. 🎵🔥 Nice app!"
    clean_text = pipeline.filter_pii_and_noise(dirty_text)
    
    assert "test@example.com" not in clean_text
    assert "+91 98765 43210" not in clean_text
    assert "https://spotify.com" not in clean_text
    assert "@spotty" not in clean_text
    assert "🎵" not in clean_text
    assert "🔥" not in clean_text
    assert "Nice app!" in clean_text


def test_pipeline_language_translation():
    """Tests language detection and translation."""
    pipeline = TextPipeline()
    
    # Test English detection
    assert pipeline.detect_language("This is a great music app") == "en"
    
    # Test Hindi translation (using mocked translator to avoid network dependency in tests)
    with patch('backend.app.pipeline.GoogleTranslator') as mock_translator:
        instance = mock_translator.return_value
        instance.translate.return_value = "This is very good"
        
        translated = pipeline.translate_to_english("यह बहुत अच्छा है", "hi")
        assert translated == "This is very good"
        instance.translate.assert_called_once_with("यह बहुत अच्छा है")


def test_pipeline_length_filter_and_priority_routing():
    """Tests that short reviews are filtered unless they contain priority keywords."""
    pipeline = TextPipeline()
    
    # 1. Short review without priority keywords -> should be filtered (None)
    short_review = {
        "id": "short_1",
        "raw_text": "Good app",
        "rating": 5,
        "source": "app_store",
        "country": "in",
        "published_at": "2026-06-29T12:00:00"
    }
    processed = pipeline.process_review(short_review)
    assert processed is None
    
    # 2. Short review WITH priority keywords -> should bypass filter
    priority_review = {
        "id": "priority_1",
        "raw_text": "Smart Shuffle is bad",
        "rating": 2,
        "source": "app_store",
        "country": "in",
        "published_at": "2026-06-29T12:00:00"
    }
    processed = pipeline.process_review(priority_review)
    assert processed is not None
    assert processed["id"] == "priority_1"


def test_pipeline_lsh_deduplication():
    """Tests MinHash + LSH near-duplicate detection."""
    pipeline = TextPipeline()
    
    rev1_text = "I really love using this application to discover new music and create custom playlists every single day."
    rev2_text = "I really love using this app to discover new music and create custom playlists every single day." # slightly different
    rev3_text = "This is a completely different review about casting issues on Sonos speakers in my home."
    
    # First review should be indexed and not flagged as duplicate
    is_dup1 = pipeline.is_duplicate_lsh("rev1", rev1_text)
    assert is_dup1 is False
    
    # Second review is highly similar -> should be flagged as duplicate
    is_dup2 = pipeline.is_duplicate_lsh("rev2", rev2_text)
    assert is_dup2 is True
    
    # Third review is completely different -> should not be flagged
    is_dup3 = pipeline.is_duplicate_lsh("rev3", rev3_text)
    assert is_dup3 is False


def test_location_extraction():
    """Tests extraction of Indian locations from review text."""
    pipeline = TextPipeline()
    
    assert pipeline.extract_location("I am using Spotify in Bengaluru, Karnataka") == "Bengaluru"
    assert pipeline.extract_location("Greeting from New Delhi!") == "Delhi NCR"
    assert pipeline.extract_location("Worst connectivity in Pune city") == "Pune"
    assert pipeline.extract_location("Nice song") is None


def test_textrank_compression():
    """Tests the extractive TextRank summarizer."""
    pipeline = TextPipeline()
    
    long_text = (
        "Spotify is a great application for music listening. "
        "I use Spotify every day to listen to my favorite songs. "
        "However, the smart shuffle feature has been very repetitive lately. "
        "It keeps playing the same 15 songs over and over again. "
        "I hope the developers fix this smart shuffle loop bug soon. "
        "Otherwise, I might switch to Apple Music or YouTube Music."
    )
    
    compressed = pipeline.compress_text_textrank(long_text, num_sentences=3)
    sentences = [s.strip() for s in compressed.split(".") if s.strip()]
    
    # Should be compressed to around 3 sentences
    assert len(sentences) <= 3
    # Key terms from the most central sentences should be present
    assert "shuffle" in compressed.lower()


@pytest.mark.asyncio
async def test_scrapers_mocked():
    """Tests that scrapers handle mocked data and format it correctly."""
    
    # 1. Mock Google Play reviews
    with patch('google_play_scraper.reviews') as mock_gp:
        mock_gp.return_value = ([
            {
                'reviewId': 'gp_1',
                'content': 'Excellent music selection',
                'score': 5,
                'at': datetime(2026, 6, 29, 12, 0, 0)
            }
        ], None)
        
        scraper = PlayStoreScraper()
        queue = asyncio.Queue()
        await scraper.scrape(queue, limit=5)
        
        results = []
        while not queue.empty():
            results.append(await queue.get())
            
        assert len(results) == 1
        assert results[0]["id"] == "gp_1"
        assert results[0]["rating"] == 5
        assert results[0]["source"] == "google_play"

    # 2. Mock App Store reviews using ApifyClient
    with patch('apify_client.ApifyClient') as mock_apify:
        mock_client = mock_apify.return_value
        mock_actor = mock_client.actor.return_value
        
        # Mock start() to return run info
        mock_run = MagicMock()
        mock_run.id = "test_run_id"
        mock_actor.start.return_value = mock_run
        
        # Mock run().get() to return status SUCCEEDED
        mock_client.run.return_value.get.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "test_dataset"
        }
        
        # Mock dataset().list_items() to return items
        mock_dataset = MagicMock()
        mock_dataset.items = [
            {
                "id": "as_1",
                "title": "Good",
                "review": "Love the UI design",
                "rating": 4,
                "date": "2026-06-29T12:00:00-07:00"
            }
        ]
        mock_client.dataset.return_value.list_items.return_value = mock_dataset

        
        with patch('backend.app.ingestion.APIFY_API_TOKEN', 'dummy_token'):
            scraper = AppStoreScraper()
            queue = asyncio.Queue()
            await scraper.scrape(queue, limit=5)
            
            results = []
            while not queue.empty():
                results.append(await queue.get())
                
            assert len(results) == 1
            assert "Love the UI design" in results[0]["raw_text"]
            assert results[0]["rating"] == 4
            assert results[0]["source"] == "app_store"
