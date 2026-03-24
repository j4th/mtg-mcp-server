# MTG MCP Server

Unified MCP server providing Magic: The Gathering data to AI assistants. Composes Scryfall, Commander Spellbook, 17Lands, and EDHREC into one server using FastMCP 3.x's provider/mount architecture.

## Stack

Python 3.12+ · FastMCP 3.1.x · httpx · Pydantic v2 · structlog
Tooling: mise · uv · ruff · ty · pytest · respx

Prerequisites: [mise](https://mise.jdx.dev) must be installed. Then `mise install` gets everything else.

## Commands

```bash
mise run setup          # Install deps, create venv
mise run check          # Lint + format + typecheck + test (the full gate)
mise run test           # pytest with coverage
mise run test:quick     # pytest --testmon (only tests affected by changes)
mise run lint           # ruff check + ruff format --check
mise run typecheck      # ty check
mise run dev            # fastmcp dev inspector (MCP Inspector on :6274)
mise run serve          # Run server via stdio
mise run fix            # Auto-fix lint and format issues
```

### Testing strategy

- **Iterating**: Use `mise run test:quick` (pytest-testmon) after edits for fast feedback — only runs tests affected by your changes.
- **Quality gate**: Use `mise run check` before commits and PRs — full lint + typecheck + test suite with coverage.

## Architecture

See @docs/ARCHITECTURE.md for full details.

- **`src/mtg_mcp_server/services/`** — Pure async API clients. No MCP awareness. Return Pydantic models.
- **`src/mtg_mcp_server/providers/`** — FastMCP sub-servers. Each independently runnable. Register tools that call services.
- **`src/mtg_mcp_server/workflows/`** — Composed tools calling multiple services. Mounted without namespace.
- **`src/mtg_mcp_server/server.py`** — Orchestrator. Mounts providers with namespaces: `scryfall_`, `spellbook_`, `draft_`, `edhrec_`, `mtgjson_`.

## Conventions

- TDD: write failing test first, then implement. Tests use respx to mock httpx. Never hit live APIs.
- Fixtures in `tests/fixtures/` — captured JSON from real API responses.
- Modern typing: `list[str]` not `List[str]`, `str | None` not `Optional[str]`. Zero ty errors.
- structlog everywhere. Bound logger per service. Log to stderr (stdout is MCP transport in stdio mode).
- Services raise typed exceptions. Provider tools catch them and raise `ToolError` (from `fastmcp.exceptions`) with actionable messages. FastMCP handles `is_error` automatically.
- Workflows are pure async functions (no MCP imports). `workflows/server.py` wraps them as tools and converts exceptions to `ToolError`.
- Workflows handle partial failures — if one backend is down, return what you can from the rest.
- Workflow tests use `unittest.mock.AsyncMock` (not respx) since they test pure functions, not HTTP.
- EDHREC is behind a feature flag (`MTG_MCP_ENABLE_EDHREC`). It scrapes undocumented endpoints and will break.

## PR Review Workflow

When PR review comments come in:

1. Fetch comments via `gh api /repos/{owner}/{repo}/pulls/{number}/comments`
2. Assess each — state what you'll fix or why you'll defer
3. Reply to each via `gh api .../comments/{id}/replies` with the assessment
4. Make all code fixes
5. Run `mise run check`
6. Commit referencing the PR, push
7. Resolve threads via GraphQL `resolveReviewThread` mutation (get thread IDs from `repository.pullRequest.reviewThreads`)

## Gotchas

- FastMCP 3.x import: `from fastmcp import FastMCP` (NOT `from mcp.server.fastmcp`).
- FastMCP 3.x CLI: `fastmcp dev inspector <file>` (NOT `fastmcp dev <file>` — the `inspector` subcommand is required).
- Tool annotations: use shared `TOOL_ANNOTATIONS` from `mtg_mcp_server.providers` (NOT inline `ToolAnnotations()` per tool).
- Error responses: raise `ToolError` from `fastmcp.exceptions`, don't manually construct `is_error` responses. Always use `from exc` in except blocks (B904).
- Service clients: managed via lifespan + module-level `_client` variable (NOT `Depends()`/`ctx.lifespan_context` — these don't propagate through `mount()`).
- Service clients are constructed with `Settings()` in the lifespan so `MTG_MCP_*_BASE_URL` env vars are honored.
- Workflow lifespan uses `AsyncExitStack` to manage multiple clients. Provider lifespans use `async with client:` directly.
- `BaseClient.__aenter__` returns `Self` (not `BaseClient`) so type-checkers infer the correct subclass through `AsyncExitStack.enter_async_context()`.
- Pydantic v2: `.model_validate()`, not `.parse_obj()`.
- Scryfall requires `User-Agent` and `Accept` headers on every request.
- 17Lands rate-limits aggressively. 1 req/sec max. Cache everything.
- Optional numeric fields: use `is not None` checks, not truthiness — `0` and `0.0` are valid values.
- Don't use `Any` type — use `Unknown` or proper types.
- When compacting, preserve the list of which services/providers are implemented vs stubbed.
- Service caching: all service methods use `@async_cached` with class-level `TTLCache`. Tests must clear caches (autouse `_clear_caches` fixture in conftest.py).
- MTGJSON is behind `MTG_MCP_ENABLE_MTGJSON` feature flag. It's a file-based service (not BaseClient). Lazy-loads on first access.

## Implementation Status

- **Phase 0** (scaffold): Complete
- **Phase 1** (Scryfall): Complete — 4 tools (search_cards, card_details, card_price, card_rulings)
- **Phase 2** (Spellbook + 17Lands + EDHREC): Complete — 9 tools across 3 backends
- **Phase 3** (Workflow tools): Complete — 4 workflow tools (commander_overview, evaluate_upgrade, draft_pack_pick, suggest_cuts)
- **Phase 4** (Caching + MTGJSON): Complete — TTL caching on all 12 service methods, MTGJSON bulk card provider (2 tools: card_lookup, card_search)
- **Phase 5** (Analysis + Comparison workflows): Complete — 4 new workflow tools (card_comparison, budget_upgrade, deck_analysis, set_overview), 4 prompts, 6 resources. Card resolver utility for MTGJSON-first lookups with Scryfall fallback. Tool tagging via `tags` parameter. 374 tests, 92% coverage.

## Environment

Copy `.env.example` to `.env` to configure. All values have sensible defaults — no credentials required (all APIs are public). See `MTG_MCP_` prefix for all env vars.

## Key References

- @docs/ARCHITECTURE.md — Full architecture, stack decisions, FastMCP patterns, mise config
- @docs/TOOL_DESIGN.md — Tool naming, inputs/outputs, prompts, resources
- @docs/SERVICE_CONTRACTS.md — API endpoints, rate limits, response shapes, caching
- @docs/DATA_SOURCES.md — All data sources evaluated, auth methods, stability, access patterns
- @docs/PROJECT_PLAN.md — Phased implementation plan
