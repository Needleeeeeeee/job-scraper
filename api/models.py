"""Pydantic schemas for the job-scraper API."""
from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

STATUSES = {"NEW", "REVIEWED", "APPLIED", "SKIP", "REJECTED"}


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    company: str
    url: str
    location: str | None = None
    date_posted: date | None = None
    status: str
    scraped_at: datetime
    applied_at: datetime | None = None
    status_updated_at: datetime | None = None


class JobStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(NEW|REVIEWED|APPLIED|SKIP|REJECTED)$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)