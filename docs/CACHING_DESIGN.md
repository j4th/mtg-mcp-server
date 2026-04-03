# MTG MCP Server — Caching Design

> **Status:** Complete (Phase 4).
> **Date:** 2026-03-21

## Problem

All four service clients make unconditional HTTP requests on every invocation. This is wasteful because:

- **17Lands** rate-limits at 1 req/sec — repeated `draft_pack_pick` calls for the same set hammer the API unnecessarily.
- **EDHREC** scrapes undocumented endpoints — minimizing requests reduces breakage risk.
- **Scryfall** card data changes almost never; prices update once daily.
- **Spellbook** combos are added infrequently.

`Settings.disable_cache` exists but no service uses it.

## Decision

**Approach: `cachetools.TTLCache` per service method.**

Each service method gets its own `TTLCache` instance with a method-appropriate TTL and maxsize. A thin `@async_cached` decorator adapts `cachetools.cached` for async functions.

### Why this over alternatives

| Approach | Verdict | Reason |
|----------|---------|--------|
| **cachetools per-method** | **Chosen** | Caches parsed Pydantic models (cache hits skip network + parsing). Per-method TTL granularity. Tiny, mature dependency (65M+ monthly downloads). |
| Hishel HTTP transport | Rejected | Caches raw bytes — every cache hit still re-parses Pydantic models. Per-route TTL is more complex than per-method. Most APIs don't send `Cache-Control` headers, so we'd force TTLs anyway. |
| Hand-rolled dict + timestamp | Rejected | Reinvents `TTLCache` poorly. No eviction, no maxsize, no `cache_info()`. |

### Why cachetools is safe for async

Our server runs a single asyncio event loop — no thread contention on dict access. The `TTLCache` is a dict subclass; reads and writes are atomic in CPython. No locks needed. The only theoretical concern (thundering herd on cold cache) is a non-issue: our rate limiter already serializes outbound requests per service.

## TTL and Maxsize Per Method

| Service | Method | TTL | Maxsize | Rationale |
|---------|--------|-----|---------|-----------|
| Scryfall | `get_card_by_name` | 24h | 500 | Card oracle text, types, colors almost never change |
| Scryfall | `get_card_by_id` | 24h | 500 | Same data, different lookup path |
| Scryfall | `search_cards` | 1h | 100 | Result sets change as new cards are added; shorter TTL ensures fresh results |
| Scryfall | `get_rulings` | 24h | 200 | Rulings change very rarely |
| Scryfall | `get_sets` / `get_set` | 24h | 50 | Set metadata is static after release |
| Spellbook | `find_combos` | 24h | 200 | Combos rarely added to the database |
| Spellbook | `get_combo` | 24h | 100 | Static once created |
| Spellbook | `find_decklist_combos` | 12h | 50 | User-specific query; 12h diverges from the blanket 24h recommendation because decklist analysis may change as the user iterates |
| Spellbook | `estimate_bracket` | 12h | 50 | Same reasoning as `find_decklist_combos` |
| 17Lands | `card_ratings` | 4h | 20 | Safe floor — updates heavily during first week of a set, then stabilizes. 4h balances freshness vs. rate limit protection |
| 17Lands | `color_ratings` | 4h | 20 | Same lifecycle |
| EDHREC | `commander_top_cards` | 24h | 100 | EDHREC aggregates daily |
| EDHREC | `card_synergy` | 24h | 200 | Same aggregation cycle |
| Moxfield | `get_deck` | 4h | 100 | Decklists change infrequently during a session; tournament-winning lists are typically stable |
| Spicerack | `get_tournaments` | 4h | 50 | Tournament data changes infrequently during a session; events added daily but results are stable |
| MTGGoldfish | `get_metagame` | 6h | 50 | Metagame shares shift slowly; 6h balances freshness vs. scraping load |
| MTGGoldfish | `get_archetype` | 12h | 100 | Sample decklists are stable once posted |
| MTGGoldfish | `get_format_staples` | 12h | 50 | Staple rankings shift slowly |
| MTGGoldfish | `get_deck_price` | 24h | 100 | Prices update daily on MTGGoldfish |

