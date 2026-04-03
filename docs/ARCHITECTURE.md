# MTG MCP Server — Architecture

> **Purpose**: Full technical reference for the MTG MCP server.

---

## 1. Overview

A unified MCP server that provides Magic: The Gathering data to AI assistants by composing multiple data source backends through FastMCP 3.x's native mount system. Exposes both raw data tools (one backend each) and composed workflow tools (cross-referencing multiple sources) through a single endpoint.

### Design Principles

1. **Vertical-first development.** Get the full pipeline working with the simplest backend (Scryfall), verify end-to-end, then add backends one at a time.
2. **Independent backends, unified interface.** Each data source is its own FastMCP server, testable and runnable in isolation. The orchestrator mounts them with namespaces.
3. **Fixture-driven TDD.** Capture real API responses as JSON fixtures. Tests run against fixtures via mocked httpx (respx), never hitting real APIs.
4. **Structured observability.** structlog with bound context on every service method. FastMCP 3's native OpenTelemetry traces every tool call.

---

## 2. System Architecture

```
Claude Code / claude.ai / any MCP client
              │
              │ stdio (default) or streamable HTTP
              │
    ┌─────────▼──────────┐
    │   MTG Orchestrator  │  ← FastMCP("MTG"), 56 tools, 17 prompts, 19 resources
    │                     │
    │  Workflow Tools:     │  ← Compose across backends (no namespace)
    │  Commander:          │  Draft/Limited:
    │  • commander_overview│  • draft_pack_pick    • set_overview
    │  • evaluate_upgrade  │  • sealed_pool_build  • draft_signal_read
    │  • card_comparison   │  • draft_log_review
    │  • budget_upgrade    │
    │  • suggest_cuts      │  Deck Building:
    │  • commander_compari.│  • theme_search  • build_around
    │  • tribal_staples    │  • complete_deck
    │  • precon_upgrade    │
    │  • color_id_staples  │  Cross-Format:
    │                      │  • deck_analysis   • deck_validate
    │  Rules Engine:       │  • suggest_mana_base
    │  • rules_lookup      │  • price_comparison • rotation_check
    │  • keyword_explain   │
    │  • rules_interaction │
    │  • rules_scenario    │
    │  • combat_calculator │
    │                     │
    ├─────────────────────┤
    │  Mounted Backends:   │  ← mount() with namespaces
    │                     │
    │  ┌─────────────┐    │
    │  │  Scryfall    │────┼──► api.scryfall.com
    │  │  ns=scryfall │    │    Card data, prices, rulings, sets
    │  └─────────────┘    │
    │  ┌─────────────┐    │
    │  │  Spellbook   │────┼──► backend.commanderspellbook.com
    │  │  ns=spellbook│    │    Combo search, bracket estimation
    │  └─────────────┘    │
    │  ┌─────────────┐    │
    │  │  17Lands     │────┼──► 17lands.com
    │  │  ns=draft    │    │    Card win rates, archetype stats
    │  └─────────────┘    │
    │  ┌─────────────┐    │
    │  │  EDHREC      │────┼──► edhrec.com (scraping)
    │  │  ns=edhrec  │    │    Commander staples, synergy scores
    │  └─────────────┘    │
    │  ┌─────────────┐    │
    │  │  Scryfall    │────┼──► api.scryfall.com (bulk data)
    │  │  Bulk ns=bulk│    │    Rate-limit-free card lookup and search
    │  └─────────────┘    │
    │  ┌─────────────┐    │
    │  │  Moxfield    │────┼──► moxfield.com (reverse-engineered)
    │  │  ns=moxfield │    │    Public decklist fetching
    │  └─────────────┘    │
    │  ┌─────────────┐    │
    │  │  Spicerack   │────┼──► api.spicerack.gg
    │  │  ns=spicerack│    │    Tournament results, standings
    │  └─────────────┘    │
    └─────────────────────┘
```

---

## 3. Tech Stack

| Layer | Tool | Version | Notes |
|-------|------|---------|-------|
| Task runner | mise | latest | Installs Python, uv, ruff, ty. Runs all dev tasks. |
| Language | Python | 3.12+ | Modern typing features |
| Package mgmt | uv | latest | Astral. Lockfiles, virtualenvs, fast resolution |
| MCP framework | fastmcp | 3.2.x | PrefectHQ/fastmcp. Provider/Transform architecture |
| Type checking | ty | 0.0.24+ (beta) | Astral. 10-60x faster than mypy/pyright |
| Linting/format | ruff | latest | Astral. Replaces black/isort/flake8/pylint |
| HTTP client | httpx | 0.28+ | Async HTTP. Used by all service clients |
| Data models | pydantic | v2 | FastMCP-native. All API responses modeled as Pydantic |
| Settings | pydantic-settings | 2.x | Config from env vars |
| Retry logic | tenacity | 9.x+ | Exponential backoff, rate limit handling |
| Logging | structlog | 24.x+ | JSON structured logging, context-bound loggers |
| Testing | pytest | 8.x | With pytest-asyncio, respx (httpx mocking), pytest-cov |
| Observability | OpenTelemetry | via FastMCP 3 | Native instrumentation — every tool call traced |

