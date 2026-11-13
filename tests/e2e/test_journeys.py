"""Browser journeys against the real app process."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def run_search(page: Page, url: str, category: str, area: str) -> None:
    page.goto(url)
    page.select_option("#category", category)
    page.fill("#area", area)
    page.click("button:has-text('Search')")


def test_search_results_detail_and_csv_export(page: Page, app_url, fake):
    run_search(page, app_url, "gift_shop", "Portland, Oregon")
    expect(page.get_by_role("heading", name="Gift shop in Portland, Oregon")).to_be_visible(
        timeout=15000
    )
    expect(page.get_by_role("link", name="Joe's Gifts")).to_be_visible()
    expect(page.get_by_text("+15035550142")).to_be_visible()
    expect(page.locator("footer")).to_contain_text("© OpenStreetMap contributors")

    page.get_by_role("link", name="Joe's Gifts").click()
    expect(page.get_by_role("heading", name="Joe's Gifts")).to_be_visible()
    expect(page.get_by_text("(503) 555-0142")).to_be_visible()  # original value
    expect(page.get_by_role("link", name="node/1001")).to_be_visible()  # provenance link
    page.go_back()

    with page.expect_download() as dl:
        page.get_by_role("link", name="Export CSV").click()
    text = open(dl.value.path(), encoding="utf-8-sig").read()
    assert "Joe's Gifts" in text and "© OpenStreetMap contributors" in text


def test_ambiguous_area_prompts_for_choice(page: Page, app_url):
    run_search(page, app_url, "gift_shop", "Springfield")
    expect(page.get_by_text("Several places match")).to_be_visible(timeout=15000)
    page.get_by_label("Portland, Cumberland County, Maine, United States").check()
    page.click("button:has-text('Search this area')")
    expect(page.get_by_role("link", name="Joe's Gifts")).to_be_visible(timeout=15000)


def test_source_failure_message_and_retry(page: Page, app_url, fake):
    fake.overpass_fail = True
    run_search(page, app_url, "gift_shop", "Portland, Oregon")
    expect(page.get_by_role("alert")).to_contain_text("Source unavailable: osm", timeout=15000)
    fake.overpass_fail = False
    page.click("button:has-text('Retry')")
    expect(page.get_by_role("link", name="Joe's Gifts")).to_be_visible(timeout=15000)


def test_area_not_found_message(page: Page, app_url):
    run_search(page, app_url, "gift_shop", "Nowhere at all")
    expect(page.get_by_role("alert")).to_contain_text("Area not found", timeout=15000)


def test_missing_area_shows_field_error(page: Page, app_url):
    page.goto(app_url)
    page.select_option("#category", "gift_shop")
    page.click("button:has-text('Search')")
    expect(page.get_by_role("alert")).to_contain_text("Please enter an area")


def test_duplicate_review_merge_and_reject(page: Page, app_url):
    run_search(page, app_url, "boutique", "Portland, Oregon")
    expect(page.get_by_role("link", name="Treasure Trove Boutique", exact=True)).to_be_visible(
        timeout=15000
    )
    page.goto(app_url + "/review")
    expect(page.get_by_role("heading", name="Treasure Trove Boutiques")).to_be_visible()
    page.get_by_role("button", name="Merge").click()
    expect(page.get_by_text("Pair merged.")).to_be_visible()
    page.goto(app_url + "/review")
    expect(page.get_by_text("Nothing needs review")).to_be_visible()

    # second scenario in a fresh area: reject keeps both and never resurfaces
    page.goto(app_url + "/history")
    page.get_by_role("button", name="Refresh").first.click()
    expect(page.get_by_role("link", name="Treasure Trove Boutique", exact=True)).to_be_visible(
        timeout=15000
    )
    page.goto(app_url + "/review")
    expect(page.get_by_text("Nothing needs review")).to_be_visible()


def test_duplicate_review_reject(page: Page, app_url):
    run_search(page, app_url, "boutique", "Portland, Oregon")
    expect(page.get_by_role("link", name="Treasure Trove Boutique", exact=True)).to_be_visible(
        timeout=15000
    )
    page.goto(app_url + "/review")
    page.get_by_role("button", name="Keep separate").click()
    expect(page.get_by_text("Pair kept separate.")).to_be_visible()
    page.goto(app_url + "/history")
    page.get_by_role("link", name="Open").first.click()
    expect(page.get_by_text("2 leads")).to_be_visible()
    page.goto(app_url + "/review")
    expect(page.get_by_text("Nothing needs review")).to_be_visible()


def test_repeat_search_served_from_cache(page: Page, app_url, fake):
    run_search(page, app_url, "gift_shop", "Portland, Oregon")
    expect(page.get_by_role("link", name="Joe's Gifts")).to_be_visible(timeout=15000)
    assert fake.stats == {"nominatim": 1, "overpass": 1}
    run_search(page, app_url, "gift_shop", "portland oregon")
    expect(page.get_by_role("link", name="Joe's Gifts")).to_be_visible(timeout=15000)
    assert fake.stats == {"nominatim": 1, "overpass": 1}  # no new calls
    page.click("button:has-text('Refresh')")
    expect(page.get_by_role("link", name="Joe's Gifts")).to_be_visible(timeout=15000)
    assert fake.stats["overpass"] == 2
