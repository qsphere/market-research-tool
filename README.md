# Market Research Tool

Performs market research for a given product in a given area using only free-to-use tools and
data sources. The first use case is **lead generation**: find businesses or events of a
specific type in an area and collect their contact details.

## Goals

**Current priority: lead generation**

- Search an area for a specific category of registered business (e.g. consignment shops, gift
  stores) or event type (e.g. craft fairs, farmers markets).
- For each match, return the **name**, **location/address**, **phone number**, and **website**.

**Later (not a priority yet)**

- Given a product and a geographic area (city, region, or country), produce a market research
  report.
- Cover demand signals, competitors, pricing ranges, demographics, and trends for that area.
- Use only free data sources and tools — no paid APIs or required subscriptions.
- Cite the source of every finding so results can be verified.

## Stack

A single local Python process with a browser UI. Everything is free and open source.

- Python 3.12+, [FastAPI](https://fastapi.tiangolo.com/) + Jinja2 templates + vendored
  [HTMX](https://htmx.org/) (no JS build step), served by uvicorn on `127.0.0.1` only
- SQLite (standard library) for all data, kept in a local file
- Data source: [OpenStreetMap](https://www.openstreetmap.org/) via Nominatim (geocoding) and
  Overpass (places); other free sources plug in through the `Source` adapter interface
- `phonenumbers` (E.164 phones), `rapidfuzz` (name matching), `pytest` + Playwright, `ruff`

## Setup and run

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m leadgen
```

Open the address it prints (default <http://127.0.0.1:8000/>). Choose a category, enter an area
such as `Portland, Oregon`, and search. Results can be sorted, filtered, opened for provenance,
reviewed for duplicates, and exported as CSV. The database is `leadgen.db` in the working
directory (git-ignored); delete it to start fresh.

Optional settings are environment variables prefixed `LEADGEN_` (e.g. `LEADGEN_PORT`,
`LEADGEN_DB_PATH`, `LEADGEN_OVERPASS_URL` to use a mirror or self-hosted instance,
`LEADGEN_CONTACT` to add a contact string to the User-Agent, `LEADGEN_CACHE_HOURS`). See
`leadgen/config.py` for the full list and validation. The category-to-OpenStreetMap-tag mapping is
the editable file `leadgen/categories.yaml` (override with `LEADGEN_CATEGORIES_PATH`).

## Data sources, terms, and attribution

- **Nominatim** (OSM Foundation usage policy): one geocode per search, at most 1 request per
  second, results cached, identifying User-Agent.
- **Overpass API**: low-volume, bounded, time-limited queries with exponential backoff on
  429/5xx; the endpoint is configurable.
- **License of the data:** OpenStreetMap data is © OpenStreetMap contributors under the
  [ODbL](https://www.openstreetmap.org/copyright). Attribution appears in the UI and in every CSV
  export. Keeping a local database for your own use is fine; if you ever share the database or
  derived data, ODbL share-alike terms apply.

### Coverage caveats

OpenStreetMap is volunteer-maintained: phone and website tags are often missing (those cells are
shown blank, never guessed), and events such as craft fairs are tagged inconsistently, so event
searches will miss many real events. Mapping notes for each category are maintained in
`leadgen/categories.yaml`; richer event sources are planned as separate changes.

## Testing

Everything is tested at three levels (unit, integration, end-to-end) and tests never hit live
services. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run each level.

## Workflow

Changes are planned with [OpenSpec](https://github.com/Fission-AI/OpenSpec) in `openspec/`:
`/opsx:propose` → `/opsx:apply` → `/opsx:archive`. Once a change is implemented, it ships as a
pull request.

## Contributing

Contributions are welcome. In short:

- Branch off `main`; **never push directly to `main`** — everything lands through a reviewed,
  CI-passing pull request.
- Plan non-trivial work with OpenSpec (propose → apply → archive).
- Ship tests at every applicable level (unit, integration, e2e), covering happy and unhappy
  paths; no live network in tests.
- Use free data sources only and respect their terms and rate limits.

Full details are in [CONTRIBUTING.md](CONTRIBUTING.md); the authoritative rules are in
[AGENTS.md](AGENTS.md), which AI coding tools follow too.

## License

The code is released under the [MIT License](LICENSE). This covers the code only: data obtained
from OpenStreetMap remains under the ODbL and must be attributed as described above.
