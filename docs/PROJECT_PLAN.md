# MTG MCP Server — Implementation Plan

This is the ordered build plan. Each phase produces a working, testable increment. Do not skip phases or build ahead.

## Phase 0: Project Scaffold

**Goal:** Empty project that builds, lints, type-checks, and runs an empty test suite.

### Steps

1. Initialize the project:
   ```bash
   mkdir mtg-mcp && cd mtg-mcp
   uv init --lib --name mtg-mcp
   ```

2. Configure `pyproject.toml`:
   - Package name: `mtg-mcp`
   - Python: `>=3.12`
   - Entry point: `[project.scripts] mtg-mcp = "mtg_mcp.main:cli"`
   - Dependencies: `fastmcp>=3.1.0`, `httpx>=0.28`, `pydantic>=2.0`, `pydantic-settings>=2.0`, `tenacity>=9.0`, `structlog>=24.0`
   - Dev dependencies: `pytest>=8.0`, `pytest-asyncio>=0.24`, `respx>=0.22`, `pytest-cov>=6.0`, `ruff`, `ty`
   - Ruff config: `line-length = 100`, `target-version = "py312"`, select = `["E", "F", "I", "UP", "B", "SIM", "TCH", "RUF"]`
   - ty config: add `[tool.ty]` section per ty docs (may need `pyproject.toml` or `ty.toml`)
   - pytest config: `asyncio_mode = "auto"`, `testpaths = ["tests"]`

3. Create the directory structure per ARCHITECTURE.md (all `__init__.py` files, empty modules).

4. Create `src/mtg_mcp/logging.py`:
   - Configure structlog with JSON output to stderr (MCP stdio servers must not log to stdout)
   - Provide `get_logger(service: str)` that returns a bound logger

5. Create `src/mtg_mcp/config.py`:
   - `Settings` class via pydantic-settings
   - Fields: `scryfall_base_url`, `spellbook_base_url`, `seventeen_lands_base_url`, `log_level`, `transport` (enum: stdio/http), `http_port`
   - Load from env vars with `MTG_MCP_` prefix and/or `.env` file

6. Create `src/mtg_mcp/main.py`:
   - Build the orchestrator: `mtg = FastMCP("MTG")`
   - No backends mounted yet
   - Register a single `ping` tool that returns `"pong"` (smoke test)
   - CLI entry point: parse `--transport` flag, run stdio or HTTP accordingly

7. Create `tests/conftest.py` with basic fixtures.

8. Create `tests/unit/test_smoke.py`:
   - Test that the server can be instantiated
   - Test that the `ping` tool is registered

9. Verify:
   ```bash
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   uv run ty check src/
   uv run pytest --cov
   uv run mtg-mcp --help        # CLI works
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

5. Write tests in `tests/unit/services/test_scryfall.py`:
   - Test `get_card_by_name` returns a Card model from fixture
   - Test `get_card_by_name` raises `CardNotFoundError` on 404 fixture
   - Test `search_cards` returns `CardSearchResult` with pagination
   - Test rate limiting behavior (mock timing)
   - All tests use `respx` to mock HTTP responses with fixture data

### 1b: Server Layer

6. Create `src/mtg_mcp/providers/scryfall.py`:
   - Lifespan: create `ScryfallClient` once at startup via `@lifespan` decorator, yield in context dict
   - `scryfall_server = FastMCP("Scryfall", lifespan=scryfall_lifespan)`
   - Dependency: `get_client(ctx: Context) -> ScryfallClient` reads from `ctx.lifespan_context`
   - Tools (each receives client via `Depends(get_client)`):
     - `search_cards(query: str, page: int = 1) -> str` — Scryfall search syntax, returns formatted results
     - `card_details(name: str) -> str` — Exact card lookup, returns full details
     - `card_price(name: str) -> str` — Price lookup (USD, EUR, foil)
     - `card_rulings(name: str) -> str` — Official rulings for a card
   - Annotations: all tools get `ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)`
   - Error handling: catch service exceptions → raise `ToolError` from `fastmcp.exceptions` with actionable messages

7. Write tests in `tests/unit/providers/test_scryfall_provider.py`:
   - Use FastMCP's test client (`async with scryfall_server.test_client() as client:`)
   - Test each tool returns expected content
   - Test error tool responses for missing cards

### 1c: Mount on Orchestrator

8. Update `src/mtg_mcp/main.py`:
   - Mount `scryfall_server` with `namespace="scryfall"`
   - Remove the `ping` tool (or keep as health check)

9. Integration test: `tests/integration/test_orchestrator.py`:
   - Instantiate the full orchestrator
   - Verify `scryfall_search_cards` appears in tools/list
   - Call `scryfall_card_details` with mocked HTTP → get card data back

10. Manual smoke test:
    ```bash
    uv run mtg-mcp  # start stdio
    # Use MCP Inspector: npx @modelcontextprotocol/inspector
    ```

**Done when:** You can search for cards and get real data back through the MCP protocol.

---

## Phase 2: Commander Spellbook Service + Server

**Goal:** Combo search and bracket estimation working as a second mounted backend.

### Steps

1. Research the Spellbook API:
   - Base URL: `https://backend.commanderspellbook.com`
   - Key endpoints: `/variants/` (combo search), `/estimate-bracket/`
   - Capture fixtures for Muldrotha combos, Gitrog combos