---

## 4. mise.toml

mise manages tool versions and task aliases. One `mise install` gets a new contributor everything they need.

```toml
[tools]
python = "3.12"
uv = "latest"
ruff = "latest"
ty = "latest"

[env]
_.python.venv = { path = ".venv", create = true }
UV_PYTHON = { value = "{{ tools.python.path }}", tools = true }

[tasks.setup]
description = "Install dependencies and create venv"
run = "uv sync"
```

See `mise.toml` for the full task list. Key tasks: `check` (full gate), `test`, `lint`, `fix`, `typecheck`, `dev`, `serve`.

---

## 5. Project Structure

```
mtg-mcp/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── mise.toml
├── uv.lock
│
├── src/
│   └── mtg_mcp_server/
│       ├── __init__.py
│       ├── server.py               # Orchestrator: mounts all providers, runs transport
│       ├── config.py               # pydantic-settings: API URLs, rate limits, feature flags
│       ├── logging.py              # structlog configuration
│       ├── smithery.py             # Smithery deployment adapter
│       ├── types.py                # Shared Pydantic models (Card, Combo, CardRating, etc.)
│       │
│       ├── services/               # HTTP API clients — NO MCP awareness
│       │   ├── __init__.py
│       │   ├── base.py             # BaseClient: httpx.AsyncClient + rate limiting + retries + structlog
│       │   ├── scryfall.py         # ScryfallClient
│       │   ├── spellbook.py        # SpellbookClient
│       │   ├── seventeen_lands.py  # SeventeenLandsClient
│       │   ├── edhrec.py           # EDHRECClient
│       │   ├── moxfield.py         # MoxfieldClient
│       │   ├── spicerack.py        # SpicerackClient
│       │   ├── scryfall_bulk.py    # ScryfallBulkClient (file-based, not BaseClient)
│       │   ├── rules.py            # RulesService (local Comprehensive Rules parser)
│       │   └── cache.py            # async_cached decorator, TTLCache helpers
│       │
│       ├── providers/              # FastMCP sub-servers (one per backend, independently runnable)
│       │   ├── __init__.py         # TOOL_ANNOTATIONS + tag constants
│       │   ├── scryfall.py         # scryfall_mcp = FastMCP("Scryfall")
│       │   ├── spellbook.py        # spellbook_mcp = FastMCP("Spellbook")
│       │   ├── seventeen_lands.py  # draft_mcp = FastMCP("17Lands")
│       │   ├── edhrec.py           # edhrec_mcp = FastMCP("EDHREC")
│       │   ├── moxfield.py         # moxfield_mcp = FastMCP("Moxfield")
│       │   ├── spicerack.py        # spicerack_mcp = FastMCP("Spicerack")
│       │   └── scryfall_bulk.py    # scryfall_bulk_mcp = FastMCP("Scryfall Bulk")
│       │
│       ├── utils/                  # Shared utilities (no MCP awareness)
│       │   ├── __init__.py
│       │   ├── color_identity.py   # Color identity parsing and validation
│       │   ├── decklist.py         # Decklist parsing (4x Card Name format)
│       │   ├── format_rules.py     # Format-specific rules (deck sizes, copy limits)
│       │   ├── formatters.py       # Shared formatting helpers (ResponseFormat, markdown)
│       │   ├── mana.py             # Mana cost parsing utilities
│       │   ├── query_parser.py     # Search query parsing for bulk data
│       │   └── slim.py             # Slim dict builders for structured_content response sizes
│       │
│       └── workflows/              # Composed tools (registered on orchestrator, no namespace)
│           ├── __init__.py
│           ├── server.py           # workflow_mcp = FastMCP("Workflows"), multi-client lifespan + prompts
│           ├── commander.py        # commander_overview, evaluate_upgrade, card_comparison, budget_upgrade
│           ├── commander_depth.py  # commander_comparison, tribal_staples, precon_upgrade, color_identity_staples
│           ├── draft.py            # draft_pack_pick, set_overview
│           ├── draft_limited.py    # sealed_pool_build, draft_signal_read, draft_log_review
│           ├── deck.py             # suggest_cuts
│           ├── analysis.py         # deck_analysis
│           ├── building.py         # theme_search, build_around, complete_deck
│           ├── constructed.py      # rotation_check
│           ├── validation.py       # deck_validate
│           ├── mana_base.py        # suggest_mana_base
│           ├── pricing.py          # price_comparison
│           ├── rules.py            # rules_lookup, keyword_explain, rules_interaction, rules_scenario, combat_calculator
│           └── card_resolver.py    # Bulk-data-first card resolution with Scryfall fallback
│
├── tests/
│   ├── conftest.py                 # Shared fixtures, mock clients, cache clearing
│   ├── test_orchestrator.py        # Orchestrator tool registration
│   ├── test_smoke.py               # Basic server smoke tests
│   ├── test_parameter_descriptions.py  # Tool parameter description validation
│   ├── test_smithery_schema.py     # Smithery schema validation
│   ├── services/
│   │   ├── test_base.py            # BaseClient behavior
│   │   ├── test_cache.py           # async_cached decorator tests
│   │   ├── test_scryfall.py        # Scryfall API client
│   │   ├── test_scryfall_bulk.py   # Bulk data service + layout filtering
│   │   ├── test_spellbook.py       # Spellbook API client
│   │   ├── test_seventeen_lands.py # 17Lands API client
│   │   ├── test_edhrec.py          # EDHREC scraping client
│   │   ├── test_rules.py           # Rules parser service
│   │   ├── test_moxfield.py        # Moxfield client
│   │   └── test_spicerack.py       # Spicerack client
│   ├── providers/
│   │   ├── test_scryfall_provider.py
│   │   ├── test_scryfall_resources.py
│   │   ├── test_scryfall_bulk_provider.py
│   │   ├── test_spellbook_provider.py
│   │   ├── test_spellbook_resources.py
│   │   ├── test_seventeen_lands_provider.py
│   │   ├── test_seventeen_lands_resources.py
│   │   ├── test_edhrec_provider.py
│   │   ├── test_edhrec_resources.py
│   │   ├── test_moxfield_provider.py
│   │   └── test_spicerack_provider.py
│   ├── workflows/
│   │   ├── test_commander.py       # commander_overview, evaluate_upgrade
│   │   ├── test_commander_new.py   # card_comparison, budget_upgrade
│   │   ├── test_commander_depth.py # commander_comparison, tribal_staples, precon_upgrade, color_identity_staples
│   │   ├── test_draft.py           # draft_pack_pick
│   │   ├── test_draft_overview.py  # set_overview
│   │   ├── test_draft_limited.py   # sealed_pool_build, draft_signal_read, draft_log_review
│   │   ├── test_deck.py            # suggest_cuts
│   │   ├── test_analysis.py        # deck_analysis
│   │   ├── test_building.py        # theme_search, build_around, complete_deck
│   │   ├── test_constructed.py     # rotation_check
│   │   ├── test_validation.py      # deck_validate
│   │   ├── test_mana_base.py       # suggest_mana_base
│   │   ├── test_pricing.py         # price_comparison
│   │   ├── test_rules.py           # Rules engine tools
│   │   ├── test_card_resolver.py   # Card resolver utility
│   │   ├── test_context_progress.py # Progress reporting
│   │   ├── test_prompts.py         # All 17 prompt registrations
│   │   └── test_workflow_server.py # Integration: tool registration + error handling
│   ├── utils/
│   │   ├── test_color_identity.py  # Color identity parsing
│   │   ├── test_decklist.py        # Decklist parsing
│   │   ├── test_format_rules.py    # Format rule validation
│   │   ├── test_mana.py            # Mana cost parsing
│   │   ├── test_query_parser.py    # Search query parsing
│   │   └── test_slim.py            # Slim dict builder tests
│   ├── integration/                # Fixture-mocked cross-component E2E tests
│   │   ├── conftest.py             # Bulk client + orchestrator fixtures (respx-mocked)
│   │   ├── test_bulk_data_e2e.py   # Bulk data pipeline: lookup, search, resources
│   │   └── test_orchestrator_e2e.py# Full orchestrator: tool registration, scryfall, ping
│   ├── live/                       # Real server + real API smoke tests
│   │   ├── conftest.py             # Server subprocess lifecycle fixtures
│   │   └── test_smoke.py           # Health, bulk data, scryfall (marked @pytest.mark.live)
│   └── fixtures/                   # Real API responses, captured once
│       ├── scryfall/               # Card data, search results, rulings, sets
│       ├── scryfall_bulk/          # Oracle Cards sample with adversarial entries
│       ├── spellbook/              # Combos, bracket estimates, decklist combos
│       ├── seventeen_lands/        # Card ratings, color ratings
│       ├── edhrec/                 # Commander pages, card synergy
│       ├── moxfield/               # Deck data
│       ├── spicerack/              # Tournament results, standings
│       └── rules/                  # Comprehensive Rules text sample
│
├── scripts/
│   └── capture_fixtures.py
│
└── docs/
    ├── ARCHITECTURE.md
    ├── TOOL_DESIGN.md
    ├── SERVICE_CONTRACTS.md
    ├── CACHING_DESIGN.md
    └── DATA_SOURCES.md
```

