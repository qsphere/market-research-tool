## Context

Greenfield repo; no code, no existing specs. Motivation and scope: see `proposal.md`; behaviour:
see `specs/`. Constraints that shape the approach:

- Free sources and tools only; single user; runs locally.
- The user asked for a Python app with a web UI.
- **Python is not currently installed on this machine** (only Node 24 was found; `python` resolves
  to the Windows Store shim, and `py`/`uv` are absent). Installing Python 3.12+ (free) is a
  prerequisite, handled as the first task.

## Goals / Non-Goals

**Goals:**
- One process, one command to start, one SQLite file; trivial to run and delete.
- A source-adapter seam so new free sources can be added without touching search, storage, or UI.
- Raw data and normalized data kept separate so normalization can be re-run offline.

**Non-Goals:**
- Background job infrastructure (Celery/Redis), auth, or deployment. Searches are short and
  run in-process.
- A JS frontend build toolchain.
- Generalising the schema for future market-research reports.

## Decisions

**1. Python 3.12 + FastAPI + Jinja2 templates + HTMX, served by uvicorn on 127.0.0.1.**
Server-rendered pages keep the UI in one language with no build step; HTMX gives progress
updates and in-place review actions without writing a SPA. FastAPI gives typed request handling
and testability via `TestClient`. *Alternatives:* Flask (comparable; FastAPI chosen for
validation and async HTTP calls); Streamlit (fast, but poor control over the review queue and
CSV download semantics and awkward to test); React/Next.js (build chain and a second language
for no benefit at this scale).

**2. SQLite via the standard `sqlite3` module with a small hand-written repository layer and
versioned SQL migration files.** Few tables, no ORM needed. *Alternative:* SQLAlchemy + Alembic
(from the reviewed proposal) is overkill for a single-file local DB; revisit if the schema grows.

**3. Schema (core tables):** `searches` (category, area, status, timestamps),
`geocode_cache` (query, result, fetched_at), `raw_records` (source, search_id, source_record_id,
payload JSON, request descriptor, fetched_at), `leads` (normalized fields + original values +
coordinates + kind business/event), `lead_sources` (lead_id ↔ raw_record_id), `duplicate_pairs`
(lead_a, lead_b, score, status pending/merged/rejected), `search_leads` (search_id ↔ lead_id).
Raw payloads are never mutated. Leads are rebuildable from `raw_records`.

**4. Source adapter contract.** A `Source` protocol: `name`, `search(category, area) ->
list[RawRecord]`, raising typed errors (`SourceUnavailable`, `RateLimited`, `BadResponse`). A
`RawRecord` carries payload, source id, and request descriptor. A separate per-source
`to_candidate(raw) -> LeadCandidate` maps to the common shape. Registered in a simple list in
config; a source is disabled by removing/flagging it.

**5. OSM adapter.** Nominatim geocodes the area (1 req/s via a shared throttle; results cached
in `geocode_cache`; returns multiple candidates so ambiguity can be surfaced to the user).
Overpass queries by the area's OSM relation/area id (or bounding box fallback) for the category's
tag criteria, `[timeout:25]`, `out center tags`. Retries on 429/504 use exponential backoff,
max 3 attempts. User-Agent is a generic client name (e.g. `market-research-tool/0.1`), with an
optional contact string in local config rather than hard-coded. Overpass public endpoint is the
default; the endpoint is configurable. Areas above a size threshold are refused.

**6. Category catalog as a YAML file in the repo** (`categories.yaml`): category key, display
name, kind (business|event), and a list of OSM tag criteria (e.g. `shop=second_hand` with
`second_hand=consignment`, `shop=gift`, `amenity=marketplace`, `leisure=fair`...). Editing the
file changes behaviour without code changes. Exact tag mapping is validated against Overpass
during implementation; OSM coverage for craft fairs is known to be weak (see risks).

