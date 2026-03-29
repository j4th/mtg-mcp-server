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

51 tools, 17 prompts, and 18 resources that give AI assistants deep access to Magic: The Gathering -- card data, combos, draft analytics, Commander metagame, deck building, rules engine, and more. Works with Claude Code, Claude Desktop, or any MCP client.

> Built on data from [Scryfall](https://scryfall.com), [Commander Spellbook](https://commanderspellbook.com), [17Lands](https://www.17lands.com), and [EDHREC](https://edhrec.com). See [Data Sources & Attribution](#data-sources--attribution) for details and usage terms.

## What You Can Do

Ask your AI assistant questions like these and it will use the MTG tools automatically:

**Commander**
- "Show me everything about Muldrotha as a commander"
- "What are the best budget upgrades for my Atraxa deck under $5?"
- "Compare Muldrotha vs Meren vs Karador as graveyard commanders"

**Draft & Limited**
- "What are the best commons in Foundations for draft?"
- "Rank these cards for my draft pack: Bitter Triumph, Monstrous Rage, Torch the Tower"
- "Build a sealed deck from this pool: [list]"

**Deck Building**
- "Validate my Modern decklist"
- "Suggest a mana base for my 3-color Commander deck"
- "Find cards that synergize with sacrifice themes in Golgari"

**Rules**
- "How do deathtouch and trample interact?"
- "Resolve this combat scenario: my 3/3 with first strike blocks their 5/5 with trample"

## Install

No API keys needed -- all data sources are public.

### Hosted (zero setup)

The fastest way to get started. No Python install required. Works on mobile.

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "mtg": {
      "type": "url",
      "url": "https://mtg-mcp-server.fastmcp.app/mcp"
    }
  }
}
```

### Claude Code

```bash
claude mcp add mtg -- uvx mtg-mcp-server
```

### Claude Desktop (local)

Runs on your machine. Requires Python 3.12+.

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

### PyPI

```bash
# Run directly (no install)
uvx mtg-mcp-server

# Install globally
uv tool install mtg-mcp-server

# Add to a project
uv add mtg-mcp-server
```

### Development

```bash
git clone https://github.com/j4th/mtg-mcp-server.git
cd mtg-mcp-server
mise install          # Installs Python 3.12, uv, ruff, ty
mise run setup        # Creates venv, installs dependencies

uv run mtg-mcp-server # Run the server
```

Claude Code config for local development:

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

## Configuration

All settings use `MTG_MCP_` environment variables. Everything works out of the box with sensible defaults.

```bash
# Feature flags for optional backends
MTG_MCP_ENABLE_EDHREC=false       # EDHREC (scrapes undocumented endpoints)
MTG_MCP_ENABLE_17LANDS=false      # 17Lands (rate-limits aggressively)
MTG_MCP_ENABLE_BULK_DATA=false    # Scryfall bulk data (~30MB download on first use)
MTG_MCP_ENABLE_RULES=false        # Comprehensive Rules engine

# Pass env vars through uvx
uvx --env MTG_MCP_ENABLE_EDHREC=false mtg-mcp-server
```

See `.env.example` for all available options including base URLs, rate limits, and cache settings.

## Tools

51 tools across 10 domains. See [docs/TOOL_DESIGN.md](docs/TOOL_DESIGN.md) for full input/output details.

### Card Data (`scryfall_*`)

| Tool | Description |
|------|-------------|
| `search_cards` | Search using full Scryfall syntax (`f:commander id:sultai t:creature`) |
| `card_details` | Full card data by exact or fuzzy name |
| `card_price` | Current USD, EUR, and foil prices |
| `card_rulings` | Official rulings and clarifications |
| `set_info` | Set metadata by code |
| `whats_new` | Recently released or previewed cards |

### Bulk Data (`bulk_*`)

| Tool | Description |
|------|-------------|
| `card_lookup` | Rate-limit-free card lookup by exact name |
| `card_search` | Search by name, type, or oracle text |
| `format_legality` | Check if a card is legal in a format |
| `format_search` | Search for cards legal in a specific format |
| `format_staples` | Top-played cards in a format by EDHREC rank |
| `ban_list` | Banned and restricted cards for a format |
| `card_in_formats` | Card legality across all formats |
| `random_card` | Random card, optionally filtered by format or type |
| `similar_cards` | Find cards similar by type, keywords, or mana cost |

### Combos (`spellbook_*`)

| Tool | Description |
|------|-------------|
| `find_combos` | Search for combos by card name and color identity |
| `combo_details` | Step-by-step combo instructions by ID |
| `find_decklist_combos` | Find combos present in a decklist |
| `estimate_bracket` | Estimate Commander bracket for a decklist |

### Draft Analytics (`draft_*`)

| Tool | Description |
|------|-------------|
| `card_ratings` | Win rates and draft data for cards in a set (17Lands) |
| `archetype_stats` | Win rates by color pair for a set |

### Commander Metagame (`edhrec_*`)

| Tool | Description |
|------|-------------|
| `commander_staples` | Most-played cards for a commander with synergy scores |
| `card_synergy` | Synergy data for a card with a specific commander |

### Commander Workflows

| Tool | Description |
|------|-------------|
| `commander_overview` | Full commander profile from all sources |
| `evaluate_upgrade` | Assess whether a card is worth adding to a deck |
| `card_comparison` | Compare 2-5 cards side-by-side for a commander |
| `budget_upgrade` | Budget-constrained upgrade suggestions ranked by synergy/$ |
| `commander_comparison` | Compare 2-5 commanders head-to-head |
| `color_identity_staples` | Top-played cards across all commanders in a color identity |

### Deck Building

| Tool | Description |
|------|-------------|
| `theme_search` | Find cards matching a mechanical or tribal theme |
| `build_around` | Detect synergies from key cards and find complements |
| `complete_deck` | Gap analysis and suggestions for a partial decklist |
| `tribal_staples` | Best cards for a creature type in a color identity |
| `precon_upgrade` | Analyze a precon and suggest swap pairs |
| `suggest_cuts` | Identify the weakest cards to cut from a decklist |
| `deck_analysis` | Full decklist health check (curve, colors, combos, budget) |
| `deck_validate` | Validate a decklist against format construction rules |
| `suggest_mana_base` | Suggest lands based on color pip distribution |
| `price_comparison` | Compare prices across multiple cards |

### Draft Workflows

| Tool | Description |
|------|-------------|
| `draft_pack_pick` | Rank cards in a draft pack using 17Lands data |
| `set_overview` | Top commons/uncommons and trap rares for a format |
| `sealed_pool_build` | Suggest the best 40-card builds from a sealed pool |
| `draft_signal_read` | Detect open colors from draft picks |
| `draft_log_review` | Pick-by-pick review of a completed draft with grade |

### Constructed

| Tool | Description |
|------|-------------|
| `rotation_check` | Standard rotation status and rotating cards |

### Rules Engine

| Tool | Description |
|------|-------------|
| `rules_lookup` | Look up rules by number or keyword |
| `keyword_explain` | Explain a keyword with rules and example cards |
| `rules_interaction` | How two mechanics interact with rule citations |
| `rules_scenario` | Rules framework for a game scenario |
| `combat_calculator` | Step-by-step combat phases with keyword interactions |

## Architecture

Built on **FastMCP 3.x**. Each data source is an independent sub-server mounted into a single orchestrator:

```
MTG (orchestrator)
├── scryfall (namespace: scryfall_)     -> Scryfall REST API
├── spellbook (namespace: spellbook_)   -> Commander Spellbook API
├── draft (namespace: draft_)           -> 17Lands data
├── edhrec (namespace: edhrec_)         -> EDHREC (scraped, feature-flagged)
├── bulk (namespace: bulk_)             -> Scryfall Oracle Cards bulk data
└── workflows (no namespace)            -> 30 composed tools + rules engine
```

Services are pure async API clients. Providers register MCP tools. Workflows compose across services with partial failure tolerance. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture.

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

## Development

```bash
git clone https://github.com/j4th/mtg-mcp-server.git
cd mtg-mcp-server
mise install          # Installs Python, uv, ruff, ty
mise run setup        # Creates venv, installs dependencies