### Key Structural Decisions

**`services/` vs `providers/`**: Services are plain Python classes with async methods that call external APIs. Providers are FastMCP server instances that register tools backed by services. Services are reusable outside MCP and independently testable.

**`workflows/`**: Pure async functions that accept service clients as keyword parameters and return `WorkflowResult` objects (markdown + structured data). Registered as tools on a separate FastMCP server (`workflow_mcp`) mounted without a namespace. The function modules (`commander.py`, `commander_depth.py`, `draft.py`, `draft_limited.py`, `deck.py`, `analysis.py`, `building.py`, `constructed.py`, `validation.py`, `mana_base.py`, `pricing.py`, `rules.py`) have zero MCP imports — `server.py` wraps them as tools and converts service exceptions to `ToolError`. This separation avoids circular imports and makes unit testing trivial with `AsyncMock`. `card_resolver.py` provides bulk-data-first card resolution with Scryfall fallback, used by `analysis.py` for rate-limit-friendly bulk lookups.

**`types.py`**: Shared Pydantic models that services return and tools consume. Ensures type safety across the service → provider → workflow pipeline.

---

## 6. FastMCP 3.x Patterns

### Composition via Mount

```python
# src/mtg_mcp_server/server.py
from fastmcp import FastMCP
from mtg_mcp_server.providers.scryfall import scryfall_mcp
from mtg_mcp_server.providers.spellbook import spellbook_mcp
from mtg_mcp_server.providers.scryfall_bulk import scryfall_bulk_mcp
from mtg_mcp_server.workflows.server import workflow_mcp

mcp = FastMCP("MTG", instructions="Magic: The Gathering data and analytics server.")

# Sub-servers get namespaced: scryfall_search_cards, spellbook_find_combos, etc.
mcp.mount(scryfall_mcp, namespace="scryfall")
mcp.mount(spellbook_mcp, namespace="spellbook")
# Feature-flagged backends mounted conditionally (see server.py)
if settings.enable_bulk_data:
    mcp.mount(scryfall_bulk_mcp, namespace="bulk")

# Workflow tools mounted WITHOUT namespace for clean names
mcp.mount(workflow_mcp)
```

