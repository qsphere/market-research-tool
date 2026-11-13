import pytest

from leadgen.config import Settings
from leadgen.db import Repository, open_db
from leadgen.dedupe import (
    CONFIDENT,
    NONE,
    POSSIBLE,
    confirm_pair,
    dedupe_lead,
    match_leads,
    merge_leads,
    reject_pair,
)

CFG = Settings()
PDX = (45.5231, -122.6765)


def L(name, phone="", website="", lat=PDX[0], lon=PDX[1], **kw):
    return {"name": name, "phone": phone, "website": website, "lat": lat, "lon": lon,
            "extra_phones": [], **kw}  # fmt: skip


def test_same_phone_is_confident():
    m = match_leads(
        L("Joe's Gifts", "+15035550142"), L("Joes Gifts", "+15035550142", lat=1, lon=1), CFG
    )
    assert m.level == CONFIDENT


def test_same_domain_is_confident():
    a = L("Gift Barn", website="https://giftbarn.com")
    b = L("The Gift Barn", website="https://www.giftbarn.com/about", lat=40, lon=-100)
    assert match_leads(a, b, CFG).level == CONFIDENT


def test_same_phone_but_unrelated_name_is_not_confident():
    assert (
        match_leads(L("Zebra Books", "+15035550142"), L("Quick Lube", "+15035550142"), CFG).level
        == NONE
    )


def test_similar_name_nearby_is_possible():
    a, b = L("Treasure Trove Consignment"), L("Treasure Trove Consignments", lat=PDX[0] + 0.0004)
    assert match_leads(a, b, CFG).level == POSSIBLE


def test_similar_name_far_apart_is_none():
    a, b = L("Treasure Trove"), L("Treasure Trove", lat=PDX[0] + 1.0)
    assert match_leads(a, b, CFG).level == NONE


def test_conflicting_phone_blocks_possible_and_domain_merge():
    a = L("Treasure Trove", "+15035550142")
    b = L("Treasure Trove", "+15035550199")
    assert match_leads(a, b, CFG).level == NONE
    c = L("Gift Barn", "+15035550142", website="https://giftbarn.com")
    d = L("Gift Barn", "+15035550199", website="https://giftbarn.com", lat=40, lon=-100)
    assert match_leads(c, d, CFG).level == NONE  # chain: same domain, different branches


def test_conflicting_website_blocks_possible():
    a = L("Treasure Trove", website="https://a.com")
    b = L("Treasure Trove", website="https://b.com")
    assert match_leads(a, b, CFG).level == NONE


def test_missing_coordinates_never_possible():
    assert (
        match_leads(L("Treasure Trove", lat=None, lon=None), L("Treasure Trove"), CFG).level == NONE
    )


def test_thresholds_are_configurable():
    strict = Settings(possible_name_threshold=1.0)
    a, b = L("Treasure Trove Consignment"), L("Treasure Trove Consignments")
    assert match_leads(a, b, strict).level == NONE


# --- persistence-backed behaviour -----------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    return Repository(open_db(tmp_path / "d.db"))


def add(repo, name, **kw):
    kw.setdefault("lat", PDX[0])
    kw.setdefault("lon", PDX[1])
    return repo.insert_lead(name=name, kind="business", category="gift_shop", **kw)


def raw(repo, sid, rid):
    return repo.save_raw_record(sid, "osm", rid, "{}", {})


def test_merge_preserves_all_sources_and_fills_fields(repo):
    sid = repo.create_search("gift_shop", "Portland")
    a = add(repo, "Shop", website="https://s.com")
    b = add(repo, "Shop", phone="+15035550142", address="1 Main St, Portland")
    repo.link_source(a, raw(repo, sid, "node/1"))
    repo.link_source(b, raw(repo, sid, "node/2"))
    merge_leads(repo, a, b)
    got = repo.get_lead(a)
    assert got["phone"] == "+15035550142" and got["address"] == "1 Main St, Portland"
    assert got["website"] == "https://s.com"
    assert len(repo.lead_sources(a)) == 2
    assert repo.resolve_lead(b) == a


def test_confident_match_auto_merges_on_ingest(repo):
    a = add(repo, "Joe's Gifts", phone="+15035550142")
    b = add(repo, "Joes Gifts", phone="+15035550142")
    assert dedupe_lead(repo, b, CFG) == a
    assert len(repo.active_leads()) == 1


def test_possible_goes_to_review_and_reject_is_permanent(repo):
    a = add(repo, "Treasure Trove Consignment")
    b = add(repo, "Treasure Trove Consignments")
    assert dedupe_lead(repo, b, CFG) == b
    assert len(repo.active_leads()) == 2
    pair = repo.pending_pairs()[0]
    reject_pair(repo, pair["id"])
    assert repo.pending_pairs() == []
    dedupe_lead(repo, b, CFG)  # re-run
    assert repo.pending_pairs() == []
    assert repo.pair_status(a, b) == "rejected"


def test_confirm_pair_merges_and_clears_queue(repo):
    sid = repo.create_search("gift_shop", "Portland")
    a = add(repo, "Treasure Trove Consignment")
    b = add(repo, "Treasure Trove Consignments")
    repo.link_source(a, raw(repo, sid, "node/1"))
    repo.link_source(b, raw(repo, sid, "node/2"))
    dedupe_lead(repo, b, CFG)
    confirm_pair(repo, repo.pending_pairs()[0]["id"])
    assert [r["id"] for r in repo.active_leads()] == [a]
    assert len(repo.lead_sources(a)) == 2
    assert repo.pending_pairs() == []


def test_rerun_creates_no_duplicates(repo):
    a = add(repo, "Joe's Gifts", phone="+15035550142")
    again = add(repo, "Joe's Gifts", phone="+15035550142")
    dedupe_lead(repo, again, CFG)
    dedupe_lead(repo, again, CFG)
    assert [r["id"] for r in repo.active_leads()] == [a]


def test_unknown_pair_raises(repo):
    from leadgen.db import NotFoundError

    with pytest.raises(NotFoundError):
        confirm_pair(repo, 123)
    with pytest.raises(NotFoundError):
        reject_pair(repo, 123)
