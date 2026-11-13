from datetime import timedelta

import pytest

from leadgen.categories import UnknownCategory
from leadgen.config import Settings
from leadgen.db import Repository, open_db
from leadgen.geocode import AmbiguousArea, AreaNotFound, AreaTooLarge
from leadgen.models import BadResponse, LeadCandidate, RateLimited, SourceUnavailable
from leadgen.service import InvalidSearch, SearchService
from tests.helpers import PORTLAND, FakeSource


class StubGeocoder:
    def __init__(self, result=PORTLAND, error=None):
        self.result, self.error, self.calls = result, error, 0

    def resolve(self, query, choice=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def cand(rid, name="Joe's Gifts", **kw):
    return LeadCandidate("fake", rid, name, "business", "gift_shop", **kw)


class Clock:
    def __init__(self):
        from datetime import UTC, datetime

        self.t = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def repo(tmp_path, clock):
    return Repository(open_db(tmp_path / "s.db"), clock=clock)


def make(repo, sources, geocoder=None, **settings):
    return SearchService(repo, sources, geocoder or StubGeocoder(), Settings(**settings))


def run(svc, category="gift shop", area="Portland, Oregon", **kw):
    sub = svc.submit(category, area, **kw)
    return sub, svc.execute(sub.search_id)


def test_success_stores_normalized_results(repo):
    src = FakeSource(candidates=[cand("1", phone="(503) 555-0142", website="example.com/")])
    svc = make(repo, [src])
    sub, status = run(svc)
    assert status == "done"
    [lead] = svc.results(sub.search_id)
    assert lead["phone"] == "+15035550142" and lead["website"] == "https://example.com"
    assert lead["kind"] == "business" and lead["source_names"] == ["fake"]
    assert lead["sources"][0]["source_record_id"] == "1"


@pytest.mark.parametrize(
    ("category", "area", "fields"),
    [
        ("", "Portland", ("category",)),
        ("gift shop", "  ", ("area",)),
        ("", "", ("category", "area")),
    ],
)
def test_missing_input_rejected_without_calls(repo, category, area, fields):
    src, geo = FakeSource(), StubGeocoder()
    svc = make(repo, [src], geo)
    with pytest.raises(InvalidSearch) as exc:
        svc.submit(category, area)
    assert exc.value.fields == fields
    assert src.calls == 0 and geo.calls == 0 and repo.list_searches() == []


def test_unsupported_category_makes_no_requests(repo):
    src, geo = FakeSource(), StubGeocoder()
    svc = make(repo, [src], geo)
    with pytest.raises(UnknownCategory):
        svc.submit("tattoo parlor", "Portland")
    assert src.calls == 0 and geo.calls == 0 and repo.list_searches() == []


def test_ambiguous_area_asks_for_choice(repo):
    geo = StubGeocoder(
        error=AmbiguousArea([PORTLAND, PORTLAND.__class__(**{**PORTLAND.__dict__, "osm_id": 2})])
    )
    src = FakeSource()
    svc = make(repo, [src], geo)
    sub, status = run(svc)
    row = repo.get_search(sub.search_id)
    assert status == "needs_choice" and src.calls == 0
    assert "relation/186579" in row["candidates"]


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (AreaNotFound("x"), "not found"),
        (AreaTooLarge(PORTLAND, 10), "too large"),
        (SourceUnavailable("down", "nominatim"), "Could not resolve"),
    ],
)
def test_area_failures(repo, error, text):
    src = FakeSource()
    svc = make(repo, [src], StubGeocoder(error=error))
    sub, status = run(svc)
    assert status == "failed" and text in repo.get_search(sub.search_id)["message"]
    assert src.calls == 0 and svc.results(sub.search_id) == []


def test_no_matches_is_done_not_error(repo):
    svc = make(repo, [FakeSource(candidates=[])])
    sub, status = run(svc)
    assert status == "done"
    assert repo.get_search(sub.search_id)["message"] == "No leads found."


def test_lead_missing_contact_fields_still_returned(repo):
    svc = make(repo, [FakeSource(candidates=[cand("1")])])
    sub, _ = run(svc)
    [lead] = svc.results(sub.search_id)
    assert lead["phone"] == "" and lead["website"] == ""


def test_one_source_fails_is_partial(repo):
    good = FakeSource("good", [cand("1")])
    bad = FakeSource("bad", error=SourceUnavailable("boom", "bad"))
    svc = make(repo, [good, bad])
    sub, status = run(svc)
    row = repo.get_search(sub.search_id)
    assert status == "partial" and "bad failed" in row["message"] and '"bad"' in row["failures"]
    assert len(svc.results(sub.search_id)) == 1


def test_all_sources_fail(repo):
    svc = make(
        repo,
        [
            FakeSource("a", error=SourceUnavailable("x", "a")),
            FakeSource("b", error=BadResponse("y", "b")),
        ],
    )
    sub, status = run(svc)
    msg = repo.get_search(sub.search_id)["message"]
    assert status == "failed" and "a, b" in msg and svc.results(sub.search_id) == []


def test_rate_limited_reported(repo):
    svc = make(repo, [FakeSource("osm", error=RateLimited("slow down", "osm"))])
    sub, status = run(svc)
    assert status == "failed" and "rate-limited" in repo.get_search(sub.search_id)["message"]


def test_multiple_sources_combined_and_deduped(repo):
    a = FakeSource(
        "a", [LeadCandidate("a", "1", "Joe's Gifts", "business", "gift_shop", phone="503-555-0142")]
    )
    b = FakeSource(
        "b",
        [LeadCandidate("b", "9", "Joes Gifts", "business", "gift_shop", phone="(503) 555-0142")],
    )
    svc = make(repo, [a, b])
    sub, _ = run(svc)
    [lead] = svc.results(sub.search_id)
    assert sorted(lead["source_names"]) == ["a", "b"]


def test_unexpected_error_does_not_leave_search_running(repo):
    class Boom(FakeSource):
        def search(self, category, area):
            raise RuntimeError("bug")

    svc = make(repo, [Boom()])
    sub, status = run(svc)
    assert status == "failed"
    assert repo.get_search(sub.search_id)["status"] == "failed"


# --- 6.2 caching ----------------------------------------------------------------------------


def test_identical_search_within_window_makes_no_source_calls(repo, clock):
    src = FakeSource(candidates=[cand("1")])
    geo = StubGeocoder()
    svc = make(repo, [src], geo)
    first, _ = run(svc)
    clock.t += timedelta(hours=1)
    second = svc.submit("Gift Shop", "portland oregon")
    assert second.cached and second.search_id == first.search_id
    assert src.calls == 1 and geo.calls == 1


def test_search_after_cache_window_requeries(repo, clock):
    src = FakeSource(candidates=[cand("1")])
    svc = make(repo, [src], cache_hours=24)
    run(svc)
    clock.t += timedelta(hours=25)
    sub, _ = run(svc)
    assert not sub.cached and src.calls == 2


def test_forced_refresh_requeries_and_creates_no_duplicates(repo):
    src = FakeSource(candidates=[cand("1")])
    svc = make(repo, [src])
    first, _ = run(svc)
    second, _ = run(svc, refresh=True)
    assert not second.cached and second.search_id != first.search_id and src.calls == 2
    assert len(repo.active_leads()) == 1
    assert svc.results(second.search_id)[0]["id"] == svc.results(first.search_id)[0]["id"]


def test_failed_search_is_not_served_from_cache(repo):
    src = FakeSource(error=SourceUnavailable("x", "fake"))
    svc = make(repo, [src])
    run(svc)
    run(svc)
    assert src.calls == 2
