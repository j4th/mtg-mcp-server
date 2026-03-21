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
| Rate limit | Reasonable use (no documented limit) |
| Documentation | https://backend.commanderspellbook.com/api/docs (Swagger) |
| Source | https://github.com/SpaceCowMedia/commander-spellbook-backend |

### Key Endpoints

**GET `/api/variants/`** — Search combos
```
?q=card:"Muldrotha" coloridentity:sultai
```
Search syntax: https://commanderspellbook.com/syntax-guide/
Returns: Paginated list of combo variants.

**POST `/api/estimate-bracket/`** — Bracket estimation
```json
{
  "commanders": ["Muldrotha, the Gravetide"],
  "main": ["Sol Ring", "Spore Frog", ...]
}
```
Returns: Bracket-relevant combo information.

### Response Shape (Combo Variant)

```json
{
  "id": "2120-5329",
  "uses": [
    {
      "card": {
        "name": "Muldrotha, the Gravetide",
        "oracleId": "uuid"
      },
      "zoneLocations": ["COMMAND_ZONE"],
      "battlefieldCardState": ""
    }
  ],
  "requires": [
    {
      "template": {
        "name": "A permanent card in your graveyard"
      }
    }
  ],
  "produces": [
    { "name": "Infinite ETB triggers" }
  ],
  "of": {
    "id": "2120",
    "prerequisites": ["All permanents on the battlefield"],
    "steps": ["Cast X from graveyard..."],
    "results": ["Infinite ETB triggers"]
  }
}
```

### Bracket Mapping

Spellbook categorizes combos into thematic buckets that map to brackets:
- Ruthless → Bracket 4
- Spicy → Bracket 3
- Powerful → Bracket 3
- Oddball → Bracket 2
- Precon Appropriate → Bracket 2
- Casual → Bracket 1

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
?expansion=LRW&format=PremierDraft&start_date=2026-01-20&end_date=2026-03-20
```
Returns: Array of card rating objects.

**GET `/color_ratings/data`** — Archetype win rates
```
?expansion=LRW&format=PremierDraft
```
Returns: Array of color pair performance data.

### Response Shape (Card Rating)

```json
{
  "name": "Nameless Inversion",
  "color": "B",
  "rarity": "common",
  "seen_count": 12500,
  "avg_seen": 4.2,
  "pick_count": 8300,
  "avg_pick": 2.1,
  "game_count": 15000,
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

Key metrics:
- **GIH WR** (Games in Hand Win Rate / `ever_drawn_win_rate`): Best single metric for card quality
- **ALSA** (Average Last Seen At / `avg_seen`): How late a card wheels — signal for openness
- **OH WR** (`opening_hand_win_rate`): How good is this card early?
- **IWD** (`drawn_improvement_win_rate`): Win rate boost when drawn vs not drawn

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
