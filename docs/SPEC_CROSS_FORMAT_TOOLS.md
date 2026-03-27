# Spec 2: Cross-Format Tools & Utilities

> **Status:** Design approved
> **Date:** 2026-03-26
> **Scope:** Format-agnostic tools, resources, and prompts that work across all MTG formats
> **Prerequisite:** Spec 1 (Infrastructure Modernization) must be complete

This spec is part of a 3-spec expansion:
- **Spec 1:** Infrastructure Modernization — Scryfall bulk data, rules engine, structured output, CodeMode readiness
- **Spec 2 (this):** Cross-Format Tools & Utilities
- **Spec 3:** Format-Specific Workflows — deck building, Commander depth, Limited expansion

---

## Context & Prerequisites

After Spec 1, the server has:
- **Scryfall bulk data** in memory (~32K cards with prices, legalities across 21 formats, color identity, EDHREC rank)
- **Comprehensive Rules** parsed and searchable (rules + glossary)
- **Structured output** on all tools (`ToolResult` with markdown + JSON)
- **`response_format` parameter** on all workflow tools
- **Expanded tag taxonomy** with format and function tags
- **Working resources** (mount propagation fixed)
- **CodeMode readiness** (opt-in)

The tools in this spec are format-agnostic — they work for Commander, Standard, Modern, Draft, or any format. They leverage Scryfall bulk data heavily (no API rate limit concerns for card lookups).

---

## New Tools

### Deck Validation

#### `deck_validate`

Validate a decklist against a format's rules. Checks everything a player would need before submitting or playing.

| Field | Detail |
|---|---|
| Input | `decklist: list[str]`, `format: str` (e.g., "commander", "standard", "modern"), `commander: str \| None = None`, `sideboard: list[str] \| None = None` |
| Output | Validation report: pass/fail, issues found (illegal cards, wrong count, banned cards, too many copies, sideboard violations, color identity violations for Commander) |
| Backends | Scryfall bulk (legalities, color identity) |
| Tags | `validate`, `all-formats`, `stable` |

Format-specific rules to enforce:

| Format | Main deck | Sideboard | Copies | Special |
|---|---|---|---|---|
| Standard, Pioneer, Modern, Legacy, Vintage | 60+ | 0-15 | max 4 (except basic lands) | Vintage: restricted = max 1 |
| Commander | exactly 100 (incl. commander) | none | max 1 (singleton) | color identity must match commander |
| Pauper | 60+ | 0-15 | max 4 | only common rarity cards |
| Limited (draft/sealed) | 40+ | unlimited | no limit | — |

Error messages must be actionable: "Sol Ring is banned in Modern" not "Illegal card found."

#### `format_legality`

Check a list of cards against a format's legality.

| Field | Detail |
|---|---|
| Input | `cards: list[str]`, `format: str` |
| Output | Per-card status: legal, banned, restricted, not_legal, with reasons |
| Backends | Scryfall bulk (legalities field) |
| Tags | `validate`, `all-formats`, `stable` |

Lighter than `deck_validate` — just legality, no deck construction rules.

---

### Card Discovery

#### `format_search`

Search for cards within a format's legal card pool with filters. This is the "build a deck" search tool — finding cards that meet specific criteria within a format.

| Field | Detail |
|---|---|
| Input | `format: str`, `query: str` (natural language or structured: "2-drop creatures", "removal spells", "card draw"), `color_identity: str \| None = None`, `max_price: float \| None = None`, `rarity: str \| None = None`, `limit: int = 20` |
| Output | Matching cards sorted by relevance (EDHREC rank as proxy), with name, mana cost, type, price |
| Backends | Scryfall bulk (legalities + full card data for filtering) |
| Tags | `search`, `all-formats`, `stable` |

Query translation strategy:
- The tool translates natural-language queries into filters over bulk data fields
- "2-drop creatures" → `cmc == 2 AND "Creature" in type_line`
- "removal spells" → oracle text contains "destroy" or "exile" or "deals damage" or "-X/-X"
- "card draw" → oracle text contains "draw" and type is instant/sorcery/enchantment
- For complex queries, return best-effort matches with a note about what was searched

