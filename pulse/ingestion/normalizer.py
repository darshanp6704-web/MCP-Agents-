import re
import logging
from typing import List, Optional
from pulse.ingestion.models import RawReview, Review

logger = logging.getLogger(__name__)

# Emoji pattern covering most unicode ranges for symbols, emojis, and dingbats
EMOJI_PATTERN = re.compile(
    "["
    "\U00010000-\U0010ffff"  # Emojis & supplementary symbols
    "\u2600-\u27bf"          # Dingbats & miscellaneous symbols
    "\u2000-\u32ff"          # Arrows, punctuation, shape characters
    "]+", flags=re.UNICODE
)

# Devanagari unicode block range
DEVANAGARI_PATTERN = re.compile(r'[\u0900-\u097f]')

# Finance, brand, and app usage keywords to filter out domain noise (e.g. cross-app spam)
DOMAIN_KEYWORDS = {
    "groww", "app", "stock", "option", "trade", "sip", "ipo", "mutual", "fund", 
    "money", "pay", "bank", "login", "bug", "issue", "glitch", "broker", "kyc", 
    "pan", "account", "withdraw", "deposit", "portfolio", "scalper", "gtt",
    "statement", "brokerage", "wallet", "balance", "charge", "fee", "ui", "chart",
    "otp", "update", "support", "help", "nifty", "sensex", "market", "intraday"
}

# Critical complaint keywords to lower the word count floor for high-value Hinglish reviews
COMPLAINT_KEYWORDS = {
    "login", "otp", "brokerage", "charge", "fee", "kyc", "fail", "pending", 
    "crash", "slow", "error", "load", "open", "close", "withdraw", "glitch",
    "hang", "delay", "fraud", "scam", "worst", "bugs", "wallet", "loss", "lost"
}

def has_emojis(text: str) -> bool:
    return bool(EMOJI_PATTERN.search(text))

def clean_for_dedup(text: str) -> str:
    """Removes casing, punctuation, and all spaces to create a canonical string for deduplication."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    return "".join(text.split())

def is_domain_relevant(text: str) -> bool:
    """Checks if the review contains at least one domain-related keyword."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in DOMAIN_KEYWORDS)

def check_hybrid_word_count(text: str, min_words: int = 8) -> bool:
    """
    Enforces the hybrid word limit floor:
    - Keep if word count >= min_words (default 8).
    - Keep if word count >= 5 and contains a critical complaint keyword.
    - Otherwise discard.
    """
    words = text.split()
    w_count = len(words)
    if w_count >= min_words:
        return True
    if w_count >= 5:
        text_lower = text.lower()
        return any(kw in text_lower for kw in COMPLAINT_KEYWORDS)
    return False

def is_allowed_language(text: str, allowed_lang: str = "en") -> bool:
    """
    Checks if text is primarily English or Latin-script Hinglish.
    Filters out regional non-Latin scripts (specifically Devanagari for Indian fintech apps like Groww).
    """
    if allowed_lang != "en":
        return True # Default to true for non-en if not specified
        
    total_len = len(text)
    if total_len == 0:
        return False
        
    devanagari_count = len(DEVANAGARI_PATTERN.findall(text))
    # If more than 10% of the characters are Devanagari script, it fails the English/Hinglish check
    if devanagari_count / total_len > 0.1:
        return False
        
    # Also verify it contains at least some ASCII/Latin alphabetical characters
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    if latin_chars == 0:
        return False
        
    return True

def normalize_review(raw: RawReview, min_words: int = 8, allowed_lang: str = "en") -> Optional[Review]:
    """
    Normalizes a RawReview to a canonical Review using a hybrid approach:
    - Discards review if it contains emojis.
    - Discards review if it contains non-latin script (like Hindi Devanagari).
    - Discards review if it has no finance, brand, or app-use domain keywords.
    - Discards review if word count < 8 (or < 5 if it contains critical complaint keywords).
    """
    # 1. Discard if it contains emojis
    if has_emojis(raw.text):
        return None
        
    # 2. Normalize whitespace
    cleaned_text = " ".join(raw.text.split()).strip()
    
    # 3. Discard if it lacks domain relevance
    if not is_domain_relevant(cleaned_text):
        return None

    # 4. Check word count threshold using hybrid logic
    if not check_hybrid_word_count(cleaned_text, min_words):
        return None
        
    # 5. Check language criteria
    if not is_allowed_language(cleaned_text, allowed_lang):
        return None
        
    return Review(
        text=cleaned_text,
        rating=raw.rating,
        review_id=raw.review_id,
        published_at=raw.published_at
    )

def normalize_reviews(
    raw_reviews: List[RawReview],
    min_words: int = 8,
    allowed_lang: str = "en"
) -> List[Review]:
    """
    Processes and filters a list of RawReviews into canonical Reviews.
    Deduplicates reviews based on normalized text hash (punctuation/whitespace stripped) to prevent spam duplicates.
    """
    seen_hashes = set()
    normalized_reviews: List[Review] = []

    for raw in raw_reviews:
        # Deduplication check using clean_for_dedup
        dedup_str = clean_for_dedup(raw.text)
        if not dedup_str:
            continue
            
        raw_hash = hash((dedup_str, raw.rating))
        if raw_hash in seen_hashes:
            continue
        seen_hashes.add(raw_hash)

        norm = normalize_review(raw, min_words=min_words, allowed_lang=allowed_lang)
        if norm:
            normalized_reviews.append(norm)

    logger.info(f"Normalized {len(raw_reviews)} raw reviews to {len(normalized_reviews)} items.")
    return normalized_reviews
