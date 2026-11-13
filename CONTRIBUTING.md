# Contributing

Thanks for helping! The project rules live in [`AGENTS.md`](AGENTS.md); this guide explains how
to follow them. Humans and AI coding tools follow the same rules.

## Dev setup

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium      # needed for the end-to-end tests
```

Run the app: `python -m leadgen`, then open the printed local address.

## Running the tests

Everything is tested at three levels, and each can run alone:

```bash
pytest -m unit          # pure logic, fast
pytest -m integration   # real SQLite/services, HTTP mocked with recorded fixtures
pytest -m e2e           # real app process + fake Nominatim/Overpass, driven in a browser
ruff check              # lint
```

Tests must **never hit live external services**. Use fixtures/mocks (see `tests/helpers.py` and
`tests/e2e/fake_services.py`). The only live check is the manual smoke check described in the
change's `tasks.md`.

## Making a change

1. **Branch off `main`** (e.g. `feat/short-name` or `fix/short-name`).
2. **Never commit or push directly to `main`.** All changes reach `main` through a merged pull
   request; open the PR early.
3. For anything non-trivial, plan with [OpenSpec](https://github.com/Fission-AI/OpenSpec):
   propose a change (`openspec/changes/<name>/` with proposal, specs, design, tasks), implement
   its tasks, then archive it once merged.
4. Any code change ships with tests at **each applicable level** (unit, integration, e2e),
   covering **happy and unhappy paths**.
5. Fill in the PR template checklist. CI runs lint and all three test levels on every PR.

## Data source rules

- **Free sources only**: no paid APIs, keys that cost money, or required subscriptions.
- Respect each source's terms of service and rate limits (identify the client, throttle, cache,
  back off). Do not scrape sites whose terms forbid it.
- OpenStreetMap data is ODbL: keep the "© OpenStreetMap contributors" attribution in the UI and
  in exports.

## AI-assisted contributions

AI-assisted changes follow exactly the same rules via `AGENTS.md`. Rules are written once there,
in tool-neutral language; tool-specific files (e.g. `CLAUDE.md`) only point to it.

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
