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
    │   MTG Orchestrator  │  ← FastMCP("MTG")
    │                     │
    │  Workflow Tools:     │  ← Compose across backends
    │  • commander_overview│  • card_comparison
    │  • evaluate_upgrade  │  • budget_upgrade
    │  • draft_pack_pick   │  • deck_analysis
    │  • suggest_cuts      │  • set_overview
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
    │  │  MTGJSON     │────┼──► mtgjson.com (bulk file)
    │  │  ns=mtgjson  │    │    Offline card data, rate-limit-free search
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
| MCP framework | fastmcp | 3.1.x | PrefectHQ/fastmcp. Provider/Transform architecture |
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
│   └── mtg_mcp/
│       ├── __init__.py
│       ├── server.py               # Orchestrator: mounts all providers, runs transport
│       ├── config.py               # pydantic-settings: API URLs, rate limits, feature flags
│       ├── logging.py              # structlog configuration
│       ├── types.py                # Shared Pydantic models (Card, Combo, CardRating, etc.)
│       │
│       ├── services/               # HTTP API clients — NO MCP awareness
│       │   ├── __init__.py
│       │   ├── base.py             # BaseClient: httpx.AsyncClient + rate limiting + retries + structlog
│       │   ├── scryfall.py         # ScryfallClient
│       │   ├── spellbook.py        # SpellbookClient
│       │   ├── seventeen_lands.py  # SeventeenLandsClient
│       │   ├── edhrec.py           # EDHRECClient
│       │   ├── mtgjson.py          # MTGJSONClient (file-based, not BaseClient)
│       │   └── cache.py            # async_cached decorator, TTLCache helpers
│       │
│       ├── providers/              # FastMCP sub-servers (one per backend, independently runnable)
│       │   ├── __init__.py         # TOOL_ANNOTATIONS + tag constants
│       │   ├── scryfall.py         # scryfall_mcp = FastMCP("Scryfall")
│       │   ├── spellbook.py        # spellbook_mcp = FastMCP("Spellbook")
│       │   ├── seventeen_lands.py  # draft_mcp = FastMCP("17Lands")
│       │   ├── edhrec.py           # edhrec_mcp = FastMCP("EDHREC")
│       │   └── mtgjson.py          # mtgjson_mcp = FastMCP("MTGJSON")
│       │
│       └── workflows/              # Composed tools (registered on orchestrator, no namespace)
│           ├── __init__.py
│           ├── server.py           # workflow_mcp = FastMCP("Workflows"), multi-client lifespan + prompts
│           ├── commander.py        # commander_overview, evaluate_upgrade, card_comparison, budget_upgrade
│           ├── draft.py            # draft_pack_pick, set_overview
│           ├── deck.py             # suggest_cuts
│           ├── analysis.py         # deck_analysis
│           └── card_resolver.py    # MTGJSON-first card resolution with Scryfall fallback
│
├── tests/
│   ├── conftest.py                 # Shared fixtures, mock clients
│   ├── services/
│   │   ├── test_scryfall.py
│   │   └── ...
│   ├── providers/
│   │   ├── test_scryfall_provider.py
│   │   └── ...
│   ├── workflows/
│   │   ├── test_commander.py       # commander_overview, evaluate_upgrade, card_comparison, budget_upgrade
│   │   ├── test_draft.py           # draft_pack_pick, set_overview
│   │   ├── test_deck.py            # suggest_cuts
│   │   ├── test_analysis.py        # deck_analysis
│   │   └── test_workflow_server.py # Integration: tool registration + prompt registration
│   └── fixtures/                   # Real API responses, captured once
│       ├── scryfall/               # Card data, search results, rulings
│       ├── spellbook/              # Combos, bracket estimates, decklist combos
│       ├── seventeen_lands/        # Card ratings, color ratings
│       ├── edhrec/                 # Commander pages, card synergy
│       └── mtgjson/                # Sample AtomicCards.json.gz
│
├── scripts/
│   └── capture_fixtures.py
│
└── docs/
    ├── ARCHITECTURE.md
    ├── TOOL_DESIGN.md
    ├── SERVICE_CONTRACTS.md
    ├── CACHING_DESIGN.md
    ├── DATA_SOURCES.md
    └── PROJECT_PLAN.md
```

### Key Structural Decisions

**`services/` vs `providers/`**: Services are plain Python classes with async methods that call external APIs. Providers are FastMCP server instances that register tools backed by services. Services are reusable outside MCP and independently testable.

**`workflows/`**: Pure async functions that accept service clients as keyword parameters and return formatted strings. Registered as tools on a separate FastMCP server (`workflow_mcp`) mounted without a namespace. The function modules (`commander.py`, `draft.py`, `deck.py`, `analysis.py`) have zero MCP imports — `server.py` wraps them as tools and converts service exceptions to `ToolError`. This separation avoids circular imports and makes unit testing trivial with `AsyncMock`. `card_resolver.py` provides MTGJSON-first card resolution with Scryfall fallback, used by `analysis.py` for rate-limit-friendly bulk lookups.

**`types.py`**: Shared Pydantic models that services return and tools consume. Ensures type safety across the service → provider → workflow pipeline.

---

## 6. FastMCP 3.x Patterns

### Composition via Mount

```python
# src/mtg_mcp/server.py
from fastmcp import FastMCP
from mtg_mcp.providers.scryfall import scryfall_mcp
from mtg_mcp.providers.spellbook import spellbook_mcp
from mtg_mcp.providers.mtgjson import mtgjson_mcp
from mtg_mcp.workflows.server import workflow_mcp

mcp = FastMCP("MTG", instructions="Magic: The Gathering data and analytics server.")