Mount options:
- **`namespace`**: Prefix all tools/resources to avoid collisions. `search_cards` → `scryfall_search_cards`.
- **`tool_names`**: Rename specific tools at mount time: `tool_names={"search": "find_cards"}`.
- **`as_proxy`**: When `True`, forwards requests to the mounted server over MCP protocol instead of importing directly. Useful for remote servers.

Mounting is dynamic — the parent forwards requests and reflects changes in the child immediately. Each mounted server's lifespan runs when the parent starts.

### Provider Sub-Server with Lifespan-Managed Clients

Service clients are expensive to create (httpx connection pools, rate limiters). Use FastMCP's
lifespan to create them once at startup. Store in a module-level variable and access via a
`_get_client()` helper.

> **Note:** `Depends()` / `ctx.lifespan_context` does NOT work when sub-servers are mounted on
> a parent — the lifespan context doesn't propagate through `mount()`. This is a known
> limitation of FastMCP 3.2.x. The module-level client pattern is the established workaround.

```python
# src/mtg_mcp_server/providers/scryfall.py
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import TOOL_ANNOTATIONS
from mtg_mcp_server.services.scryfall import ScryfallClient

_client: ScryfallClient | None = None

@lifespan
async def scryfall_lifespan(server: FastMCP):
    global _client
    settings = Settings()
    client = ScryfallClient(base_url=settings.scryfall_base_url)
    async with client:
        _client = client
        yield {}
    _client = None

scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan)

def _get_client() -> ScryfallClient:
    if _client is None:
        raise RuntimeError("ScryfallClient not initialized — server lifespan not running")
    return _client

@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def search_cards(query: str, page: int = 1) -> str:
    """Search for Magic cards using Scryfall syntax."""
    client = _get_client()
    result = await client.search_cards(query, page=page)
    ...
```

### Workflow Server with Multi-Client Lifespan

Workflow tools need multiple service clients. Use `AsyncExitStack` to manage them in a single
lifespan, respecting feature flags for optional backends.

