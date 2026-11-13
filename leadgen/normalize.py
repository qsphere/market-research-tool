"""Normalization of phones, websites, and addresses. Originals are always kept by callers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers

from leadgen.models import LeadCandidate

_PHONE_SPLIT = re.compile(r"\s*(?:;|/|,|\bor\b|\band\b)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class PhoneResult:
    primary: str  # E.164 or ""
    extras: tuple[str, ...]  # other valid numbers, E.164
    original: str


def normalize_phones(text: str | None, region: str = "US") -> PhoneResult:
    original = (text or "").strip()
    if not original:
        return PhoneResult("", (), "")
    valid: list[str] = []
    for part in _PHONE_SPLIT.split(original):
        part = part.strip()
        if not part:
            continue
        try:
            num = phonenumbers.parse(part, region)
        except phonenumbers.NumberParseException:
            continue
        if not phonenumbers.is_valid_number(num):
            continue
        e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        if e164 not in valid:
            valid.append(e164)
    if not valid:
        return PhoneResult("", (), original)
    return PhoneResult(valid[0], tuple(valid[1:]), original)


_TRACKING = ("utm_", "fbclid", "gclid", "msclkid", "mc_eid", "mc_cid", "igshid", "ref_src")
_BAD_SCHEMES = re.compile(r"^(javascript|data|vbscript|file|mailto|tel|about|blob):", re.I)
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def canonicalize_website(text: str | None) -> str:
    """Return a canonical http(s) URL, or "" when the value is not a valid web address."""
    raw = (text or "").strip()
    if not raw or any(c.isspace() for c in raw):
        return ""
    if _BAD_SCHEMES.match(raw):
        return ""
    if "://" not in raw:
        raw = "https://" + raw.lstrip("/")
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not _HOST_RE.match(host):
        return ""
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = parts.path.rstrip("/")
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if not k.lower().startswith(_TRACKING)]
    )  # fmt: skip
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu"}


def registrable_domain(url: str) -> str:
    """Approximate registrable domain (no public-suffix list; good enough for matching)."""
    host = (urlsplit(url).hostname or "").lower()
    labels = host.split(".")
    if len(labels) < 2:
        return host
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def assemble_address(parts: dict[str, str] | None) -> str:
    """Build one readable line from address parts, skipping anything missing."""
    p = {k.removeprefix("addr:"): (v or "").strip() for k, v in (parts or {}).items()}
    street = " ".join(x for x in (p.get("housenumber", ""), p.get("street", "")) if x)
    if p.get("unit"):
        street = f"{street} #{p['unit']}".strip()
    region = " ".join(x for x in (p.get("state", ""), p.get("postcode", "")) if x)
    return ", ".join(x for x in (street, p.get("city", ""), region) if x)


def valid_coordinates(lat: float | None, lon: float | None) -> tuple[float | None, float | None]:
    if lat is None or lon is None:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return float(lat), float(lon)


def normalize_candidate(candidate: LeadCandidate, region: str = "US") -> dict[str, object]:
    """Map a candidate to ``leads`` table fields (normalized values plus originals)."""
    phone = normalize_phones(candidate.phone, region)
    website = canonicalize_website(candidate.website)
    lat, lon = valid_coordinates(candidate.lat, candidate.lon)
    return {
        "name": candidate.name.strip(),
        "kind": candidate.kind,
        "category": candidate.category,
        "address": assemble_address(candidate.address_parts),
        "phone": phone.primary,
        "phone_original": phone.original,
        "extra_phones": list(phone.extras),
        "website": website,
        "website_original": (candidate.website or "").strip(),
        "lat": lat,
        "lon": lon,
    }
