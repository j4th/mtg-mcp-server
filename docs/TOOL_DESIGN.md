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
| Input | `card_name: str`, `color_identity: str | None = None` (e.g. "sultai", "BUG", "wubrg") |
| Output | List of combos with: cards involved, prerequisites, steps, results. Limited to top 10 by default. |
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

### `spellbook_estimate_bracket`
Estimate the Commander bracket for a decklist based on its combo density.

| Field | Detail |
|-------|--------|
| Input | `commander: str`, `decklist: list[str]` (card names) |
| Output | Bracket estimate (1-4), combos found, bracket-relevant details |
| Backend | `SpellbookClient.estimate_bracket()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

---

## 17Lands Backend (namespace: `draft`)

### `draft_card_ratings`
Get win rate and draft data for cards in a set.

| Field | Detail |
|-------|--------|
| Input | `set_code: str` (e.g. "LRW"), `format: str = "PremierDraft"`, `colors: str | None = None` (e.g. "BG") |
| Output | Per-card: name, color, rarity, GIH WR, OH WR, GD WR, IWD, ALSA, games played |
| Backend | `SeventeenLandsClient.card_ratings()` |
| Annotations | readOnly=true, idempotent=true, openWorld=true |

### `draft_archetype_stats`
Get win rates by color pair/archetype for a set.

| Field | Detail |
|-------|--------|
| Input | `set_code: str`, `format: str = "PremierDraft"` |
| Output | Per-color-pair: win rate, games played, popularity |
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
| Backends | Spellbook (optional) + EDHREC (optional) |
| Scoring | Low synergy + low inclusion = more cuttable. Combo pieces protected (-2.0). No data = slight penalty (+0.5) |
| Annotations | readOnly=true, idempotent=true, openWorld=true |
