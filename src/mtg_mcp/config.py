"""Application configuration via environment variables.

All settings use the ``MTG_MCP_`` prefix and can be overridden via a ``.env`` file.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """MTG MCP server settings loaded from environment variables."""

    # Transport
    transport: Literal["stdio", "http"] = "stdio"
    http_port: int = 8000

    # Logging
    log_level: str = "INFO"

    # Scryfall
    scryfall_base_url: str = "https://api.scryfall.com"
    scryfall_rate_limit_ms: int = 100

    # Commander Spellbook
    spellbook_base_url: str = "https://backend.commanderspellbook.com"

    # 17Lands
    seventeen_lands_base_url: str = "https://www.17lands.com"
    enable_17lands: bool = True

    # EDHREC
    edhrec_base_url: str = "https://json.edhrec.com"
    enable_edhrec: bool = True

    # Caching
    cache_ttl_seconds: int = 3600

    model_config = {"env_prefix": "MTG_MCP_", "env_file": ".env", "extra": "ignore"}
