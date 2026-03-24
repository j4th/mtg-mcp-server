# MTG MCP Server — Implementation Plan

This is the ordered build plan. Each phase produces a working, testable increment. Do not skip phases or build ahead.

## Phase 0: Project Scaffold [COMPLETE]

**Goal:** Empty project that builds, lints, type-checks, and runs an empty test suite.

### Steps

1. Project initialization is already done — `pyproject.toml` and `mise.toml` are configured. Phase 0 starts at creating the directory structure and source modules.

2. Already configured. See `pyproject.toml` for current settings.

3. Create the directory structure per ARCHITECTURE.md (all `__init__.py` files, empty modules).

4. Create `src/mtg_mcp_server/logging.py`:
   - Configure structlog with JSON output to stderr (MCP stdio servers must not log to stdout)
   - Provide `get_logger(service: str)` that returns a bound logger

5. Create `src/mtg_mcp_server/config.py`:
   - `Settings` class via pydantic-settings
   - Fields: `scryfall_base_url`, `spellbook_base_url`, `seventeen_lands_base_url`, `edhrec_base_url`, `log_level`, `transport` (enum: stdio/http), `http_port`, `enable_edhrec: bool`, `enable_17lands: bool`, `cache_ttl_seconds: int`
   - Load from env vars with `MTG_MCP_` prefix and/or `.env` file

6. Create `src/mtg_mcp_server/server.py`:
   - Build the orchestrator: `mcp = FastMCP("MTG")`
   - No backends mounted yet
   - Register a single `ping` tool that returns `"pong"` (smoke test)
   - Entry point: `mtg_mcp_server.server:main`. Parse `--transport` flag, run stdio or HTTP accordingly

7. Create `tests/conftest.py` with basic fixtures.

8. Create `tests/test_smoke.py`:
   - Test that the server can be instantiated
   - Test that the `ping` tool is registered

9. Verify:
   ```bash
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   uv run ty check src/
   uv run pytest --cov
   ```

**Done when:** All commands pass. The MCP server starts via stdio and responds to tools/list with the `ping` tool.

**Completed:** Phase 0 was done as project initialization before Phase 1 began.

---

## Phase 1: Scryfall Service + Server [COMPLETE]

**Goal:** Working Scryfall backend with real card search, lookup, and pricing tools.

### 1a: Service Layer (TDD)

1. Capture fixtures:
   - Hit `api.scryfall.com/cards/named?exact=Muldrotha, the Gravetide` and save response to `tests/fixtures/scryfall/card_muldrotha.json`
   - Hit `api.scryfall.com/cards/search?q=commander:sultai+type:creature` (small query) → `search_sultai_commander.json`
   - Hit `api.scryfall.com/cards/named?exact=Sol Ring` → `card_sol_ring.json`
   - Hit a nonexistent card to capture 404 response → `card_not_found.json`

2. Create `src/mtg_mcp_server/services/base.py`:
   - `BaseClient` class wrapping `httpx.AsyncClient`
   - Constructor takes `base_url`, `rate_limit` (requests/sec), `user_agent`
   - Async context manager (`async with`)
   - Rate limiting via `asyncio.Semaphore` + `asyncio.sleep`
   - Retry decorator factory using tenacity: retry on 429/5xx, respect `Retry-After` header
   - structlog bound logger with `service=<name>`
   - Debug log on every request: method, url, status, elapsed_ms
   - Error log on non-2xx with response body (truncated)

3. Create `src/mtg_mcp_server/types.py`:
   - `Card` model: name, mana_cost, type_line, oracle_text, colors, color_identity, set_code, collector_number, prices (usd, usd_foil, eur), image_uris, legalities, edhrec_rank, keywords, power, toughness, rarity, scryfall_uri
   - `CardSearchResult` model: total_cards, has_more, data (list[Card])
   - Map from Scryfall's JSON response shape to these models

4. Create `src/mtg_mcp_server/services/scryfall.py`:
   - `ScryfallClient(BaseClient)` with `base_url = "https://api.scryfall.com"`, `user_agent = DEFAULT_USER_AGENT`, `rate_limit = 10`
   - Methods:
     - `async def search_cards(query: str, page: int = 1) -> CardSearchResult`
     - `async def get_card_by_name(name: str, fuzzy: bool = False) -> Card`
     - `async def get_card_by_id(scryfall_id: str) -> Card`
     - `async def get_rulings(scryfall_id: str) -> list[Ruling]`
   - Custom exceptions: `CardNotFoundError`, `ScryfallError`

