# MTG MCP Server — Tool Catalog

Every tool the server exposes, organized by source. Tools prefixed with a namespace come from mounted backend servers. Unprefixed tools are workflow tools on the orchestrator.

---

## Scryfall Backend (namespace: `scryfall`)

### `scryfall_search_cards`
Search for cards using Scryfall's full search syntax.

| Field | Detail |
|-------|--------|
| Input | `query: str` (Scryfall syntax, e.g. `"f:commander id:sultai t:creature cmc<=3"`), `page: int = 1`, `limit: int = 30` (0 for all), `response_format: "detailed" \| "concise" = "detailed"` |
| Output | Formatted list of matching cards with name, type, mana cost, price. Pagination info. Structured content uses slim card fields. |
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

### `scryfall_set_info`
Get set metadata by set code.

| Field | Detail |
|-------|--------|
| Input | `set_code: str` (e.g. "dom", "mkm") |
| Output | Set name, code, release date, set type, card count, icon URI |
| Backend | `ScryfallClient.get_set()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `scryfall_whats_new`
Get recently released or previewed cards.

| Field | Detail |
|-------|--------|
| Input | `days: int = 30` |
| Output | List of recently released cards with names, sets, rarities |
| Backend | `ScryfallClient.search_cards()` (date filter) |
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
| Input | `set_code: str` (e.g. "LCI", "MKM", "OTJ"), `event_type: str = "PremierDraft"`, `limit: int = 50` (0 for all), `sort_by: str = "gih_wr"` (also: "alsa", "iwd", "name") |
| Output | Per-card: name, color, rarity, GIH WR, ALSA, IWD, games played. Structured content uses slim rating fields. |
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
| Input | `commander_name: str`, `category: str | None = None` (e.g. "creatures", "enchantments", "lands"), `limit: int = 10` per category (0 for all) |
| Output | Top cards with: name, synergy score, inclusion %, total decks analyzed. Structured content uses slim EDHREC card fields. |
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

### `bulk_format_legality`
Check if a card is legal in a format.

| Field | Detail |
|-------|--------|
| Input | `card_name: str`, `format: str` |
| Output | Legality status (legal, not_legal, banned, restricted) with details |
| Backend | `ScryfallBulkClient.get_card()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_format_search`
Search for cards legal in a specific format.

| Field | Detail |
|-------|--------|
| Input | `format: str`, `query: str`, `limit: int = 20` |
| Output | Formatted list of format-legal matching cards |
| Backend | `ScryfallBulkClient.filter_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_format_staples`
Top-played cards in a format (by EDHREC rank).

| Field | Detail |
|-------|--------|
| Input | `format: str`, `card_type: str | None = None`, `limit: int = 20` |
| Output | Ranked list of staple cards in the format |
| Backend | `ScryfallBulkClient.filter_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_ban_list`
Get banned/restricted cards for a format.

| Field | Detail |
|-------|--------|
| Input | `format: str` |
| Output | List of banned and restricted cards for the format |
| Backend | `ScryfallBulkClient.filter_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_card_in_formats`
Check a card's legality across all formats.

| Field | Detail |
|-------|--------|
| Input | `card_name: str` |
| Output | Table of format legality (legal/not_legal/banned/restricted per format) |
| Backend | `ScryfallBulkClient.get_card()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_random_card`
Get a random card, optionally filtered by format or type.

| Field | Detail |
|-------|--------|
| Input | `format: str | None = None`, `card_type: str | None = None` |
| Output | Random card with full details |
| Backend | `ScryfallBulkClient.filter_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `bulk_similar_cards`
Find cards similar to a given card by type, keywords, or mana cost.

