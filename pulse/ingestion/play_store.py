import logging
from datetime import datetime, timedelta
from typing import List, Tuple
from google_play_scraper import reviews as play_reviews, Sort
from pulse.ingestion.models import RawReview

logger = logging.getLogger(__name__)

def fetch_play_store_reviews(
    app_id: str,
    end_date: datetime,
    window_weeks: int,
    max_reviews: int = 5000
) -> List[RawReview]:
    """
    Fetches reviews for `app_id` from Google Play Store published within the window:
    [end_date - window_weeks, end_date].
    Paginates using continuation tokens.
    """
    start_date = end_date - timedelta(weeks=window_weeks)
    logger.info(f"Ingesting reviews for {app_id} between {start_date.date()} and {end_date.date()}")

    all_raw_reviews: List[RawReview] = []
    continuation_token = None
    total_fetched = 0
    
    # We fetch in batches of 200 reviews (max allowed or standard size)
    batch_size = 200

    while total_fetched < max_reviews:
        try:
            if continuation_token:
                result, continuation_token = play_reviews(
                    app_id,
                    continuation_token=continuation_token
                )
            else:
                result, continuation_token = play_reviews(
                    app_id,
                    lang='en',
                    country='in',
                    sort=Sort.NEWEST,
                    count=batch_size
                )
        except Exception as e:
            logger.error(f"Error fetching reviews from Google Play Scraper: {e}")
            raise e

        if not result:
            logger.info("No more reviews returned from Play Store scraper.")
            break

        batch_added = 0
        reached_older_than_window = False

        for r in result:
            pub_at = r.get("at")
            if not isinstance(pub_at, datetime):
                # Fallback parser if at is a string, though google-play-scraper returns datetime
                pub_at = datetime.fromisoformat(str(pub_at)) if pub_at else datetime.utcnow()
            
            # Since Sort.NEWEST returns newest reviews first, if we see a review older than start_date,
            # we can stop paging.
            if pub_at < start_date:
                reached_older_than_window = True
                continue
            
            # We filter reviews that fall within the exact window [start_date, end_date]
            if pub_at <= end_date:
                raw_rev = RawReview(
                    text=r.get("content", ""),
                    rating=r.get("score", 0),
                    published_at=pub_at,
                    review_id=r.get("reviewId"),
                    user_name=r.get("userName"),
                    app_version=r.get("reviewCreatedVersion")
                )
                all_raw_reviews.append(raw_rev)
                batch_added += 1

        total_fetched += len(result)
        logger.info(f"Fetched batch of {len(result)} reviews. Added {batch_added} within window. Total in window: {len(all_raw_reviews)}")

        if reached_older_than_window:
            logger.info("Reached reviews older than window start date. Stopping pagination.")
            break

        if not continuation_token:
            logger.info("No continuation token returned. End of reviews pagination.")
            break

    logger.info(f"Ingestion complete. Total reviews in window: {len(all_raw_reviews)}")
    return all_raw_reviews