**Note on Moxfield cache keys:** The `get_deck` cache uses a custom key function that normalizes Moxfield URLs to raw deck IDs before hashing. This means `get_deck("https://moxfield.com/decks/abc123")` and `get_deck("abc123")` share the same cache entry. The `get_deck_info` method delegates to `get_deck` and benefits from the same cache.

**Note on `card_synergy`:** This method internally delegates to `commander_top_cards` and scans the result. Both are cached independently — this means a cache hit on `card_synergy` skips the scan too, but the two caches may briefly diverge if `commander_top_cards` refreshes first. This is acceptable: the data is from the same daily aggregation, and the worst case is returning slightly stale synergy data for up to 24h.

Maxsize values are conservative estimates of working-set size for a typical session. `TTLCache` evicts least-recently-used entries when full, so overshooting slightly is fine.

## Implementation Sketch

### New dependency

```toml
# pyproject.toml
dependencies = [
    # ... existing ...
    "cachetools>=6.0",
]
```

### Async cache decorator

A thin wrapper in `services/cache.py`:

```python
import functools
from cachetools import TTLCache, keys

def _method_key(*args, **kwargs):
    """Cache key that skips `self` (first arg) for instance methods."""
    return keys.hashkey(*args[1:], **kwargs)

def async_cached(cache: TTLCache, key=_method_key):
    """Decorator for caching async method results in a TTLCache.

    By default uses ``_method_key`` which skips ``self`` so that the cache
    is keyed only on the method arguments, not the instance identity.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            k = key(*args, **kwargs)
            try:
                return cache[k]
            except KeyError:
                pass
            result = await func(*args, **kwargs)
            cache[k] = result
            return result
        wrapper.cache = cache
        return wrapper
    return decorator
```

**Key design choices:**
- `_method_key` skips `self` — the cache is keyed on arguments only, not instance identity. This is correct because each client class has exactly one instance (singleton via lifespan), and avoids accidental duplicate entries if a second instance is ever created (e.g., in tests).
- `@functools.wraps(func)` preserves `__name__`, `__doc__`, and the function signature.

### Cache key edge case

`find_decklist_combos` and `estimate_bracket` take `list[str]` args (POST body), which are unhashable. These methods need a custom key function that converts lists to tuples:

```python
def _decklist_key(*args, **kwargs):
    """Cache key for methods taking list[str] args — converts to tuples."""
    # Skip self (args[0]), tuple-ize remaining positional args
    converted = tuple(tuple(a) if isinstance(a, list) else a for a in args[1:])
    return keys.hashkey(*converted, **kwargs)
```

**Note on caching POST methods:** `find_decklist_combos` and `estimate_bracket` use POST requests, but they are semantically read-only queries that use POST for the request body. Caching is correct here.

### Per-method usage

```python
class ScryfallClient(BaseClient):
    _card_cache = TTLCache(maxsize=500, ttl=86400)

    @async_cached(_card_cache)
    async def get_card_by_name(self, name: str, fuzzy: bool = False) -> Card:
        ...
```

### Cache observability

Log cache hits/misses via structlog for debugging and TTL tuning:

```python
log.debug("cache.hit", method="get_card_by_name", key=name)
log.debug("cache.miss", method="get_card_by_name", key=name)
```

### Config integration

Per-method TTLs are hardcoded as class-level constants (the table above), since they reflect data staleness characteristics of the upstream APIs, not deployment config. A global `Settings.disable_cache: bool = False` flag disables all caching for debugging and testing. The `disable_all_caches()` function in `services/cache.py` sets a module-level kill switch that makes `@async_cached` a no-op.

## Cache Lifecycle

- Caches are class-level `TTLCache` instances — shared across all instances of a client class.
- In practice, each client class has exactly one instance (singleton via lifespan), so this is equivalent to instance-level.
- Cache lives for the server's lifetime. Restarting the server clears all caches.
- No persistence needed — cold-start penalty is one API call per unique query.
- If `enable_edhrec` or `enable_17lands` is `False`, the corresponding client is never instantiated and its class-level cache is never populated (trivial memory cost for empty `TTLCache` objects).

## Testing Strategy

