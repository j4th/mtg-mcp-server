# MTG MCP Server — Tool Catalog

Every tool the server exposes, organized by source. Tools prefixed with a namespace come from mounted backend servers. Unprefixed tools are workflow tools on the orchestrator.

---

## Scryfall Backend (namespace: `scryfall`)

### `scryfall_search_cards`
Search for cards using Scryfall's full search syntax.

| Field | Detail |
|-------|--------|
| Input | `query: str` (Scryfall syntax, e.g. `"f:commander id:sultai t:creature cmc<=3"`), `page: int = 1` |
| Output | Formatted list of matching cards with name, type, mana cost, price. Pagination info. |
| Backend | `ScryfallClient.search_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `scryfall_card_details`
Get full details for a card by exact or fuzzy name.

| Field | Detail |
|-------|--------|
| Input | `name: str`, `fuzzy: bool = false` |
| Output | Full card data: name, mana cost, type, oracle text, colors, color identity, legalities, prices, set, rarity, EDHREC rank |
| Backend | `ScryfallClient.get_card_by_name()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `scryfall_card_price`
Get current prices for a card.

| Field | Detail |
|-------|--------|
| Input | `name: str` |
| Output | USD, USD foil, EUR prices. Note: prices update once per day. |
| Backend | `ScryfallClient.get_card_by_name()` (price subset) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `scryfall_card_rulings`
Get official rulings and clarifications for a card.

| Field | Detail |
|-------|--------|
| Input | `name: str` |
| Output | List of rulings with dates and sources |
| Backend | `ScryfallClient.get_card_by_name()` → `ScryfallClient.get_rulings()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Commander Spellbook Backend (namespace: `spellbook`)

### `spellbook_find_combos`
Search for known combos involving specific cards or within a color identity.

| Field | Detail |
|-------|--------|
| Input | `card_name: str`, `color_identity: str | None = None` (e.g. "sultai", "BUG", "wubrg"), `limit: int = 10` |
| Output | List of combos with: cards involved, prerequisites, steps, results. Limited to `limit` combos. |
| Backend | `SpellbookClient.find_combos()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `spellbook_combo_details`
Get detailed steps for a specific combo by its Spellbook ID.

| Field | Detail |
|-------|--------|
| Input | `combo_id: str` (e.g. "2120-5329") |
| Output | Full combo: all cards, zone requirements, step-by-step instructions, results |
| Backend | `SpellbookClient.get_combo()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `spellbook_find_decklist_combos`
Find combos present in (or nearly present in) a Commander decklist.

| Field | Detail |
|-------|--------|
| Input | `commanders: list[str]`, `decklist: list[str]` (card names) |
| Output | Included combos (fully present) and almost-included combos with card lists and results |
| Backend | `SpellbookClient.find_decklist_combos()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `spellbook_estimate_bracket`
Estimate the Commander bracket for a decklist based on its combo density.

| Field | Detail |
|-------|--------|
| Input | `commanders: list[str]`, `decklist: list[str]` (card names) |
| Output | Bracket tag, banned cards, game-changer cards, two-card combos, lock combos |
| Backend | `SpellbookClient.estimate_bracket()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## 17Lands Backend (namespace: `draft`)

### `draft_card_ratings`
Get win rate and draft data for cards in a set.

| Field | Detail |
|-------|--------|
| Input | `set_code: str` (e.g. "LCI", "MKM", "OTJ"), `event_type: str = "PremierDraft"` |
| Output | Per-card: name, color, rarity, GIH WR, ALSA, IWD, games played |
| Backend | `SeventeenLandsClient.card_ratings()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `draft_archetype_stats`
Get win rates by color pair/archetype for a set.

| Field | Detail |
|-------|--------|
| Input | `set_code: str`, `start_date: str` (YYYY-MM-DD, **required**), `end_date: str` (YYYY-MM-DD, **required**), `event_type: str = "PremierDraft"` |
| Output | Per-color-pair: win rate, games played. Includes mono-color, two-color, and summary rows |
| Backend | `SeventeenLandsClient.color_ratings()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## EDHREC Backend (namespace: `edhrec`)

### `edhrec_commander_staples`
Get the most-played cards for a commander, with synergy scores and inclusion rates.

| Field | Detail |
|-------|--------|
| Input | `commander_name: str`, `category: str | None = None` (e.g. "creatures", "enchantments", "lands") |
| Output | Top cards with: name, synergy score, inclusion %, total decks analyzed |
| Backend | `EDHRECClient.commander_top_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `edhrec_card_synergy`
Get synergy data for a specific card with a specific commander.

