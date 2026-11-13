"""The Source contract and the enabled-sources registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from leadgen.config import Settings
from leadgen.http import HttpClient
from leadgen.models import Area, Category, LeadCandidate, RawRecord


@runtime_checkable
class Source(Protocol):
    """A lead source. ``search`` may raise SourceUnavailable, RateLimited or BadResponse."""

    name: str

    def search(self, category: Category, area: Area) -> list[RawRecord]: ...

    def to_candidate(self, raw: RawRecord, category: Category) -> LeadCandidate | None:
        """Map a raw record to the common shape (None to skip it)."""
        ...


SourceFactory = Callable[[Settings, HttpClient], Source]


def default_factories() -> dict[str, SourceFactory]:
    from leadgen.sources.osm import OsmSource

    return {"osm": lambda settings, http: OsmSource(settings, http)}


def build_sources(
    settings: Settings,
    http: HttpClient,
    factories: Mapping[str, SourceFactory] | None = None,
) -> list[Source]:
    """Instantiate only the sources enabled in settings, in configured order."""
    available = dict(default_factories() if factories is None else factories)
    unknown = [n for n in settings.enabled_sources if n not in available]
    if unknown:
        raise ValueError(f"unknown source(s) enabled: {', '.join(unknown)}")
    return [available[name](settings, http) for name in settings.enabled_sources]