```python
# src/mtg_mcp_server/workflows/server.py
from contextlib import AsyncExitStack
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from mtg_mcp_server.config import Settings

_scryfall: ScryfallClient | None = None
_spellbook: SpellbookClient | None = None
_seventeen_lands: SeventeenLandsClient | None = None
_edhrec: EDHRECClient | None = None
_bulk: ScryfallBulkClient | None = None
_rules: RulesService | None = None

@lifespan
async def workflow_lifespan(server: FastMCP):
    global _scryfall, _spellbook, _seventeen_lands, _edhrec, _bulk, _rules
    settings = Settings()
    async with AsyncExitStack() as stack:
        _scryfall = await stack.enter_async_context(
            ScryfallClient(base_url=settings.scryfall_base_url)
        )
        _spellbook = await stack.enter_async_context(
            SpellbookClient(base_url=settings.spellbook_base_url)
        )
        if settings.enable_17lands:
            _seventeen_lands = await stack.enter_async_context(
                SeventeenLandsClient(base_url=settings.seventeen_lands_base_url)
            )
        if settings.enable_edhrec:
            _edhrec = await stack.enter_async_context(
                EDHRECClient(base_url=settings.edhrec_base_url)
            )
        if settings.enable_bulk_data:
            client = ScryfallBulkClient(
                base_url=settings.scryfall_base_url,
                refresh_hours=settings.bulk_data_refresh_hours,
            )
            _bulk = await stack.enter_async_context(client)
            _bulk.start_background_refresh()
        if settings.enable_rules:
            _rules = RulesService(
                rules_url=settings.rules_url,
                refresh_hours=settings.rules_refresh_hours,
            )
            await _rules.ensure_loaded()
        yield {}
    _scryfall = _spellbook = _seventeen_lands = _edhrec = _bulk = _rules = None

workflow_mcp = FastMCP("Workflows", lifespan=workflow_lifespan)
```

> **Note:** `BaseClient.__aenter__` returns `Self` (not `BaseClient`) so that
> `AsyncExitStack.enter_async_context()` infers the correct subclass type.

Workflow tools wrap pure functions from the workflow modules. All tools return
`ToolResult` with both markdown (`content`) and structured data (`structured_content`):

```python
@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def commander_overview(commander_name: str, response_format: str = "detailed") -> ToolResult:
    """Comprehensive commander profile from all available sources."""
    from mtg_mcp_server.workflows.commander import commander_overview as impl
    result = await impl(
        commander_name,
        scryfall=_require_scryfall(),
        spellbook=_require_spellbook(),
        edhrec=_edhrec,  # None when disabled
        response_format=response_format,
    )
    return ToolResult(content=result.markdown, structured_content=result.data)
```

### Tool Annotations

All tools share a single `TOOL_ANNOTATIONS` constant from `mtg_mcp_server.providers`:

```python
# src/mtg_mcp_server/providers/__init__.py
from mcp.types import ToolAnnotations

TOOL_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
```

All tools are read-only and idempotent (they query external APIs, never mutate state).
Each provider imports and uses this constant rather than defining its own.

### Resources

Resources use `mtg://` URI templates, registered on both provider sub-servers and the workflow server (19 templates total):

```python
@scryfall_mcp.resource("mtg://card/{name}")
async def get_card(name: str) -> dict:
    """Card data as JSON by exact name."""
    ...

@scryfall_mcp.resource("mtg://set/{code}")
async def get_set(code: str) -> dict: ...
```

### Prompts (User-Invoked Templates)

```python
@workflow_mcp.prompt()
def evaluate_commander_swap(commander: str, adding: str, cutting: str) -> str:
    """Evaluate swapping a card in a Commander deck."""
    return f"""Evaluate this Commander deck change:
    Commander: {commander}
    Adding: {adding}
    Cutting: {cutting}
    
    1. Look up both cards with scryfall_card_details
    2. Check EDHREC synergy scores for both
    3. Check if the new card enables any combos
    4. Give a clear recommendation with reasoning"""
```

### Transport

```python
if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
    else:
        mcp.run(transport="stdio")
```

### Testing

Four test tiers (973 tests total, 89% coverage), each with a specific purpose. CI runs all tiers on PRs to main.

**Unit tests** (`tests/services/`, `tests/providers/`, `tests/utils/`, `tests/workflows/`): Test individual services, providers, utilities, and workflow functions in isolation. HTTP mocked via respx with fixture data. FastMCP servers tested using `fastmcp.Client` with the server instance as transport (in-memory, no network). Workflow tests use `AsyncMock` (not respx) since they test pure functions. `~2.5min`