# Sub-servers get namespaced: scryfall_search_cards, spellbook_find_combos, etc.
mcp.mount(scryfall_mcp, namespace="scryfall")
mcp.mount(spellbook_mcp, namespace="spellbook")
# Feature-flagged backends mounted conditionally (see server.py)
if settings.enable_mtgjson:
    mcp.mount(mtgjson_mcp, namespace="mtgjson")

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
> limitation of FastMCP 3.1.x. The module-level client pattern is the established workaround.

```python
# src/mtg_mcp/providers/scryfall.py
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from mtg_mcp.config import Settings
from mtg_mcp.providers import TOOL_ANNOTATIONS
from mtg_mcp.services.scryfall import ScryfallClient

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
# src/mtg_mcp/workflows/server.py
from contextlib import AsyncExitStack
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from mtg_mcp.config import Settings

_scryfall: ScryfallClient | None = None
_spellbook: SpellbookClient | None = None
_seventeen_lands: SeventeenLandsClient | None = None
_edhrec: EDHRECClient | None = None
_mtgjson: MTGJSONClient | None = None

@lifespan
async def workflow_lifespan(server: FastMCP):
    global _scryfall, _spellbook, _seventeen_lands, _edhrec, _mtgjson
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
        if settings.enable_mtgjson:
            _mtgjson = await stack.enter_async_context(
                MTGJSONClient(data_url=settings.mtgjson_data_url, ...)
            )
        yield {}
    _scryfall = _spellbook = _seventeen_lands = _edhrec = _mtgjson = None

workflow_mcp = FastMCP("Workflows", lifespan=workflow_lifespan)
```

> **Note:** `BaseClient.__aenter__` returns `Self` (not `BaseClient`) so that
> `AsyncExitStack.enter_async_context()` infers the correct subclass type.

Workflow tools wrap pure functions from the workflow modules:

```python
@workflow_mcp.tool(annotations=TOOL_ANNOTATIONS, tags=TAGS_COMMANDER)
async def commander_overview(commander_name: str) -> str:
    """Comprehensive commander profile from all available sources."""
    from mtg_mcp.workflows.commander import commander_overview as impl
    return await impl(
        commander_name,
        scryfall=_require_scryfall(),
        spellbook=_require_spellbook(),
        edhrec=_edhrec,  # None when disabled
    )
```

### Tool Annotations

All tools share a single `TOOL_ANNOTATIONS` constant from `mtg_mcp.providers`:

```python
# src/mtg_mcp/providers/__init__.py
from mcp.types import ToolAnnotations

TOOL_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
```

All tools are read-only and idempotent (they query external APIs, never mutate state).
Each provider imports and uses this constant rather than defining its own.

### Resources

```python
@scryfall_mcp.resource("mtg://sets")
async def list_sets() -> list[dict]:
    """All Magic sets with codes, names, release dates."""
    ...

@scryfall_mcp.resource("mtg://sets/{code}")
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

FastMCP servers are tested using `fastmcp.Client` with the server instance as the transport.
This creates an in-memory connection — no network, no stdio.

`Client.call_tool()` returns a `CallToolResult` — use `.content[0].text` to access the response
string. For testing error responses, pass `raise_on_error=False`.

```python
# tests/providers/test_scryfall_provider.py
import pytest
from fastmcp import Client
from mtg_mcp.providers.scryfall import scryfall_mcp

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
# src/mtg_mcp/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    scryfall_base_url: str = "https://api.scryfall.com"
    scryfall_rate_limit_ms: int = 100
    spellbook_base_url: str = "https://backend.commanderspellbook.com"
    seventeen_lands_base_url: str = "https://www.17lands.com"
    edhrec_base_url: str = "https://json.edhrec.com"
    enable_edhrec: bool = True
    enable_17lands: bool = True
    cache_ttl_seconds: int = 3600

    model_config = {"env_prefix": "MTG_MCP_"}
```

---

## 10. Development Workflow

See @docs/PROJECT_PLAN.md for the phased implementation sequence.

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
| Framework | FastMCP 3.1.x | Native composition, provider arch, OTEL, annotations, DI |
| Architecture | Single server, mounted sub-servers | Independent testability + single deployment |
| Transport | stdio default, HTTP optional | stdio for Claude Code/Desktop; HTTP for remote use |
| Type checker | ty (beta) | Astral stack, speed, FastMCP validates against it |
| HTTP mocking | respx | Decorator-based, clean API for async httpx mocking |
| Namespace convention | `scryfall_`, `spellbook_`, `draft_`, `edhrec_`, `mtgjson_` | FastMCP mount namespacing |
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
| MTGJSON | Bulk file service (not BaseClient) | File-based, not HTTP API — lazy download, in-memory dict for O(1) lookups. Behind feature flag |
| MTGJSON integration | Workflow layer, not ScryfallClient | Preserves service independence — workflows can check MTGJSON before Scryfall |
| Card resolver | Shared utility in `workflows/card_resolver.py` | MTGJSON-first resolution with Scryfall fallback. Avoids duplicating lookup logic across workflow modules |
| Progress reporting | `ctx.report_progress()` via callback | Workflow pure functions accept `on_progress` callback; `server.py` bridges to MCP `Context.report_progress()` |
| Tool tags | Tag constants in `providers/__init__.py` | Categorize tools by domain (commander, draft, pricing, beta). Shared constants avoid duplication |
| Prompts | Registered on workflow server | Guide multi-step analysis workflows. No namespace — clean invocation names |
| Resources | Registered on provider sub-servers | `mtg://` URI templates for cached JSON data access. Namespaced with providers |

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
