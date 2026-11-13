## Why

The tool's first goal is lead generation: given a business category (consignment shops, gift
stores) or event type (craft fairs, farmers markets) and an area, return each match's name,
location, phone, and website. Today the repo has no code, so this is the first working slice. It
must run entirely on free data and free tooling, on the user's own machine.

## What Changes

- Add a local Python app (single process, no external services) with a browser UI.
- Add a **search** flow: the user enters a category/event type and an area; the app resolves the
  area to a bounding region and queries free sources through a pluggable source-adapter interface.
- Ship one adapter in this change: **OpenStreetMap** (Nominatim for geocoding the area, Overpass
  for POI queries). The adapter interface lets later changes add more free sources.
- Map user-facing categories (e.g. "consignment", "gift shop", "craft fair", "farmers market") to
  source-specific tag queries via a small, editable category catalog.
- Store every raw source response in SQLite with provenance (source, query, URL, fetched-at),
  separate from normalized lead records.
- Normalize leads: phone to E.164, website URL canonicalization, address assembly.
- Deduplicate leads across and within sources; ambiguous matches are flagged for **manual review**
  in the UI rather than silently merged.
- UI: search form, results table (name, location, phone, website, source), a review queue for
  possible duplicates, and **CSV export**.
- Enforce source ToS/rate limits in code: identifying User-Agent, throttling (max 1 request/second
  to Nominatim), caching of responses, and OSM attribution shown in the UI and CSV.

## Capabilities

### New Capabilities
- `lead-search`: Accepting a category/event type plus an area, resolving the area, running source
  adapters, and returning lead results.
- `source-adapters`: The adapter contract, the category catalog, the OpenStreetMap adapter, and
  rate-limit/caching/attribution rules for sources.
- `lead-data`: Raw-response storage with provenance, lead normalization, deduplication, and the
  duplicate review path (SQLite persistence).
- `lead-ui`: The local web UI (search, results table, review queue) and CSV export.

### Modified Capabilities
<!-- None: openspec/specs/ is empty. -->

## Impact

- New code only: a Python package, SQLite database file (git-ignored), web UI assets, tests.
- New dependencies, all free/open-source: an HTTP client, a lightweight web framework, a phone
  parsing library (`phonenumbers`), and a test runner. Exact choices are in `design.md`.
- Network: outbound calls to the public Nominatim and Overpass endpoints only.
- README "Stack: TBD" gets filled in.
- Project is licensed under MIT (`LICENSE` added). This covers the code only; OSM-derived data
  remains under ODbL.

### Data sources and terms

- **Nominatim** (geocoding): OSM Foundation usage policy permits light use with a valid
  identifying User-Agent, absolute max 1 request/second, no bulk/repeated queries, and caching of
  results. This app makes one geocode per search and caches it.
- **Overpass API** (public instances): free for fair use; no key required. Requests are
  low-volume, bounded by area, with a query timeout; the app backs off on 429/504.
- **Data license:** OSM data is ODbL. Using and exporting it for lead lists is permitted with
  attribution ("© OpenStreetMap contributors"), which the app displays and includes in exports.
  Storing a local derived database is allowed under ODbL; sharing it would carry share-alike terms.
- Coverage caveat: OSM phone/website tags are incomplete, so some leads will have blanks. Filling
  them from businesses' own websites is out of scope here.

## Non-goals

- Paid APIs, Google Maps/Places, Yelp, or scraping sites whose terms prohibit it.
- Social-media or business-website scraping to enrich contact info.
- Multi-user accounts, auth, multi-tenancy, hosting/deployment, or any SaaS concerns.
- LLM/AI features, embeddings, or RAG.
- Broader market-research reports (demand, pricing, demographics, trends).
- Recurring/scheduled monitoring or change alerts.
- Event-date/schedule modeling beyond what OSM exposes (events are matched where OSM tags
  them, e.g. `amenity=marketplace`; richer event sources come in a later change).