**Integration tests** (`tests/integration/`): Test the full MCP pipeline end-to-end with all backends fixture-mocked via respx. Catches cross-component issues like tool registration, namespacing, and data flow through the orchestrator. Marked `@pytest.mark.integration`. `~2s`

**Live smoke tests** (`tests/live/`): Start a real server subprocess on an ephemeral port, connect via `Client("http://127.0.0.1:PORT/mcp")`, and hit real APIs. Catches real-world data issues that fixtures miss (e.g. Scryfall bulk data containing non-playable card layouts that overwrite real cards). Marked `@pytest.mark.live`, skipped by default. `~1-2min`

**Full suite** (`mise run check`): lint + typecheck + all tests except live. `~3min`
**Complete gate** (`mise run check:full`): Full suite + live smoke tests. `~4-5min`. CI runs this on PRs.

`Client.call_tool()` returns a `CallToolResult` — use `.content[0].text` to access the response
string. For testing error responses, pass `raise_on_error=False`.

```python
# tests/providers/test_scryfall_provider.py
import pytest
from fastmcp import Client
from mtg_mcp_server.providers.scryfall import scryfall_mcp

@pytest.fixture
async def client():
    async with Client(transport=scryfall_mcp) as c:
        yield c

async def test_search_cards(client):
    result = await client.call_tool("search_cards", {"query": "t:creature id:sultai"})
    text = result.content[0].text
    assert "Found" in text

async def test_card_not_found(client):
    result = await client.call_tool("card_details", {"name": "Nonexistent"}, raise_on_error=False)
    assert result.is_error
    assert "not found" in result.content[0].text.lower()
```

---

## 7. Service Layer Design

All API clients inherit from BaseClient:
- **httpx.AsyncClient** with configurable timeouts
- **Rate limiting** via `asyncio.Semaphore` + delay between requests
- **Retry logic** via tenacity (exponential backoff, retry on 429/5xx)
- **Structured logging** with bound context (service name, endpoint)

### Rate Limits

| Service | Limit | Strategy |
|---------|-------|----------|
| Scryfall | 10 req/sec | 100ms delay between requests |
| Commander Spellbook | ~3 req/sec | Backoff on 429 |
| 17Lands | 1 req/sec | Cache 1-6hr, exponential backoff |
| EDHREC | 0.5 req/sec | Cache 24hr, behind feature flag |
| Moxfield | 1 req/sec | Cache 4hr, behind feature flag |
| Spicerack | 1 req/sec | Cache 4hr, documented public API |

### Error Handling

- **Service layer**: Typed exceptions (`ScryfallNotFound`, `RateLimitExceeded`). Never MCP-formatted.
- **Provider layer**: Catches service exceptions → raises `ToolError` from `fastmcp.exceptions` with actionable messages. FastMCP automatically converts `ToolError` into an MCP error response (`is_error=True`). Other unhandled exceptions are also caught by FastMCP (use `mask_error_details=True` on the server to hide internals from clients).
- **Workflow layer**: Partial failure tolerance. If EDHREC is down, `commander_overview` returns what it can.

```python
from fastmcp.exceptions import ToolError

@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def card_details(name: str) -> str:
    """Get full details for a card by exact name."""
    client = _get_client()
    try:
        card = await client.get_card_by_name(name)
        ...
    except CardNotFoundError as exc:
        raise ToolError(f"Card not found: '{name}'. Check spelling or try fuzzy=true.") from exc
    except ScryfallError as exc:
        raise ToolError(f"Scryfall API error: {exc}") from exc
```

---

## 8. Logging Convention

```python
log = structlog.get_logger(service="scryfall")

async def search(self, query: str, limit: int) -> list[Card]:
    log.debug("search", query=query, limit=limit)
    result = await self._get("/cards/search", params={"q": query})
    log.debug("search.complete", count=len(result["data"]))
    return [Card.model_validate(c) for c in result["data"]]
```

All logging to stderr (stdout is MCP transport in stdio mode).

---

## 9. Configuration

