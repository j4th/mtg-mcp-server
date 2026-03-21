# MTG MCP Server — Data Sources Reference

All data sources evaluated for the MTG MCP server, organized by implementation priority. Covers what data each provides, how to authenticate, how to access it, and known constraints.

---

## Tier 1: Proper APIs — Build First

These have official or well-documented REST APIs with clear access patterns.

| | Scryfall | Commander Spellbook |
|---|---|---|
| **URL** | `https://api.scryfall.com` | `https://backend.commanderspellbook.com` |
| **What it has** | Complete MTG card database: every card ever printed with oracle text, types, colors, mana costs, legalities, prices (USD/EUR/TIX), rulings, set metadata, art URIs. Full-text search with powerful query syntax. Bulk data downloads. | Every known Commander combo: cards involved, prerequisites, step-by-step instructions, results, color identity. Bracket/power-level estimation. Search by card, color identity, or result type. |
| **Auth** | None. Public API. Requires `User-Agent` header (app name) and `Accept` header on every request. | None. Public API. No special headers required. |
| **Access method** | REST API. GET for searches/lookups, POST for batch collection lookups (up to 75 cards). Paginated responses with `has_more` + `next_page`. | REST API (Django REST Framework). GET with query string using Spellbook search syntax. POST for bracket estimation. Paginated. |
| **Rate limit** | 50-100ms between requests (~10/sec). HTTP 429 on exceed. | Undocumented. ~2-5 req/sec is safe. Backoff on 429. |
| **Caching** | Prices update once daily. Card data changes infrequently. Cache cards 24h, searches 1h, sets 7d. | Combos update infrequently. Cache 24h. |
| **Docs** | https://scryfall.com/docs/api | Swagger at backend URL. Source: https://github.com/SpaceCowMedia/commander-spellbook-backend |
| **Key endpoints** | `/cards/search?q=`, `/cards/named?exact=`, `/cards/{id}/rulings`, `/cards/collection` (POST), `/sets`, `/sets/{code}`, `/bulk-data` | `/api/variants/?q=` (combo search), `/api/variants/{id}/` (combo detail), `/estimate-bracket` (POST) |
| **Existing MCP servers** | Multiple (pato/mtg-mcp, artillect/mtg-mcp-servers, ericraio/mtg-mcp) — all basic Scryfall wrappers | None found |
| **Client libraries** | Numerous. We build our own with httpx. | `commander-spellbook` npm package. `pyedhrec` includes some. We build our own. |
| **Notes** | The foundation everything else builds on. Card identity resolution for all other services. Cannot paywall access to Scryfall data per ToS. | Open source (MIT). Powers EDHREC's combo feature. Bracket labels map to 1-4 scale. |

### MTGJSON (Supplementary Tier 1)

| | |
|---|---|
| **URL** | `https://mtgjson.com` |
| **What it has** | Canonical open-source card database as JSON files. AllCards, AllSets, full deck data. Same underlying data as Scryfall but in downloadable bulk format. |
| **Auth** | None. Public downloads. |
| **Access method** | Static JSON file downloads. No REST API for queries — download and parse locally. |
| **Rate limit** | N/A (file downloads). |
| **Use case** | Local cache/reference layer to reduce Scryfall API calls for basic card lookups. Not needed immediately — Scryfall API is sufficient. |

---

## Tier 2: High Value — Creative Access Required

These provide critical data but lack official public APIs. Access is through undocumented endpoints, bulk data downloads, or scraping.

