"""Application settings: defaults, environment overrides, validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from pathlib import Path


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("leadgen.db")
    host: str = "127.0.0.1"
    port: int = 8000
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    contact: str = ""  # optional contact string appended to the User-Agent
    cache_hours: float = 24.0
    max_area_km2: float = 5000.0
    max_attempts: int = 3
    request_timeout: float = 30.0
    nominatim_min_interval: float = 1.0
    confident_name_threshold: float = 0.6
    possible_name_threshold: float = 0.85
    possible_distance_m: float = 150.0
    default_region: str = "US"
    enabled_sources: tuple[str, ...] = ("osm",)
    categories_path: Path | None = None

    def __post_init__(self) -> None:
        if not (1 <= self.port <= 65535):
            raise ConfigError(f"port must be 1-65535, got {self.port}")
        if not self.host:
            raise ConfigError("host must not be empty")
        for name in ("cache_hours", "max_area_km2", "request_timeout"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be positive")
        if self.nominatim_min_interval < 1.0:
            raise ConfigError("nominatim_min_interval must be at least 1.0 second (usage policy)")
        if self.max_attempts < 1:
            raise ConfigError("max_attempts must be at least 1")
        for name in ("confident_name_threshold", "possible_name_threshold"):
            if not (0.0 <= getattr(self, name) <= 1.0):
                raise ConfigError(f"{name} must be between 0 and 1")
        if self.possible_distance_m < 0:
            raise ConfigError("possible_distance_m must not be negative")
        if len(self.default_region) != 2:
            raise ConfigError("default_region must be a 2-letter country code")

    @property
    def user_agent(self) -> str:
        base = "market-research-tool/0.1"
        return f"{base} ({self.contact})" if self.contact else base

    def with_overrides(self, **overrides: object) -> Settings:
        return replace(self, **overrides)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        """Build settings from ``LEADGEN_*`` environment variables."""
        env = dict(os.environ if env is None else env)
        kwargs: dict[str, object] = {}
        for f in fields(cls):
            raw = env.get(f"LEADGEN_{f.name.upper()}")
            if raw is None:
                continue
            kwargs[f.name] = _coerce(f.name, raw)
        return cls(**kwargs)  # type: ignore[arg-type]


def _coerce(name: str, raw: str) -> object:
    try:
        if name in ("db_path", "categories_path"):
            return Path(raw)
        if name in ("port", "max_attempts"):
            return int(raw)
        if name == "enabled_sources":
            return tuple(s.strip() for s in raw.split(",") if s.strip())
        if name in ("host", "nominatim_url", "overpass_url", "contact", "default_region"):
            return raw
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"invalid value for {name}: {raw!r}") from exc