```python
# src/mtg_mcp_server/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    transport: Literal["stdio", "http"] = "stdio"
    http_port: int = 8000
    log_level: str = "INFO"

    scryfall_base_url: str = "https://api.scryfall.com"
    scryfall_rate_limit_ms: int = 100
    spellbook_base_url: str = "https://backend.commanderspellbook.com"
    seventeen_lands_base_url: str = "https://www.17lands.com"
    edhrec_base_url: str = "https://json.edhrec.com"
    moxfield_base_url: str = "https://api2.moxfield.com"
    spicerack_base_url: str = "https://api.spicerack.gg"
    spicerack_api_key: str = ""  # Optional — sent as X-API-Key if non-empty

    enable_17lands: bool = True
    enable_edhrec: bool = True  # Behind flag — scrapes undocumented endpoints
    enable_moxfield: bool = True  # Behind flag — reverse-engineered API
    enable_spicerack: bool = True  # Documented public API
    enable_bulk_data: bool = True  # Scryfall Oracle Cards bulk download (~30MB)
    disable_cache: bool = False

    bulk_data_refresh_hours: int = 12

    # Comprehensive Rules
    rules_url: str = "https://media.wizards.com/2025/downloads/MagicCompRules%2020250404.txt"
    rules_refresh_hours: int = 168  # Weekly check (rules update ~4x/year)
    enable_rules: bool = True

    # Experimental
    enable_code_mode: bool = False  # FastMCP CodeMode transform

    model_config = {"env_prefix": "MTG_MCP_", "env_file": ".env", "extra": "ignore"}
```

---

## 10. Development Workflow

### TDD Cycle

1. **Capture fixture**: Hit the real API once, save JSON to `tests/fixtures/`
2. **Write failing service test**: Against fixture using respx
3. **Implement service method**: Make test pass
4. **Write failing provider test**: MCP tool registration and invocation (use `fastmcp.Client(transport=server)`, not `test_client()`)
5. **Implement provider tool**: Register with FastMCP, call the service
6. **Smoke test**: `mise run dev` → MCP Inspector → invoke tool

### Quality Gates

```bash
mise run check    # Runs lint + typecheck + test — all must pass
```

---

## 11. Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | FastMCP 3.2.x | Native composition, provider arch, OTEL, annotations, DI |
| Architecture | Single server, mounted sub-servers | Independent testability + single deployment |
| Transport | stdio default, HTTP optional | stdio for Claude Code/Desktop; HTTP for remote use |
| Type checker | ty (beta) | Astral stack, speed, FastMCP validates against it |
| HTTP mocking | respx | Decorator-based, clean API for async httpx mocking |
| Namespace convention | `scryfall_`, `spellbook_`, `draft_`, `edhrec_`, `moxfield_`, `bulk_`, `spicerack_` | FastMCP mount namespacing |
| Workflow tools | No namespace prefix | Clean names: `commander_overview`, `evaluate_upgrade` |
| Client lifecycle | Lifespan + module-level `_client` | `Depends()`/`lifespan_context` breaks through `mount()` — module-level is the workaround |
| Settings wiring | `Settings()` in each lifespan | Base URLs are configurable via `MTG_MCP_*` env vars, not hardcoded |
| Shared annotations | `TOOL_ANNOTATIONS` in `providers/__init__.py` | DRY — single constant shared by all provider tools |
| Error responses | ToolError (fastmcp.exceptions) | Cleaner than manual is_error; FastMCP handles conversion |
| Tool metadata | ToolAnnotations (mcp.types) + tags | Standard MCP annotations; tags categorize tools (commander, draft, pricing, beta) |
| EDHREC | Behind feature flag | Fragile scraping; disable if breaking |
| 17Lands | Aggressive caching | Rate limited; cache 1-6 hours |
| Multi-agent execution | Parallel worktree agents | Independent backends (Spellbook, 17Lands, EDHREC) follow same pattern — build simultaneously after Phase 1 establishes the template |
| Workflow architecture | Pure functions + wiring layer | Workflow modules export pure async functions (no MCP imports); `server.py` wraps them as tools. Avoids circular imports, enables AsyncMock testing |
| Multi-client lifespan | AsyncExitStack | Cleaner than nested `async with` for managing 5 service clients with feature flags |
| BaseClient.__aenter__ | Returns `Self` | Enables correct type inference through `AsyncExitStack.enter_async_context()` |
| Workflow testing | AsyncMock (not respx) | Workflows are pure functions — mock the service clients directly, no HTTP layer to test |
| draft_pack_pick backends | 17Lands only | 17Lands already provides name, color, rarity, all win rate metrics — no Scryfall calls needed |
| Service caching | cachetools TTLCache per method | Caches parsed Pydantic models (skips network + parsing). Per-method TTL granularity. Single asyncio loop = no locking needed |
| Scryfall bulk data | File-based service (not BaseClient) | Lazy download of Oracle Cards, in-memory dict for O(1) lookups. Returns full Card objects with prices, legalities, images. Behind feature flag |
| Bulk data integration | Workflow layer, not ScryfallClient | Preserves service independence — workflows can check bulk data before Scryfall API |
| Card resolver | Shared utility in `workflows/card_resolver.py` | Bulk-data-first resolution with Scryfall fallback. Avoids duplicating lookup logic across workflow modules |
| Progress reporting | `ctx.report_progress()` via callback | Workflow pure functions accept `on_progress` callback; `server.py` bridges to MCP `Context.report_progress()` |
| Tool tags | Tag constants in `providers/__init__.py` | Categorize tools by domain (commander, draft, pricing, beta). Shared constants avoid duplication |
| Prompts | Registered on workflow server | Guide multi-step analysis workflows. No namespace — clean invocation names |
| Resources | Registered on provider sub-servers + workflow server | `mtg://` URI templates for cached JSON data access. 18 templates across providers and workflow server |
| Structured output | `ToolResult` with `structured_content` | All tools return both markdown and a structured `data` dict for programmatic consumption |
| Response format | `response_format` parameter on all workflow tools | "detailed" (default) or "concise" — controls output verbosity without separate tools |
| Rules engine | Local file-based service (not BaseClient) | Downloads Comprehensive Rules text, parses into searchable indexes. Behind `MTG_MCP_ENABLE_RULES` flag |
| Rules integration | RulesService in workflow lifespan | Rules tools are workflow tools (not a separate provider) since they compose with bulk data for card examples |
| Utilities package | `utils/` directory | Shared helpers (color identity, decklist parsing, format rules, mana parsing, query parsing) extracted from workflows for reuse and testability |
| Attribution lines | Constants in `providers/__init__.py` | `ATTRIBUTION_*` strings appended to tool outputs for data source compliance |
| Response limiting | Per-tool `ResponseLimitingMiddleware(max_size=30_000)` for heavy tools + global `100_000` safety net | Primary size control via slim field sets and limit params; middleware is a safety net |
| Slim structured output | `utils/slim.py` dict builders | `slim_card()`, `slim_rating()`, `slim_edhrec_card()`, `slim_combo()` — essential fields only for `structured_content`, full data via resource URIs |
| CodeMode transform | Experimental, behind `enable_code_mode` flag | FastMCP CodeMode replaces individual tools with meta-tools for discovery and code execution at 40+ tools |
| MTGJSON replacement | Scryfall Oracle Cards bulk data | Scryfall bulk data includes prices, legalities, images, EDHREC rank — everything MTGJSON lacked |
| Smithery adapter | `smithery.py` | Smithery deployment support via adapter module |
| Moxfield provider | Behind feature flag, `ns=moxfield` | Reverse-engineered API — fragile, can break without notice |
| Spicerack provider | Behind feature flag, `ns=spicerack` | Documented public REST API for tournament results. Lowest-risk new data source. Optional `X-API-Key` for higher rate limits |

