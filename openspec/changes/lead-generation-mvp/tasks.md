## 1. Setup

- [x] 1.1 Create branch `lead-generation-mvp` off `main`; verify with `git branch --show-current`
- [x] 1.2 Install Python 3.12+ (free, python.org) and verify `python --version` reports 3.12 or newer
- [x] 1.3 Add an MIT `LICENSE` file (copyright holder "London C", year 2026) and declare `license = "MIT"` in `pyproject.toml`; verify `LICENSE` starts with "MIT License" and `pip install -e .` metadata shows the MIT license
- [x] 1.4 Add `pyproject.toml` (fastapi, uvicorn, jinja2, httpx, phonenumbers, rapidfuzz, pyyaml; dev: pytest, pytest-playwright, ruff), `.gitignore` (venv, `*.db`, caches), package skeleton with `python -m leadgen` entry point, and a `tests/unit`, `tests/integration`, `tests/e2e` layout with matching pytest markers (`unit`, `integration`, `e2e`) so each level can be run separately; verify `pip install -e .[dev]` succeeds, `pytest -m unit`, `pytest -m integration` and `pytest -m e2e` each run (collect with zero failures) and `ruff check` passes
- [x] 1.5 Add config module (db path, host 127.0.0.1, port, Overpass/Nominatim endpoints, cache window, dedup thresholds, optional contact string); verify unit tests cover defaults, overrides, and an invalid value being rejected

## 2. Storage (lead-data)

- [x] 2.1 Implement SQLite connection + versioned SQL migrations creating `searches`, `geocode_cache`, `raw_records`, `leads`, `lead_sources`, `search_leads`, `duplicate_pairs`; verify tests: fresh DB migrates, re-running migrations is a no-op, data persists after reopening the file
- [x] 2.2 Implement repository functions (save raw record, upsert lead, link sources, record search, read/write geocode cache, duplicate pair status); verify tests cover happy paths plus unique-constraint/duplicate-insert and missing-row cases, and that raw payloads are stored unmodified

## 3. Normalization (lead-data)

- [x] 3.1 Implement phone normalization to E.164 with region default, original retained, multiple-number handling; verify tests for local format, already-international, invalid text, empty, and multiple numbers
- [x] 3.2 Implement website canonicalization (missing scheme, host case, trailing slash, tracking params, invalid values dropped); verify tests for each case including garbage input and `javascript:` URLs being rejected
- [x] 3.3 Implement address assembly from address parts and coordinates handling; verify tests for full, partial, coordinates-only, and empty inputs

## 4. Deduplication (lead-data)

- [x] 4.1 Implement match scoring (confident vs possible vs none) with configurable thresholds; verify fixture-pair tests: same phone, same domain, similar-name-nearby, similar-name-far-apart, conflicting phone, identical re-run
- [x] 4.2 Implement merge (union sources, keep most complete fields), reject (persisted, never re-suggested), and review-queue population; verify tests for merge preserving all sources, reject permanence, and re-running a search creating no duplicates

## 5. Source adapters (source-adapters)

- [x] 5.1 Define the `Source` protocol, `RawRecord`/`LeadCandidate` types, typed errors, and the enabled-sources registry; verify tests that a fake source is queried when enabled, skipped when disabled, and that multiple sources are combined
- [x] 5.2 Add `categories.yaml` catalog loader (business/event kinds, multiple criteria per category) and a lookup that rejects unknown categories; verify tests for multi-criteria category, unknown category, malformed YAML, and a catalog edit taking effect without code changes
- [x] 5.3 Implement shared HTTP client behaviour: descriptive User-Agent, 1 req/s throttle for Nominatim, bounded exponential backoff on 429/5xx/timeouts; verify tests with a mocked transport and fake clock for spacing, backoff, and giving up after the max attempts
- [x] 5.4 Implement Nominatim geocoding with caching, multiple candidates (ambiguity), not-found, and too-large-area refusal; verify mocked-transport tests for each outcome and that a repeat lookup makes no network call
- [x] 5.5 Implement the Overpass query builder and OSM adapter (tags → raw records → candidates, unnamed places excluded, OSM id kept); verify tests against recorded fixture responses covering full fields, missing phone/website, unnamed place, empty result, malformed JSON, and 429/504 handling
- [ ] 5.6 Validate the catalog's OSM tag mappings (consignment, gift shop, craft fair, farmers market, etc.) with a few real low-volume Overpass queries, adjust `categories.yaml`, and record known coverage gaps in `README.md`; verify by saving the sample result counts in the PR description

