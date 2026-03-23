# MTG MCP Server — Service Contracts

API details, authentication, rate limits, and response shapes for each backend service.

---

## Scryfall

**Status:** Official public REST API. Well-documented, stable, generous rate limits.

### Connection Details

| Field | Value |
|-------|-------|
| Base URL | `https://api.scryfall.com` |
| Auth | None (public API) |
| Rate limit | 10 req/sec (50-100ms delay between requests) |
| Required headers | `User-Agent: mtg-mcp/0.1.0` and `Accept: application/json` |
| Documentation | https://scryfall.com/docs/api |

### Key Endpoints

**GET `/cards/named`** — Exact or fuzzy card lookup
```
?exact=Muldrotha, the Gravetide
?fuzzy=muldrotha
```
Returns: Single card object. 404 if not found.

**GET `/cards/search`** — Full Scryfall search syntax
```
?q=commander:sultai+type:creature&page=1
```
Returns: `{ object: "list", total_cards: N, has_more: bool, data: [card, ...] }`

Scryfall search syntax reference: https://scryfall.com/docs/syntax
Key syntax for our use cases:
- `f:commander` — Commander-legal cards
- `id:sultai` or `id<=sultai` — Color identity filtering
- `t:creature` — Type filtering
- `o:"whenever"` — Oracle text search
- `usd<5` — Price filtering

**GET `/cards/{id}`** — Lookup by Scryfall ID (UUID)

**GET `/cards/{id}/rulings`** — Official rulings for a card
Returns: `{ object: "list", data: [{ source, published_at, comment }] }`

**GET `/sets`** — List all sets
**GET `/sets/{code}`** — Set details by code

### Response Shape (Card Object)

Key fields we care about (subset of full response):
```json
{
  "id": "uuid",
  "name": "Muldrotha, the Gravetide",
  "mana_cost": "{3}{B}{G}{U}",
  "cmc": 6.0,
  "type_line": "Legendary Creature — Elemental Avatar",
  "oracle_text": "During each of your turns, you may play...",
  "colors": ["B", "G", "U"],
  "color_identity": ["B", "G", "U"],
  "keywords": [],
  "power": "6",
  "toughness": "6",
  "set": "dom",
  "collector_number": "199",
  "rarity": "mythic",
  "prices": {
    "usd": "5.50",
    "usd_foil": "12.00",
    "eur": "4.80"
  },
  "legalities": {
    "commander": "legal",
    "standard": "not_legal",
    "modern": "legal"
  },
  "image_uris": {
    "normal": "https://...",
    "art_crop": "https://..."
  },
  "scryfall_uri": "https://scryfall.com/card/dom/199",
  "edhrec_rank": 245,
  "related_uris": {
    "edhrec": "https://edhrec.com/route/..."
  }
}
```

### Usage Terms
- Do not paywall access to Scryfall data
- Do not simply repackage/republish — must create additional value
- Image usage: do not crop/distort, keep copyright/artist visible
- Bulk data available for offline use (updates daily)

---

## Commander Spellbook

**Status:** Official public REST API. Open source (MIT license), Django backend.

### Connection Details

| Field | Value |
|-------|-------|
| Base URL | `https://backend.commanderspellbook.com` |
| Auth | None (public API) |
| Rate limit | No documented limit. Community practice: ~2-5 req/sec is safe. Backoff on 429. |
| Documentation | https://backend.commanderspellbook.com/schema/swagger/ (Swagger), `/schema/` (raw OpenAPI), `/schema/redoc/` (ReDoc) |
| Source | https://github.com/SpaceCowMedia/commander-spellbook-backend |

### Key Endpoints

**GET `/variants/`** — Search combos
```
?q=card:"Muldrotha" coloridentity:sultai
```
Search syntax: https://commanderspellbook.com/syntax-guide/
The `q` parameter supports aliases for common filters: `card:` or `cards:`, `coloridentity:` or `color`, `ci`, `id`, etc.
Pagination uses `limit` and `offset` (not `page`). Also supports `ordering` and `groupByCombo`.
Additional useful query params: `commander:`, `bracket:`, `popularity:`, `legal:`.
Returns: Paginated list of combo variants.

**GET `/variants/{id}/`** — Combo detail by ID
Returns: Single combo variant object.

