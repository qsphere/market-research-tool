"""Deterministic, explainable duplicate detection and merging."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from leadgen.config import Settings
from leadgen.db import Repository
from leadgen.normalize import registrable_domain

CONFIDENT = "confident"
POSSIBLE = "possible"
NONE = "none"


@dataclass(frozen=True)
class Match:
    level: str
    score: float  # name similarity, 0..1
    reason: str


def _norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", (name or "").lower()).split())


def name_similarity(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(_norm_name(a), _norm_name(b)) / 100.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _phones(lead: Mapping[str, Any]) -> set[str]:
    extra = lead.get("extra_phones") or []
    if isinstance(extra, str):
        extra = json.loads(extra)
    return {p for p in [lead.get("phone"), *extra] if p}


def match_leads(a: Mapping[str, Any], b: Mapping[str, Any], cfg: Settings) -> Match:
    a, b = dict(a), dict(b)
    sim = name_similarity(a["name"], b["name"])
    pa, pb = _phones(a), _phones(b)
    same_phone = bool(pa & pb)
    conflicting_phone = bool(pa and pb and not same_phone)
    da = registrable_domain(a["website"]) if a.get("website") else ""
    db = registrable_domain(b["website"]) if b.get("website") else ""
    same_domain = bool(da) and da == db
    conflicting_site = bool(da and db and da != db)

    if sim >= cfg.confident_name_threshold:
        if same_phone:
            return Match(CONFIDENT, sim, "same phone")
        if same_domain and not conflicting_phone:
            return Match(CONFIDENT, sim, "same website domain")

    if sim >= cfg.possible_name_threshold and not (conflicting_phone or conflicting_site):
        coords = (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))
        if None not in coords and distance_m(*coords) <= cfg.possible_distance_m:
            return Match(POSSIBLE, sim, "similar name nearby")
    return Match(NONE, sim, "")


_FIELDS = ("address", "phone", "phone_original", "website", "website_original")


def merge_leads(repo: Repository, keep_id: int, drop_id: int) -> int:
    """Merge ``drop_id`` into ``keep_id``: union sources, keep the most complete values."""
    keep, drop = repo.get_lead(keep_id), repo.get_lead(drop_id)
    updates: dict[str, Any] = {}
    for f in _FIELDS:
        if not keep[f] and drop[f]:
            updates[f] = drop[f]
    if len(drop["address"]) > len(keep["address"]):
        updates["address"] = drop["address"]
    if keep["lat"] is None and drop["lat"] is not None:
        updates["lat"], updates["lon"] = drop["lat"], drop["lon"]
    phones = [p for p in [keep["phone"], *json.loads(keep["extra_phones"])] if p]
    for p in [drop["phone"], *json.loads(drop["extra_phones"])]:
        if p and p not in phones:
            phones.append(p)
    if not keep["phone"] and phones:
        updates["phone"] = phones[0]
    primary = updates.get("phone", keep["phone"])
    updates["extra_phones"] = [p for p in phones if p != primary]
    repo.update_lead(keep_id, **updates)
    repo.move_sources(drop_id, keep_id)
    repo.mark_merged(drop_id, keep_id)
    return keep_id


def dedupe_lead(repo: Repository, lead_id: int, cfg: Settings) -> int:
    """Compare a new lead against stored ones. Auto-merge confident matches, queue possible
    ones for review, skip pairs the user already rejected. Returns the surviving lead id."""
    current = lead_id
    for other in repo.active_leads():
        if other["id"] == current:
            continue
        if repo.pair_status(current, other["id"]) in ("rejected", "merged"):
            continue
        me = repo.get_lead(current)
        if me["merged_into"] is not None:  # pragma: no cover - defensive
            break
        result = match_leads(me, other, cfg)
        if result.level == CONFIDENT:
            keep = min(current, other["id"])
            drop = max(current, other["id"])
            current = merge_leads(repo, keep, drop)
        elif result.level == POSSIBLE:
            repo.add_pair(current, other["id"], result.score)
    return current


def confirm_pair(repo: Repository, pair_id: int) -> int:
    pair = repo.get_pair(pair_id)
    keep = repo.resolve_lead(pair["lead_a"])
    drop = repo.resolve_lead(pair["lead_b"])
    if keep != drop:
        keep, drop = min(keep, drop), max(keep, drop)
        merge_leads(repo, keep, drop)
    repo.set_pair_status(pair_id, "merged")
    return keep


def reject_pair(repo: Repository, pair_id: int) -> None:
    repo.get_pair(pair_id)
    repo.set_pair_status(pair_id, "rejected")
