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


def _method_key(*args: object, **kwargs: object) -> object:
    """Cache key that skips ``self`` (first arg) for instance methods."""
    return keys.hashkey(*args[1:], **kwargs)


def _decklist_key(*args: object, **kwargs: object) -> object:
    """Cache key for methods taking ``list[str]`` args — converts to tuples."""
    converted = tuple(tuple(a) if isinstance(a, list) else a for a in args[1:])
    converted_kw = {k: tuple(v) if isinstance(v, list) else v for k, v in kwargs.items()}
    return keys.hashkey(*converted, **converted_kw)


def async_cached(cache: TTLCache, key: _KeyFunc = _method_key):
    """Decorator for caching async method results in a TTLCache.

    By default uses ``_method_key`` which skips ``self`` so that the cache
    is keyed only on the method arguments, not the instance identity.

    The wrapped function exposes a ``.cache`` attribute for test access.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> object:
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
