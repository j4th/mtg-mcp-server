# Spec 1: Infrastructure Modernization

> **Status:** Partially complete — Scryfall bulk data done, remaining items folded into Spec 3
> **Date:** 2026-03-26
> **Scope:** Foundation upgrades that unblock all future tool expansion

This spec is part of a 3-spec expansion:
- **Spec 1 (this):** Infrastructure Modernization — Scryfall bulk data *(complete)*, rules engine, structured output, CodeMode readiness *(moved to Spec 3)*
- **Spec 2:** [Cross-Format Tools & Utilities](SPEC_CROSS_FORMAT_TOOLS.md) — validation, card discovery, format info, mana base *(complete)*
- **Spec 3:** [Format-Specific Workflows](SPEC_FORMAT_WORKFLOWS.md) — comprehensive v2.0: rules engine, structured output, CodeMode, format workflows

> **Note (2026-03-27):** Phase 1A item 1 (Scryfall bulk data) was implemented during Spec 2. The remaining Spec 1 items — Comprehensive Rules engine (§2), structured output (§4), response_format (§5), CodeMode (§7), rules tools (§8), and structured output retrofit (§10) — have been folded into Spec 3 for the v2.0 release. This spec remains as the original design reference.

This spec covers two phases:
- **Phase 1A — Infrastructure Build:** New services, platform fixes, patterns
- **Phase 1B — Retrofit & Validation:** Migrate existing tools, add rules tools, verify everything

---

## Context & Motivation

The server has 23 tools, 6 resources (broken), 4 prompts across 5 backends. It's heavily Commander-oriented. To expand to all formats and scale to 50-80+ tools, we need:

1. **Richer offline card data** — MTGJSON lacks prices, legalities, rarity. Every deck analysis does ~99 Scryfall API calls to fill prices.
2. **Rules engine** — No way to look up game rules, keywords, or interactions. High community demand.
3. **Working resources** — 6 registered but invisible in Inspector due to FastMCP mount() propagation bug.
4. **Structured output** — Tools return markdown strings only. No machine-readable JSON for future clients.
5. **Scalable tool discovery** — At 50+ tools, flat listing degrades LLM accuracy. Need tags + CodeMode readiness.
6. **Existing tool retrofit** — Current tools don't leverage the improved infrastructure.

---

## Phase 1A: Infrastructure Build

### 1. Scryfall Bulk Data Service (replaces MTGJSON)

**What:** Download Scryfall's Oracle Cards bulk file (~32K cards, 162 MB) and serve from memory. Strict superset of MTGJSON — includes prices, legalities (21 formats), EDHREC rank, image URIs, rarity, set info.

**Service: `services/scryfall_bulk.py`**

Not a `BaseClient` subclass (file-based, same pattern as current MTGJSON).

