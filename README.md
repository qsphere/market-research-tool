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

TBD.

## Workflow

Changes are planned with [OpenSpec](https://github.com/Fission-AI/OpenSpec) in `openspec/`:
`/opsx:propose` → `/opsx:apply` → `/opsx:archive`. Once a change is implemented, it ships as a
pull request.
