"""MTG Comprehensive Rules service — download, parse, and index.

Downloads the official Comprehensive Rules text file, parses it into
searchable indexes (rules by number, glossary by term), and serves lookups
from memory.  File-based service (not ``BaseClient``) — same lifecycle
pattern as ``ScryfallBulkClient``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_mcp_server.types import GlossaryEntry, Rule


class RulesService:
    """Index and query the MTG Comprehensive Rules.

    Not a ``BaseClient`` subclass — downloads a plain-text file, parses it
    into in-memory dicts, and serves lookups.  Lazy-loads on first access.

    Args:
        rules_url: URL of the Comprehensive Rules text file.
        refresh_hours: Hours between refresh checks.
    """

    def __init__(self, rules_url: str, refresh_hours: int = 168) -> None:
        self._rules_url = rules_url
        self._refresh_hours = refresh_hours
        self._rules: dict[str, Rule] = {}
        self._glossary: dict[str, GlossaryEntry] = {}
        self._loaded = False

    async def lookup_by_number(self, number: str) -> Rule | None:
        """Look up a rule by its number (e.g. '704.5k'). O(1)."""
        raise NotImplementedError  # Phase 2b agent implements

    async def keyword_search(self, keyword: str) -> list[Rule]:
        """Search rule text for a keyword, ranked by relevance."""
        raise NotImplementedError  # Phase 2b agent implements

    async def glossary_lookup(self, term: str) -> GlossaryEntry | None:
        """Look up a glossary term. Case-insensitive."""
        raise NotImplementedError  # Phase 2b agent implements

    async def list_keywords(self) -> list[dict]:
        """Return all keywords with brief definitions."""
        raise NotImplementedError  # Phase 2b agent implements

    async def list_sections(self) -> list[dict]:
        """Return the section index (100s = Game Concepts, etc.)."""
        raise NotImplementedError  # Phase 2b agent implements

    async def section_rules(self, section_prefix: str) -> list[Rule]:
        """Return all rules in a section (e.g. all 7xx rules)."""
        raise NotImplementedError  # Phase 2b agent implements
