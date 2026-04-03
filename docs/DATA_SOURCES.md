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
| **Docs** | https://scryfall.com/docs/api | Swagger at `/schema/swagger/`. Source: https://github.com/SpaceCowMedia/commander-spellbook-backend |
| **Key endpoints** | `/cards/search?q=`, `/cards/named?exact=`, `/cards/{id}/rulings`, `/cards/collection` (POST), `/sets`, `/sets/{code}`, `/bulk-data` | `/variants/?q=` (combo search), `/variants/{id}/` (combo detail), `/find-my-combos` (POST), `/estimate-bracket` (POST) |
| **Existing MCP servers** | Multiple (pato/mtg-mcp, artillect/mtg-mcp-servers, ericraio/mtg-mcp) — all basic Scryfall wrappers | None found |
| **Client libraries** | Numerous. We build our own with httpx. | `commander-spellbook` npm package. `pyedhrec` includes some. We build our own. |
| **Notes** | The foundation everything else builds on. Card identity resolution for all other services. Cannot paywall access to Scryfall data per ToS. | Open source (MIT). Powers EDHREC's combo feature. Bracket labels map to 1-4 scale. |

### Scryfall Oracle Cards Bulk Data (Supplementary Tier 1)

| | |
|---|---|
| **URL** | Discovered via `https://api.scryfall.com/bulk-data` (Oracle Cards type) |
| **What it has** | Every unique card as a JSON array — same shape as Scryfall API responses. Includes oracle text, types, colors, mana costs, legalities, prices (USD/EUR/foil), images, EDHREC rank, keywords. |
| **Auth** | None. Public downloads. |
| **Access method** | JSON file download (~30MB). Parsed into in-memory dict for O(1) lookups. |
| **Rate limit** | N/A (file download). |
| **Use case** | Rate-limit-free card lookup and search. Returns full `Card` objects (same as Scryfall API). Used by workflows for bulk card resolution. Replaces MTGJSON, which lacked prices, legalities, and images. |
| **Notes** | Behind `MTG_MCP_ENABLE_BULK_DATA` feature flag (default `true`). Refreshes every 12h (configurable via `MTG_MCP_BULK_DATA_REFRESH_HOURS`). Non-playable layouts (tokens, emblems, art series) filtered during loading. |

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
| **Our priority** | Complete (Phase 2). Critical for draft/sealed analytics. | Complete (Phase 2). Critical for Commander upgrade recommendations. Behind feature flag due to fragility. | Complete. Public decklist fetching (2 tools). Behind feature flag due to fragility. |

### Spicerack (Documented Public API)

| | |
|---|---|
| **URL** | `https://api.spicerack.gg` |
| **What it has** | Tournament results database: decklists, standings, Swiss/bracket records, format metadata, Moxfield decklist URLs. Covers competitive paper events across participating stores. Formats include Modern, Legacy, Pauper, Pioneer, Standard, Premodern, Commander, and more. |
| **Auth** | None required for public endpoint. Optional `X-API-Key` header for higher rate limits. |
| **Access method** | REST API: `GET /api/export-decklists/?num_days={N}&event_format={FORMAT}`. Returns JSON array of tournaments with embedded standings. |
| **Rate limit** | Undocumented. 1 req/sec recommended. |
| **Caching** | 4h TTL. Tournament results are stable once posted. |
| **Docs** | `https://docs.spicerack.gg/api-reference/public-decklist-database` |
| **Fragility** | Low. Documented public API with stable endpoint. |
| **Key data** | Tournament name, format, date, player count, Swiss rounds, top cut, standings with player name, Swiss record (W-L-D), bracket record, Moxfield decklist URLs. Format names are title-case (e.g. "Modern", "Legacy", "Pauper"). |
| **Our priority** | Complete. 3 tools (recent_tournaments, tournament_results, format_decklists). Fills the competitive constructed metagame gap. |

### MTGGoldfish (HTML Scraping)

| | |
|---|---|
| **URL** | `https://www.mtggoldfish.com` |
| **What it has** | Constructed metagame data: archetype meta shares, sample decklists, format staples (most-played cards with deck inclusion %), deck price estimates. Covers Modern, Legacy, Pioneer, Pauper, Standard, Vintage. |
| **Auth** | None. Requires browser-like User-Agent (blocks bot UAs). |
| **Access method** | HTML scraping with selectolax. No JSON API (returns HTTP 406). Endpoints: `/metagame/{format}/full`, `/archetype/{format}-{slug}`, `/deck/download/{deck_id}` (plaintext), `/format-staples/{format}`. |
| **Rate limit** | Self-imposed: 0.5 req/sec (conservative — no documented limits). |
| **Caching** | Metagame 6h, archetype 12h, staples 12h, price 24h. |
| **Docs** | None. Reverse-engineered from HTML structure. Community confirms no secret API. |
| **Fragility** | High. HTML scraping — structure changes break selectors. Behind feature flag. |
| **Key data** | Archetype name, meta share %, deck count, estimated paper price, archetype colors, key cards. Format staples: card name, % of decks, avg copies played, rank. Decklists: mainboard + sideboard in plaintext `4 Card Name` format. |
| **Our priority** | Complete. 4 tools (metagame, archetype_list, format_staples, deck_price), 1 resource. Fills the constructed metagame gap alongside Spicerack tournament data. |

---

## Tier 3: Supplementary / Niche

Useful for specific use cases but not core to the initial build.

| | Archidekt |
|---|---|
| **URL** | `https://archidekt.com` |
| **What it has** | Deck building platform. Public deck data including card lists, categories, stats. EDHREC pulls data from Archidekt (along with Moxfield and Scryfall). |
| **Auth** | None for public decks. Archidekt's position: "reverse-engineer our network requests if you want, but if heavy usage causes problems we'll lock it down." |
| **Access method** | Undocumented REST API. Community `archidekt` npm package wraps some endpoints. Network inspection to discover endpoints. |
| **Rate limit** | No official limits. Risk of lockdown if abused. |
| **Use case** | Deck data. Less relevant since EDHREC already aggregates from Archidekt. Could be useful for fetching specific public decklists by URL. |
| **Our priority** | Deferred. EDHREC covers the same data in aggregated form. |

---

## Access Pattern Summary

| Source | Auth | Method | Stability | Status |
|--------|------|--------|-----------|--------|
| Scryfall API | None (headers required) | REST API | Rock solid | Complete |
| Scryfall Bulk Data | None | File download | Rock solid | Complete (replaced MTGJSON) |
| Commander Spellbook | None | REST API | Solid (open source) | Complete |
| 17Lands | None | Undocumented REST + bulk CSV | Stable but unofficial | Complete |
| EDHREC | None | Reverse-engineered JSON | Fragile — feature flag | Complete |
| Comprehensive Rules | None | File download | Stable (Wizards-hosted) | Complete |
| Moxfield | User-Agent header | Reverse-engineered REST | Fragile — feature flag | Complete |
| Spicerack | None (optional API key) | Documented REST API | Solid | Complete |
| MTGGoldfish | None (browser UA required) | HTML scraping | Fragile — feature flag | Complete |
| Archidekt | None | Reverse-engineered REST | Fragile | Deferred |
