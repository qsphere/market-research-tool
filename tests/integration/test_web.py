"""Web layer driven through HTTP against a temp DB and fake sources."""

import csv
import io
import re

import pytest
from fastapi.testclient import TestClient

from leadgen.config import Settings
from leadgen.models import LeadCandidate, SourceUnavailable
from leadgen.web.app import create_app
from tests.helpers import FakeSource, Router, fixture_text, json_response, make_http


def cand(rid, name, **kw):
    return LeadCandidate("fake", rid, name, "business", "gift_shop", **kw)


def build(tmp_path, candidates=None, error=None, **settings):
    router = Router()
    router.respond("/search", json_response(fixture_text("nominatim_portland.json")))
    src = FakeSource(candidates=candidates if candidates is not None else [], error=error)
    s = Settings(db_path=tmp_path / "w.db", enabled_sources=("fake",), **settings)
    app = create_app(s, sources=[src], http=make_http(router), background=False)
    return TestClient(app), src, router


def token(client):
    html = client.get("/").text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def search(client, category="gift_shop", area="Portland, Oregon", **extra):
    return client.post(
        "/search",
        data={"category": category, "area": area, "csrf_token": token(client), **extra},
        follow_redirects=False,
    )


SHOPS = [
    cand("1", "Zebra Gifts", phone="(503) 555-0142", website="zebra.example.com",
         address_parts={"addr:street": "Main St", "addr:city": "Portland"}),
    cand("2", "Apple Gifts"),
]  # fmt: skip


# --- 7.1 app basics -----------------------------------------------------------------------


def test_index_page_and_attribution(tmp_path):
    client, *_ = build(tmp_path)
    r = client.get("/")
    assert r.status_code == 200 and "Find leads" in r.text
    assert "© OpenStreetMap contributors" in r.text
    assert "Consignment shop" in r.text  # category list from catalog


def test_default_bind_host_is_loopback():
    assert Settings().host == "127.0.0.1"


def test_foreign_host_header_rejected(tmp_path):
    client, *_ = build(tmp_path)
    assert client.get("/", headers={"host": "evil.example.com"}).status_code == 400


# --- 7.2 search flow ----------------------------------------------------------------------


def test_valid_submit_runs_and_shows_results(tmp_path):
    client, src, _ = build(tmp_path, SHOPS)
    r = search(client)
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    assert "Zebra Gifts" in page.text and "+15035550142" in page.text
    assert "https://zebra.example.com" in page.text and src.calls == 1


@pytest.mark.parametrize(
    ("category", "area", "msg"),
    [("gift_shop", "", "Please enter an area"), ("", "Portland", "Please enter a category")],
)
def test_missing_fields_show_error_and_start_nothing(tmp_path, category, area, msg):
    client, src, router = build(tmp_path, SHOPS)
    r = search(client, category, area)
    assert r.status_code == 422 and msg in r.text
    assert src.calls == 0 and router.count("/search") == 0


def test_unsupported_category_rejected(tmp_path):
    client, src, _ = build(tmp_path)
    r = search(client, category="tattoo parlor")
    assert r.status_code == 422 and "not a supported category" in r.text and src.calls == 0


def test_running_search_shows_polling_fragment(tmp_path):
    client, *_ = build(tmp_path)
    sid = client.app.state.repo.create_search("gift_shop", "Portland")
    page = client.get(f"/search/{sid}")
    assert 'hx-trigger="every 1s"' in page.text
    assert client.get(f"/search/{sid}/status").status_code == 200
    client.app.state.repo.finish_search(sid, "done")
    done = client.get(f"/search/{sid}/status")
    assert done.status_code == 204 and done.headers["HX-Redirect"] == f"/search/{sid}"


def test_ambiguous_area_prompts_and_choice_continues(tmp_path):
    ambiguous = fixture_text("nominatim_portland.json").replace(
        '"importance": 0.4', '"importance": 0.7'
    )
    client, src, router = build(tmp_path, SHOPS)
    router.routes.clear()
    router.respond("/search", json_response(ambiguous))
    loc = search(client, area="Portland").headers["location"]
    page = client.get(loc)
    assert "choose one" in page.text and "Maine" in page.text and src.calls == 0
    sid = loc.rsplit("/", 1)[1]
    r = client.post(f"/search/{sid}/choose", data={"choice": "relation/2747", "csrf_token": token(client)},
                    follow_redirects=True)  # fmt: skip
    assert "Zebra Gifts" in r.text and src.calls == 1


