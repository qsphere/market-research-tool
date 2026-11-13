"""OpenStreetMap source: Overpass POI queries mapped to lead candidates."""

from __future__ import annotations

import json
from typing import Any

from leadgen.config import Settings
from leadgen.http import HttpClient
from leadgen.models import Area, BadResponse, Category, LeadCandidate, RawRecord

ATTRIBUTION = "© OpenStreetMap contributors"
SOURCE_NAME = "osm"


def build_query(category: Category, area: Area, timeout: int = 25) -> str:
    """Overpass QL for every criterion of a category within the area (bounded and timed out)."""
    area_id = area.overpass_area_id
    if area_id is not None:
        scope = f"(area:{area_id})"
    else:
        south, west, north, east = area.bbox
        scope = f"({south},{west},{north},{east})"
    lines = []
    for criterion in category.criteria:
        filters = "".join(f'["{k}"="{v}"]' for k, v in criterion.items())
        lines.append(f"  nwr{filters}{scope};")
    body = "\n".join(lines)
    return f"[out:json][timeout:{timeout}];\n(\n{body}\n);\nout center tags;"


class OsmSource:
    name = SOURCE_NAME

    def __init__(self, settings: Settings, http: HttpClient):
        self.settings = settings
        self.http = http

    def search(self, category: Category, area: Area) -> list[RawRecord]:
        query = build_query(category, area)
        resp = self.http.post(self.settings.overpass_url, data={"data": query}, source=self.name)
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadResponse("Overpass returned invalid JSON", self.name) from exc
        elements = data.get("elements") if isinstance(data, dict) else None
        if not isinstance(elements, list):
            raise BadResponse("Overpass response has no 'elements' list", self.name)

        request = {"endpoint": self.settings.overpass_url, "query": query, "area": area.name}
        records = []
        for el in elements:
            if not isinstance(el, dict) or "type" not in el or "id" not in el:
                raise BadResponse("Overpass element missing type/id", self.name)
            tags = el.get("tags") or {}
            if not isinstance(tags, dict) or not str(tags.get("name", "")).strip():
                continue  # unnamed places are excluded
            rid = f"{el['type']}/{el['id']}"
            records.append(
                RawRecord(
                    source=self.name,
                    source_record_id=rid,
                    payload=json.dumps(el, ensure_ascii=False, sort_keys=True),
                    request=request,
                    url=f"https://www.openstreetmap.org/{rid}",
                )
            )
        return records

    def to_candidate(self, raw: RawRecord, category: Category) -> LeadCandidate | None:
        try:
            el: dict[str, Any] = json.loads(raw.payload)
        except ValueError:
            return None
        tags: dict[str, str] = el.get("tags") or {}
        name = str(tags.get("name", "")).strip()
        if not name:
            return None
        center = el.get("center") or {}
        lat = el.get("lat", center.get("lat"))
        lon = el.get("lon", center.get("lon"))
        return LeadCandidate(
            source=self.name,
            source_record_id=raw.source_record_id,
            name=name,
            kind=category.kind,
            category=category.key,
            phone=str(tags.get("phone") or tags.get("contact:phone") or ""),
            website=str(
                tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
            ),
            address_parts={k: v for k, v in tags.items() if k.startswith("addr:")},
            lat=lat,
            lon=lon,
        )
