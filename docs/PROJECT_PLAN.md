# MTG MCP Server — Implementation Plan

This is the ordered build plan. Each phase produces a working, testable increment. Do not skip phases or build ahead.

## Phase 0: Project Scaffold

**Goal:** Empty project that builds, lints, type-checks, and runs an empty test suite.

### Steps

1. Project initialization is already done — `pyproject.toml` and `mise.toml` are configured. Phase 0 starts at creating the directory structure and source modules.

2. Already configured. See `pyproject.toml` for current settings.

3. Create the directory structure per ARCHITECTURE.md (all `__init__.py` files, empty modules).

4. Create `src/mtg_mcp/logging.py`:
   - Configure structlog with JSON output to stderr (MCP stdio servers must not log to stdout)
   - Provide `get_logger(service: str)` that returns a bound logger

5. Create `src/mtg_mcp/config.py`:
   - `Settings` class via pydantic-settings
   - Fields: `scryfall_base_url`, `spellbook_base_url`, `seventeen_lands_base_url`, `edhrec_base_url`, `log_level`, `transport` (enum: stdio/http), `http_port`, `enable_edhrec: bool`, `enable_17lands: bool`, `cache_ttl_seconds: int`
   - Load from env vars with `MTG_MCP_` prefix and/or `.env` file

6. Create `src/mtg_mcp/server.py`:
   - Build the orchestrator: `mcp = FastMCP("MTG")`
   - No backends mounted yet
   - Register a single `ping` tool that returns `"pong"` (smoke test)
   - Entry point: `mtg_mcp.server:main`. Parse `--transport` flag, run stdio or HTTP accordingly

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

---

## Phase 1: Scryfall Service + Server

**Goal:** Working Scryfall backend with real card search, lookup, and pricing tools.

### 1a: Service Layer (TDD)

1. Capture fixtures:
   - Hit `api.scryfall.com/cards/named?exact=Muldrotha, the Gravetide` and save response to `tests/fixtures/scryfall/card_muldrotha.json`
   - Hit `api.scryfall.com/cards/search?q=commander:sultai+type:creature` (small query) → `search_sultai_commander.json`
   - Hit `api.scryfall.com/cards/named?exact=Sol Ring` → `card_sol_ring.json`
   - Hit a nonexistent card to capture 404 response → `card_not_found.json`

2. Create `src/mtg_mcp/services/base.py`:
   - `BaseClient` class wrapping `httpx.AsyncClient`
   - Constructor takes `base_url`, `rate_limit` (requests/sec), `user_agent`
   - Async context manager (`async with`)
   - Rate limiting via `asyncio.Semaphore` + `asyncio.sleep`
   - Retry decorator factory using tenacity: retry on 429/5xx, respect `Retry-After` header
   - structlog bound logger with `service=<name>`
   - Debug log on every request: method, url, status, elapsed_ms
   - Error log on non-2xx with response body (truncated)

3. Create `src/mtg_mcp/types.py`:
   - `Card` model: name, mana_cost, type_line, oracle_text, colors, color_identity, set_code, collector_number, prices (usd, usd_foil, eur), image_uris, legalities, edhrec_rank, keywords, power, toughness, rarity, scryfall_uri
   - `CardSearchResult` model: total_cards, has_more, data (list[Card])
   - Map from Scryfall's JSON response shape to these models

4. Create `src/mtg_mcp/services/scryfall.py`:
   - `ScryfallClient(BaseClient)` with `base_url = "https://api.scryfall.com"`, `user_agent = "mtg-mcp/0.1.0"`, `rate_limit = 10`
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

6. Create `src/mtg_mcp/providers/scryfall.py`:
   - Lifespan: create `ScryfallClient` once at startup via `@lifespan` decorator, yield in context dict
   - `scryfall_mcp = FastMCP("Scryfall", lifespan=scryfall_lifespan)`
   - Dependency: `get_client(ctx: Context) -> ScryfallClient` reads from `ctx.lifespan_context`
   - Tools (each receives client via `Depends(get_client)`):
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

8. Update `src/mtg_mcp/server.py`:
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

---

## Phase 2: Parallel Backend Build (Spellbook + 17Lands + EDHREC)

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

---

## Phase 3: Workflow Tools

**Goal:** Composed workflow tools that cross-reference multiple backends.

**Prerequisites:** At minimum Scryfall + Spellbook backends working. Enhanced versions need all backends.

**Parallel execution plan:**

Start `commander_overview` as soon as Spellbook is done (only needs Scryfall + Spellbook initially). Other workflows can start once their required backends are ready.

### Steps

1. Create `workflows/commander.py`:
   - `commander_overview(commander_name: str)` calls:
     - `ScryfallClient.get_card_by_name()` → card data
     - `SpellbookClient.find_combos()` → combos for that commander
     - (If EDHREC available) `EDHRECClient.commander_top_cards()` → top staples
   - Returns formatted markdown combining all available data
   - Handles partial failure (any backend down → still return what you can with notes)

2. Once all backends are ready, build remaining workflows in parallel:

| Agent | Workflow | Backends Required |
|-------|----------|-------------------|
| Agent A | `evaluate_upgrade` | Scryfall + EDHREC + Spellbook |
| Agent B | `draft_pack_pick` | 17Lands + Scryfall |
| Agent C | `suggest_cuts` | EDHREC + Spellbook |

3. Register all workflow tools on the workflow server, mount on orchestrator without namespace

4. Test: mock all services, verify composed responses and partial failure handling

**Done when:** All workflow tools return composed data from multiple backends with graceful partial failure handling.

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