5. Write tests in `tests/services/test_scryfall.py`:
   - Test `get_card_by_name` returns a Card model from fixture
   - Test `get_card_by_name` raises `CardNotFoundError` on 404 fixture
   - Test `search_cards` returns `CardSearchResult` with pagination
   - Test rate limiting behavior (mock timing)
   - All tests use `respx` to mock HTTP responses with fixture data

### 1b: Server Layer

6. Create `src/mtg_mcp_server/providers/scryfall.py`:
   - Lifespan: create `ScryfallClient` once at startup via `@lifespan` decorator, store in module-level `_client`
   - Construct client with `Settings().scryfall_base_url` so env overrides work
   - `scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan)`
   - Helper: `_get_client()` returns `_client` or raises `RuntimeError`
   - Tools (each calls `_get_client()` at the start):
     - `search_cards(query: str, page: int = 1) -> str` — Scryfall search syntax, returns formatted results
     - `card_details(name: str) -> str` — Exact card lookup, returns full details
     - `card_price(name: str) -> str` — Price lookup (USD, EUR, foil)
     - `card_rulings(name: str) -> str` — Official rulings for a card
   - Annotations: all tools get `ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)`
   - Error handling: catch service exceptions → raise `ToolError` from `fastmcp.exceptions` with actionable messages

7. Write tests in `tests/providers/test_scryfall_provider.py`:
   - Use `fastmcp.Client` with the server as transport:
   ```python
   from fastmcp import Client
   async with Client(transport=scryfall_mcp) as client:
       result = await client.call_tool("search_cards", {"query": "..."})
   ```
   - Test each tool returns expected content
   - Test error tool responses for missing cards

### 1c: Mount on Orchestrator

8. Update `src/mtg_mcp_server/server.py`:
   - Mount `scryfall_mcp` with `namespace="scryfall"`
   - Remove the `ping` tool (or keep as health check)

9. Integration test: `tests/test_orchestrator.py`:
   - Instantiate the full orchestrator
   - Verify `scryfall_search_cards` appears in tools/list
   - Call `scryfall_card_details` with mocked HTTP → get card data back

10. Manual smoke test:
    ```bash
    mise run dev  # MCP Inspector
    ```

**Done when:** You can search for cards and get real data back through the MCP protocol.

**Completed:** Scryfall service (4 methods), provider (4 tools), 14 tests. Established the module-level client pattern (not `Depends()` DI) after discovering `lifespan_context` doesn't propagate through `mount()`.

**Key learnings from Phase 1:**
- `Depends(get_client)` + `ctx.lifespan_context` breaks when sub-server is mounted — use module-level `_client` set by `@lifespan`
- `from __future__ import annotations` breaks FastMCP's auto-detection of `Context` parameters
- `Client.call_tool()` returns `CallToolResult` — access via `.content[0].text`, not subscriptable
- For error tests, use `raise_on_error=False` on `call_tool()`
- All `raise ToolError(...)` inside except blocks need `from exc` (B904 lint rule)

---

## Phase 2: Parallel Backend Build (Spellbook + 17Lands + EDHREC) [COMPLETE]

**Goal:** All three remaining backends built simultaneously by parallel agents, following the pattern established in Phase 1.

**Prerequisites:** Phase 1 complete. The service→provider→mount pattern is proven and can be replicated.

**Parallel execution plan:**

| Agent | Backend | Namespace | Endpoints |
|-------|---------|-----------|-----------|
| Agent A | Commander Spellbook | `spellbook` | `/variants/`, `/find-my-combos`, `/estimate-bracket` |
| Agent B | 17Lands | `draft` | `/card_ratings/data`, `/color_ratings/data` |
| Agent C | EDHREC | `edhrec` | `/pages/commanders/{slug}.json`, `/pages/cards/{slug}.json` |

