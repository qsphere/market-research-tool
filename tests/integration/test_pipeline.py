"""search -> raw storage -> normalize -> dedupe -> read-back with real SQLite, geocoder and OSM
adapter; only the HTTP transport is mocked (recorded fixtures)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from leadgen.config import Settings
from leadgen.db import Repository, open_db
from leadgen.geocode import Geocoder
from leadgen.service import SearchService
from leadgen.sources.osm import OsmSource
from tests.helpers import FakeClock, FakeSource, Router, fixture_text, json_response, make_http


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.t


def build(tmp_path, router, clock=None, extra_sources=(), **settings):
    s = Settings(db_path=tmp_path / "p.db", **settings)
    fake_clock = FakeClock()
    http = make_http(router, fake_clock, **settings)
    repo = Repository(open_db(s.db_path), clock=clock or Clock())
    svc = SearchService(repo, [OsmSource(s, http), *extra_sources], Geocoder(http, repo, s), s)
    return svc, repo, fake_clock


@pytest.fixture
def router():
    r = Router()
    r.respond("nominatim", json_response(fixture_text("nominatim_portland.json")))
    r.respond("overpass", json_response(fixture_text("overpass_gift.json")))
    return r


def run(svc, **kw):
    sub = svc.submit("gift shop", "Portland, Oregon", **kw)
    return sub, ("done" if sub.cached else svc.execute(sub.search_id))


def test_full_pipeline_success(tmp_path, router):
    svc, repo, _ = build(tmp_path, router)
    sub, status = run(svc)
    assert status == "done"
    leads = {r["name"]: r for r in svc.results(sub.search_id)}
    assert set(leads) == {"Joe's Gifts", "Gift Barn"}  # unnamed place excluded
    joe = leads["Joe's Gifts"]
    assert joe["phone"] == "+15035550142" and joe["phone_original"] == "(503) 555-0142"
    assert joe["website"] == "https://example.com/gifts"
    assert joe["address"] == "12 Main St, Portland, OR 97201"
    assert leads["Gift Barn"]["phone"] == "" and leads["Gift Barn"]["lat"] == 45.53
    # provenance: raw payload preserved and linked
    raw = repo.lead_sources(joe["id"])[0]
    assert '"Joe\'s Gifts"' in raw["payload"] and raw["source_record_id"] == "node/1001"
    assert "[out:json]" in raw["request"]
    assert router.count("nominatim") == 1 and router.count("overpass") == 1


def test_persistence_across_reopening_db(tmp_path, router):
    svc, repo, _ = build(tmp_path, router)
    sub, _ = run(svc)
    repo.conn.close()
    svc2, repo2, _ = build(tmp_path, Router())  # no routes: any network call would 404
    assert {r["name"] for r in svc2.results(sub.search_id)} == {"Joe's Gifts", "Gift Barn"}
    assert repo2.get_search(sub.search_id)["status"] == "done"


def test_rerun_creates_no_duplicates(tmp_path, router):
    svc, repo, _ = build(tmp_path, router)
    run(svc)
    run(svc, refresh=True)
    run(svc, refresh=True)
    assert len(repo.active_leads()) == 2
    assert len(repo.list_searches()) == 3
    assert repo.pending_pairs() == []


def test_cache_hit_then_forced_refresh(tmp_path, router):
    clock = Clock()
    svc, _, _ = build(tmp_path, router, clock=clock)
    run(svc)
    clock.t += timedelta(hours=2)
    sub, _ = run(svc)
    assert sub.cached and router.count("overpass") == 1 and router.count("nominatim") == 1
    sub, _ = run(svc, refresh=True)
    assert not sub.cached and router.count("overpass") == 2
    assert router.count("nominatim") == 1  # geocode result cached separately


def test_partial_failure_keeps_good_results(tmp_path, router):
    from leadgen.models import SourceUnavailable

    bad = FakeSource("other", error=SourceUnavailable("down", "other"))
    svc, repo, _ = build(tmp_path, router, extra_sources=[bad])
    sub, status = run(svc)
    assert status == "partial" and len(svc.results(sub.search_id)) == 2
    assert "other" in repo.get_search(sub.search_id)["message"]


def test_all_sources_fail(tmp_path):
    r = Router()
    r.respond("nominatim", json_response(fixture_text("nominatim_portland.json")))
    r.respond("overpass", httpx.Response(504))
    svc, repo, _ = build(tmp_path, r)
    sub, status = run(svc)
    assert status == "failed" and svc.results(sub.search_id) == []
    assert "osm" in repo.get_search(sub.search_id)["message"]
    assert r.count("overpass") == 3  # bounded retries


def test_rate_limit_backoff_then_success(tmp_path):
    r = Router()
    r.respond("nominatim", json_response(fixture_text("nominatim_portland.json")))
    r.respond(
        "overpass",
        httpx.Response(429),
        httpx.Response(429),
        json_response(fixture_text("overpass_gift.json")),
    )
    svc, _, clock = build(tmp_path, r)
    sub, status = run(svc)
    assert status == "done" and len(svc.results(sub.search_id)) == 2
    assert clock.sleeps == [2.0, 4.0]


def test_persistent_rate_limit_reported(tmp_path):
    r = Router()
    r.respond("nominatim", json_response(fixture_text("nominatim_portland.json")))
    r.respond("overpass", httpx.Response(429))
    svc, repo, _ = build(tmp_path, r)
    sub, status = run(svc)
    assert status == "failed" and "rate-limited" in repo.get_search(sub.search_id)["message"]


def test_malformed_overpass_stores_no_leads(tmp_path):
    r = Router()
    r.respond("nominatim", json_response(fixture_text("nominatim_portland.json")))
    r.respond("overpass", json_response("<html>gateway</html>"))
    svc, repo, _ = build(tmp_path, r)
    sub, status = run(svc)
    assert status == "failed" and repo.active_leads() == []
    assert repo.raw_records_for_search(sub.search_id) == []


def test_unfound_area_never_calls_overpass(tmp_path):
    r = Router()
    r.respond("nominatim", json_response("[]"))
    svc, _, _ = build(tmp_path, r)
    sub, status = run(svc)
    assert status == "failed" and r.count("overpass") == 0


def test_geocode_is_throttled_between_distinct_areas(tmp_path, router):
    svc, _, clock = build(tmp_path, router)
    svc.execute(svc.submit("gift shop", "Portland, Oregon").search_id)
    svc.execute(svc.submit("gift shop", "Salem, Oregon").search_id)
    assert 1.0 in clock.sleeps  # second Nominatim call waited >= 1s
