"""Async caching utilities for service methods.

Provides an ``async_cached`` decorator that adapts ``cachetools.TTLCache``
for use with async instance methods. Cache key functions skip ``self`` so
that the cache is keyed only on method arguments.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING

from cachetools import keys

if TYPE_CHECKING:
    from cachetools import TTLCache

type _KeyFunc = Callable[..., object]

# Module-level kill switch for tests. When True, @async_cached is a no-op
# and every call goes straight to the wrapped function.
_disabled: bool = False


def disable_all_caches() -> None:
    """Bypass all ``@async_cached`` decorators (calls go straight through).

    Used by the test suite's autouse ``_clear_caches`` fixture to prevent
    cached results from leaking between tests.
    """
    global _disabled
    _disabled = True


def _method_key(*args: object, **kwargs: object) -> object:
    """Build a cache key that skips ``self`` (first positional arg).

    Used as the default key function for ``@async_cached`` on instance methods.
    Without skipping ``self``, cache hits would require the same object identity.
    """
    return keys.hashkey(*args[1:], **kwargs)


def _decklist_key(*args: object, **kwargs: object) -> object:
    """Build a cache key for methods whose args contain lists.

    Lists are unhashable, so we convert them to tuples before hashing.
    Must handle both positional and keyword list args — e.g.
    ``find_decklist_combos(commanders=[...], decklist=[...])`` passes lists
    as kwargs.
    """
    converted = tuple(tuple(a) if isinstance(a, list) else a for a in args[1:])
    converted_kw = {k: tuple(v) if isinstance(v, list) else v for k, v in kwargs.items()}
    return keys.hashkey(*converted, **converted_kw)


def async_cached(cache: TTLCache, key: _KeyFunc = _method_key):
    """Decorate an async method to cache its results in a TTLCache.

    Caches are class-level (shared across instances) since service clients
    are singletons managed by provider lifespans. No locking is needed
    because we run in a single asyncio event loop.

    Args:
        cache: TTLCache instance (typically a class attribute).
        key: Key function; defaults to ``_method_key`` (skips ``self``).

    The wrapped function exposes a ``.cache`` attribute for test introspection.
    Respects the module-level ``_disabled`` flag set by ``disable_all_caches()``.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> object:
            if _disabled:
                return await func(*args, **kwargs)
            k = key(*args, **kwargs)
            try:
                return cache[k]
            except KeyError:
                pass
            result = await func(*args, **kwargs)
            cache[k] = result
            return result

        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator
