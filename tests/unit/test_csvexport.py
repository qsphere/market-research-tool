import csv
import io

import pytest

from leadgen.csvexport import ATTRIBUTION, HEADERS, leads_to_csv, neutralize


def lead(**kw):
    base = {"name": "Shop", "address": "1 Main St", "phone": "", "website": "", "category": "gift_shop",
            "source_names": ["osm"]}  # fmt: skip
    return {**base, **kw}


def parse(data: bytes):
    assert data.startswith(b"\xef\xbb\xbf")  # BOM for Excel
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))


def test_headers_attribution_and_source_per_row():
    rows = parse(leads_to_csv([lead(), lead(name="Other", source_names=["osm", "fake"])]))
    assert rows[0] == HEADERS
    assert rows[1][4] == "osm" and rows[2][4] == "osm, fake"
    assert all(r[-1] == ATTRIBUTION for r in rows[1:])
    assert len(rows) == 3


def test_commas_quotes_newlines_roundtrip():
    nasty = 'Joe, "The Gift" Shop\nSecond line'
    rows = parse(leads_to_csv([lead(name=nasty, address="1 Main St, Apt 2\r\nPortland")]))
    assert rows[1][0] == nasty
    assert rows[1][1] == "1 Main St, Apt 2\r\nPortland"


def test_accents_survive():
    assert parse(leads_to_csv([lead(name="Café Été")]))[1][0] == "Café Été"


@pytest.mark.parametrize("value", ["=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(A1)", "\t=1"])
def test_formula_values_neutralised(value):
    assert neutralize(value).startswith("'")
    assert parse(leads_to_csv([lead(name=value)]))[1][0] == "'" + value


@pytest.mark.parametrize("value", ["Plain", "", None, "a=b", "12 Main St"])
def test_safe_values_untouched(value):
    assert neutralize(value) == (value or "")
