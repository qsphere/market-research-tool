# market-research-tool

A tool for market research on a given product in a given area, using only free tools and data
sources. The first feature is lead generation: find businesses of a given category (e.g.
consignment and gift stores) or events (e.g. craft fairs, farmers markets) in an area and
return each one's name, location, phone number, and website. See `README.md` for the full
goals; broader market research reports come later.

This file is the **single source of truth for project rules**, for humans and for every AI
coding tool (Claude Code, Cursor, ChatGPT/Codex, Copilot, Gemini, etc.).

## Rules

- **Free sources only** — no paid APIs or subscriptions. Respect each source's terms of service
  and rate limits.
- Plan changes with OpenSpec (`openspec/`); the `openspec` CLI is installed globally.
- Branch off `main` for changes. After implementing an OpenSpec change's `tasks.md`, open a
  PR — don't stop at local commits.
- **Never commit or push directly to `main`.** All changes reach `main` only through a merged
  PR; create the PR first.
- **Everything is tested at three levels:** unit, integration, and end-to-end (e2e) tests. Any
  code change ships with tests at each applicable level, covering happy and unhappy paths. Tests
  must not hit live external services (use fixtures/mocks), except the clearly marked manual
  smoke check.
- **Contributing:** `README.md` has a Contributing section (and `CONTRIBUTING.md` if it grows)
  describing how others can contribute. Keep it in sync with these rules.

## Rules must be AI-tool agnostic

- Every project rule is written once, here in `AGENTS.md`, in plain tool-neutral language. A
  rule must work for any AI tool or human; do not phrase rules around one tool's features
  (slash commands, tool names, model names).
- Tool-specific files (`CLAUDE.md`, `.cursor/rules/*`, `.github/copilot-instructions.md`,
  `GEMINI.md`, etc.) must only point to this file and never hold rules of their own. When a
  request adds a rule "for" one tool, add it here instead so all tools follow it.
- Tools that read `AGENTS.md` natively (Cursor, Codex, Copilot, and others) need no extra file.
  Add a pointer file only for a tool that doesn't.
