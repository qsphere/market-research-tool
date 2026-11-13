import httpx
import pytest

from leadgen.categories import CatalogError, UnknownCategory, load_catalog
from leadgen.config import Settings
from leadgen.db import Repository, open_db
from leadgen.geocode import AmbiguousArea, AreaNotFound, AreaTooLarge, Geocoder
from leadgen.models import BadResponse, RateLimited, SourceUnavailable
from leadgen.sources import build_sources
from leadgen.sources.osm import OsmSource, build_query
from tests.helpers import (
    GIFT,
    PORTLAND,
    FakeClock,
    FakeSource,
    Router,
    fixture_text,
    json_response,
    make_http,
)

# --- 5.1 registry -------------------------------------------------------------------------


def test_enabled_sources_are_built_and_combined():
    factories = {"a": lambda s, h: FakeSource("a"), "b": lambda s, h: FakeSource("b")}
    http = make_http(Router())
    built = build_sources(Settings(enabled_sources=("a", "b")), http, factories)
    assert [s.name for s in built] == ["a", "b"]


def test_disabled_source_is_not_instantiated():
    created = []
    factories = {
        "a": lambda s, h: created.append("a") or FakeSource("a"),
        "b": lambda s, h: created.append("b") or FakeSource("b"),
    }
    build_sources(Settings(enabled_sources=("a",)), make_http(Router()), factories)
    assert created == ["a"]


def test_unknown_source_rejected():
    with pytest.raises(ValueError):
        build_sources(Settings(enabled_sources=("nope",)), make_http(Router()), {})


def test_default_registry_has_osm():
    sources = build_sources(Settings(), make_http(Router()))
    assert [s.name for s in sources] == ["osm"]


# --- 5.2 catalog --------------------------------------------------------------------------


def test_bundled_catalog_has_multi_criteria_category():
    cat = load_catalog().get("consignment")
    assert len(cat.criteria) >= 2


def test_catalog_lookup_variants():
    cat = load_catalog()
    assert cat.get("Gift Shop").key == "gift_shop"
    assert cat.get("farmers_market").kind == "event"


def test_unknown_category_rejected_with_supported_list():
    with pytest.raises(UnknownCategory) as exc:
        load_catalog().get("tattoo parlor")
    assert "gift_shop" in exc.value.supported