Each agent follows the same sequence independently:
1. Capture fixtures from live API → `tests/fixtures/{service}/`
2. Add Pydantic models to `types.py` (coordinate to avoid conflicts — each agent adds its own models)
3. Create service client in `services/{service}.py` (TDD: test first, implement second)
4. Create provider in `providers/{service}.py` with lifespan + tools
5. Write provider tests in `tests/providers/test_{service}_provider.py`
6. Mount on orchestrator in `server.py` with namespace

### Agent A: Spellbook

1. Research the Spellbook API:
   - Base URL: `https://backend.commanderspellbook.com`
   - Swagger docs: `/schema/swagger/`
   - Key endpoints: `/variants/` (combo search, uses `limit`/`offset` pagination), `/find-my-combos` (decklist combo analysis), `/estimate-bracket` (bracket estimation)
   - Response uses camelCase, zone codes are single letters (B/H/G/E/L/C), bracket tags are single letters
   - Capture fixtures for Muldrotha combos, Gitrog combos

2. Create `SpellbookClient` in `services/spellbook.py`:
   - `find_combos(card_name: str, color_identity: str | None) -> list[Combo]`
   - `get_combo(combo_id: str) -> Combo`
   - `find_decklist_combos(commanders: list[str], decklist: list[str]) -> DecklistCombos`
   - `estimate_bracket(commanders: list[str], decklist: list[str]) -> BracketEstimate`

3. Create `Combo`, `DecklistCombos`, and `BracketEstimate` Pydantic models in `types.py`

4. Create `spellbook_mcp` in `providers/spellbook.py`:
   - Tools: `find_combos`, `combo_details`, `find_decklist_combos`, `estimate_bracket`

5. Mount on orchestrator with `namespace="spellbook"`

6. Write tests at every layer (service, provider, integration)

### Agent B: 17Lands

1. Research the 17Lands API:
   - Card ratings: `GET /card_ratings/data?expansion={SET}&event_type={FORMAT}`
   - Color ratings: `GET /color_ratings/data?expansion={SET}&event_type={FORMAT}&start_date={DATE}&end_date={DATE}` (start_date and end_date are REQUIRED)
   - Note: `event_type` is the correct parameter name (not `format`)
   - Capture fixtures for a recent set

2. Create `SeventeenLandsClient`:
   - `card_ratings(set_code: str, format: str = "PremierDraft") -> list[DraftCardRating]`
   - `color_ratings(set_code: str, start_date: str, end_date: str, format: str = "PremierDraft") -> list[ArchetypeRating]`

3. Create server, mount as `namespace="draft"`

4. Write tests

### Agent C: EDHREC

**Goal:** Commander staples and synergy scores. This is the scraping-based backend — expect fragility.

1. Research EDHREC's internal JSON endpoints (pyedhrec uses these):
   - Commander page data: `https://json.edhrec.com/pages/commanders/<name>.json`
   - Card data: `https://json.edhrec.com/pages/cards/<name>.json`
   - Capture fixtures

2. Create `EDHRECClient`:
   - `commander_top_cards(commander_name: str) -> list[EDHRECCard]`
   - `card_synergy(card_name: str, commander_name: str) -> SynergyData`

3. Create server, mount as `namespace="edhrec"`

4. Write tests (fixture-only — never hit EDHREC in tests)

### Coordination notes for parallel agents

- Each agent works in a git worktree to avoid conflicts
- `types.py` additions: each agent adds models for their service only. Merge conflicts in this file are expected and straightforward to resolve.
- `server.py` mount statements: each agent adds their mount line. Resolve on merge.
- Integration tests may need adjustment after all three are merged.

**Done when:** All three backends are mounted. Consumer sees `scryfall_*`, `spellbook_*`, `draft_*`, and `edhrec_*` tools.

**Completed:** All 3 agents ran in parallel worktrees, merged back to main. Post-merge cleanup deduplicated `TOOL_ANNOTATIONS`, extracted helpers, pre-compiled regexes, removed dead `ComboSearchResult` model, wired `Settings` into all provider lifespans, and fixed truthiness checks on optional float fields. Final state: 104 tests, 88% coverage, 13 tools.

**Key learnings from Phase 2:**
- Worktree agents work well for independent backends — merge conflicts in `types.py`/`server.py` are straightforward (additive)
- Provider lifespans must construct clients from `Settings()` so env var overrides work
- Optional numeric fields (win rates, ranks) need `is not None`, not truthiness — `0.0` is valid data
- Shared constants (`TOOL_ANNOTATIONS`) belong in `providers/__init__.py` but must NOT import provider sub-modules (circular import risk)