Lifecycle:
- Lazy-load on first access (not startup — keeps stdio transport instant)
- Staleness check via `GET /bulk-data/oracle_cards` metadata endpoint (returns `updated_at` timestamp, ~1 KB response)
- Conditional download with `If-None-Match: <etag>` header (304 = data unchanged, skip download)
- Background refresh via `asyncio.create_task()` from lifespan, every 12 hours
- Atomic swap: parse into local variables, single-assignment swap of `self._cards`
- On refresh failure: log warning, serve stale data, retry after next interval
- On first-load failure: propagate error (can't serve without data)
- Concurrent access protection: `asyncio.Lock` around download to prevent duplicate downloads when multiple calls arrive on stale data simultaneously

Data structure:
- `dict[str, Card]` keyed by lowercase card name
- DFC handling: key by both front-face name and full `Front // Back` name (same as current MTGJSON approach)
- Uses the existing `Card` Pydantic model from `types.py` — no new types needed
- Separate `list[Card]` for substring search (same as MTGJSON's `_unique_cards`)

Configuration (`config.py`):
- `bulk_data_refresh_hours: int = 12` (replaces `mtgjson_refresh_hours`)
- `enable_bulk_data: bool = True` (replaces `enable_mtgjson`)
- Remove: `mtgjson_data_url`, `mtgjson_refresh_hours`, `enable_mtgjson`

Search capabilities:
- Exact name lookup: O(1) dict access
- Substring search by name, type line, or oracle text: linear scan over `_unique_cards`
- Format legality filtering: cards have `legalities` dict — can filter by format
- Color identity filtering: cards have `color_identity` — can filter by colors

**Provider: `providers/scryfall_bulk.py`**

Replaces `providers/mtgjson.py`. Mounted with `namespace="bulk"`.

Tools (backward-compatible interface, richer output):
- `card_lookup(name: str)` — exact name lookup, returns full card data including prices/legalities
- `card_search(query: str, search_field: str = "name", limit: int = 20)` — search by name, type, or oracle text

Resource:
- `mtg://card-data/{name}` — card data as JSON (same URI, richer payload)

Tags: `lookup`, `search`, `stable`

**What gets removed:**
- `services/mtgjson.py`
- `providers/mtgjson.py`
- `MTGJSONCard` model from `types.py`
- MTGJSON fixtures from `tests/fixtures/mtgjson/`
- All MTGJSON-specific test files

---

### 2. Comprehensive Rules Service

**What:** Download the MTG Comprehensive Rules text file (~943 KB), parse into a searchable index, and serve rule lookups from memory.

**Service: `services/rules.py`**

Not a `BaseClient` subclass (file-based).

Data source:
- URL is not stable (date embedded in filename, e.g., `MagicCompRules 20260227.txt`)
- Strategy: configurable URL in settings with a known-good default. Updated manually when new rules drop (~4x/year with set releases). Env override via `MTG_MCP_RULES_URL` for users who want to point to a newer version immediately.
- Default URL: `https://media.wizards.com/2026/downloads/MagicCompRules%2020260227.txt`
- The file is ~943 KB plain text, UTF-8 with BOM

Parsing:
- ~9,274 lines, ~3,490 numbered rule entries
- Structure: table of contents, then numbered rules (e.g., `100.1`, `704.5k`), then glossary
- Parse into: `dict[str, Rule]` keyed by rule number, `dict[str, GlossaryEntry]` keyed by term
- `Rule` model: `number: str`, `text: str`, `subrules: list[Rule]`
- `GlossaryEntry` model: `term: str`, `definition: str`

Lifecycle:
- Lazy-load on first access (same pattern as bulk data)
- Refresh much less frequently (rules update ~4x per year with set releases)
- `rules_refresh_hours: int = 168` (weekly check, default)
- On refresh failure: serve stale data

Search capabilities:
- Lookup by rule number: O(1) dict access (e.g., `704.5k`)
- Keyword search: scan rule text for substring/regex matches
- Glossary lookup: exact term match + fuzzy matching
- Section browsing: return all rules in a section (e.g., all `7xx` rules = "Additional Rules")

Configuration (`config.py`):
- `rules_url: str = "https://media.wizards.com/2026/downloads/MagicCompRules%2020260227.txt"` — override via `MTG_MCP_RULES_URL`
- `rules_refresh_hours: int = 168`
- `enable_rules: bool = True` — feature flag

**No provider in Phase 1A.** The service is built and tested here. Tools are added in Phase 1B.

---

### 3. Fix Resource Propagation Through mount()

**Problem:** Resources registered on sub-servers (e.g., `scryfall_mcp.resource("mtg://card/{name}")`) don't appear in the parent server's `list_resources()` response. Known FastMCP 3.x issue with mount() not propagating resources.

**Investigation needed during implementation:**
- Confirm the bug exists in our current FastMCP version (3.1.x)
- Check if it's been fixed in a newer FastMCP release
- If not fixed upstream: determine the right workaround (re-register on parent? patch the mount behavior? file upstream issue?)

**Acceptance criteria:**
- All 6 existing resources visible in MCP Inspector's Resources tab
- New resources added in this spec also visible
- Resources return correct data when accessed by URI

**Namespace behavior for resources:**
- Currently, tool names get prefixed by namespace (e.g., `search_cards` → `scryfall_search_cards`)
- Document whether resource URIs also get namespaced (e.g., `mtg://card/{name}` → `mtg://scryfall/card/{name}`) and ensure consistency

---

### 4. Structured Output Pattern

**What:** Return `ToolResult` with both human-readable markdown (`content`) and machine-readable JSON (`structured_content`) from all tools. Backward-compatible — existing clients see markdown, future clients can consume JSON.

**Pattern:**

```python
from fastmcp.tools.tool import ToolResult

@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def card_details(name: str, response_format: str = "detailed") -> ToolResult:
    client = _get_client()
    card = await client.get_card_by_name(name)
    return ToolResult(
        content=format_card_markdown(card, response_format),
        structured_content=card.model_dump(mode="json"),
    )
```

**Implementation approach:**
- Phase 1A: establish the pattern and helper utilities
- Phase 1B: retrofit all existing tools to use it

**Helpers to create:**
- `format_card_markdown(card: Card, format: str = "detailed") -> str` — shared formatter
- `format_combo_markdown(combo: Combo, format: str = "detailed") -> str`
- Similar formatters for each data type
- These likely already exist inline in tools — extract and share

---

### 5. Response Format Parameter

**What:** Per Anthropic's best practice, add a `response_format` parameter to workflow tools so LLMs can control token consumption.

**Values:**
- `"detailed"` (default) — current verbose output with full card text, all metrics, explanations
- `"concise"` — compact tables, key metrics only, no explanations. Useful when the LLM is chaining multiple tool calls and doesn't need prose.

**Scope:** All 8 workflow tools + backend tools that return significant text (card_details, find_combos, etc.).

**Implementation:** The `response_format` parameter is passed to markdown formatting helpers. The `structured_content` JSON is always full — only the human-readable text varies.

---

### 6. Tag Taxonomy Expansion

**Current tags:** `lookup`, `search`, `commander`, `draft`, `combo`, `pricing`, `stable`, `beta`, `analysis`

**Expanded taxonomy:**

Format tags (new):
- `commander`, `draft` (existing)
- `standard`, `modern`, `pioneer`, `legacy`, `vintage`, `pauper` — applied to format-specific tools
- `constructed` — umbrella tag for 60-card format tools
- `limited` — umbrella tag for draft + sealed tools
- `all-formats` — for cross-format utilities

Function tags (refined):
- `lookup`, `search` (existing)
- `build` — deck building tools
- `analyze` — analysis/evaluation tools (replaces `analysis` for consistency)
- `validate` — validation/legality tools
- `rules` — rules and keyword tools
- `pricing` (existing)
- `combo` (existing)

Stability tags:
- `stable`, `beta` (existing)

**Why this matters:** CodeMode's `GetTags` discovery tool and `Search(tags=...)` filtering use these. Good tags = better tool discovery at scale.

---

### 7. CodeMode Readiness

**What:** Make the server ready to serve via CodeMode without requiring it. CodeMode is opt-in, not default.

**Implementation:**
- Add `fastmcp[code-mode]` as an optional dependency (extra in pyproject.toml)
- Add `MTG_MCP_ENABLE_CODE_MODE: bool = False` feature flag
- When enabled, wrap the server: `mcp.add_transform(CodeMode())`
- Alternatively, serve a second server instance for CodeMode clients
- Document in README how to enable CodeMode

**What makes us "ready" (no CodeMode dependency required):**
- All tools have clear, descriptive names and docstrings (LLM needs these for search)
- All tools are tagged (CodeMode `GetTags` uses them)
- No tools with ambiguous overlap (confuses CodeMode search)
- Tool descriptions explain when to use THIS tool vs. similar ones

**Serving strategy:** Feature flag that transforms the single server (`MTG_MCP_ENABLE_CODE_MODE=true`). Simpler than maintaining two entry points, and stdio transport means one client at a time anyway. Can revisit if CodeMode graduates from experimental and multi-client HTTP transport becomes common.

---

## Phase 1B: Retrofit & Validation

### 8. Rules Tools

**Provider: registered on workflow server** (no separate namespace — these are cross-cutting utilities)

Tools:
- `rules_lookup(query: str, section: str | None = None)` — Search comprehensive rules by keyword, rule number, or concept. Optional section filter (e.g., "combat", "stack", "lands"). Returns matching rules with context.
- `keyword_explain(keyword: str)` — Explain what a keyword or ability word does. Checks glossary first, then searches rules. Includes examples if available.

Resources:
- `mtg://rules/{number}` — specific rule by number (e.g., `mtg://rules/704.5k`)
- `mtg://rules/glossary/{term}` — glossary entry by term

Prompts:
- `rules_question(question: str)` — Guide for answering a rules question: look up relevant rules, check glossary, explain in plain language with rule citations

Tags: `rules`, `all-formats`, `stable`

---

### 9. Migrate Card Resolver

**Current:** `workflows/card_resolver.py` resolves cards via MTGJSON-first with Scryfall API fallback. Returns `Card | MTGJSONCard`.

**After:** Resolves cards via Scryfall bulk data. Returns `Card` (always). Scryfall API fallback only for cards not in bulk data (extremely rare — maybe spoiled cards not yet in the daily dump).

Changes:
- `card_resolver.py`: accept `ScryfallBulkClient` instead of `MTGJSONClient`
- Return type simplifies to `Card` everywhere
- `need_prices` flag becomes unnecessary (bulk data always has prices)
- `_fill_missing_prices()` in `analysis.py` removed entirely

---

### 10. Retrofit All Existing Tools

**Structured output:** Every tool returns `ToolResult(content=..., structured_content=...)`:
- Backend tools (15): card_details, search_cards, card_price, card_rulings, find_combos, combo_details, find_decklist_combos, estimate_bracket, card_ratings, archetype_stats, commander_staples, card_synergy, card_lookup, card_search, ping
- Workflow tools (8): commander_overview, evaluate_upgrade, card_comparison, budget_upgrade, suggest_cuts, deck_analysis, draft_pack_pick, set_overview

**Response format:** Add `response_format: str = "detailed"` to all workflow tools and text-heavy backend tools.

**Tag update:** Apply expanded taxonomy to all existing tools.

---

### 11. Resource Expansion

New resources (in addition to fixing the 6 existing ones):

| URI | Provider | Description |
|---|---|---|
| `mtg://format/{format}/banned` | scryfall_bulk | Banned/restricted cards for a format |
| `mtg://format/{format}/staples` | scryfall_bulk | Most-played cards in a format (by EDHREC rank proxy) |
| `mtg://set/{code}` | scryfall | Set metadata (name, release date, card count, type) |
| `mtg://rules/{number}` | workflow | Rule text by number |
| `mtg://rules/glossary/{term}` | workflow | Glossary definition |
| `mtg://rules/keywords` | workflow | List of all keywords with brief definitions |

---

### 12. Prompt Expansion

New prompts (in addition to the 4 existing ones):

| Prompt | Arguments | What it guides |
|---|---|---|
| `rules_question` | `question: str` | Look up rules, check glossary, explain in plain language |
| `build_commander_deck` | `commander: str, budget: float \| None` | Full deck construction workflow using commander_overview → theme selection → card search → deck_analysis |
| `prepare_for_draft` | `set_code: str` | Pre-draft study: set_overview → archetype analysis → pick heuristics → trap cards |
| `upgrade_on_budget` | `commander: str, budget: float` | Budget upgrade session: budget_upgrade → evaluate each → suggest cuts for slots |
| `learn_format` | `format: str` | Format introduction: legal sets, banned cards, format staples, deck archetypes |
| `card_deep_dive` | `card_name: str` | Everything about a card: details, rulings, combos, formats, price, similar cards |

---

## What This Unblocks (Spec 2 & 3 Preview)

With Spec 1 complete, future specs can:
- **Add format-specific tools** without rate limit anxiety (bulk data serves all card lookups offline)
- **Add deck building tools** with full price/legality data available instantly
- **Scale to 50-80+ tools** with CodeMode as an escape valve
- **Add theme/tribal search** using bulk data's oracle text + type line fields
- **Add sealed pool building** using bulk data's color identity + mana value fields
- **Return rich structured data** that future UI clients can render (charts, tables, interactive lists)
- **Support all 21 formats** — legality data is in every card object from bulk data

---

## Testing Strategy

**New services:**
- `ScryfallBulkClient`: mock the metadata endpoint + bulk download with respx. Test lazy loading, staleness detection, ETag handling, atomic swap, refresh failure recovery, concurrent access locking.
- `RulesService`: capture rules text as fixture. Test parsing, rule number lookup, keyword search, glossary lookup, section filtering.

**Retrofitted tools:**
- All existing tool tests updated to verify `ToolResult` return type with both `content` and `structured_content`
- Test `response_format="concise"` produces shorter output than `"detailed"`
- Test that structured_content contains valid JSON matching expected schema

**Resources:**
- Integration test: full orchestrator → `list_resources()` returns all resources
- Test each resource URI returns valid data

**CodeMode:**
- Test that `CodeMode()` transform wraps server correctly
- Test that search discovers tools by name and tag
- Test that execute can chain multiple tool calls

---

## Migration Checklist

MTGJSON → Scryfall bulk migration:
- [ ] Build `ScryfallBulkClient` service with tests
- [ ] Build `scryfall_bulk` provider with tests
- [ ] Update `card_resolver.py` to use `ScryfallBulkClient`
- [ ] Update `workflows/server.py` lifespan to manage `ScryfallBulkClient` instead of `MTGJSONClient`
- [ ] Update `workflows/analysis.py` — remove `_fill_missing_prices()`
- [ ] Update `server.py` — mount `scryfall_bulk_mcp` instead of `mtgjson_mcp`
- [ ] Update `config.py` — replace MTGJSON settings with bulk data settings
- [ ] Remove `services/mtgjson.py`, `providers/mtgjson.py`, `MTGJSONCard` from `types.py`
- [ ] Remove MTGJSON fixtures, update/remove MTGJSON tests
- [ ] Update all workflow tests that mock `MTGJSONClient` → mock `ScryfallBulkClient`
- [ ] Update CLAUDE.md, ARCHITECTURE.md, and other docs
