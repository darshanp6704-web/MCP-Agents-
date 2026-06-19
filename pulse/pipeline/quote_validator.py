import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def normalize_whitespace_and_punctuation(text: str) -> str:
    """
    Normalizes whitespace and removes punctuation, converting text to lowercase.
    This ensures quote comparisons are robust to minor formatting changes.
    """
    if not text:
        return ""
    text = text.lower()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse multiple spaces
    return " ".join(text.split())

def is_quote_in_review(quote: str, review_text: str) -> bool:
    """
    Checks if a quote matches a review text.
    Handles ellipsis (...) or unicode ellipsis (\u2026) split checks to ensure
    all sub-parts appear sequentially in the review.
    """
    # Split quote by standard ellipsis patterns
    parts = re.split(r'\.\.\.|\u2026', quote)
    # Filter out empty entries
    clean_parts = [p.strip() for p in parts if p.strip()]
    if not clean_parts:
        return False

    norm_review = normalize_whitespace_and_punctuation(review_text)
    norm_parts = [normalize_whitespace_and_punctuation(p) for p in clean_parts]

    # Verify each part is present sequentially in the review
    current_index = 0
    for part in norm_parts:
        idx = norm_review.find(part, current_index)
        if idx == -1:
            return False
        current_index = idx + len(part)

    return True

def validate_theme_quotes(
    theme_data: Dict[str, Any],
    cluster_reviews: List[str],
    full_corpus_reviews: List[str]
) -> Dict[str, Any]:
    """
    Validates all quotes inside theme_data.
    Checks target cluster reviews first, and falls back to full corpus.
    Failing quotes are removed from the theme.
    """
    quotes = theme_data.get("quotes", [])
    valid_quotes = []

    for q in quotes:
        # Check against reviews in the same cluster first
        matched = False
        for rev_text in cluster_reviews:
            if is_quote_in_review(q, rev_text):
                valid_quotes.append(q)
                matched = True
                break
                
        if not matched:
            # Fallback to check against all other reviews in the runs
            for rev_text in full_corpus_reviews:
                if is_quote_in_review(q, rev_text):
                    valid_quotes.append(q)
                    matched = True
                    break
                    
        if not matched:
            logger.warning(f"Quote validation FAILED. Dropping hallucinated quote: \"{q}\"")

    theme_data["quotes"] = valid_quotes
    return theme_data