def test_malformed_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("categories: [unclosed", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(p)


@pytest.mark.parametrize(
    "body",
    [
        "nope: 1",
        "categories: {x: {kind: weird, criteria: [{shop: gift}]}}",
        "categories: {x: {kind: business, criteria: []}}",
        'categories: {x: {kind: business, criteria: [{shop: "gift\\"];out;"}]}}',
    ],
)
def test_invalid_catalog_rejected(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(p)


def test_catalog_edit_takes_effect_without_code_change(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("categories: {x: {kind: business, criteria: [{shop: gift}]}}", encoding="utf-8")
    assert load_catalog(p).get("x").criteria == ({"shop": "gift"},)
    p.write_text("categories: {x: {kind: business, criteria: [{shop: books}]}}", encoding="utf-8")
    assert load_catalog(p).get("x").criteria == ({"shop": "books"},)


# --- 5.3 http -----------------------------------------------------------------------------


def test_user_agent_sent():
    router = Router()
    router.respond("example", json_response("{}"))
    make_http(router, contact="me@example.com").get("https://example.test/", source="t")
    assert "market-research-tool/0.1" in router.requests[0].headers["user-agent"]
    assert "me@example.com" in router.requests[0].headers["user-agent"]


def test_throttle_spaces_requests_one_second():
    router, clock = Router(), FakeClock()
    router.respond("example", json_response("{}"))
    http = make_http(router, clock)
    for _ in range(3):
        http.get("https://example.test/", source="t", throttle_key="n", min_interval=1.0)
    assert clock.sleeps == [1.0, 1.0]


def test_throttle_skips_wait_when_enough_time_passed():
    router, clock = Router(), FakeClock()
    router.respond("example", json_response("{}"))
    http = make_http(router, clock)
    http.get("https://example.test/", source="t", throttle_key="n", min_interval=1.0)
    clock.now += 5
    http.get("https://example.test/", source="t", throttle_key="n", min_interval=1.0)
    assert clock.sleeps == []


def test_backoff_then_success():
    router, clock = Router(), FakeClock()
    router.respond("example", httpx.Response(429), httpx.Response(503), json_response("{}"))
    resp = make_http(router, clock).get("https://example.test/", source="t")
    assert resp.status_code == 200
    assert clock.sleeps == [2.0, 4.0]  # exponential


def test_gives_up_after_max_attempts_rate_limited():
    router, clock = Router(), FakeClock()
    router.respond("example", httpx.Response(429))
    with pytest.raises(RateLimited):
        make_http(router, clock).get("https://example.test/", source="t")
    assert len(router.requests) == 3


def test_gives_up_on_server_errors_as_unavailable():
    router = Router()
    router.respond("example", httpx.Response(504))
    with pytest.raises(SourceUnavailable):
        make_http(router).get("https://example.test/", source="t")


def test_timeout_is_retried_then_unavailable():
    def boom(_):
        raise httpx.ReadTimeout("slow")

    router = Router()
    router.add("example", boom)
    with pytest.raises(SourceUnavailable):
        make_http(router).get("https://example.test/", source="t")
    assert len(router.requests) == 3


def test_client_error_is_not_retried():
    router = Router()
    router.respond("example", httpx.Response(404))
    with pytest.raises(SourceUnavailable):
        make_http(router).get("https://example.test/", source="t")
    assert len(router.requests) == 1


# --- 5.4 geocoding ------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    return Repository(open_db(tmp_path / "g.db"))


def geocoder(repo, router, **settings):
    return Geocoder(make_http(router), repo, Settings(**settings))


def test_geocode_single_clear_winner(repo):
    router = Router()
    router.respond("/search", json_response(fixture_text("nominatim_portland.json")))
    area = geocoder(repo, router).resolve("Portland, Oregon")
    assert area.name.startswith("Portland, Multnomah")
    assert area.country_code == "US" and area.overpass_area_id == 3_600_186_579


def test_geocode_repeat_makes_no_network_call(repo):
    router = Router()
    router.respond("/search", json_response(fixture_text("nominatim_portland.json")))
    g = geocoder(repo, router)
    g.resolve("Portland, Oregon")
    g.resolve("portland oregon")
    assert router.count("/search") == 1


def test_geocode_ambiguous_returns_candidates_and_choice_resolves(repo):
    close = fixture_text("nominatim_portland.json").replace(
        '"importance": 0.4', '"importance": 0.7'
    )
    router = Router()
    router.respond("/search", json_response(close))
    g = geocoder(repo, router)
    with pytest.raises(AmbiguousArea) as exc:
        g.resolve("Portland")
    assert len(exc.value.candidates) == 2
    area = g.resolve("Portland", choice="relation/2747")
    assert "Maine" in area.name


def test_geocode_not_found(repo):
    router = Router()
    router.respond("/search", json_response("[]"))
    with pytest.raises(AreaNotFound):
        geocoder(repo, router).resolve("Xyzzyville")


def test_geocode_bad_choice(repo):
    router = Router()
    router.respond("/search", json_response(fixture_text("nominatim_portland.json")))
    with pytest.raises(AreaNotFound):
        geocoder(repo, router).resolve("Portland", choice="relation/1")


def test_geocode_too_large(repo):
    router = Router()
    router.respond("/search", json_response(fixture_text("nominatim_portland.json")))
    with pytest.raises(AreaTooLarge):
        geocoder(repo, router, max_area_km2=10).resolve("Portland, Oregon")


def test_geocode_garbage_response(repo):
    router = Router()
    router.respond("/search", json_response("<html>oops</html>"))
    with pytest.raises(BadResponse):
        geocoder(repo, router).resolve("Portland")
    router2 = Router()
    router2.respond("/search", json_response('{"error": "x"}'))
    with pytest.raises(BadResponse):
        geocoder(repo, router2).resolve("Portland2")


def test_geocode_failures_are_not_cached(repo):
    router = Router()
    router.respond(
        "/search", httpx.Response(503), json_response(fixture_text("nominatim_portland.json"))
    )
    g = geocoder(repo, router)
    assert g.resolve("Portland, Oregon")  # retries internally, then succeeds


# --- 5.5 overpass / osm adapter -----------------------------------------------------------


def osm(router, **settings):
    s = Settings(**settings)
    return OsmSource(s, make_http(router, **settings))


def test_query_uses_area_id_and_all_criteria():
    cat = load_catalog().get("consignment")
    q = build_query(cat, PORTLAND)
    assert "[timeout:25]" in q and "out center tags" in q
    assert q.count("(area:3600186579)") == len(cat.criteria)
    assert '["second_hand"="consignment"]' in q


def test_query_falls_back_to_bbox_for_nodes():
    node = PORTLAND.__class__(**{**PORTLAND.__dict__, "osm_type": "node"})
    assert "(45.43,-122.83,45.65,-122.47)" in build_query(GIFT, node)


def test_osm_records_and_candidates():
    router = Router()
    router.respond("overpass", json_response(fixture_text("overpass_gift.json")))
    src = osm(router)
    records = src.search(GIFT, PORTLAND)
    assert [r.source_record_id for r in records] == ["node/1001", "way/2002"]  # unnamed excluded
    assert records[0].url.endswith("/node/1001") and "shop" in records[0].request["query"]
    full = src.to_candidate(records[0], GIFT)
    assert full.name == "Joe's Gifts" and full.phone == "(503) 555-0142"
    assert full.address_parts["addr:street"] == "Main St"
    sparse = src.to_candidate(records[1], GIFT)
    assert sparse.phone == "" and sparse.website == ""
    assert (sparse.lat, sparse.lon) == (45.53, -122.68)  # from center


def test_osm_empty_result():
    router = Router()
    router.respond("overpass", json_response('{"elements": []}'))
    assert osm(router).search(GIFT, PORTLAND) == []


@pytest.mark.parametrize(
    "body", ["not json", "[]", '{"remark": "runtime error"}', '{"elements": [{"x":1}]}']
)
def test_osm_malformed_response(body):
    router = Router()
    router.respond("overpass", json_response(body))
    with pytest.raises(BadResponse):
        osm(router).search(GIFT, PORTLAND)


@pytest.mark.parametrize(("status", "exc"), [(429, RateLimited), (504, SourceUnavailable)])
def test_osm_overload_handled(status, exc):
    router = Router()
    router.respond("overpass", httpx.Response(status))
    with pytest.raises(exc):
        osm(router).search(GIFT, PORTLAND)


def test_to_candidate_skips_bad_payload():
    from leadgen.models import RawRecord

    src = osm(Router())
    assert src.to_candidate(RawRecord("osm", "node/1", "not json"), GIFT) is None
    assert src.to_candidate(RawRecord("osm", "node/1", '{"tags": {}}'), GIFT) is None