- **Unit tests:** Mock the underlying HTTP call, verify first call hits the API, second call returns cached result without hitting the API.
- **TTL tests:** Use `cachetools.TTLCache` with a short TTL, verify expiry behavior.
- **Cache key tests:** Verify that `(name, fuzzy=True)` and `(name, fuzzy=False)` are cached separately.
- **Test isolation:** Each test fixture must call `.cache.clear()` on cached methods (or replace the class-level `TTLCache` with a fresh instance) to prevent cache state leaking between tests.
- **Workflow tests:** Unchanged — they mock service clients with `AsyncMock`, which bypasses caching entirely.

## What This Does NOT Cover

- **Persistent caching** (SQLite, Redis): Not needed. Server restarts are rare, cold-start penalty is minimal.
- **Cache invalidation API**: No manual invalidation needed. TTL handles freshness. If needed later, each `TTLCache` supports `.clear()`.
- **Shared cache across services**: Each service owns its caches. No cross-service cache sharing.
- **Adaptive TTLs**: 17Lands data updates more frequently during the first week of a new set (could justify 1h TTL) and stabilizes after (12-24h would be fine). The 4h floor is a pragmatic middle ground. Adaptive TTL is possible but not worth the complexity now.

---

## Scryfall Bulk Data Cache

### Overview

Scryfall provides Oracle Cards bulk data — a ~30MB JSON file containing every unique card with full details (oracle text, prices, legalities, images, EDHREC rank). This replaced MTGJSON in Phase 4 because Scryfall bulk data includes prices, legalities, and image URIs that MTGJSON lacked. It serves as:

1. **Cold-start cache** — eliminates Scryfall API calls for basic card lookups when the server first starts (before TTL caches warm up).
2. **Standalone MCP provider** — rate-limit-free card search via `bulk_card_lookup`, `bulk_card_search`, and 7 additional tools (format legality, staples, ban lists, similar cards, random card).
3. **Workflow backbone** — workflows use `card_resolver.py` for bulk-data-first card resolution with Scryfall API fallback.

### Data Source

| Field | Value |
|-------|-------|
| URL | Discovered via `https://api.scryfall.com/bulk-data` (Oracle Cards type) |
| Format | JSON array of card objects — same shape as Scryfall API responses |
| Contains | name, mana_cost, type_line, oracle_text, colors, color_identity, keywords, power, toughness, prices (USD/EUR/foil), legalities, image_uris, edhrec_rank, rarity, set |
| Update frequency | Daily |

### Download Strategy

- **Lazy download**: Data is fetched on first access (not at server startup), avoiding blocking server initialization.
- **Background refresh**: After initial load, `start_background_refresh()` periodically re-downloads in the background.
- **Refresh via TTL**: Configurable via `MTG_MCP_BULK_DATA_REFRESH_HOURS` (default 12h).
- **In-memory storage**: Parsed into `dict[str, Card]` keyed by lowercase card name for O(1) exact lookups. Non-playable layouts (art_series, token, double_faced_token, emblem, vanguard, planar, scheme, augment, host) are filtered out during loading.
- **Layout filtering**: Prevents non-playable card layouts from overwriting real cards with the same name.

### Integration with Scryfall

Scryfall bulk data is both a **standalone provider** and **wired into the workflow server**:

- `providers/scryfall_bulk.py` mounts on the orchestrator with `namespace="bulk"` (9 tools).
- Workflow server creates its own `ScryfallBulkClient` instance for rate-limit-free card resolution.
- `card_resolver.py` checks bulk data first, falls back to Scryfall API for unresolved cards.
- Provider-level Scryfall tools continue to hit the API directly (with TTL caching).

### Relationship to TTL Caching

The two caching layers are complementary:

| Layer | Purpose | When it helps |
|-------|---------|---------------|
| TTL cache (cachetools) | Hot-path deduplication | Repeated calls for the same card within a session |
| Scryfall bulk data | Cold-start + offline data | First call for any card, rate limit avoidance, bulk search, format legality |

A typical workflow request flow: bulk data hit → return Card. If miss: Scryfall API call → TTL cache populated.

### Feature Flag

Scryfall bulk data is behind `MTG_MCP_ENABLE_BULK_DATA` (default `true`). When disabled:
- The bulk data provider is not mounted on the orchestrator.
- Workflow tools skip bulk data lookups and go directly to Scryfall API.
- No downloads are attempted.