| Field | Detail |
|-------|--------|
| Input | `card_name: str`, `commander_name: str` |
| Output | Synergy score, inclusion %, number of decks, whether it's a "signature card" |
| Backend | `EDHRECClient.card_synergy()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Scryfall Bulk Data Backend (namespace: `bulk`)

### `bulk_card_lookup`
Look up a Magic card by exact name using Scryfall bulk data. Rate-limit-free.

| Field | Detail |
|-------|--------|
| Input | `name: str` |
| Output | Full card data: name, mana cost, type, oracle text, colors, color identity, P/T, keywords, prices, legalities, EDHREC rank, image URIs |
| Backend | `ScryfallBulkClient.get_card()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_card_search`
Search for Magic cards in Scryfall bulk data by name, type, or oracle text. Rate-limit-free.

| Field | Detail |
|-------|--------|
| Input | `query: str`, `search_field: str = "name"` (one of "name", "type", "text"), `limit: int = 20` |
| Output | Formatted list of matching cards with name, mana cost, type line |
| Backend | `ScryfallBulkClient.search_cards()` / `search_by_type()` / `search_by_text()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Workflow Tools (orchestrator, no namespace)

Workflow tools compose data from multiple backends. They are implemented as pure async functions
in `workflows/` modules and wrapped as MCP tools in `workflows/server.py`. All use
`asyncio.gather(return_exceptions=True)` for concurrent backend calls with graceful partial failure.

### `commander_overview`
Comprehensive data for a commander from all available sources.

| Field | Detail |
|-------|--------|
| Input | `commander_name: str` |
| Output | Markdown with: card header (name, mana cost, type, text, color identity, P/T, rarity, EDHREC rank), top 5 combos (card lists + results), top 10 EDHREC staples (by inclusion, with synergy), Data Sources footer |
| Backends | Scryfall (required) + Spellbook (optional) + EDHREC (optional) |
| Partial failure | Scryfall failure propagates. Spellbook/EDHREC failures noted in output, available data still returned |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `evaluate_upgrade`
Assess whether a card is worth adding to a specific commander deck.

| Field | Detail |
|-------|--------|
| Input | `card_name: str`, `commander_name: str` |
| Output | Markdown with: card details (name, mana cost, type, text, price, EDHREC rank), synergy section (score, inclusion rate, deck count), top 5 combos enabled, Data Sources footer |
| Backends | Scryfall (required) + Spellbook (optional) + EDHREC (optional) |
| Partial failure | Scryfall failure propagates. Spellbook/EDHREC failures noted in output |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `draft_pack_pick`
Rank cards in a draft pack using 17Lands data.

| Field | Detail |
|-------|--------|
| Input | `pack: list[str]` (card names), `set_code: str`, `current_picks: list[str] | None = None` |
| Output | Markdown table ranked by GIH WR descending, with: color, rarity, GIH WR (%), ALSA, IWD (+/-%), game count. Optional color fit analysis ([on-color]/[off-color]) when `current_picks` provided. "No data" section for unrecognized cards |
| Backends | 17Lands only (already has name, color, rarity — no Scryfall needed) |
| Error | Raises `ToolError` if 17Lands is disabled |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `suggest_cuts`
Identify the weakest cards to cut from a commander decklist.

| Field | Detail |
|-------|--------|
| Input | `decklist: list[str]`, `commander_name: str`, `num_cuts: int = 5` |
| Output | Markdown with: data source status, ranked cut candidates with reasoning (synergy/inclusion for EDHREC data, "PROTECTED — combo piece" for combo cards, "Low confidence — no data found" for unknown cards), failure notes |
| Backends | Spellbook (required) + EDHREC (optional) |
| Scoring | Low synergy + low inclusion = more cuttable. Combo pieces protected (-2.0). No data = slight penalty (+0.5) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `card_comparison`
Compare 2-5 cards side-by-side for a specific commander deck.

| Field | Detail |
|-------|--------|
| Input | `cards: list[str]` (2-5 card names), `commander_name: str` |
| Output | Markdown comparison table with: name, mana cost, type, synergy, inclusion %, combo count, price for each card |
| Backends | Scryfall (required) + Spellbook (required) + EDHREC (optional) |
| Partial failure | Card not found propagates. EDHREC/Spellbook failures show "N/A" per card |
| Progress | Reports progress (1/3 resolving, 2/3 fetching data, 3/3 formatting) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `budget_upgrade`
Suggest budget-friendly upgrades for a commander deck.

