"""CSV export with spreadsheet-formula neutralisation and OSM attribution."""

from __future__ import annotations

import csv
import io
from typing import Any

ATTRIBUTION = "© OpenStreetMap contributors"
HEADERS = ["name", "address", "phone", "website", "source", "category", "attribution"]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def neutralize(value: Any) -> str:
    """Prefix risky cells with an apostrophe so spreadsheets treat them as text."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def leads_to_csv(leads: list[dict[str, Any]]) -> bytes:
    """UTF-8 with BOM so Excel reads accents; the csv module handles quoting/newlines."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for lead in leads:
        writer.writerow(
            [
                neutralize(lead["name"]),
                neutralize(lead["address"]),
                neutralize(lead["phone"]),
                neutralize(lead["website"]),
                neutralize(", ".join(lead["source_names"])),
                neutralize(lead["category"]),
                ATTRIBUTION,
            ]
        )
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