---

## 12. Multi-Agent Development Strategy

The architecture's independent backend design enables parallel development via multi-agent teams. Each backend (service + provider + tests) shares no state with others beyond `types.py` model definitions and `server.py` mount statements.

### Parallelization Map

```
Phase 0 (scaffold) — serial                                    ✓ COMPLETE
    │
Phase 1 (Scryfall) — serial, establishes the pattern           ✓ COMPLETE
    │
    ├── Agent A: Spellbook service + provider ──┐
    ├── Agent B: 17Lands service + provider     ├── Phase 2    ✓ COMPLETE
    └── Agent C: EDHREC service + provider ─────┘
                                                  │
    Scaffold (serial): workflow server + mount ────┤
    ├── Agent A: commander_overview + evaluate_upgrade ──┐
    ├── Agent B: draft_pack_pick                         ├── Phase 3  ✓ COMPLETE
    └── Agent C: suggest_cuts                      ──────┘
```

### Execution Pattern

Each parallel agent works in a **git worktree** for isolation:
1. Create worktree from the feature branch (not main)
2. Implement in exclusive files only — shared files scaffolded first
3. Run quality gates (`mise run check`) in the worktree
4. Cherry-pick implementation files back to feature branch (don't merge agents' shared file rewrites)

### Shared File Coordination

**Phase 2 lesson:** Agents that modify shared files (`types.py`, `server.py`) produce straightforward additive merge conflicts.

**Phase 3 lesson:** Each agent rewrote `server.py` for its own scope, dropping others' tools. The fix: scaffold shared files first (serial step), then give agents exclusive files only. Cherry-pick implementations, don't merge shared file rewrites.

Files that are agent-exclusive (no conflicts):
- `services/{backend}.py` — one per agent
- `providers/{backend}.py` — one per agent
- `workflows/{module}.py` — one per agent
- `tests/services/test_{backend}.py` — one per agent
- `tests/providers/test_{backend}_provider.py` — one per agent
- `tests/workflows/test_{module}.py` — one per agent
- `tests/fixtures/{backend}/` — one directory per agent
