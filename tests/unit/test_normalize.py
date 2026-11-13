import pytest

from leadgen.models import LeadCandidate
from leadgen.normalize import (
    assemble_address,
    canonicalize_website,
    normalize_candidate,
    normalize_phones,
    registrable_domain,
    valid_coordinates,
)

# --- phones -------------------------------------------------------------------------------


def test_phone_local_format():
    r = normalize_phones("(503) 555-0142", "US")
    assert r.primary == "+15035550142"
    assert r.original == "(503) 555-0142"


def test_phone_already_international():
    assert normalize_phones("+44 20 7946 0958", "US").primary == "+442079460958"


def test_phone_invalid_keeps_original():
    r = normalize_phones("call us anytime", "US")
    assert r.primary == "" and r.original == "call us anytime"


@pytest.mark.parametrize("value", ["", None, "   "])
def test_phone_empty(value):
    r = normalize_phones(value)
    assert r.primary == "" and r.extras == () and r.original == ""


def test_phone_multiple_numbers_first_valid_is_primary():
    r = normalize_phones("garbage; (503) 555-0142 / (212) 555-0188", "US")
    assert r.primary == "+15035550142"
    assert r.extras == ("+12125550188",)
    assert "garbage" in r.original


def test_phone_duplicate_numbers_collapsed():
    r = normalize_phones("503-555-0142; (503) 555-0142")
    assert r.extras == ()


# --- websites -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.com/shop/", "https://example.com/shop"),
        ("HTTPS://WWW.Example.COM/", "https://www.example.com"),
        ("http://example.com/a/?utm_source=x&id=3&fbclid=abc", "http://example.com/a?id=3"),
        ("https://example.com/#frag", "https://example.com"),
        ("example.com:8080/x", "https://example.com:8080/x"),
        ("  https://example.com  ", "https://example.com"),
    ],
)
def test_website_canonical(raw, expected):
    assert canonicalize_website(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", None, "not a url", "javascript:alert(1)", "JAVASCRIPT:alert(1)", "ftp://example.com",
     "data:text/html,hi", "mailto:a@b.com", "localhost", "http://", "https://exa mple.com"],
)  # fmt: skip
def test_website_invalid_dropped(raw):
    assert canonicalize_website(raw) == ""


def test_registrable_domain():
    assert registrable_domain("https://www.shop.example.com/x") == "example.com"
    assert registrable_domain("https://www.example.co.uk") == "example.co.uk"


# --- addresses ----------------------------------------------------------------------------


def test_address_full():
    parts = {"addr:housenumber": "12", "addr:street": "Main St", "addr:city": "Portland",
             "addr:state": "OR", "addr:postcode": "97201"}  # fmt: skip
    assert assemble_address(parts) == "12 Main St, Portland, OR 97201"


def test_address_partial_has_no_placeholders():
    assert assemble_address({"street": "Main St", "city": "Portland"}) == "Main St, Portland"


def test_address_empty():
    assert assemble_address({}) == ""
    assert assemble_address(None) == ""
    assert assemble_address({"city": "  "}) == ""


def test_coordinates():
    assert valid_coordinates(45.5, -122.6) == (45.5, -122.6)
    assert valid_coordinates(None, None) == (None, None)
    assert valid_coordinates(95, 0) == (None, None)


def test_candidate_coordinates_only():
    c = LeadCandidate("osm", "node/1", " Shop ", "business", "gift_shop", lat=45.5, lon=-122.6)
    out = normalize_candidate(c)
    assert out["address"] == "" and out["lat"] == 45.5 and out["name"] == "Shop"


def test_candidate_keeps_originals():
    c = LeadCandidate("osm", "node/1", "Shop", "business", "gift_shop", phone="bad",
                      website="javascript:x")  # fmt: skip
    out = normalize_candidate(c)
    assert out["phone"] == "" and out["phone_original"] == "bad"
    assert out["website"] == "" and out["website_original"] == "javascript:x"