**POST `/estimate-bracket`** — Bracket estimation
```json
{
  "commanders": [{"card": "Muldrotha, the Gravetide", "quantity": 1}],
  "main": [{"card": "Sol Ring", "quantity": 1}, {"card": "Spore Frog", "quantity": 1}]
}
```
Also accepts plain-text decklist format with `// Commander` section headers.
Returns: Bracket-relevant combo information with fields: `bracketTag`, `bannedCards`, `gameChangerCards`, `massLandDenialCards`, `massLandDenialTemplates`, `massLandDenialCombos`, `extraTurnCards`, `extraTurnTemplates`, `extraTurnsCombos`, `lockCombos`, `controlAllOpponentsCombos`, `controlSomeOpponentsCombos`, `skipTurnsCombos`, `twoCardCombos`.

**POST `/find-my-combos`** — Find combos in a decklist
Same request body format as `/estimate-bracket`. Returns combos categorized as `included`, `almostIncluded`, `almostIncludedByAddingColors`. Very useful for workflow tools like `suggest_cuts` and `evaluate_upgrade`.

### Response Shape (Combo Variant)

```json
{
  "id": "1414-2730-5131-5256",
  "status": "OK",
  "uses": [{
    "card": {
      "id": 5131,
      "name": "Muldrotha, the Gravetide",
      "oracleId": "uuid",
      "typeLine": "Legendary Creature — Elemental Avatar",
      "spoiler": false
    },
    "quantity": 1,
    "zoneLocations": ["C"],
    "battlefieldCardState": "",
    "exileCardState": "",
    "libraryCardState": "",
    "graveyardCardState": "",
    "mustBeCommander": true
  }],
  "requires": [{
    "template": {
      "id": 123,
      "name": "A permanent card in your graveyard",
      "scryfallQuery": "...",
      "scryfallApi": "..."
    },
    "quantity": 1,
    "zoneLocations": ["G"]
  }],
  "produces": [{
    "feature": {
      "id": 7,
      "name": "Infinite death triggers",
      "uncountable": true
    },
    "quantity": 1
  }],
  "of": [{"id": 1167}],
  "identity": "BGU",
  "manaNeeded": "",
  "manaValueNeeded": 0,
  "easyPrerequisites": "All permanents on the battlefield.",
  "notablePrerequisites": "",
  "description": "Step-by-step combo description...",
  "notes": "",
  "popularity": 3382,
  "bracketTag": "E",
  "legalities": {"commander": true},
  "prices": {
    "tcgplayer": "63.22",
    "cardmarket": "31.17",
    "cardkingdom": "63.26"
  },
  "variantCount": 1
}
```

Notes:
- `zoneLocations` uses single-letter codes: B=Battlefield, H=Hand, G=Graveyard, E=Exile, L=Library, C=Command Zone
- `bracketTag` is a single letter (e.g., "E"), not human-readable labels
- `of` contains only combo IDs — prerequisites, steps, and results are flattened into `easyPrerequisites`, `notablePrerequisites`, and `description`
- `produces` wraps each result in a `{"feature": {...}, "quantity": N}` object

### Bracket Mapping

Bracket tags in the API use single-letter codes (e.g., "E") rather than human-readable labels. The old documentation referenced labels like "Ruthless", "Spicy", "Powerful", etc., but these are not what the API actually returns. The mapping from single-letter codes to bracket numbers (1-4) will need to be reverse-engineered when we implement Phase 2.

---

## 17Lands

**Status:** Semi-public API. No official documentation. Used by community tools. Rate limits enforced.

### Connection Details

| Field | Value |
|-------|-------|
| Base URL | `https://www.17lands.com` |
| Auth | None |
| Rate limit | Aggressive — rate-limited after multiple set downloads |
| Public datasets | https://www.17lands.com/public_datasets |
| Usage guidelines | https://www.17lands.com/usage_guidelines |

### Key Endpoints

**GET `/card_ratings/data`** — Card performance data
```
?expansion=LRW&event_type=PremierDraft&start_date=2026-01-20&end_date=2026-03-20
```
The canonical parameter name is `event_type`. The legacy alias `format` also works for this endpoint.
`start_date` and `end_date` are optional but affect which fields are populated (e.g., `avg_pick` may be null without an explicit date range).
Returns: Array of card rating objects.