def test_source_failure_shows_message_and_retry_works(tmp_path):
    client, src, _ = build(tmp_path, error=SourceUnavailable("down", "fake"))
    loc = search(client).headers["location"]
    page = client.get(loc)
    assert "Source unavailable: fake" in page.text and "Retry" in page.text
    src.error = None
    src.candidates = SHOPS
    r = client.post(f"{loc}/rerun", data={"csrf_token": token(client)}, follow_redirects=True)
    assert "Zebra Gifts" in r.text


def test_unknown_search_404(tmp_path):
    client, *_ = build(tmp_path)
    assert client.get("/search/999").status_code == 404
    assert client.get("/search/999/status").status_code == 404
    assert client.get("/lead/999").status_code == 404


# --- 7.3 results ---------------------------------------------------------------------------


def test_table_columns_blank_cells_sort_and_filter(tmp_path):
    client, *_ = build(tmp_path, SHOPS)
    loc = search(client).headers["location"]
    page = client.get(loc).text
    for col in ("Name", "Location", "Phone", "Website", "Source"):
        assert f">{col}</a>" in page
    asc = client.get(loc, params={"sort": "name", "dir": "asc"}).text
    desc = client.get(loc, params={"sort": "name", "dir": "desc"}).text
    assert asc.index("Apple Gifts") < asc.index("Zebra Gifts")
    assert desc.index("Zebra Gifts") < desc.index("Apple Gifts")
    filtered = client.get(loc, params={"contact": 1}).text
    assert "Zebra Gifts" in filtered and "Apple Gifts" not in filtered


def test_blank_phones_sort_last(tmp_path):
    client, *_ = build(tmp_path, SHOPS)
    loc = search(client).headers["location"]
    for d in ("asc", "desc"):
        page = client.get(loc, params={"sort": "phone", "dir": d}).text
        assert page.index("Zebra Gifts") < page.index("Apple Gifts")


def test_empty_state_message(tmp_path):
    client, *_ = build(tmp_path, [])
    page = client.get(search(client).headers["location"])
    assert "No leads found" in page.text and "broadening" in page.text
    assert "export.csv" not in page.text


def test_filter_with_no_matches_explains(tmp_path):
    client, *_ = build(tmp_path, [cand("2", "Apple Gifts")])
    loc = search(client).headers["location"]
    assert "No leads match this filter" in client.get(loc, params={"contact": 1}).text


def test_lead_detail_shows_originals_and_source_links(tmp_path):
    client, *_ = build(tmp_path, SHOPS)
    loc = search(client).headers["location"]
    lead_href = re.search(r'href="(/lead/\d+)">Zebra', client.get(loc).text).group(1)
    page = client.get(lead_href).text
    assert "(503) 555-0142" in page and "zebra.example.com" in page and "+15035550142" in page
    assert "Collected" in page and "<td>fake</td>" in page and "Main St, Portland" in page


def test_untrusted_text_is_escaped(tmp_path):
    client, *_ = build(tmp_path, [cand("1", "<script>alert(1)</script>")])
    page = client.get(search(client).headers["location"]).text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


# --- 7.4 review queue and history ---------------------------------------------------------------

PAIR = [cand("1", "Treasure Trove Consignment", lat=45.5, lon=-122.6),
        cand("2", "Treasure Trove Consignments", lat=45.5001, lon=-122.6)]  # fmt: skip


def review_ids(client):
    return re.findall(r'action="/review/(\d+)/merge"', client.get("/review").text)


def test_empty_review_queue(tmp_path):
    client, *_ = build(tmp_path)
    assert "Nothing needs review" in client.get("/review").text


def test_review_merge(tmp_path):
    client, *_ = build(tmp_path, PAIR)
    loc = search(client).headers["location"]
    [pid] = review_ids(client)
    page = client.get("/review").text
    assert "Treasure Trove Consignment" in page and "Keep separate" in page
    r = client.post(
        f"/review/{pid}/merge", data={"csrf_token": token(client)}, follow_redirects=True
    )
    assert "Nothing needs review" in r.text
    assert client.get(loc).text.count("<tr>") == 2  # header + one merged lead