mise run check        # Full quality gate: lint + typecheck + tests
mise run check:quick  # Fast gate: lint + typecheck + affected tests only
mise run test         # All tests with coverage
mise run test:quick   # Only tests affected by recent changes
mise run lint         # ruff check + format check
mise run typecheck    # ty check
mise run dev          # MCP Inspector for interactive testing
mise run fix          # Auto-fix lint and format issues
```

## Documentation

| Doc | What it covers |
|-----|----------------|
| [COOKBOOK.md](docs/COOKBOOK.md) | Usage recipes -- Commander, draft, deck building, rules workflows |
| [TOOL_DESIGN.md](docs/TOOL_DESIGN.md) | Full reference for all 51 tools, 17 prompts, 18 resources |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical architecture, FastMCP patterns, design decisions |
| [SERVICE_CONTRACTS.md](docs/SERVICE_CONTRACTS.md) | API endpoints, rate limits, response shapes per backend |
| [DATA_SOURCES.md](docs/DATA_SOURCES.md) | All data sources with auth, stability, and access patterns |
| [CACHING_DESIGN.md](docs/CACHING_DESIGN.md) | TTL cache strategy and Scryfall bulk data design |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, TDD workflow, code style, PR process |
| [CHANGELOG.md](CHANGELOG.md) | Version history in Keep a Changelog format |

## Status

51 tools, 17 prompts, 18 resource templates. 973 tests at 89% coverage.

| Phase | What | Status |
|-------|------|--------|
| 0 | Project scaffold | Done |
| 1 | Scryfall backend (4 tools) | Done |
| 2 | Spellbook + 17Lands + EDHREC backends (9 tools) | Done |
| 3 | Workflow tools -- commander, draft, deck (4 tools) | Done |
| 4 | TTL caching + Scryfall bulk data provider (6 tools) | Done |
| 5 | Analysis & comparison workflows, prompts, resources (4 tools) | Done |
| Branch A | Structured output, rules engine, validation tools (17 tools) | Done |
| Branch B | Format workflows -- deck building, commander depth, limited, constructed (11 tools) | Done |

## Data Sources & Attribution

This project composes data from multiple third-party services:

- **[Scryfall](https://scryfall.com)** -- Card database, prices, rulings, search, bulk data ([API guidelines](https://scryfall.com/docs/api))
- **[Commander Spellbook](https://commanderspellbook.com)** -- Combo search, bracket estimation ([MIT license](https://github.com/SpaceCowMedia/commander-spellbook-backend))
- **[17Lands](https://www.17lands.com)** -- Draft card ratings, archetype win rates ([usage guidelines](https://www.17lands.com/usage_guidelines))
- **[EDHREC](https://edhrec.com)** -- Commander staples, synergy scores (undocumented endpoints, behind feature flag)

Scryfall bulk data (Oracle Cards) replaced MTGJSON in v2.0 for richer card information including prices, legalities, images, and EDHREC rank.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for full license texts and usage terms.

## Disclaimer

mtg-mcp-server is unofficial Fan Content permitted under the [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. &copy; Wizards of the Coast LLC.

## License

MIT -- see [LICENSE](LICENSE)
