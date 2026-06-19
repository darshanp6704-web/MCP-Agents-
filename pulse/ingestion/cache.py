import os
import json
import logging
from datetime import datetime
from typing import List, Tuple, Optional
from pulse.ingestion.models import RawReview, Review

logger = logging.getLogger(__name__)

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def get_cache_dir(product: str, iso_week: str) -> str:
    """Returns the cache path for a product and ISO week."""
    # Using project workspace directory
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_path = os.path.join(base_dir, "data", "cache", product, iso_week)
    return cache_path

def save_to_cache(
    product: str,
    iso_week: str,
    raw_reviews: List[RawReview],
    normalized_reviews: List[Review],
    window_weeks: int
) -> None:
    """Saves raw reviews, normalized reviews, and ingestion manifest to disk."""
    cache_dir = get_cache_dir(product, iso_week)
    os.makedirs(cache_dir, exist_ok=True)

    raw_path = os.path.join(cache_dir, "reviews_raw.json")
    normalized_path = os.path.join(cache_dir, "reviews_normalized.json")
    manifest_path = os.path.join(cache_dir, "manifest.json")

    # Serialize raw reviews
    raw_data = [
        {
            "text": r.text,
            "rating": r.rating
        }
        for r in raw_reviews
    ]
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2)

    # Serialize normalized reviews
    normalized_data = [
        {
            "text": r.text,
            "rating": r.rating
        }
        for r in normalized_reviews
    ]
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(normalized_data, f, indent=2)

    # Save manifest details
    manifest = {
        "product": product,
        "iso_week": iso_week,
        "window_weeks": window_weeks,
        "raw_count": len(raw_reviews),
        "normalized_count": len(normalized_reviews),
        "timestamp": datetime.utcnow().isoformat()
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Saved ingestion cache to {cache_dir}")

def load_from_cache(product: str, iso_week: str) -> Optional[Tuple[List[RawReview], List[Review]]]:
    """Loads raw and normalized reviews from local cache if they exist."""
    cache_dir = get_cache_dir(product, iso_week)
    raw_path = os.path.join(cache_dir, "reviews_raw.json")
    normalized_path = os.path.join(cache_dir, "reviews_normalized.json")
    manifest_path = os.path.join(cache_dir, "manifest.json")

    if not (os.path.exists(raw_path) and os.path.exists(normalized_path) and os.path.exists(manifest_path)):
        return None

    try:
        # Load raw reviews
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        raw_reviews = [
            RawReview(
                text=item["text"],
                rating=item["rating"],
                published_at=None,
                review_id=None,
                user_name=None,
                app_version=None
            )
            for item in raw_data
        ]

        # Load normalized reviews
        with open(normalized_path, "r", encoding="utf-8") as f:
            normalized_data = json.load(f)
        normalized_reviews = [
            Review(
                text=item["text"],
                rating=item["rating"],
                review_id=None,
                published_at=None
            )
            for item in normalized_data
        ]

        logger.info(f"Loaded {len(raw_reviews)} raw / {len(normalized_reviews)} normalized reviews from cache ({cache_dir})")
        return raw_reviews, normalized_reviews

    except Exception as e:
        logger.warning(f"Failed to load cache from {cache_dir}: {e}. Falling back to full scrape.")
        return None