**GET `/color_ratings/data`** — Archetype win rates
```
?expansion=MKM&event_type=PremierDraft&start_date=2024-02-06&end_date=2024-04-06
```
**Important:** This endpoint REQUIRES `start_date` and `end_date` parameters (returns HTTP 400 without them). This endpoint uses `event_type` NOT `format` as the parameter name.
Returns: Array of color pair performance data.

### Response Shape (Card Rating)

```json
{
  "name": "Nameless Inversion",
  "color": "B",
  "rarity": "common",
  "mtga_id": 12345,
  "url": "https://cards.scryfall.io/normal/front/...",
  "url_back": "",
  "types": ["Tribal", "Instant"],
  "layout": "standard",
  "seen_count": 12500,
  "avg_seen": 4.2,
  "pick_count": 8300,
  "avg_pick": 2.1,
  "game_count": 15000,
  "pool_count": 5000,
  "play_rate": 0.85,
  "win_rate": 0.572,
  "opening_hand_game_count": 3200,
  "opening_hand_win_rate": 0.591,
  "drawn_game_count": 5100,
  "drawn_win_rate": 0.583,
  "ever_drawn_game_count": 8300,
  "ever_drawn_win_rate": 0.587,
  "never_drawn_game_count": 6700,
  "never_drawn_win_rate": 0.554,
  "drawn_improvement_win_rate": 0.033
}
```

Note: `avg_pick` may be null when `start_date`/`end_date` are not provided. `play_rate` may also be null.

Key metrics:
- **GIH WR** (Games in Hand Win Rate / `ever_drawn_win_rate`): Best single metric for card quality
- **ALSA** (Average Last Seen At / `avg_seen`): How late a card wheels — signal for openness
- **OH WR** (`opening_hand_win_rate`): How good is this card early?
- **IWD** (`drawn_improvement_win_rate`): Win rate boost when drawn vs not drawn

### Response Shape (Color Rating)

```json
{
  "is_summary": false,
  "color_name": "Azorius (WU)",
  "short_name": "WU",
  "wins": 38191,
  "games": 68100
}
```

Note: Win rate must be derived as `wins / games`. The array includes mono-color, two-color, three-color, four-color, five-color, and splash variants, plus summary rows (where `is_summary=true`).

### Caveats
- Cards with <500 samples won't have win rate data
- 17Lands users skew slightly above average skill (56% baseline, not 50%)
- Not an official API — may change or rate-limit without notice

---

## EDHREC

**Status:** No official public API. Internal JSON endpoints used by community wrappers.

### Connection Details

| Field | Value |
|-------|-------|
| Base URL | `https://json.edhrec.com` (for JSON data) |
| Alt URL | `https://edhrec.com` (for scraping) |
| Auth | None |
| Rate limit | Self-imposed: 2 req/sec max, respect robots.txt |
| Community wrapper | https://pypi.org/project/pyedhrec/ |

### Key Endpoints (Reverse-Engineered)

**GET `/pages/commanders/{slug}.json`** — Commander page data
```
/pages/commanders/muldrotha-the-gravetide.json
```
Slug format: lowercase, hyphens, no commas/apostrophes.

Returns: Full commander page including top cards by category (creatures, instants, sorceries, etc.), with synergy scores and inclusion percentages.

**GET `/pages/cards/{slug}.json`** — Card page data
```
/pages/cards/spore-frog.json
```

### Response Shape (Commander Page)

The response is large and nested. Key fields:
```json
{
  "header": "Muldrotha, the Gravetide",
  "description": "...",
  "container": {
    "json_dict": {
      "cardlists": [
        {
          "header": "Creatures",
          "cardviews": [
            {
              "name": "Spore Frog",
              "sanitized": "spore-frog",
              "synergy": 0.61,
              "inclusion": 61,
              "num_decks": 12050,
              "label": "61% of 19,741 decks"
            }
          ]
        }
      ]
    }
  }
}
```

Key data points:
- **`synergy`**: Score from -1.0 to 1.0. High synergy = card is specifically good with this commander (not just generically popular)
- **`inclusion`**: Percentage of decks running this card
- **`num_decks`**: Total decks analyzed