## 6. Search orchestration (lead-search)

- [x] 6.1 Implement the search service: validate category/area, resolve area, run enabled sources, persist raw records, normalize, dedupe, link results to the search, and report per-source failures as partial; verify tests for success, unsupported category, ambiguous area, area not found, no matches, one-source-fails, all-sources-fail, and rate-limited
- [x] 6.2 Implement result caching and forced refresh; verify tests that an identical search inside the cache window makes no source calls and a refresh does

## 7. Web UI (lead-ui)

- [x] 7.1 Create the FastAPI app with base template, vendored HTMX and CSS, bound to 127.0.0.1, with OSM attribution in the footer; verify `TestClient` tests for the index page and that the default bind host is loopback
- [x] 7.2 Build the search form, background search execution, and HTMX status polling; verify tests for valid submit, missing category/area errors, ambiguity choice prompt, failure message with retry, and unsupported category
- [x] 7.3 Build the results table with sorting, "has contact info" filter, empty-state message, and lead detail view with provenance; verify tests for columns, blanks for missing values, filter behaviour, and detail showing original values and source links
- [x] 7.4 Build the duplicate review queue (side-by-side, merge / keep-separate, CSRF-protected) and search history with reopen/refresh; verify tests for merge, reject, empty queue, missing/invalid CSRF token rejected, and reopening a past search without new source calls
- [x] 7.5 Implement CSV export (UTF-8 BOM, attribution, per-row source, formula-injection neutralisation, empty-results message); verify tests for escaping commas/quotes/newlines, a `=cmd` value being neutralised, attribution present, and nothing-to-export behaviour

## 8. Integration and end-to-end tests

Unit tests live with each task above. These groups add the other two required levels; none may
call live external services.

- [x] 8.1 Integration tests (`tests/integration`): real SQLite file + real services + the OSM adapter against a mocked HTTP transport with recorded fixtures, exercising search → raw storage → normalize → dedupe → read-back; verify the suite covers success, partial source failure, all-sources-fail, rate-limit backoff, cache hit and forced refresh, re-run creating no duplicates, and persistence across reopening the DB
- [x] 8.2 Integration tests for the web layer: FastAPI app wired to a temp DB and fake sources, driven through HTTP (search, status polling, results, detail, review merge/reject with CSRF, history, CSV export); verify unhappy paths (invalid form, bad CSRF, unknown category, empty results, nothing to export) pass
- [ ] 8.3 End-to-end tests (`tests/e2e`): launch the real app process against a local fake Nominatim/Overpass server and drive it in a browser with Playwright; verify these journeys pass: search → results table → open lead detail → export CSV; ambiguous area prompt; source-failure message and retry; duplicate review merge and reject; repeat search served from cache
- [ ] 8.4 Add a GitHub Actions workflow (free for public repos) that runs `ruff check` and the unit, integration and e2e suites on every PR and on pushes to `main`; verify the workflow runs green on the PR

## 9. Contribution, process, and wrap-up

- [ ] 9.1 Add a "Contributing" section to `README.md` and a `CONTRIBUTING.md` covering: dev setup, running the three test levels, branch naming, the rule that all changes go through a PR into `main` (no direct pushes), the OpenSpec propose/apply/archive workflow for non-trivial changes, the testing requirements (unit + integration + e2e, happy and unhappy paths), and the free-sources-only and ToS/rate-limit rules; also add `.github/pull_request_template.md` with a checklist (tests at all three levels, spec updated, free sources only); and note in `CONTRIBUTING.md` that AI-assisted contributions follow the same rules via `AGENTS.md`; verify by reading the files against `AGENTS.md` for consistency
- [ ] 9.2 Update `README.md` (stack, setup, run command, data source terms and attribution, coverage caveats), replace "Stack: TBD", and add a License section pointing to `LICENSE` (MIT) noting that OSM-derived data stays under ODbL; verify a clean checkout can follow the README to a running app
- [ ] 9.3 Run a manual smoke check (not part of CI) with the app started locally against the real Overpass/Nominatim for one small area: results appear, CSV downloads, repeat search hits the cache; verify and note the outcome in the PR description
- [ ] 9.4 Run `pytest` (all three levels), `ruff check`, and `openspec validate lead-generation-mvp --strict`; verify all pass, then push the branch and open a PR against `main` (never push to `main`)
- [ ] 9.5 Ask the user before enabling GitHub branch protection on `main` (require a PR, require the CI check to pass, block direct pushes); once confirmed, apply it with `gh api` and verify a direct push to `main` is rejected