def test_review_reject_is_permanent(tmp_path):
    client, *_ = build(tmp_path, PAIR)
    search(client)
    [pid] = review_ids(client)
    client.post(f"/review/{pid}/reject", data={"csrf_token": token(client)})
    assert review_ids(client) == []
    search(client, refresh="1")  # same search again must not re-suggest
    client.post("/search/1/rerun", data={"csrf_token": token(client), "refresh": 1})
    assert review_ids(client) == []


def test_review_htmx_returns_fragment(tmp_path):
    client, *_ = build(tmp_path, PAIR)
    search(client)
    [pid] = review_ids(client)
    r = client.post(
        f"/review/{pid}/merge", data={"csrf_token": token(client)}, headers={"HX-Request": "true"}
    )
    assert r.status_code == 200 and "<html" not in r.text and "merged" in r.text


@pytest.mark.parametrize("bad", [None, "", "wrong-token"])
def test_review_requires_valid_csrf(tmp_path, bad):
    client, *_ = build(tmp_path, PAIR)
    search(client)
    [pid] = review_ids(client)
    data = {} if bad is None else {"csrf_token": bad}
    assert client.post(f"/review/{pid}/merge", data=data).status_code == 403
    assert len(review_ids(client)) == 1  # nothing changed


def test_csrf_cookie_required(tmp_path):
    client, *_ = build(tmp_path, PAIR)
    search(client)
    [pid] = review_ids(client)
    tok = token(client)
    client.cookies.clear()
    assert client.post(f"/review/{pid}/merge", data={"csrf_token": tok}).status_code == 403


def test_search_post_requires_csrf(tmp_path):
    client, src, _ = build(tmp_path, SHOPS)
    r = client.post("/search", data={"category": "gift_shop", "area": "Portland"})
    assert r.status_code == 403 and src.calls == 0


def test_review_unknown_pair_and_action(tmp_path):
    client, *_ = build(tmp_path)
    tok = token(client)
    assert client.post("/review/99/merge", data={"csrf_token": tok}).status_code == 404
    assert client.post("/review/99/explode", data={"csrf_token": tok}).status_code == 404


def test_history_lists_and_reopens_without_source_calls(tmp_path):
    client, src, _ = build(tmp_path, SHOPS)
    assert "No searches yet" in client.get("/history").text
    loc = search(client).headers["location"]
    hist = client.get("/history").text
    assert "Gift shop" in hist and "Portland, Oregon" in hist and loc in hist
    assert "Zebra Gifts" in client.get(loc).text and src.calls == 1


def test_repeat_search_served_from_cache(tmp_path):
    client, src, router = build(tmp_path, SHOPS)
    first = search(client).headers["location"]
    second = search(client, area="portland oregon").headers["location"]
    assert first == second and src.calls == 1 and router.count("/search") == 1


def test_refresh_requeries(tmp_path):
    client, src, _ = build(tmp_path, SHOPS)
    loc = search(client).headers["location"]
    r = client.post(
        f"{loc}/rerun", data={"csrf_token": token(client), "refresh": 1}, follow_redirects=True
    )
    assert src.calls == 2 and "Zebra Gifts" in r.text


# --- 7.5 CSV export ------------------------------------------------------------------------


def rows_of(resp):
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"), newline="")))


def test_csv_export_download(tmp_path):
    client, *_ = build(tmp_path, SHOPS)
    loc = search(client).headers["location"]
    r = client.get(f"{loc}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = rows_of(r)
    assert rows[0][:2] == ["name", "address"] and len(rows) == 3
    assert rows[1][-1] == "© OpenStreetMap contributors"
    assert "'+15035550142" in {c for row in rows for c in row}  # formula-neutralised phone


def test_csv_respects_filter_and_neutralises_formulas(tmp_path):
    shops = [cand("1", '=HYPERLINK("http://evil")', phone="(503) 555-0142"), cand("2", "Plain")]
    client, *_ = build(tmp_path, shops)
    loc = search(client).headers["location"]
    rows = rows_of(client.get(f"{loc}/export.csv", params={"contact": 1}))
    assert len(rows) == 2 and rows[1][0].startswith("'=HYPERLINK")


def test_csv_nothing_to_export(tmp_path):
    client, *_ = build(tmp_path, [])
    loc = search(client).headers["location"]
    r = client.get(f"{loc}/export.csv")
    assert r.status_code == 404 and "nothing to export" in r.text.lower()
    assert "text/csv" not in r.headers["content-type"]
