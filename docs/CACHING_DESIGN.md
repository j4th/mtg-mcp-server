# MTG MCP Server — Caching Design

> **Status:** Implementing (Phase 4).
> **Date:** 2026-03-21

## Problem

All four service clients make unconditional HTTP requests on every invocation. This is wasteful because:

- **17Lands** rate-limits at 1 req/sec — repeated `draft_pack_pick` calls for the same set hammer the API unnecessarily.
- **EDHREC** scrapes undocumented endpoints — minimizing requests reduces breakage risk.
- **Scryfall** card data changes almost never; prices update once daily.
- **Spellbook** combos are added infrequently.

`Settings.cache_ttl_seconds` exists (default 3600) but no service uses it.

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
| Spellbook | `find_combos` | 24h | 200 | Combos rarely added to the database |
| Spellbook | `get_combo` | 24h | 100 | Static once created |
| Spellbook | `find_decklist_combos` | 12h | 50 | User-specific query; 12h diverges from the blanket 24h recommendation because decklist analysis may change as the user iterates |
| Spellbook | `estimate_bracket` | 12h | 50 | Same reasoning as `find_decklist_combos` |
| 17Lands | `card_ratings` | 4h | 20 | Safe floor — updates heavily during first week of a set, then stabilizes. 4h balances freshness vs. rate limit protection |
| 17Lands | `color_ratings` | 4h | 20 | Same lifecycle |
| EDHREC | `commander_top_cards` | 24h | 100 | EDHREC aggregates daily |
| EDHREC | `card_synergy` | 24h | 200 | Same aggregation cycle |

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

Per-method TTLs are hardcoded as class-level constants (the table above), since they reflect data staleness characteristics of the upstream APIs, not deployment config. The existing `Settings.cache_ttl_seconds` will be removed — it was a placeholder for a single global TTL that this design supersedes. If a global disable is needed for debugging, a `Settings.disable_cache: bool = False` flag is simpler and more explicit.

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

## MTGJSON Bulk Card Cache

### Overview

MTGJSON provides `AtomicCards.json` — a ~120MB JSON file keyed by card name containing oracle-level card data (no prices, rulings, or set-specific data). This serves as:

1. **Cold-start cache** — eliminates Scryfall API calls for basic card lookups when the server first starts (before TTL caches warm up).
2. **Standalone MCP provider** — rate-limit-free card search via `mtgjson_card_lookup` and `mtgjson_card_search` tools.

### Data Source

| Field | Value |
|-------|-------|
| URL | `https://mtgjson.com/api/v5/AtomicCards.json.gz` (~20MB gzipped) |
| Format | JSON dict keyed by card name, each value is array of printings |
| Contains | name, mana_cost, type, oracle_text, colors, color_identity, types, subtypes, supertypes, keywords, power, toughness, mana_value |
| Does NOT contain | prices, rulings, images, set-specific data |
| Update frequency | Daily |

### Download Strategy

- **Lazy download**: Data is fetched on first access (not at server startup), avoiding blocking server initialization.
- **Refresh via TTL**: Configurable via `MTG_MCP_MTGJSON_REFRESH_HOURS` (default 24h). After the TTL expires, the next access triggers a re-download.
- **In-memory storage**: Parsed into `dict[str, MTGJSONCard]` keyed by lowercase card name for O(1) exact lookups.
- **Gzip decompression**: Downloaded as `.json.gz`, decompressed in memory.

### Integration with Scryfall

MTGJSON is a **standalone provider** (not wired into the workflow server). This preserves service independence:

- MTGJSON has its own provider lifespan (`providers/mtgjson.py`) and is mounted on the orchestrator with `namespace="mtgjson"`.
- Provider-level Scryfall tools continue to hit the API directly (with TTL caching).
- Future workflow-layer integration (checking MTGJSON before Scryfall) can be added when a workflow needs it, without modifying existing services.

### Relationship to TTL Caching

The two caching layers are complementary:

| Layer | Purpose | When it helps |
|-------|---------|---------------|
| TTL cache (cachetools) | Hot-path deduplication | Repeated calls for the same card within a session |
| MTGJSON bulk cache | Cold-start + offline data | First call for any card, rate limit avoidance, bulk search |

A typical request flow: MTGJSON hit → TTL cache miss → Scryfall API call → TTL cache populated.

### Feature Flag

MTGJSON is behind `MTG_MCP_ENABLE_MTGJSON` (default `true`). When disabled:
- The MTGJSON provider is not mounted on the orchestrator.
- Workflow tools skip the MTGJSON lookup step.
- No downloads are attempted.
