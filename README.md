<!-- mcp-name: io.github.j4th/mtg-mcp-server -->
# mtg-mcp-server

[![CI](https://github.com/j4th/mtg-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/j4th/mtg-mcp-server/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mtg-mcp-server)](https://pypi.org/project/mtg-mcp-server/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)](https://github.com/j4th/mtg-mcp-server)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![codecov](https://codecov.io/gh/j4th/mtg-mcp-server/graph/badge.svg)](https://codecov.io/gh/j4th/mtg-mcp-server)
[![CodeQL](https://github.com/j4th/mtg-mcp-server/workflows/CodeQL/badge.svg)](https://github.com/j4th/mtg-mcp-server/actions/workflows/codeql.yml)
[![Smithery](https://smithery.ai/badge/@j4th/mtg-mcp-server)](https://smithery.ai/server/@j4th/mtg-mcp-server)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-blue?logo=dependabot)](https://github.com/j4th/mtg-mcp-server/security/dependabot)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A Magic: The Gathering MCP server for AI assistants. Search cards, analyze draft formats, explore Commander combos, evaluate deck upgrades — all from Claude Code, Claude Desktop, or any MCP client.

> **Built on data from [Scryfall](https://scryfall.com), [Commander Spellbook](https://commanderspellbook.com), [17Lands](https://www.17lands.com), [EDHREC](https://edhrec.com), and [MTGJSON](https://mtgjson.com).** See [Data Sources & Attribution](#data-sources--attribution) for details and usage terms.

## What It Does

**Card Data** (via Scryfall) — Search the full MTG card database, check prices, look up rulings, verify format legality.

**Combo Discovery** (via Commander Spellbook) — Find combos for any commander or card, estimate deck bracket/power level.

**Draft Analytics** (via 17Lands) — Card win rates by set and archetype, format speed analysis, draft pick recommendations.

**Commander Metagame** (via EDHREC) — Top cards by commander, synergy scores, inclusion rates, average decklists.

**Composed Workflows** — Higher-level tools that cross-reference multiple sources: commander overviews, upgrade evaluations, sealed pool analysis, deck audits.

## Install

Requires Python 3.12+. No API keys needed — all data sources are public.

```bash
# Run directly with uvx (no install needed)
uvx mtg-mcp-server

# Or install globally
uv tool install mtg-mcp-server

# Or install in a project
uv add mtg-mcp-server
```

## Connect to Claude Code

```bash
claude mcp add mtg -- uvx mtg-mcp-server
```

Or add to your MCP config (`.mcp.json` or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uvx",
      "args": ["mtg-mcp-server"]
    }
  }
}
```

Then in Claude Code:

```
> Search for Sultai creatures with CMC 3 or less that are legal in Commander
> What combos does Muldrotha enable?
> Show me draft ratings for the top BG commons in Lorwyn Eclipsed
> Evaluate adding Spore Frog to my Muldrotha deck, cutting Eternal Skylord
```

## Connect to Claude Desktop

Add to your Claude Desktop config:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uvx",
      "args": ["mtg-mcp-server"]
    }
  }
}
```

## Configuration

All settings use `MTG_MCP_` environment variables with sensible defaults. No configuration required to get started.

```bash
# Disable optional backends
MTG_MCP_ENABLE_EDHREC=false    # EDHREC scrapes undocumented endpoints
MTG_MCP_ENABLE_17LANDS=false   # 17Lands rate-limits aggressively
MTG_MCP_ENABLE_MTGJSON=false   # MTGJSON downloads ~100MB bulk file on first use

# Pass env vars to uvx
uvx --env MTG_MCP_ENABLE_EDHREC=false mtg-mcp-server
```

See `.env.example` for all available options.

## Local Install (from source)

If you want to run from a local checkout instead of PyPI:

```bash
git clone https://github.com/j4th/mtg-mcp-server.git
cd mtg-mcp-server
mise install && mise run setup

# Run the server directly
uv run mtg-mcp-server

# Or use uvx with a local path
uvx --from /path/to/mtg-mcp-server mtg-mcp-server
```

Claude Code config for a local install:

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mtg-mcp-server", "mtg-mcp-server"]
    }
  }
}
```

## Development

```bash
git clone https://github.com/j4th/mtg-mcp-server.git
cd mtg-mcp-server
mise install          # Installs Python, uv, ruff, ty
mise run setup        # Creates venv, installs dependencies

mise run check        # Full quality gate: lint + format + typecheck + test
mise run test         # pytest with coverage
mise run lint         # ruff check + format check
mise run typecheck    # ty check
mise run dev          # MCP Inspector for interactive testing
mise run fix          # Auto-fix lint and format issues
```

## Architecture

Built on **FastMCP 3.x**. Each data source is an independent sub-server mounted into a single orchestrator:

```
MTG (orchestrator)
├── scryfall (namespace: scryfall_)     → Scryfall REST API
├── spellbook (namespace: spellbook_)   → Commander Spellbook API
├── draft (namespace: draft_)           → 17Lands data
├── edhrec (namespace: edhrec_)         → EDHREC (scraped)
├── mtgjson (namespace: mtgjson_)       → MTGJSON bulk data
└── workflows (no namespace)            → Composed tools: commander_overview, etc.
```

Services are pure async API clients. Providers register MCP tools. Workflows compose across services. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture.

## Stack

| | |
|---|---|
| Runtime | Python 3.12+, uv |
| MCP | FastMCP 3.1.x |
| HTTP | httpx (async) |
| Validation | Pydantic v2 |
| Logging | structlog |
| Tooling | mise, ruff, ty (Astral) |
| Testing | pytest, respx, pytest-asyncio |

## Status

All planned phases are **complete**: 23 tools, 4 prompts, 6 resources, 374 tests at 92% coverage.

| Phase | What | Status |
|-------|------|--------|
| 0 | Project scaffold | Done |
| 1 | Scryfall backend (4 tools) | Done |
| 2 | Spellbook + 17Lands + EDHREC backends (9 tools) | Done |
| 3 | Workflow tools — commander, draft, deck (4 tools) | Done |
| 4 | TTL caching + MTGJSON bulk provider (2 tools) | Done |
| 5 | Analysis & comparison workflows, prompts, resources (4 tools) | Done |

## Data Sources & Attribution

This project composes data from multiple third-party services:

- **[Scryfall](https://scryfall.com)** — Card database, prices, rulings, search ([API guidelines](https://scryfall.com/docs/api))
- **[Commander Spellbook](https://commanderspellbook.com)** — Combo search, bracket estimation ([MIT license](https://github.com/SpaceCowMedia/commander-spellbook-backend))
- **[17Lands](https://www.17lands.com)** — Draft card ratings, archetype win rates ([usage guidelines](https://www.17lands.com/usage_guidelines))
- **[EDHREC](https://edhrec.com)** — Commander staples, synergy scores (undocumented endpoints, behind feature flag)
- **[MTGJSON](https://mtgjson.com)** — Bulk card data for rate-limit-free lookups ([MIT license](https://mtgjson.com/license/))

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for full license texts and usage terms.

## Disclaimer

mtg-mcp-server is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. &copy; Wizards of the Coast LLC.

## License

MIT — see [LICENSE](LICENSE)