This is NOT a Scryfall API search (that's `scryfall_search_cards`). This searches our in-memory bulk data with no rate limits, and supports format + price + color filtering that Scryfall's API doesn't natively combine.

#### `format_staples`

Top-played or highest-ranked cards in a format, filterable by color and card type.

| Field | Detail |
|---|---|
| Input | `format: str`, `color: str \| None = None`, `card_type: str \| None = None` (e.g., "creature", "instant", "land"), `limit: int = 20` |
| Output | Ranked list of cards with name, mana cost, type, EDHREC rank (as popularity proxy), price |
| Backends | Scryfall bulk (EDHREC rank + legalities for filtering) |
| Tags | `search`, `all-formats`, `stable` |

Note: EDHREC rank is a rough popularity proxy even for non-Commander formats — it reflects how many decks across EDHREC include the card. For truly format-specific metagame data, we'd need MTGTop8/MTGGoldfish (future spec or data source). This tool is honest about its data source in the output.

#### `similar_cards`

Find cards with similar effects or roles. Useful for budget alternatives, format-legal replacements, or discovering cards you didn't know about.

| Field | Detail |
|---|---|
| Input | `card_name: str`, `format: str \| None = None`, `max_price: float \| None = None`, `limit: int = 10` |
| Output | Similar cards with name, mana cost, type, oracle text, price, and why they're similar |
| Backends | Scryfall bulk (oracle text matching + type matching) |
| Tags | `search`, `all-formats`, `stable` |

Similarity strategy:
- Parse the source card's oracle text for key mechanics (keywords, triggered abilities, static abilities)
- Search bulk data for cards sharing those mechanics
- Score by: keyword overlap, type match, mana cost proximity
- Filter by format legality and price if specified
- This is heuristic-based, not semantic search — good enough for "cards like Swords to Plowshares" (exile + creature + removal) without needing embeddings

#### `random_card`

Random card discovery with optional filters. Fun and genuinely useful for Commander players looking for hidden gems.

| Field | Detail |
|---|---|
| Input | `format: str \| None = None`, `color_identity: str \| None = None`, `card_type: str \| None = None`, `rarity: str \| None = None` |
| Output | Random card with full details |
| Backends | Scryfall bulk (random selection from filtered pool) |
| Tags | `lookup`, `all-formats`, `stable` |

---

### Deck Building Support

#### `suggest_mana_base`

Analyze a decklist's color requirements and suggest a mana base. Counts color pips, calculates ratios, recommends land counts by color.

| Field | Detail |
|---|---|
| Input | `decklist: list[str]`, `format: str`, `total_lands: int \| None = None` |
| Output | Color pip breakdown, recommended land count per color, suggested dual/fetch/utility lands within format legality, mana curve impact |
| Backends | Scryfall bulk (mana costs for pip counting, legalities for land suggestions) |
| Tags | `build`, `analyze`, `all-formats`, `stable` |

Mana base calculation:
- Count color pips across all non-land cards (e.g., {W}{W}{U} = 2W, 1U)
- Calculate pip ratios to determine land color distribution
- Suggest total land count based on average mana value (default ~24 for 60-card, ~37 for Commander)
- Recommend specific lands legal in the format (shock lands, fetch lands, check lands, etc.) based on budget if provided
- Flag cards with heavy color requirements (e.g., {B}{B}{B}) that need special mana support

---

### Format Information

#### `ban_list`

Current banned and restricted cards for any format.

| Field | Detail |
|---|---|
| Input | `format: str` |
| Output | Banned cards list, restricted cards list (Vintage), with card names and brief descriptions of why they matter |
| Backends | Scryfall bulk (legalities field, filter for "banned"/"restricted" status) |
| Tags | `lookup`, `all-formats`, `stable` |

#### `set_info`

Set metadata — release date, card count, what formats it's legal in, set type.

| Field | Detail |
|---|---|
| Input | `set_code: str` |
| Output | Set name, code, release date, card count, set type (expansion, core, masters, etc.), which formats include it |
| Backends | Scryfall API (`/sets/{code}`) — set data is not in bulk card data |
| Tags | `lookup`, `all-formats`, `stable` |

Note: This uses the Scryfall API (not bulk data) since set metadata is not included in Oracle Cards bulk data. The sets endpoint is lightweight and rarely called.

#### `card_in_formats`

Where is a card legal across all formats? Combines legality info with pricing.

| Field | Detail |
|---|---|
| Input | `card_name: str` |
| Output | Table showing each format, legality status (legal/banned/restricted/not_legal), and current price |
| Backends | Scryfall bulk (legalities + prices from single card lookup) |
| Tags | `lookup`, `all-formats`, `stable` |

#### `whats_new`

Recently released or previewed cards. Useful during spoiler season or right after a set release.

| Field | Detail |
|---|---|
| Input | `days: int = 30`, `set_code: str \| None = None`, `format: str \| None = None` |
| Output | Cards with release date within the window, sorted by recency. Filterable by set or format. |
| Backends | Scryfall API (`/cards/search?q=date>={date}`) — needs API since bulk data doesn't have precise release dates per card, and newly spoiled cards may not be in bulk yet |
| Tags | `search`, `all-formats`, `stable` |

#### `price_comparison`

Compare prices across multiple cards. Useful for budget decisions and trade evaluation.

| Field | Detail |
|---|---|
| Input | `cards: list[str]` (2-20 card names) |
| Output | Table with name, USD, USD foil, EUR, total. Sorted by price descending. |
| Backends | Scryfall bulk (prices from card data) |
| Tags | `pricing`, `all-formats`, `stable` |

---

## New Resources

| URI | Provider | Description |
|---|---|---|
| `mtg://format/{format}/legal-cards` | scryfall_bulk | Count of legal cards in a format |
| `mtg://format/{format}/banned` | scryfall_bulk | Banned/restricted card list as JSON |
| `mtg://card/{name}/formats` | scryfall_bulk | Format legality map for a card |
| `mtg://card/{name}/similar` | scryfall_bulk | Similar cards as JSON |
| `mtg://set/{code}` | scryfall | Set metadata as JSON |

---

## New Prompts

| Prompt | Arguments | What it guides |
|---|---|---|
| `build_deck` | `concept: str, format: str, budget: float \| None` | Iterative deck building: search for cards matching concept → suggest mana base → validate → analyze |
| `evaluate_collection` | `cards: str` | Assess a collection of cards: what formats are they legal in, total value, which are staples |
| `format_intro` | `format: str` | Comprehensive format introduction: rules, banned list, staple cards, common archetypes, entry-level deck ideas |
| `card_alternatives` | `card_name: str, format: str, budget: float` | Find budget-friendly alternatives to an expensive card in a specific format |

---

## Tool Count Impact

This spec adds 12 new tools, bringing the total from ~25 (post Spec 1) to ~37.

| Category | New tools | Existing tools | Total |
|---|---|---|---|
| Validation | 2 (deck_validate, format_legality) | 0 | 2 |
| Card discovery | 4 (format_search, format_staples, similar_cards, random_card) | 5 (scryfall search/details, bulk lookup/search) | 9 |
| Deck building | 1 (suggest_mana_base) | 0 | 1 |
| Format info | 5 (ban_list, set_info, card_in_formats, whats_new, price_comparison) | 0 | 5 |

At 37 tools we're above the 30-tool threshold where Anthropic recommends Tool Search. This is where the tag taxonomy from Spec 1 and CodeMode readiness pay off. Workflow tools (unprefixed, intent-level names) should remain the primary entry points; backend tools (prefixed) are for power users and chained calls.

---

## Implementation Notes for Fresh Session

**Key patterns established in Spec 1 that this spec follows:**

1. **Structured output:** All tools return `ToolResult(content=markdown, structured_content=json)`
2. **Response format:** Workflow-level tools accept `response_format: str = "detailed"`
3. **Tags:** Every tool gets both format tags and function tags from the expanded taxonomy
4. **Scryfall bulk client:** Available as `ScryfallBulkClient` — provides `get_card(name)`, `search_cards(query, field, limit)`, and direct access to `self._cards` dict for custom filtering
5. **Error handling:** Service exceptions → `ToolError` from `fastmcp.exceptions` with actionable messages
6. **Testing:** respx for API mocks, `fastmcp.Client(transport=server)` for provider tests, `AsyncMock` for workflow tests

**Most tools in this spec are bulk-data-only** — no HTTP calls, no rate limits, no mocking needed beyond the bulk client. Testing is straightforward: load fixture cards into a mock bulk client, call tool, verify output.

**Tools that DO need the Scryfall API:**
- `set_info` — set metadata endpoint
- `whats_new` — search by date (cards may not be in bulk yet)

These should use the existing `ScryfallClient` from the scryfall provider.

**Where to register tools:**
- Validation tools (`deck_validate`, `format_legality`): new provider `providers/validation.py` mounted with `namespace="validate"` — OR on workflow server if they compose multiple backends
- Card discovery tools: on `scryfall_bulk` provider (they only use bulk data)
- Deck building tools (`suggest_mana_base`): on workflow server (cross-cutting)
- Format info tools: split between `scryfall_bulk` provider (bulk data tools) and `scryfall` provider (API tools like `set_info`)
- `price_comparison`: on workflow server (utility workflow)

Architecture decision: tools that use ONLY bulk data go on `scryfall_bulk` provider. Tools that compose multiple sources or represent user-intent workflows go on the workflow server.

---

## Testing Strategy

**Bulk data tools:** Create a small fixture set (~50 cards across formats) loaded into a mock `ScryfallBulkClient`. Test filtering by format, color, type, price. Test validation rules for each format.

**API tools:** Mock Scryfall API responses with respx (same as existing tests).

**Integration:** Full orchestrator test — verify all new tools appear in `list_tools()`, all new resources in `list_resources()`, all new prompts in `list_prompts()`.

**Edge cases to cover:**
- `deck_validate` with split cards, DFCs, adventure cards (count as one card, not two)
- `format_legality` with cards not in bulk data (newly spoiled)
- `similar_cards` with a card that has no similar cards (should return helpful message, not empty)
- `suggest_mana_base` with colorless decks, 5-color decks, hybrid mana
- `ban_list` for formats with no bans (should say "no cards currently banned")
