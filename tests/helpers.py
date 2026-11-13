"""Shared test helpers: fixtures, a mock HTTP transport, a fake clock, and a fake source."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from leadgen.config import Settings
from leadgen.http import HttpClient
from leadgen.models import Area, Category, LeadCandidate, RawRecord

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeClock:
    """Deterministic clock whose sleep() advances time instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Router:
    """httpx mock transport routing by URL substring; records every request."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, Callable[[httpx.Request], httpx.Response]]] = []
        self.requests: list[httpx.Request] = []

    def add(self, fragment: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.routes.append((fragment, handler))

    def respond(self, fragment: str, *responses: httpx.Response) -> None:
        queue = list(responses)

        def handler(_: httpx.Request) -> httpx.Response:
            return queue.pop(0) if len(queue) > 1 else queue[0]

        self.add(fragment, handler)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for fragment, handler in self.routes:
            if fragment in str(request.url):
                return handler(request)
        return httpx.Response(404, text="no route")

    def count(self, fragment: str) -> int:
        return sum(fragment in str(r.url) for r in self.requests)


def make_http(router: Router, clock: FakeClock | None = None, **settings) -> HttpClient:
    clock = clock or FakeClock()
    return HttpClient(
        Settings(**settings),
        transport=httpx.MockTransport(router),
        sleep=clock.sleep,
        clock=clock.time,
    )


def json_response(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"content-type": "application/json"})


PORTLAND = Area(
    name="Portland, Oregon, United States", lat=45.52, lon=-122.67,
    bbox=(45.43, -122.83, 45.65, -122.47), osm_type="relation", osm_id=186579,
    country_code="US", area_km2=400.0,
)  # fmt: skip

GIFT = Category("gift_shop", "Gift shop", "business", ({"shop": "gift"},))


class FakeSource:
    """In-memory source for service/web tests."""

    def __init__(self, name="fake", candidates=None, error: Exception | None = None):
        self.name = name
        self.error = error
        self.calls = 0
        self.candidates = candidates if candidates is not None else []

    def search(self, category: Category, area: Area) -> list[RawRecord]:
        self.calls += 1
        if self.error:
            raise self.error
        return [
            RawRecord(self.name, c.source_record_id, json.dumps({"name": c.name}), {"q": "fake"},
                      f"https://example.test/{c.source_record_id}")
            for c in self.candidates
        ]  # fmt: skip

    def to_candidate(self, raw: RawRecord, category: Category) -> LeadCandidate | None:
        return next(
            (c for c in self.candidates if c.source_record_id == raw.source_record_id), None
        )
