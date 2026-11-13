"""Shared types: raw records, lead candidates, and typed source errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SourceError(Exception):
    """Base class for source failures."""

    def __init__(self, message: str, source: str = ""):
        super().__init__(message)
        self.source = source


class SourceUnavailable(SourceError):
    """The source could not be reached or timed out."""


class RateLimited(SourceError):
    """The source kept rate-limiting us after bounded retries."""


class BadResponse(SourceError):
    """The source returned something we cannot parse."""


@dataclass(frozen=True)
class RawRecord:
    """One unmodified record from a source, plus how it was obtained."""

    source: str
    source_record_id: str
    payload: str  # raw JSON text of just this record
    request: dict[str, Any] = field(default_factory=dict)
    url: str = ""  # human-viewable page for the record, when the source has one


@dataclass(frozen=True)
class LeadCandidate:
    """Source-independent shape a raw record is mapped to before normalization."""

    source: str
    source_record_id: str
    name: str
    kind: str  # "business" | "event"
    category: str
    phone: str = ""
    website: str = ""
    address_parts: dict[str, str] = field(default_factory=dict)
    lat: float | None = None
    lon: float | None = None
