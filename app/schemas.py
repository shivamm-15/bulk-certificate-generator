import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import settings

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RecipientIn(BaseModel):
    """Validated per recipient (not at request level) so one bad row doesn't reject the batch."""

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=320)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v


class JobCreate(BaseModel):
    """Request-level validation: shape of the whole request."""

    course_title: str = Field(min_length=1, max_length=200)
    issuer_name: str = Field(default="Certificate Authority", min_length=1, max_length=200)
    issue_date: date = Field(default_factory=date.today)
    # Items are validated individually later (see services.create_job).
    recipients: list[Any] = Field(min_length=1, max_length=settings.max_recipients)


class JobOut(BaseModel):
    id: str
    status: str
    course_title: str
    issuer_name: str
    issue_date: date
    total: int
    succeeded: int
    failed: int
    pending: int
    progress: float  # 0.0 - 1.0 (finished / total)
    created_at: datetime
    completed_at: datetime | None


class CertificateOut(BaseModel):
    id: str
    index: int
    recipient_name: str | None
    recipient_email: str | None
    status: str
    error: str | None
    download_url: str | None


class CertificateList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]