| | 17Lands | EDHREC | Moxfield |
|---|---|---|---|
| **URL** | `https://www.17lands.com` | `https://edhrec.com` / `https://json.edhrec.com` | `https://www.moxfield.com` |
| **What it has** | Draft/sealed performance data from Arena: per-card win rates (GIH WR, OH WR, GND WR, IWD), pick rates (ALSA, ATA), archetype win rates by color pair, sample sizes. The gold standard for limited format analytics. | Commander metagame data: top cards per commander with synergy scores and inclusion rates, average decklists, card recommendations by theme, combo data (via Commander Spellbook). The primary deckbuilding resource for Commander. | Collection management, deck building, deck sharing. User-specific data: owned cards, deck lists, binders, want lists. |
| **Auth** | None for public data. No API key. | None. No official API exists. | No official public API. Reverse-engineered endpoints require a Moxfield User-Agent header. |
| **Access method** | **Card ratings endpoint** (undocumented but widely used): `GET /card_ratings/data?expansion={SET}&format={EVENT_TYPE}&colors={COLORS}`. **Public datasets**: bulk CSV downloads at `/public_datasets` with per-game and per-draft data. | **Internal JSON endpoints** (reverse-engineered): `GET /pages/commanders/{sanitized-name}.json`, `/pages/cards/{name}.json`, `/pages/average-decks/{name}.json`. Name sanitization: lowercase, spaces→hyphens, strip special chars. `pyedhrec` Python library wraps these. | **Reverse-engineered REST endpoints**. Community wrappers exist (`moxfield-api` npm, `mtg-parser` Python). Deck data accessible by deck ID. Collection data requires authentication. |
| **Rate limit** | Aggressive. Rate-limits after a few rapid requests. 1 req/sec max recommended. Cards need 500+ game samples before win rate data appears. | No official limits. Be very gentle: 1 req/2sec. Endpoints can change without notice. | Undocumented. Respect reasonable use. |
| **Caching** | Card ratings: 4-6h normally, 1h during first week of a new set, 12-24h after format stabilizes. Bulk datasets updated periodically. | 24h for all data. Deck stats update daily. | Per-session for deck lookups. |
| **Docs** | No official API docs. Community blog posts and tools document the endpoints. Joel Nitta's R tutorial covers public datasets well. | No docs. `pyedhrec` library source code is the best reference. EDHREC FAQ describes data sourcing. | No docs. Community reverse-engineering via network inspection. |
| **Fragility** | Medium. The card_ratings endpoint has been stable for years and is used by multiple community tools. Could break or get locked down. | High. Scraping undocumented JSON endpoints. EDHREC can change internal structure at any time. Must be behind a feature flag. | High. No official API commitment. Could change or add auth requirements. |
| **Key metrics / data** | GIH WR (Games In Hand Win Rate) is the primary card quality metric. IWD (Improvement When Drawn) shows how much drawing a card helps. ALSA (Average Last Seen At) shows how late a card wheels. 17Lands user base skews above average — baseline WR is ~56%, not 50%. | Synergy score (+/- percentage vs average deck), inclusion rate (% of decks running the card), number of decks analyzed, card categories (creatures, enchantments, etc.), salt scores. | Deck lists with card counts, categories, tags. Collection with conditions, languages, foil status. Price tracking via TCGPlayer/Cardmarket. |
| **Our priority** | Phase 4. Critical for draft/sealed analytics and Lorwyn Eclipsed prep. | Phase 5. Critical for Commander upgrade recommendations. Behind feature flag due to fragility. | Deferred. Would enable cross-referencing owned collection against upgrade suggestions, but access is unreliable. |

---

## Tier 3: Supplementary / Niche

Useful for specific use cases but not core to the initial build.

| | Spicerack | Archidekt |
|---|---|---|
| **URL** | `https://docs.spicerack.gg/api-reference/public-decklist-database` | `https://archidekt.com` |
| **What it has** | Tournament results database: decklists, standings, Swiss/bracket records, format metadata, Moxfield decklist URLs. Covers competitive paper events across participating stores. | Deck building platform. Public deck data including card lists, categories, stats. EDHREC pulls data from Archidekt (along with Moxfield and Scryfall). |
| **Auth** | None for public endpoint. | None for public decks. Archidekt's position: "reverse-engineer our network requests if you want, but if heavy usage causes problems we'll lock it down." |
| **Access method** | REST API with documented endpoints. Returns JSON with tournament metadata, player standings, and decklist links. | Undocumented REST API. Community `archidekt` npm package wraps some endpoints. Network inspection to discover endpoints. |
| **Rate limit** | Undocumented. Respectful use expected. | No official limits. Risk of lockdown if abused. |
| **Use case** | Relevant if tracking competitive paper results at Taps or analyzing tournament meta. Not needed for core Commander/draft functionality. | Deck data. Less relevant since EDHREC already aggregates from Archidekt. Could be useful for fetching specific public decklists by URL. |
| **Our priority** | Deferred. Potentially useful for Phase 6+ if competitive paper tracking becomes a goal. | Deferred. EDHREC covers the same data in aggregated form. |

---

## Access Pattern Summary

| Source | Auth | Method | Stability | Our Phase |
|--------|------|--------|-----------|-----------|
| Scryfall | None (headers required) | REST API | Rock solid | Phase 1 |
| Commander Spellbook | None | REST API | Solid (open source) | Phase 2 |
| MTGJSON | None | File download | Solid | Optional cache layer |
| 17Lands | None | Undocumented REST + bulk CSV | Stable but unofficial | Phase 3 |
| EDHREC | None | Reverse-engineered JSON | Fragile — feature flag | Phase 4 |
| Moxfield | User-Agent header | Reverse-engineered REST | Fragile | Deferred |
| Spicerack | None | Documented REST API | Solid | Deferred |
| Archidekt | None | Reverse-engineered REST | Fragile | Deferred |
