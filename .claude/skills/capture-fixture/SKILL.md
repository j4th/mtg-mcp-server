---
name: capture-fixture
description: Capture a live API response as a JSON test fixture for a given service and endpoint
disable-model-invocation: true
---

# Capture Fixture

Capture a real API response and save it as a JSON fixture for TDD testing.

## Usage

`/capture-fixture <service> <description>`

Examples:
- `/capture-fixture scryfall card lookup for Muldrotha`
- `/capture-fixture spellbook combos for Muldrotha`
- `/capture-fixture 17lands card ratings for LRW PremierDraft`
- `/capture-fixture edhrec commander page for Muldrotha`

## Workflow

1. **Identify the endpoint** from `docs/SERVICE_CONTRACTS.md` based on the service and description.

2. **Make the request** using `curl` or `python -c` with httpx. Include required headers:
   - Scryfall: `User-Agent: mtg-mcp/0.1.0` and `Accept: application/json`
   - All others: `Accept: application/json`

3. **Save the response** to `tests/fixtures/<service>/`:
   - Use a descriptive snake_case filename (e.g., `card_muldrotha.json`, `search_sultai_commander.json`, `card_not_found.json`)
   - Pretty-print with `jq .` or `python -m json.tool`
   - Create the directory if it doesn't exist

4. **Capture error responses too** — 404s, rate limits, etc. are valuable fixtures.

5. **Show the user**:
   - The full URL hit
   - The saved file path
   - A brief summary of the response shape (top-level keys, array lengths)

## Service Endpoints Quick Reference

| Service | Base URL | Key Endpoints |
|---------|----------|---------------|
| scryfall | `https://api.scryfall.com` | `/cards/named?exact=`, `/cards/search?q=`, `/cards/{id}/rulings` |
| spellbook | `https://backend.commanderspellbook.com` | `/api/variants/?q=`, `/api/estimate-bracket/` |
| 17lands | `https://www.17lands.com` | `/card_ratings/data?expansion=&format=` |
| edhrec | `https://json.edhrec.com` | `/pages/commanders/{slug}.json`, `/pages/cards/{slug}.json` |

## Rules

- Never overwrite an existing fixture without asking first
- Always pretty-print JSON
- Respect rate limits — wait between requests if capturing multiple fixtures
- EDHREC slugs: lowercase, hyphens for spaces, strip commas/apostrophes