---

## Phase 3: Workflow Tools [COMPLETE]

**Goal:** Composed workflow tools that cross-reference multiple backends.

**Prerequisites:** At minimum Scryfall + Spellbook backends working. Enhanced versions need all backends.

**Parallel execution plan:**

All 4 workflows built simultaneously by 3 parallel agents in git worktrees, after a serial scaffold step.

### Steps

1. **Scaffold (serial):** Create `workflows/server.py` with `AsyncExitStack` lifespan managing up to 4 service clients (Scryfall, Spellbook, 17Lands, EDHREC) respecting feature flags. Mount on orchestrator without namespace. Register all 4 tool stubs that import from pure-function modules.

2. **Parallel implementation (3 agents in worktrees):**

| Agent | Workflow(s) | Files |
|-------|-------------|-------|
| Agent A | `commander_overview`, `evaluate_upgrade` | `workflows/commander.py`, `tests/workflows/test_commander.py` |
| Agent B | `draft_pack_pick` | `workflows/draft.py`, `tests/workflows/test_draft.py` |
| Agent C | `suggest_cuts` | `workflows/deck.py`, `tests/workflows/test_deck.py` |

3. **Merge and integration (serial):** Copy implementation files from worktrees (agents rewrote `server.py` for their own scope — scaffold's version kept). All tests pass after merge.

**Completed:** All planned workflow tools implemented, with all tests passing and coverage meeting or exceeding the project's quality targets across backend and workflow tools.

**Key learnings from Phase 3:**
- Pure functions + wiring layer is the right pattern for workflows — pure functions take service clients as params, `server.py` wraps them as MCP tools. No circular imports, trivially unit-testable with `AsyncMock`.
- Agents that modify shared files (`server.py`) need careful coordination — scaffold first (serial), then give agents exclusive files only. Cherry-pick implementations, not shared file rewrites.
- `AsyncExitStack` is cleaner than nested `async with` for managing multiple clients in a single lifespan.
- `BaseClient.__aenter__` must return `Self` (not `BaseClient`) for `AsyncExitStack.enter_async_context()` to infer the correct type.
- `asyncio.gather(return_exceptions=True)` + `isinstance(result, BaseException)` is the pattern for concurrent optional backends — no try/except needed per task.
- `draft_pack_pick` only needs 17Lands (not Scryfall) — 17Lands already has name, color, rarity, all win rate metrics.
- Workflow tests use `unittest.mock.AsyncMock` instead of respx, since they test pure functions not HTTP calls.

---

## Quality Gates (Every Phase)

Before considering any phase complete:

```bash
# All must pass
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check src/
uv run pytest --cov --cov-report=term-missing
```

Coverage target: **80%+ on services and servers**, measured per phase.

---

## Phase 4: Service Caching + MTGJSON Bulk Card Cache [COMPLETE]

**Goal:** Two complementary caching layers: in-memory TTL caching across all 4 existing services, and MTGJSON bulk card data as a standalone MCP provider with rate-limit-free search.

### Steps

1. Add `cachetools` dependency and `async_cached` decorator in `services/cache.py`
2. Update `Settings`: replace `cache_ttl_seconds` with `disable_cache: bool` + MTGJSON settings (`mtgjson_data_url`, `mtgjson_refresh_hours`, `enable_mtgjson`)
3. Add `MTGJSONCard` model to `types.py`
4. Apply `@async_cached` to all 12 service methods with per-method TTLs (24h for card data, 1h for search, 4h for 17Lands, 12h for decklist analysis)
5. Build `MTGJSONClient` in `services/mtgjson.py` — lazy download, gzip decompress, in-memory dict for O(1) lookups
6. Build MTGJSON provider in `providers/mtgjson.py` — `card_lookup` and `card_search` tools
7. Mount MTGJSON provider on orchestrator with `namespace="mtgjson"` behind feature flag

**Done when:** All 12 service methods cached, MTGJSON tools appear in tools/list, `disable_cache` flag works.

**Completed:** Two parallel agents in worktrees (Agent A: TTL caching, Agent B: MTGJSON). Cherry-picked and merged. Final state: 245 tests, 92% coverage, 15 tools + 4 workflows.

**Key learnings from Phase 4:**
- `_decklist_key` must convert lists in both positional args AND kwargs — `find_decklist_combos(commanders=[...], decklist=[...])` uses kwargs
- Autouse `_clear_caches` fixture in conftest.py is essential — without it, cached results leak between tests
- MTGJSON is file-based (not BaseClient) — different lifecycle from HTTP services, but same lifespan/module-level-client pattern for the provider
- MTGJSON `AtomicCards.json` keys by display name (with `//` for DFCs) — need to key by both short name and full name for DFC lookup

---

## Phase 5: Analysis & Comparison Workflows [COMPLETE]

**Goal:** Higher-order workflow tools that compose across backends for deck analysis, card comparison, budget suggestions, and draft format overviews. Prompts to guide multi-step analysis. Resources for cached data access.

**Prerequisites:** All backend providers and Phase 3 workflow tools working. MTGJSON available for rate-limit-free card resolution.

### Steps

1. **Card resolver utility** (`workflows/card_resolver.py`):
   - MTGJSON-first card resolution with Scryfall fallback
   - `need_prices` flag to bypass MTGJSON when price data is required
   - Used by `deck_analysis` for bulk card lookups without rate-limit pressure

2. **card_comparison** (`workflows/commander.py`):
   - Compare 2-5 cards side-by-side for a specific commander
   - Parallel Scryfall resolution, EDHREC synergy lookups, Spellbook combo counts
   - Progress reporting via `ctx.report_progress()` callback
   - Validation: 2-5 cards enforced at tool wrapper level

3. **budget_upgrade** (`workflows/commander.py`):
   - Fetch EDHREC staples, look up Scryfall prices in parallel (semaphore=10)
   - Filter by budget ceiling, rank by synergy-per-dollar
   - Requires EDHREC (not optional) + Scryfall for prices

4. **deck_analysis** (`workflows/analysis.py`):
   - Full decklist health check: mana curve, color pips, combos, bracket, budget, synergy
   - 4-step progress: resolve cards → spellbook data → EDHREC data → fill prices
   - MTGJSON-first card resolution via `card_resolver` with Scryfall fallback for prices
   - All backends optional except Scryfall

5. **set_overview** (`workflows/draft.py`):
   - Top 10 commons/uncommons by GIH WR, trap rares/mythics below median
   - 17Lands only — single backend, 2-step progress

6. **Prompts** (`workflows/server.py`):
   - `evaluate_commander_swap`: Multi-step swap evaluation guide
   - `deck_health_check`: Full deck health assessment workflow
   - `draft_strategy`: Draft format preparation session
   - `find_upgrades`: Budget upgrade session guide

7. **Resources** (registered on provider sub-servers):
   - `mtg://card/{name}` and `mtg://card/{name}/rulings` (Scryfall)
   - `mtg://combo/{combo_id}` (Spellbook)
   - `mtg://draft/{set_code}/ratings` (17Lands)
   - `mtg://commander/{name}/staples` (EDHREC)
   - `mtg://card-data/{name}` (MTGJSON)

8. **Tool tags** (`providers/__init__.py`):
   - Tag constants: `TAGS_LOOKUP`, `TAGS_SEARCH`, `TAGS_COMMANDER`, `TAGS_DRAFT`, `TAGS_COMBO`, `TAGS_PRICING`, `TAGS_BETA`
   - Applied to all tools via `tags=` parameter for categorization

**Done when:** All 8 workflow tools, 4 prompts, and 6 resources registered. 374 tests passing, 92% coverage.

**Completed:** Final state: 15 backend tools + 8 workflow tools + 4 prompts + 6 resources. 374 tests, 92% coverage.

**Key learnings from Phase 5:**
- Progress reporting works best as a callback pattern: pure functions accept `on_progress: Callable[[int, int], Awaitable[None]]`, `server.py` bridges to `ctx.report_progress()`
- Card resolver utility avoids duplicating MTGJSON-first logic across workflows
- `budget_upgrade` requires EDHREC (not optional) — unlike other workflows, it has no fallback for staples data
- Semaphore(10) on Scryfall price lookups prevents overwhelming the API during bulk operations
- Tool tags provide categorization without affecting tool naming or behavior