| Field | Detail |
|-------|--------|
| Input | `commander_name: str`, `budget: float` (max price per card in USD), `num_suggestions: int = 10` |
| Output | Markdown table ranked by synergy-per-dollar: name, synergy, inclusion %, price, synergy/$ |
| Backends | Scryfall (required, for prices) + EDHREC (required, for staples) |
| Error | Returns message if EDHREC disabled, no staples found, or no cards under budget |
| Progress | Reports progress (1/2 fetching staples, 2/2 fetching prices) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `deck_analysis`
Full decklist health check — mana curve, colors, combos, bracket, budget, synergy.

| Field | Detail |
|-------|--------|
| Input | `decklist: list[str]`, `commander_name: str` |
| Output | Markdown with: mana curve distribution table, color pip requirements, combos & bracket estimate, total/average budget, 5 lowest-synergy cards, unresolved cards, Data Sources footer |
| Backends | Scryfall bulk data/Scryfall API (card data) + Spellbook (combos/bracket) + EDHREC (synergy) |
| Card resolution | Uses bulk-data-first strategy via `card_resolver` with Scryfall API fallback |
| Partial failure | Degrades gracefully — all backends except Scryfall are optional |
| Progress | Reports progress (1/3 resolving, 2/3 combos/bracket, 3/3 synergy) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `set_overview`
Draft format overview — top commons/uncommons and trap rares.

| Field | Detail |
|-------|--------|
| Input | `set_code: str`, `event_type: str = "PremierDraft"` |
| Output | Markdown with: event type, median GIH WR, cards with data count, top 10 commons table (rank, name, color, GIH WR, ALSA, IWD, games), top 10 uncommons table, trap rares/mythics list (GIH WR below median) |
| Backends | 17Lands only |
| Error | Raises `ToolError` if 17Lands is disabled |
| Progress | Reports progress (1/2 fetching, 2/2 analyzing) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Prompts (workflow server)

Prompts are user-invocable templates registered on the workflow server. They guide multi-step analysis workflows by generating structured instructions for the AI assistant.

### `evaluate_commander_swap`
Evaluate swapping a card in a Commander deck.

| Field | Detail |
|-------|--------|
| Input | `commander: str`, `adding: str`, `cutting: str` |
| Output | Multi-step prompt: look up both cards, compare synergy via `card_comparison`, check combo implications via `spellbook_find_combos`, recommend SWAP/KEEP/CONSIDER |

### `deck_health_check`
Guide a comprehensive deck health assessment.

| Field | Detail |
|-------|--------|
| Input | `commander: str` |
| Output | Multi-step prompt: run `deck_analysis` with full decklist, run `suggest_cuts`, analyze mana curve/colors/bracket, provide prioritized recommendations |

### `draft_strategy`
Guide a draft format preparation session.

| Field | Detail |
|-------|--------|
| Input | `set_code: str` |
| Output | Multi-step prompt: use `set_overview` for card ratings, analyze top archetypes with key commons/uncommons, provide draft heuristics cheat sheet with GIH WR/IWD/ALSA thresholds |

### `find_upgrades`
Guide a budget upgrade session for a Commander deck.

| Field | Detail |
|-------|--------|
| Input | `commander: str`, `budget: float` |
| Output | Multi-step prompt: use `budget_upgrade` for ranked suggestions, use `evaluate_upgrade` on top 5, evaluate by synergy/$, combo potential, inclusion rate, recommend top 3-5 |

---

## Resources (mtg:// URIs)

Resources provide cached data access via URI templates. Each returns JSON for programmatic consumption.

### Scryfall Resources

| URI | Description |
|-----|-------------|
| `mtg://card/{name}` | Card data as JSON by exact name |
| `mtg://card/{name}/rulings` | Card rulings as JSON by card name |

### Spellbook Resources

| URI | Description |
|-----|-------------|
| `mtg://combo/{combo_id}` | Combo details as JSON by Spellbook ID |

### 17Lands Resources

| URI | Description |
|-----|-------------|
| `mtg://draft/{set_code}/ratings` | Card ratings for a set as JSON |

### EDHREC Resources

| URI | Description |
|-----|-------------|
| `mtg://commander/{name}/staples` | Commander staples data as JSON |

### Scryfall Bulk Data Resources

| URI | Description |
|-----|-------------|
| `mtg://card-data/{name}` | Card data from Scryfall bulk data as JSON |
