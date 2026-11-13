"""Editable category catalog (YAML) mapping user categories to source criteria."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from leadgen.models import Category

DEFAULT_PATH = Path(__file__).with_name("categories.yaml")
_SAFE = re.compile(r"^[A-Za-z0-9_:\-]+$")


class CatalogError(ValueError):
    """The catalog file is malformed."""


class UnknownCategory(LookupError):
    def __init__(self, key: str, supported: list[str]):
        super().__init__(f"unsupported category: {key!r}")
        self.key = key
        self.supported = supported


class Catalog:
    def __init__(self, categories: dict[str, Category]):
        self._by_key = categories

    def all(self) -> list[Category]:
        return list(self._by_key.values())

    def get(self, key: str) -> Category:
        """Look up by key or display name (case-insensitive); reject unknown categories."""
        wanted = " ".join((key or "").lower().replace("_", " ").split())
        for cat in self._by_key.values():
            if wanted in (cat.key.replace("_", " "), cat.name.lower()):
                return cat
        raise UnknownCategory(key, [c.key for c in self._by_key.values()])


def load_catalog(path: Path | str | None = None) -> Catalog:
    """Read the catalog from disk (called per search so edits take effect immediately)."""
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"invalid YAML in {p.name}: {exc}") from exc
    except OSError as exc:
        raise CatalogError(f"cannot read {p}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
        raise CatalogError("catalog must contain a 'categories' mapping")

    out: dict[str, Category] = {}
    for key, body in data["categories"].items():
        if not isinstance(body, dict):
            raise CatalogError(f"category {key!r} must be a mapping")
        kind = body.get("kind")
        if kind not in ("business", "event"):
            raise CatalogError(f"category {key!r}: kind must be 'business' or 'event'")
        raw_criteria = body.get("criteria")
        if not isinstance(raw_criteria, list) or not raw_criteria:
            raise CatalogError(f"category {key!r}: criteria must be a non-empty list")
        criteria = []
        for crit in raw_criteria:
            if not isinstance(crit, dict) or not crit:
                raise CatalogError(f"category {key!r}: each criterion must be a tag mapping")
            clean = {}
            for tag, value in crit.items():
                tag, value = str(tag), str(value)
                if not _SAFE.match(tag) or not _SAFE.match(value):
                    raise CatalogError(f"category {key!r}: unsafe tag {tag}={value}")
                clean[tag] = value
            criteria.append(clean)
        out[str(key)] = Category(
            key=str(key),
            name=str(body.get("name") or key),
            kind=kind,
            criteria=tuple(criteria),
        )
    return Catalog(out)