2. Create `SpellbookClient` in `services/spellbook.py`:
   - `find_combos(card_name: str, color_identity: str | None) -> list[Combo]`
   - `estimate_bracket(decklist: list[str]) -> BracketEstimate`

3. Create `Combo` and `BracketEstimate` Pydantic models in `types.py`

4. Create `spellbook_server` in `providers/spellbook.py`:
   - Tools: `find_combos`, `combo_details`, `estimate_bracket`

5. Mount on orchestrator with `namespace="spellbook"`

6. Write tests at every layer (service, server, integration)

**Done when:** Both backends are mounted. Consumer sees `scryfall_*` and `spellbook_*` tools.

---

## Phase 3: First Workflow Tool

**Goal:** A composed `commander_overview` tool that calls both Scryfall and Spellbook.

### Steps

1. Create `workflows/commander.py`:
   - `commander_overview(commander_name: str)` calls:
     - `ScryfallClient.get_card_by_name()` → card data
     - `SpellbookClient.find_combos()` → combos for that commander
   - Returns formatted markdown combining both
   - Handles partial failure (Spellbook down → still return card data with note)

2. Register on orchestrator in `main.py`

3. Test: mock both services, verify composed response

**Done when:** `commander_overview("Muldrotha, the Gravetide")` returns card info + combo list.

---

## Phase 4: 17Lands Service + Server

**Goal:** Draft card ratings and archetype stats.

### Steps

1. Research the 17Lands API:
   - Card ratings endpoint: `https://www.17lands.com/card_ratings/data?expansion=<SET>&format=<FORMAT>`
   - Capture fixtures for a recent set

2. Create `SeventeenLandsClient`:
   - `card_ratings(set_code: str, format: str = "PremierDraft") -> list[DraftCardRating]`
   - `color_ratings(set_code: str, format: str = "PremierDraft") -> list[ArchetypeRating]`

3. Create server, mount as `namespace="draft"`

4. Write tests

**Done when:** `draft_card_ratings` returns win rate data for any Standard-legal set.

---

## Phase 5: EDHREC Service + Server

**Goal:** Commander staples and synergy scores. This is the scraping-based backend — expect fragility.

### Steps

1. Research EDHREC's internal JSON endpoints (pyedhrec uses these):
   - Commander page data: `https://json.edhrec.com/pages/commanders/<name>.json`
   - Card data: `https://json.edhrec.com/pages/cards/<name>.json`
   - Capture fixtures

2. Create `EDHRECClient`:
   - `commander_top_cards(commander_name: str) -> list[EDHRECCard]`
   - `card_synergy(card_name: str, commander_name: str) -> SynergyData`

3. Create server, mount as `namespace="edhrec"`

4. Write tests (fixture-only — never hit EDHREC in tests)

**Done when:** `edhrec_commander_staples("Muldrotha, the Gravetide")` returns top cards with inclusion rates.

---

## Phase 6: Full Workflow Suite

**Goal:** Composed tools that deliver real value by cross-referencing all backends.

### Workflow tools to build

1. **`commander_overview`** (Phase 3, now enhanced with EDHREC data):
   - Card details (Scryfall) + top staples (EDHREC) + combos (Spellbook)

2. **`evaluate_upgrade`** (new):
   - Input: card_name, commander_name
   - Scryfall: what does the card do, what does it cost?
   - EDHREC: what % of decks run it? What's the synergy score?
   - Spellbook: does adding this card enable new combos?
   - Output: structured recommendation

3. **`draft_pack_pick`** (new):
   - Input: list of card names (the pack), current_picks (what you've drafted so far), set_code
   - 17Lands: GIHWR and ALSA for each card in the pack
   - Scryfall: card details for context
   - Output: ranked picks with data

4. **`suggest_cuts`** (new):
   - Input: decklist (card names), commander_name
   - EDHREC: synergy scores for each card
   - Spellbook: which cards are combo pieces?
   - Output: ranked list of weakest cards to cut

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