### Fragility Warning

These are undocumented internal endpoints. They WILL break eventually. Design the EDHREC service to:
1. Cache aggressively (24hr TTL)
2. Fail gracefully — EDHREC being down should never crash the orchestrator
3. Have fixture-based tests that don't hit the real endpoints
4. Log warnings when response shapes don't match expected models

---

## MTGJSON

**Status:** Open-source card data project. Bulk JSON file downloads. No rate limits.

### Connection Details

| Field | Value |
|-------|-------|
| Data URL | `https://mtgjson.com/api/v5/AtomicCards.json.gz` (~20MB gzipped, ~120MB uncompressed) |
| Auth | None (public downloads) |
| Rate limit | N/A (file download, not API) |
| Update frequency | Daily |
| Documentation | https://mtgjson.com/data-models/ |

### Data File

**`AtomicCards.json.gz`** — Oracle-level card data keyed by display name.

Gzip-compressed JSON file. After decompression, the structure is:
```json
{
  "data": {
    "Sol Ring": [
      {
        "name": "Sol Ring",
        "manaCost": "{1}",
        "type": "Artifact",
        "text": "{T}: Add {C}{C}.",
        "colors": [],
        "colorIdentity": [],
        "types": ["Artifact"],
        "subtypes": [],
        "supertypes": [],
        "keywords": [],
        "power": null,
        "toughness": null,
        "manaValue": 1.0
      }
    ],
    "Muldrotha, the Gravetide": [
      { "..." : "..." }
    ]
  }
}
```

Each card name maps to an array of printings. We use `printings[0]` for oracle data (oracle text is the same across all printings).

### Key Fields Extracted

| MTGJSON Field | Our Model Field | Notes |
|---------------|-----------------|-------|
| `name` | `name` | Display name (front face for DFCs) |
| `manaCost` | `mana_cost` | Mana cost string (e.g. `"{3}{B}{G}{U}"`) |
| `type` | `type_line` | Full type line |
| `text` | `oracle_text` | Oracle text |
| `colors` | `colors` | Color list |
| `colorIdentity` | `color_identity` | Color identity list |
| `types` | `types` | Card types (e.g. `["Creature"]`) |
| `subtypes` | `subtypes` | Subtypes (e.g. `["Elemental", "Avatar"]`) |
| `supertypes` | `supertypes` | Supertypes (e.g. `["Legendary"]`) |
| `keywords` | `keywords` | Keywords (e.g. `["Flying", "Trample"]`) |
| `power` | `power` | Power (nullable) |
| `toughness` | `toughness` | Toughness (nullable) |
| `manaValue` | `mana_value` | Converted mana cost as float |

### What MTGJSON Does NOT Have

- **Prices** — Must use Scryfall for price data
- **Rulings** — Must use Scryfall for official rulings
- **Images** — No image URIs
- **Set-specific data** — AtomicCards is oracle-level, not printing-level
- **Legalities** — Not in the atomic data
- **EDHREC rank** — Not included

### Double-Faced Card (DFC) Handling

AtomicCards keys DFCs by their full display name with `//` separator (e.g. `"Jace, Vryn's Prodigy // Jace, Telepath Unbound"`). The `name` field in each printing contains only the front face name. Our service keys lookups by both:
- The front face name (from `printing.name`)
- The full `//` name (from the dict key)

This allows lookup by either `"Jace, Vryn's Prodigy"` or `"Jace, Vryn's Prodigy // Jace, Telepath Unbound"`.

### Service Architecture

Unlike other services, MTGJSON is **not** a `BaseClient` subclass. It's a file-based service that:
1. Downloads `AtomicCards.json.gz` lazily on first access (not at startup)
2. Decompresses and parses into `dict[str, MTGJSONCard]` keyed by lowercase name
3. Maintains a separate `list[MTGJSONCard]` for substring search
4. Refreshes when `MTG_MCP_MTGJSON_REFRESH_HOURS` has elapsed (default 24h)
5. On refresh failure with existing data, serves stale data rather than failing

### Feature Flag

Behind `MTG_MCP_ENABLE_MTGJSON` (default `true`). When disabled:
- Provider is not mounted on the orchestrator
- Workflow tools skip MTGJSON lookups and go directly to Scryfall
