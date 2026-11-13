"""Search orchestration: validate, resolve the area, query sources, normalize, dedupe, store."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from leadgen.categories import Catalog, UnknownCategory, load_catalog
from leadgen.config import Settings
from leadgen.db import DuplicateRecordError, Repository
from leadgen.dedupe import dedupe_lead
from leadgen.geocode import AmbiguousArea, AreaError, AreaNotFound, AreaTooLarge, Geocoder
from leadgen.models import BadResponse, RateLimited, SourceError
from leadgen.normalize import normalize_candidate
from leadgen.sources.base import Source


class InvalidSearch(ValueError):
    """The search input is missing or unusable; ``fields`` names what to fix."""

    def __init__(self, message: str, fields: tuple[str, ...] = ()):
        super().__init__(message)
        self.fields = fields


@dataclass(frozen=True)
class Submission:
    search_id: int
    cached: bool  # True when an identical recent search is reused (no work to do)


def _failure_kind(exc: SourceError) -> str:
    if isinstance(exc, RateLimited):
        return "rate_limited"
    if isinstance(exc, BadResponse):
        return "bad_response"
    return "unavailable"


class SearchService:
    def __init__(
        self,
        repo: Repository,
        sources: list[Source],
        geocoder: Geocoder,
        settings: Settings,
        catalog_loader: Callable[[], Catalog] | None = None,
    ):
        self.repo = repo
        self.sources = sources
        self.geocoder = geocoder
        self.settings = settings
        self._load_catalog = catalog_loader or (lambda: load_catalog(settings.categories_path))

    def catalog(self) -> Catalog:
        return self._load_catalog()

    # --- step 1: validate and register ----------------------------------------------------
    def submit(self, category: str, area: str, refresh: bool = False) -> Submission:
        """Validate input and create (or reuse) a search. Raises InvalidSearch/UnknownCategory
        before any source or geocoder is contacted."""
        category, area = (category or "").strip(), (area or "").strip()
        missing = tuple(n for n, v in (("category", category), ("area", area)) if not v)
        if missing:
            raise InvalidSearch("Please provide " + " and ".join(missing), missing)
        cat = self.catalog().get(category)  # raises UnknownCategory
        if not refresh:
            prior = self.repo.latest_finished_search(cat.key, area)
            if prior is not None:
                age = self.repo.now() - _parse(prior["finished_at"])
                if age < timedelta(hours=self.settings.cache_hours):
                    return Submission(prior["id"], cached=True)
        return Submission(self.repo.create_search(cat.key, area), cached=False)

    # --- step 2: do the work --------------------------------------------------------------
    def execute(self, search_id: int, choice: str | None = None) -> str:
        """Run a registered search to completion and return its final status."""
        try:
            return self._execute(search_id, choice)
        except Exception as exc:  # never leave a search stuck as "running"
            self.repo.finish_search(
                search_id, "failed", f"Unexpected error: {exc.__class__.__name__}"
            )
            return "failed"

    def _execute(self, search_id: int, choice: str | None) -> str:
        row = self.repo.get_search(search_id)
        try:
            category = self.catalog().get(row["category"])
        except UnknownCategory:
            self.repo.finish_search(search_id, "failed", "That category is no longer supported.")
            return "failed"

        try:
            area = self.geocoder.resolve(row["area"], choice)
        except AmbiguousArea as exc:
            choices = [{"choice_id": a.choice_id, "name": a.name} for a in exc.candidates]
            self.repo.finish_search(
                search_id, "needs_choice", "Several places match. Please choose one.",
                candidates=choices,
            )  # fmt: skip
            return "needs_choice"
        except AreaNotFound:
            self.repo.finish_search(
                search_id, "failed", "Area not found. Try adding a state or country."
            )
            return "failed"
        except AreaTooLarge as exc:
            self.repo.finish_search(
                search_id, "failed", f"Area too large to search: {exc}. Pick a smaller area."
            )
            return "failed"
        except AreaError as exc:  # pragma: no cover - future subclasses
            self.repo.finish_search(search_id, "failed", str(exc))
            return "failed"
        except SourceError as exc:
            failure = {
                "source": exc.source or "geocoder",
                "error": str(exc),
                "kind": _failure_kind(exc),
            }
            self.repo.finish_search(
                search_id, "failed", f"Could not resolve the area: {exc}", failures=[failure]
            )
            return "failed"

        region = area.country_code or self.settings.default_region
        failures: list[dict[str, str]] = []
        succeeded = 0
        for source in self.sources:
            try:
                records = source.search(category, area)
            except SourceError as exc:
                failures.append(
                    {"source": source.name, "error": str(exc), "kind": _failure_kind(exc)}
                )
                continue
            succeeded += 1
            for raw in records:
                self._store(search_id, source, category, raw, region)

        if self.sources and succeeded == 0:
            names = ", ".join(f["source"] for f in failures)
            kinds = {f["kind"] for f in failures}
            reason = "rate-limited" if kinds == {"rate_limited"} else "unavailable"
            self.repo.finish_search(
                search_id,
                "failed",
                f"Source {reason}: {names}. Try again later.",
                failures=failures,
            )
            return "failed"
        if failures:
            names = ", ".join(f["source"] for f in failures)
            self.repo.finish_search(
                search_id, "partial", f"Results may be incomplete: {names} failed.", failures=failures
            )  # fmt: skip
            return "partial"
        n = len(self.repo.search_lead_ids(search_id))
        self.repo.finish_search(search_id, "done", "" if n else "No leads found.")
        return "done"

    def _store(self, search_id: int, source: Source, category: Any, raw: Any, region: str) -> None:
        request = {**raw.request, "url": raw.url}
        try:
            raw_id = self.repo.save_raw_record(
                search_id, raw.source, raw.source_record_id, raw.payload, request
            )
        except DuplicateRecordError:
            return
        candidate = source.to_candidate(raw, category)
        if candidate is None:
            return
        existing = self.repo.find_lead_by_source_record(raw.source, raw.source_record_id)
        if existing is not None:
            lead_id = existing
            self.repo.link_source(lead_id, raw_id)
        else:
            lead_id = self.repo.insert_lead(**normalize_candidate(candidate, region))
            self.repo.link_source(lead_id, raw_id)
            lead_id = dedupe_lead(self.repo, lead_id, self.settings)
        self.repo.link_search_lead(search_id, lead_id)

    # --- reading --------------------------------------------------------------------------
    def results(self, search_id: int) -> list[dict[str, Any]]:
        return [self.lead_view(lid) for lid in self.repo.search_lead_ids(search_id)]

    def lead_view(self, lead_id: int) -> dict[str, Any]:
        lead = dict(self.repo.get_lead(lead_id))
        lead["extra_phones"] = json.loads(lead["extra_phones"])
        sources = []
        for raw in self.repo.lead_sources(lead_id):
            request = json.loads(raw["request"])
            sources.append(
                {
                    "source": raw["source"],
                    "source_record_id": raw["source_record_id"],
                    "fetched_at": raw["fetched_at"],
                    "url": request.get("url", ""),
                }
            )
        lead["sources"] = sources
        lead["source_names"] = sorted({s["source"] for s in sources})
        return lead


def _parse(ts: str):
    from datetime import datetime

    return datetime.fromisoformat(ts)