| Field | Detail |
|-------|--------|
| Input | `card_name: str`, `limit: int = 10` |
| Output | List of similar cards with shared attributes highlighted |
| Backend | `ScryfallBulkClient.get_card()` + `filter_cards()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Workflow Tools (orchestrator, no namespace)

Workflow tools compose data from multiple backends. They are implemented as pure async functions
in `workflows/` modules and wrapped as MCP tools in `workflows/server.py`. All use
`asyncio.gather(return_exceptions=True)` for concurrent backend calls with graceful partial failure.

All workflow tools return `ToolResult` with both markdown (`content`) and structured data
(`structured_content`). All accept an optional `response_format: "detailed" | "concise"` parameter
(default `"detailed"`) that controls output verbosity without requiring separate tool variants.

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

### `theme_search`
Search for cards matching a mechanical, tribal, or abstract theme via oracle text patterns.

| Field | Detail |
|-------|--------|
| Input | `theme: str` (e.g. "sacrifice", "lifegain", "tokens"), `color_identity: str | None = None`, `format: str | None = None`, `max_price: float | None = None`, `limit: int = 20` |
| Output | Formatted list of matching cards with type, oracle text excerpt, price. Sorted by match quality. |
| Backends | Bulk data (required) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `build_around`
Detect synergies from 1-5 key cards and find cards that work with them.

| Field | Detail |
|-------|--------|
| Input | `cards: list[str]` (1-5 card names), `format: str` (required), `budget: float | None = None`, `limit: int = 20` |
| Output | Markdown with: resolved cards, detected keywords/mechanics, synergy candidates with type and oracle text, combo potential from Spellbook |
| Backends | Bulk data (required) + Spellbook (required) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `complete_deck`
Gap analysis and card suggestions to fill out a partial decklist.

| Field | Detail |
|-------|--------|
| Input | `decklist: list[str]`, `format: str`, `commander: str | None = None`, `budget: float | None = None` |
| Output | Markdown with: current deck composition, format-specific target size, category gaps (creatures, removal, card draw, etc.), suggested cards per gap |
| Backends | Bulk data (required) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `commander_comparison`
Compare 2-5 commanders head-to-head across card data, combos, and EDHREC popularity.

| Field | Detail |
|-------|--------|
| Input | `commanders: list[str]` (2-5 names) |
| Output | Markdown comparison table with: mana cost, type, color identity, EDHREC rank, combo count, top staples, unique strengths |
| Backends | Bulk data (required) + Spellbook (required) + EDHREC (optional) |
| Partial failure | EDHREC failure degrades to N/A for staple data |
| Progress | Reports progress (1/3 resolving, 2/3 fetching data, 3/3 formatting) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `tribal_staples`
Best cards for a creature type within a color identity.

| Field | Detail |
|-------|--------|
| Input | `tribe: str` (e.g. "Elf", "Zombie"), `color_identity: str | None = None` (e.g. "golgari"), `format: str | None = None` |
| Output | Markdown with: lords, synergy pieces, tribe members, support cards — each with oracle text and price |
| Backends | Bulk data (required) + EDHREC (optional) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `precon_upgrade`
Analyze a precon decklist and suggest swaps — pair weakest cards with upgrade candidates.

| Field | Detail |
|-------|--------|
| Input | `decklist: list[str]`, `commander: str`, `budget: float = 50.0`, `num_upgrades: int = 10` |
| Output | Markdown with: data source status, ranked swap pairs (cut → add with reasoning), upgrade priority based on synergy delta |
| Backends | Bulk data (required) + Spellbook (required) + EDHREC (optional) |
| Scoring | Cuts scored by low synergy + low inclusion. Upgrades ranked by synergy improvement |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `color_identity_staples`
Top-played cards across all commanders in a color identity.

| Field | Detail |
|-------|--------|
| Input | `color_identity: str` (e.g. "simic", "UG"), `category: str | None = None` (e.g. "creatures") |
| Output | Markdown with: staple cards ranked by EDHREC rank (popularity), with prices |
| Backends | Bulk data (required) + EDHREC (optional, for enrichment) |
| Partial failure | Degrades gracefully when EDHREC is disabled — falls back to EDHREC rank from bulk data |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `sealed_pool_build`
Suggest the best 40-card sealed deck builds from a card pool.

| Field | Detail |
|-------|--------|
| Input | `pool: list[str]` (card names, typically 84-90), `set_code: str` |
| Output | Markdown with: top 1-3 two-color builds ranked by total score, per-build card list grouped by type, mana curve, removal/bomb counts |
| Backends | Bulk data (required) + 17Lands (optional, for GIH WR scoring) |
| Scoring | GIH WR when available, heuristic fallback (rarity + bomb/removal detection) |
| Progress | Reports progress (1/3 resolving, 2/3 evaluating pairs, 3/3 formatting) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `draft_signal_read`
Analyze draft picks to detect open color signals and recommend direction.

| Field | Detail |
|-------|--------|
| Input | `picks: list[str]` (in draft order), `set_code: str`, `current_pack: list[str] | None = None` |
| Output | Markdown with: color commitment analysis, ALSA-based openness signals per color, recommended direction, optional current pack ranking |
| Backends | Bulk data (required) + 17Lands (required) |
| Error | Raises `ToolError` if 17Lands disabled |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `draft_log_review`
Review a completed draft — pick-by-pick GIH WR analysis with overall grade.

| Field | Detail |
|-------|--------|
| Input | `picks: list[str]` (P1P1 through P3P14), `set_code: str`, `final_deck: list[str] | None = None` |
| Output | Markdown with: pick-by-pick table (pick#, name, GIH WR, verdict), average GIH WR, letter grade, optional deck inclusion analysis |
| Backends | Bulk data (required) + 17Lands (required) |
| Grading | A (≥60% avg GIH WR) through F (<50%) |
| Error | Raises `ToolError` if 17Lands disabled |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `rotation_check`
Check Standard rotation status and which cards are in rotating sets.

| Field | Detail |
|-------|--------|
| Input | `cards: list[str] | None = None` |
| Output | Markdown with: Standard-legal sets sorted by release date, rotation timing, optional per-card rotation status |
| Backends | Scryfall API (sets) + Bulk data (card legality) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `deck_validate`
Validate a decklist against format construction rules.

| Field | Detail |
|-------|--------|
| Input | `decklist: list[str]`, `format: str`, `commander: str | None = None`, `sideboard: list[str] | None = None` |
| Output | Markdown with: VALID/INVALID status, per-card legality issues, deck size check, copy limit violations, color identity violations (Commander), rarity check (Pauper) |
| Backends | Bulk data (required) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `suggest_mana_base`
Suggest a mana base based on color pip distribution.

| Field | Detail |
|-------|--------|
| Input | `decklist: list[str]`, `format: str`, `total_lands: int | None = None` |
| Output | Markdown with: color pip analysis, recommended land count, basic land distribution, format-legal dual land suggestions |
| Backends | Bulk data (required) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `price_comparison`
Compare prices across multiple cards using bulk data.

| Field | Detail |
|-------|--------|
| Input | `cards: list[str]` |
| Output | Markdown price table with: USD, USD foil, EUR per card, total cost |
| Backends | Bulk data (required) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Rules Engine Tools (orchestrator, no namespace)

Rules tools provide access to the Magic: The Gathering Comprehensive Rules. Backed by a local rules parser service.

### `rules_lookup`
Look up rules by number or keyword search.

| Field | Detail |
|-------|--------|
| Input | `query: str` (rule number like "704.5k" or keyword like "deathtouch"), `section: str | None = None` |
| Output | Markdown with: matching rules with full text, parent/child rules, cross-references |
| Backends | RulesService (local) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `keyword_explain`
Explain a Magic keyword with glossary definition, rules, and example cards.

| Field | Detail |
|-------|--------|
| Input | `keyword: str` (e.g. "deathtouch", "trample") |
| Output | Markdown with: glossary definition, related rules, example cards (if bulk data available) |
| Backends | RulesService (local) + Bulk data (optional, for card examples) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `rules_interaction`
Explain how two mechanics interact with relevant rule citations.

| Field | Detail |
|-------|--------|
| Input | `mechanic_a: str`, `mechanic_b: str` |
| Output | Markdown with: rules for each mechanic, interaction analysis, relevant rule citations |
| Backends | RulesService (local) + Bulk data (optional, for card lookups) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `rules_scenario`
Provide rules framework for a game scenario.

| Field | Detail |
|-------|--------|
| Input | `scenario: str` (game situation description) |
| Output | Markdown with: extracted keywords/concepts, relevant rules per concept, organized framework for LLM reasoning |
| Backends | RulesService (local) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `combat_calculator`
Provide combat phase rules framework with card data.

| Field | Detail |
|-------|--------|
| Input | `attackers: list[str]`, `blockers: list[str]`, `keywords: list[str] | None = None` |
| Output | Markdown with: step-by-step combat phases, attacker/blocker card data, relevant combat rules, keyword interactions |
| Backends | RulesService (local) + Bulk data (optional, for card lookups) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## Prompts (workflow server)

Prompts are user-invocable templates registered on the workflow server. They guide multi-step analysis workflows by generating structured instructions for the AI assistant. 17 prompts total.

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

### `build_deck`
Guide building a deck from scratch for any format.

| Field | Detail |
|-------|--------|
| Input | `concept: str`, `format: str`, `budget: float | None = None` |
| Output | Multi-step prompt: format search for key cards, format staples, mana curve/color assembly, deck_validate, suggest_mana_base |

### `evaluate_collection`
Evaluate a card collection for trade and deck-building value.

| Field | Detail |
|-------|--------|
| Input | `cards: str` (comma-separated list of card names) |
| Output | Multi-step prompt: price lookup, format legality, Commander staple potential |

### `format_intro`
Introduction to a Magic format with key cards and strategies.

| Field | Detail |
|-------|--------|
| Input | `format: str` |
| Output | Multi-step prompt: format staples, top archetypes, entry budget |

### `card_alternatives`
Find alternatives to a card for budget or format reasons.

| Field | Detail |
|-------|--------|
| Input | `card_name: str`, `format: str`, `budget: float` |
| Output | Multi-step prompt: card analysis, similar card search, price comparison, ranked alternatives |

### `rules_question`
Ask a rules question with full Comprehensive Rules citations.

| Field | Detail |
|-------|--------|
| Input | `question: str` |
| Output | Multi-step prompt: rules lookup, keyword explanation, scenario resolution |

### `build_around_deck`
Build a deck around specific cards or a win condition in any format.

| Field | Detail |
|-------|--------|
| Input | `cards: str`, `format: str`, `budget: float | None = None` |
| Output | Multi-step prompt: theme/synergy search → build_around → rotation_check (if Standard) → complete_deck → deck_validate → suggest_mana_base |

### `build_tribal_deck`
Build a tribal deck for any format.

| Field | Detail |
|-------|--------|
| Input | `tribe: str`, `format: str`, `commander: str | None = None`, `budget: float | None = None` |
| Output | Multi-step prompt: tribal_staples → build_around → suggest_mana_base → deck_validate |

### `build_theme_deck`
Build a themed deck around a strategy or archetype.

| Field | Detail |
|-------|--------|
| Input | `theme: str`, `format: str`, `color_identity: str | None = None`, `budget: float | None = None` |
| Output | Multi-step prompt: theme_search → build_around → complete_deck → deck_validate → suggest_mana_base |

### `upgrade_precon`
Upgrade a precon Commander deck with a budget.

| Field | Detail |
|-------|--------|
| Input | `commander: str`, `budget: float` |
| Output | Multi-step prompt: commander_overview → deck_analysis → suggest_cuts → precon_upgrade → deck_validate |

### `sealed_session`
Guide a sealed deck building session.

| Field | Detail |
|-------|--------|
| Input | `set_code: str` |
| Output | Multi-step prompt: sealed_pool_build → build evaluation with 17Lands data → sideboard planning |

### `draft_review`
Review a completed draft with analysis and grade.

| Field | Detail |
|-------|--------|
| Input | `set_code: str` |
| Output | Multi-step prompt: draft_log_review → draft_signal_read analysis |

### `compare_commanders`
Compare commanders to choose between them.

| Field | Detail |
|-------|--------|
| Input | `commanders: str` |
| Output | Multi-step prompt: commander_comparison → combo analysis → staples comparison |

### `rotation_plan`
Plan for Standard rotation — identify rotating cards and replacements.

| Field | Detail |
|-------|--------|
| Input | *(no parameters)* |
| Output | Multi-step prompt: rotation_check → bulk_similar_cards for replacements → price_comparison |

---

## Resources (mtg:// URIs)

Resources provide cached data access via URI templates. Each returns JSON for programmatic consumption.

### Scryfall Resources

| URI | Description |
|-----|-------------|
| `mtg://card/{name}` | Card data as JSON by exact name |
| `mtg://card/{name}/rulings` | Card rulings as JSON by card name |
| `mtg://set/{code}` | Set metadata as JSON by set code |

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
| `mtg://format/{format}/legal-cards` | Legal cards in a format |
| `mtg://format/{format}/banned` | Banned cards in a format |
| `mtg://card/{name}/formats` | Format legality for a card |
| `mtg://card/{name}/similar` | Similar cards by type, keywords, or mana cost |

### Rules Resources

| URI | Description |
|-----|-------------|
| `mtg://rules/{number}` | Rule text by number (e.g. "702.2") |
| `mtg://rules/glossary/{term}` | Glossary definition for a term |
| `mtg://rules/keywords` | List of all keywords with rule references |
| `mtg://rules/sections` | List of all rule sections |

### Format Workflow Resources

| URI | Description |
|-----|-------------|
| `mtg://theme/{theme}` | Cards matching a theme (oracle text patterns) |
| `mtg://tribe/{tribe}/staples` | Staple cards for a creature type |
| `mtg://draft/{set_code}/signals` | Draft color openness signals for a set |
