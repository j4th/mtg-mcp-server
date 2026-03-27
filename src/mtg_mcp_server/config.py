"""Application configuration via environment variables.

All settings use the ``MTG_MCP_`` prefix and can be overridden via a ``.env``
file. No credentials are required — all APIs are public.

Example::

    MTG_MCP_ENABLE_EDHREC = false  # Disable fragile EDHREC scraping
    MTG_MCP_TRANSPORT = http  # Use streamable HTTP instead of stdio
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings

__all__ = ["Settings"]


class Settings(BaseSettings):
    """MTG MCP server settings loaded from environment variables.

    All fields have sensible defaults and can be overridden with
    ``MTG_MCP_``-prefixed environment variables or a ``.env`` file.
    """

    # --- Transport ---
    transport: Literal["stdio", "http"] = "stdio"
    http_port: int = 8000

    # --- Logging ---
    log_level: str = "INFO"

    # --- Backend URLs ---
    # Each service client reads its base URL from here so tests can point
    # at a local mock server via env var override.
    scryfall_base_url: str = "https://api.scryfall.com"
    scryfall_rate_limit_ms: int = 100
    spellbook_base_url: str = "https://backend.commanderspellbook.com"
    seventeen_lands_base_url: str = "https://www.17lands.com"
    edhrec_base_url: str = "https://json.edhrec.com"

    # --- Feature flags ---
    # Optional backends can be disabled without code changes.
    enable_17lands: bool = True
    enable_edhrec: bool = True  # Behind flag — scrapes undocumented endpoints
    enable_bulk_data: bool = True  # Scryfall Oracle Cards bulk download (~30MB)

    # --- Caching ---
    disable_cache: bool = False  # Set True in tests to bypass TTLCache

    # --- Scryfall Bulk Data ---
    bulk_data_refresh_hours: int = 12

    model_config = {"env_prefix": "MTG_MCP_", "env_file": ".env", "extra": "ignore"}