**7. Normalization.** `phonenumbers` library for E.164 with region defaulting from the geocoded
country; `urllib.parse` plus a small canonicalizer (force https where scheme missing, lowercase
host, strip trailing slash and `utm_*`/`fbclid` params); address assembled from `addr:*` tags.
Originals retained next to normalized values.

**8. Deduplication.** Deterministic, explainable rules, no ML:
- *Confident match:* equal normalized phone, OR equal website registrable domain, AND name
  similarity ≥ 0.6.
- *Possible match (review queue):* name similarity ≥ 0.85 (token-based, `rapidfuzz`) and within
  150 m, with no conflicting phone/website.
- Otherwise separate. Rejected pairs persist and are never re-suggested. Confirmed merges union
  the sources and keep the most complete field values.
Thresholds live in config and are covered by tests with fixture pairs.

**9. Searches run synchronously in a worker thread, with status polled by HTMX.** The request
creates a `searches` row and starts a thread; the page polls a status fragment until done. No
queue infrastructure. *Alternative:* hold the HTTP request open — simple, but poor UX on a slow
Overpass response and fragile to timeouts.

**10. CSV export** via the `csv` module with UTF-8 BOM (so Excel reads accents), an attribution
row/column, and a leading apostrophe on cells starting with `= + - @` to block formula injection.

**11. Security posture for a local app.** Bind to 127.0.0.1 by default; Jinja2 autoescape on;
parameterized SQL only; treat all source text as untrusted data (never rendered as HTML); CSRF
token on state-changing review actions.

**12. Tooling:** `pytest` (+ `respx` or `httpx` mock transport; no live network in tests),
`ruff`, project metadata in `pyproject.toml`; a single `python -m leadgen` entry point.

**13. Testing strategy (project rule: unit, integration, and e2e for everything).**
- *Unit* (`tests/unit`): pure logic — normalization, scoring, catalog, throttle/backoff with a
  fake clock, CSV escaping.
- *Integration* (`tests/integration`): real SQLite and real services with HTTP mocked via
  recorded fixtures; also the FastAPI app driven through HTTP against a temp DB.
- *E2E* (`tests/e2e`): the real app process plus a local fake Nominatim/Overpass server, driven
  in a browser with Playwright (free). This keeps e2e deterministic and ToS-friendly.
- Markers (`unit`, `integration`, `e2e`) let each level run alone; CI runs all three.
- The only live-network check is a manual smoke test, excluded from CI.

**14. Process enforcement.** A GitHub Actions workflow (free on public repos) runs lint and all
tests on PRs. Branch protection on `main` (PR required, CI required, no direct pushes) is applied
only after explicit user confirmation, since it changes shared repository settings. A
`CONTRIBUTING.md`, README Contributing section, and PR template document the rules for outside
contributors.

## Risks / Trade-offs

- [OSM has sparse phone/website data and weak coverage of events like craft fairs] → Show blanks
  honestly, document the coverage caveat in the UI, keep the adapter seam so event-focused
  sources (e.g. municipal open data, other free listings with compatible terms) can be added next.
- [Public Overpass/Nominatim can be slow or rate-limit] → Throttle, cache, bounded retries,
  clear UI messaging; endpoint configurable so users can point at a self-hosted/mirror instance.
- [Dedup false merges or misses] → Conservative auto-merge thresholds, review queue for the gray
  zone, reversible: merges keep original raw links so a lead can be rebuilt.
- [ODbL share-alike if the user ever shares the database] → Documented; CSV/DB are for the user's
  own use, attribution always included.
- [Python not installed] → First task installs/verifies Python 3.12 and documents setup.
- [Category→OSM tag mapping may be inaccurate (e.g. "consignment" is loosely tagged)] → Catalog
  is editable; validate mappings with real queries during implementation and note known gaps.
- [HTMX loaded from a CDN would add an external dependency] → Vendor the small HTMX file into
  the repo's static assets.

## Open Questions

- Default country/region for phone parsing when the geocoder returns none: assume the area's
  country, fall back to US. Revisit if non-US use becomes common.
