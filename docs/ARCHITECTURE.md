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
    │  • commander_overview│
    │  • evaluate_upgrade  │
    │  • draft_pack_pick   │
    │  • suggest_cuts      │
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
│       │   └── edhrec.py           # EDHRECClient
│       │
│       ├── providers/              # FastMCP sub-servers (one per backend, independently runnable)
│       │   ├── __init__.py
│       │   ├── scryfall.py         # scryfall_mcp = FastMCP("Scryfall")
│       │   ├── spellbook.py        # spellbook_mcp = FastMCP("Spellbook")
│       │   ├── seventeen_lands.py  # draft_mcp = FastMCP("17Lands")
│       │   └── edhrec.py           # edhrec_mcp = FastMCP("EDHREC")
│       │
│       └── workflows/              # Composed tools (registered on orchestrator, no namespace)
│           ├── __init__.py
│           ├── server.py           # workflow_mcp = FastMCP("Workflows")
│           ├── commander.py        # commander_overview, evaluate_upgrade, suggest_cuts
│           ├── draft.py            # draft_pack_analysis, sealed_pool_analysis
│           └── deck.py             # deck_audit, find_upgrades
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
│   │   └── test_commander_workflows.py
│   └── fixtures/                   # Real API responses, captured once
│       ├── scryfall/
│       │   ├── card_muldrotha.json
│       │   └── search_sultai_commander.json
│       ├── spellbook/
│       │   └── combos_muldrotha.json
│       ├── seventeen_lands/
│       │   └── card_ratings_lwe.json
│       └── edhrec/
│           └── commander_muldrotha.json
│
├── scripts/
│   └── capture_fixtures.py
│
└── docs/
    ├── ARCHITECTURE.md
    ├── TOOL_DESIGN.md
    ├── SERVICE_CONTRACTS.md
    └── PROJECT_PLAN.md
```

### Key Structural Decisions

**`services/` vs `providers/`**: Services are plain Python classes with async methods that call external APIs. Providers are FastMCP server instances that register tools backed by services. Services are reusable outside MCP and independently testable.

**`workflows/`**: Functions registered as tools on a separate FastMCP server mounted without a namespace. They import and call service classes directly (not through MCP tool calls), avoiding round-trip overhead.

**`types.py`**: Shared Pydantic models that services return and tools consume. Ensures type safety across the service → provider → workflow pipeline.

---

## 6. FastMCP 3.x Patterns

### Composition via Mount

```python
# src/mtg_mcp/server.py
from fastmcp import FastMCP
from mtg_mcp.providers.scryfall import scryfall_mcp
from mtg_mcp.providers.spellbook import spellbook_mcp
from mtg_mcp.workflows.server import workflow_mcp

mcp = FastMCP("MTG", instructions="Magic: The Gathering data and analytics server.")

# Sub-servers get namespaced: scryfall_search_cards, spellbook_find_combos, etc.
mcp.mount(scryfall_mcp, namespace="scryfall")
mcp.mount(spellbook_mcp, namespace="spellbook")

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
lifespan to create them once at startup and `Depends()` to inject them into tools. This keeps
tools thin and avoids per-call overhead.

```python
# src/mtg_mcp/providers/scryfall.py
from fastmcp import FastMCP, Context
from fastmcp.server.lifespan import lifespan
from fastmcp.dependencies import Depends
from mcp.types import ToolAnnotations
from mtg_mcp.services.scryfall import ScryfallClient

@lifespan
async def scryfall_lifespan(server):
    async with ScryfallClient() as client:
        yield {"scryfall_client": client}

scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan)

def get_client(ctx: Context) -> ScryfallClient:
    return ctx.lifespan_context["scryfall_client"]

@scryfall_mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
)
async def search_cards(
    query: str,
    limit: int = 20,
    client: ScryfallClient = Depends(get_client),
) -> list[dict]:
    """Search for Magic cards using Scryfall syntax."""
    return await client.search(query, limit=limit)
```

### Tool Annotations

Use `ToolAnnotations` from `mcp.types` to provide metadata hints to clients. All our tools
are read-only and idempotent (they query external APIs, never mutate state).

```python
from mcp.types import ToolAnnotations

@scryfall_mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
)
async def card_price(name: str, client: ScryfallClient = Depends(get_client)) -> dict: ...

@draft_mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
)
async def card_rating(
    card_name: str, set_code: str, client: SeventeenLandsClient = Depends(get_client)
) -> dict: ...
```

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

@scryfall_mcp.tool(...)
async def card_details(name: str, client: ScryfallClient = Depends(get_client)) -> str:
    """Get full details for a card by exact name."""
    try:
        card = await client.get_card_by_name(name)
        return card.format_details()
    except CardNotFoundError:
        raise ToolError(f"Card not found: '{name}'. Check spelling or try a fuzzy search.")
    except ScryfallError as e:
        raise ToolError(f"Scryfall API error: {e}")
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
4. **Write failing provider test**: MCP tool registration and invocation
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
| Namespace convention | `scryfall_`, `spellbook_`, `draft_`, `edhrec_` | FastMCP mount namespacing |
| Workflow tools | No namespace prefix | Clean names: `commander_overview`, `evaluate_upgrade` |
| Client lifecycle | Lifespan + Depends() DI | Shared httpx pool per provider; avoids per-call overhead |
| Error responses | ToolError (fastmcp.exceptions) | Cleaner than manual is_error; FastMCP handles conversion |
| Tool metadata | ToolAnnotations (mcp.types) | Standard MCP annotations; tags param not supported |
| EDHREC | Behind feature flag | Fragile scraping; disable if breaking |
| 17Lands | Aggressive caching | Rate limited; cache 1-6 hours |
