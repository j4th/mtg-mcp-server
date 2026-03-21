# mtg-mcp

A Magic: The Gathering MCP server for AI assistants. Search cards, analyze draft formats, explore Commander combos, evaluate deck upgrades — all from Claude Code, Claude Desktop, or any MCP client.

## What It Does

**Card Data** (via Scryfall) — Search the full MTG card database, check prices, look up rulings, verify format legality.

**Combo Discovery** (via Commander Spellbook) — Find combos for any commander or card, estimate deck bracket/power level.

**Draft Analytics** (via 17Lands) — Card win rates by set and archetype, format speed analysis, draft pick recommendations.

**Commander Metagame** (via EDHREC) — Top cards by commander, synergy scores, inclusion rates, average decklists.

**Composed Workflows** — Higher-level tools that cross-reference multiple sources: commander overviews, upgrade evaluations, sealed pool analysis, deck audits.

## Prerequisites

- [mise](https://mise.jdx.dev) — tool & task manager
- Python 3.12+ (installed automatically by mise)
- [uv](https://docs.astral.sh/uv/) (installed automatically by mise)

## Quick Start

```bash
git clone https://github.com/youruser/mtg-mcp.git
cd mtg-mcp
mise install          # Installs Python, uv, ruff, ty
mise run setup        # Creates venv, installs dependencies

# Try it out
mise run dev          # Opens MCP Inspector — browse tools, invoke them interactively
```

## Connect to Claude Code

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "mtg": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mtg-mcp", "python", "-m", "mtg_mcp.server"]
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

Same config as above, placed in:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

## Development

```bash
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
└── workflows (no namespace)           → Composed tools: commander_overview, etc.
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

🚧 **Under active development.** See [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) for current progress.

## License

MIT
