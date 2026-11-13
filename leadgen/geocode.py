"""Nominatim geocoding with caching, ambiguity detection, and size limits."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from leadgen.config import Settings
from leadgen.db import Repository
from leadgen.http import HttpClient
from leadgen.models import Area, BadResponse


class AreaError(Exception):
    """Base class for area resolution failures."""


class AreaNotFound(AreaError):
    pass


class AreaTooLarge(AreaError):
    def __init__(self, area: Area, limit: float):
        super().__init__(
            f"{area.name} is about {area.area_km2:,.0f} km², over the {limit:,.0f} km² limit"
        )
        self.area = area


class AmbiguousArea(AreaError):
    def __init__(self, candidates: list[Area]):
        super().__init__("area matches several places")
        self.candidates = candidates


def bbox_area_km2(south: float, west: float, north: float, east: float) -> float:
    height = abs(north - south) * 111.32
    mid = math.radians((north + south) / 2)
    return height * abs(east - west) * 111.32 * math.cos(mid)


def _to_area(item: dict[str, Any]) -> Area:
    try:
        south, north, west, east = (float(x) for x in item["boundingbox"])
        return Area(
            name=str(item["display_name"]),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            bbox=(south, west, north, east),
            osm_type=str(item.get("osm_type", "")),
            osm_id=int(item.get("osm_id", 0)),
            country_code=str(item.get("address", {}).get("country_code", "")).upper(),
            area_km2=bbox_area_km2(south, west, north, east),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BadResponse(f"unexpected Nominatim result: {exc}", "nominatim") from exc


class Geocoder:
    def __init__(self, http: HttpClient, repo: Repository, settings: Settings):
        self.http = http
        self.repo = repo
        self.settings = settings

    def _fetch(self, query: str) -> list[dict[str, Any]]:
        cached = self.repo.get_geocode(query)
        if cached is not None:
            return cached[0]
        resp = self.http.get(
            self.settings.nominatim_url.rstrip("/") + "/search",
            params={"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 1},
            source="nominatim",
            throttle_key="nominatim",
            min_interval=self.settings.nominatim_min_interval,
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadResponse("Nominatim returned invalid JSON", "nominatim") from exc
        if not isinstance(data, list):
            raise BadResponse("Nominatim returned an unexpected shape", "nominatim")
        self.repo.put_geocode(query, data)
        return data

    def resolve(self, query: str, choice: str | None = None) -> Area:
        """Resolve text to a single area.

        Raises AreaNotFound, AmbiguousArea (with candidates), or AreaTooLarge. ``choice`` is an
        ``osm_type/osm_id`` string picked by the user from a previous AmbiguousArea.
        """
        items = [i for i in self._fetch(query) if isinstance(i, dict)]
        if not items:
            raise AreaNotFound(f"area not found: {query!r}")
        areas = [_to_area(i) for i in items]
        importance = [float(i.get("importance") or 0) for i in items]

        if choice:
            picked = next((a for a in areas if a.choice_id == choice), None)
            if picked is None:
                raise AreaNotFound(f"chosen area {choice!r} is not among the matches")
        elif len(areas) == 1 or importance[0] >= 1.5 * max(importance[1], 1e-9):
            picked = areas[0]
        else:
            raise AmbiguousArea(areas)

        if picked.area_km2 > self.settings.max_area_km2:
            raise AreaTooLarge(picked, self.settings.max_area_km2)
        return picked

    def cache_age(self, query: str) -> timedelta | None:
        cached = self.repo.get_geocode(query)
        return None if cached is None else self.repo.now() - cached[1]
