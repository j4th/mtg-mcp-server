# MTG MCP Server

Unified MCP server providing Magic: The Gathering data to AI assistants. Composes Scryfall, Commander Spellbook, 17Lands, and EDHREC into one server using FastMCP 3.x's provider/mount architecture.

## Stack

Python 3.12+ · FastMCP 3.1.x · httpx · Pydantic v2 · structlog
Tooling: mise · uv · ruff · ty · pytest · respx

## Commands

```bash
mise run setup          # Install deps, create venv
mise run check          # Lint + format + typecheck + test (the full gate)
mise run test           # pytest with coverage
mise run lint           # ruff check + ruff format --check
mise run typecheck      # ty check
mise run dev            # fastmcp dev src/mtg_mcp/server.py (MCP Inspector)
mise run serve          # Run server via stdio
mise run fix            # Auto-fix lint and format issues
```

## Architecture

See @docs/ARCHITECTURE.md for full details.

- **`src/mtg_mcp/services/`** — Pure async API clients. No MCP awareness. Return Pydantic models.
- **`src/mtg_mcp/providers/`** — FastMCP sub-servers. Each independently runnable. Register tools that call services.
- **`src/mtg_mcp/workflows/`** — Composed tools calling multiple services. Mounted without namespace.
- **`src/mtg_mcp/server.py`** — Orchestrator. Mounts providers with namespaces: `scryfall_`, `spellbook_`, `draft_`, `edhrec_`.

## Conventions

- TDD: write failing test first, then implement. Tests use respx to mock httpx. Never hit live APIs.
- Fixtures in `tests/fixtures/` — captured JSON from real API responses.
- Modern typing: `list[str]` not `List[str]`, `str | None` not `Optional[str]`. Zero ty errors.
- structlog everywhere. Bound logger per service. Log to stderr (stdout is MCP transport in stdio mode).
- Services raise typed exceptions. Provider tools catch them and raise `ToolError` (from `fastmcp.exceptions`) with actionable messages. FastMCP handles `is_error` automatically.
- Workflows handle partial failures — if one backend is down, return what you can from the rest.
- EDHREC is behind a feature flag (`MTG_MCP_ENABLE_EDHREC`). It scrapes undocumented endpoints and will break.

## Gotchas

- FastMCP 3.x import: `from fastmcp import FastMCP` (NOT `from mcp.server.fastmcp`).
- Tool annotations: `from mcp.types import ToolAnnotations`, not `tags={}` (tags is not a supported parameter).
- Error responses: raise `ToolError` from `fastmcp.exceptions`, don't manually construct `is_error` responses.
- Service clients: managed via lifespan + `Depends()` injection, not instantiated per tool call.
- Pydantic v2: `.model_validate()`, not `.parse_obj()`.
- Scryfall requires `User-Agent` and `Accept` headers on every request.
- 17Lands rate-limits aggressively. 1 req/sec max. Cache everything.
- Don't use `Any` type — use `Unknown` or proper types.
- Don't build workflow tools before their backend services work.
- When compacting, preserve the list of which services/providers are implemented vs stubbed.

## Key References

- @docs/ARCHITECTURE.md — Full architecture, stack decisions, FastMCP patterns, mise config
- @docs/TOOL_DESIGN.md — Tool naming, inputs/outputs, prompts, resources
- @docs/SERVICE_CONTRACTS.md — API endpoints, rate limits, response shapes, caching
- @docs/DATA_SOURCES.md — All data sources evaluated, auth methods, stability, access patterns
- @docs/PROJECT_PLAN.md — Phased implementation plan
