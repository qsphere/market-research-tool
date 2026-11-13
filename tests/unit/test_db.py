import json

import pytest

from leadgen.db import DuplicateRecordError, NotFoundError, Repository, migrate, open_db

TABLES = {
    "searches", "geocode_cache", "raw_records", "leads", "lead_sources", "search_leads",
    "duplicate_pairs",
}  # fmt: skip


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


@pytest.fixture
def repo(tmp_path):
    return Repository(open_db(tmp_path / "t.db"))


def lead(repo, name="Shop", **kw):
    return repo.insert_lead(name=name, kind="business", category="gift_shop", **kw)


def test_fresh_db_migrates(tmp_path):
    conn = open_db(tmp_path / "a.db")
    assert TABLES <= table_names(conn)


def test_migrate_twice_is_noop(tmp_path):
    conn = open_db(tmp_path / "a.db")
    v1 = migrate(conn)
    v2 = migrate(conn)
    assert v1 == v2 >= 1


def test_data_persists_after_reopen(tmp_path):
    path = tmp_path / "p.db"
    r1 = Repository(open_db(path))
    sid = r1.create_search("gift_shop", "Portland")
    lead(r1, "Persisted")
    r1.conn.close()
    r2 = Repository(open_db(path))
    assert r2.get_search(sid)["area"] == "Portland"
    assert r2.active_leads()[0]["name"] == "Persisted"


def test_raw_payload_stored_unmodified(repo):
    sid = repo.create_search("gift_shop", "Portland")
    payload = '{"b": 1,   "a": [1, 2],\n "z":"é"}'  # odd spacing/order must survive
    rid = repo.save_raw_record(sid, "osm", "node/1", payload, {"q": "x"})
    row = repo.get_raw_record(rid)
    assert row["payload"] == payload
    assert json.loads(row["request"]) == {"q": "x"}


def test_duplicate_raw_record_rejected(repo):
    sid = repo.create_search("gift_shop", "Portland")
    repo.save_raw_record(sid, "osm", "node/1", "{}", {})
    with pytest.raises(DuplicateRecordError):
        repo.save_raw_record(sid, "osm", "node/1", "{}", {})
    # same record in a different search is fine
    sid2 = repo.create_search("gift_shop", "Portland")
    repo.save_raw_record(sid2, "osm", "node/1", "{}", {})


def test_missing_rows_raise(repo):
    for call in (repo.get_search, repo.get_lead, repo.get_raw_record, repo.get_pair):
        with pytest.raises(NotFoundError):
            call(999)
    with pytest.raises(NotFoundError):
        repo.update_lead(999, name="x")


def test_unknown_lead_field_rejected(repo):
    with pytest.raises(ValueError):
        repo.insert_lead(name="x", kind="business", category="c", bogus=1)


def test_link_sources_and_find_by_source_record(repo):
    sid = repo.create_search("gift_shop", "Portland")
    rid = repo.save_raw_record(sid, "osm", "node/1", "{}", {})
    lid = lead(repo)
    repo.link_source(lid, rid)
    repo.link_source(lid, rid)  # idempotent
    assert [r["id"] for r in repo.lead_sources(lid)] == [rid]
    assert repo.find_lead_by_source_record("osm", "node/1") == lid
    assert repo.find_lead_by_source_record("osm", "node/404") is None


def test_geocode_cache_roundtrip_and_key_normalisation(repo):
    assert repo.get_geocode("Portland, Oregon") is None
    repo.put_geocode("Portland, Oregon", [{"name": "Portland"}])
    value, fetched = repo.get_geocode("portland oregon")
    assert value == [{"name": "Portland"}]
    assert fetched.tzinfo is not None


def test_pairs_ordering_status_and_no_reinsert(repo):
    a, b = lead(repo, "A"), lead(repo, "B")
    assert repo.add_pair(b, a, 0.9) is True
    assert repo.add_pair(a, b, 0.9) is False
    pair = repo.pending_pairs()[0]
    assert (pair["lead_a"], pair["lead_b"]) == (a, b)
    repo.set_pair_status(pair["id"], "rejected")
    assert repo.pair_status(a, b) == "rejected"
    assert repo.pending_pairs() == []
    assert repo.add_pair(a, b, 0.9) is False  # rejected pairs are never re-suggested
    with pytest.raises(ValueError):
        repo.set_pair_status(pair["id"], "bogus")
    with pytest.raises(ValueError):
        repo.add_pair(a, a, 1.0)


def test_merge_resolution_and_search_leads(repo):
    sid = repo.create_search("gift_shop", "Portland")
    a, b = lead(repo, "A"), lead(repo, "B")
    repo.link_search_lead(sid, a)
    repo.link_search_lead(sid, b)
    repo.mark_merged(b, a)
    assert repo.resolve_lead(b) == a
    assert repo.search_lead_ids(sid) == [a]
    assert [r["id"] for r in repo.active_leads()] == [a]


def test_search_lifecycle(repo):
    sid = repo.create_search("gift_shop", "Portland, OR")
    assert repo.get_search(sid)["status"] == "running"
    repo.finish_search(sid, "done")
    assert repo.latest_finished_search("gift_shop", "portland or")["id"] == sid
    assert repo.latest_finished_search("farmers_market", "portland or") is None
