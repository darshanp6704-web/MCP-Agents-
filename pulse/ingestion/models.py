from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class RawReview:
    text: str
    rating: int
    published_at: datetime
    review_id: Optional[str] = None
    user_name: Optional[str] = None
    app_version: Optional[str] = None

@dataclass
class Review:
    text: str
    rating: int
    review_id: Optional[str] = None
    published_at: Optional[datetime] = None

@dataclass
class RunContext:
    product: str
    iso_week: str
    window_weeks: int
    dry_run: bool = False
    email_mode: str = "draft"
