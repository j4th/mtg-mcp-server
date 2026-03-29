"""MTG Comprehensive Rules service -- download, parse, and index.

Downloads the official Comprehensive Rules text file, parses it into
searchable indexes (rules by number, glossary by term), and serves lookups
from memory.  File-based service (not ``BaseClient``) -- same lifecycle
pattern as ``ScryfallBulkClient``.
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx
import structlog

from mtg_mcp_server.services.base import DEFAULT_USER_AGENT, ServiceError
from mtg_mcp_server.types import GlossaryEntry, Rule

__all__ = ["RulesDownloadError", "RulesError", "RulesService"]

log = structlog.get_logger(service="rules")

# Rule numbers: digits, dot, digits, optional letter suffix
# e.g., "100.1", "100.2a", "704.5k", "702.19b"
_RULE_NUMBER_RE = re.compile(r"^(\d{3}\.\d+[a-z]?)\.?\s")

# Section headers in the table of contents: "1. Game Concepts"
_SECTION_HEADER_RE = re.compile(r"^(\d+)\.\s+(.+)$")


class RulesError(ServiceError):
    """Base exception for Comprehensive Rules service errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=None)


class RulesDownloadError(RulesError):
    """Error downloading the Comprehensive Rules file."""


class RulesService:
    """Index and query the MTG Comprehensive Rules.

    Not a ``BaseClient`` subclass -- downloads a plain-text file, parses it
    into in-memory dicts, and serves lookups.  Lazy-loads on first access.

    Args:
        rules_url: URL of the Comprehensive Rules text file.
        refresh_hours: Hours between refresh checks.
    """

    def __init__(self, rules_url: str, refresh_hours: int = 168) -> None:
        self._rules_url = rules_url
        self._refresh_seconds = refresh_hours * 3600

        self._rules: dict[str, Rule] = {}
        self._glossary: dict[str, GlossaryEntry] = {}
        self._sections: dict[str, str] = {}  # section number -> name
        self._keyword_rule_numbers: set[str] = set()  # rule numbers under 702.x

        self._loaded = False
        self._loaded_at: float = 0.0
        self._load_lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        """Download and parse rules if not loaded or stale.

        On first load failure the error propagates. On refresh failure
        with existing data, logs a warning and serves stale data.
        """
        if not self._is_stale():
            return

        async with self._load_lock:
            if not self._is_stale():
                return

            is_refresh = self._loaded
            log.info("rules.loading", url=self._rules_url, is_refresh=is_refresh)

            try:
                raw_text = await self._download()
                self._parse(raw_text)
                self._loaded = True
                self._loaded_at = time.monotonic()
                log.info(
                    "rules.loaded",
                    rule_count=len(self._rules),
                    glossary_count=len(self._glossary),
                    section_count=len(self._sections),
                )
            except RulesError:
                if is_refresh:
                    log.warning("rules.refresh_failed", exc_info=True)
                    self._loaded_at = time.monotonic() - self._refresh_seconds + 300
                    return
                raise
            except Exception as exc:
                if is_refresh:
                    log.warning("rules.refresh_failed", exc_info=True)
                    self._loaded_at = time.monotonic() - self._refresh_seconds + 300
                    return
                raise RulesError(f"Unexpected error loading rules: {exc}") from exc

    # -------------------------------------------------------------------
    # Public query methods
    # -------------------------------------------------------------------

    async def lookup_by_number(self, number: str) -> Rule | None:
        """Look up a rule by its number (e.g. ``'704.5k'``). O(1).

        Normalizes trailing periods (``"100.1."`` -> ``"100.1"``).
        """
        await self.ensure_loaded()
        normalized = number.rstrip(".")
        return self._rules.get(normalized)

    async def keyword_search(self, keyword: str) -> list[Rule]:
        """Search rule text for a keyword, ranked by relevance.

        Ranking priority:
        1. Exact match (entire rule text equals the keyword)
        2. Word boundary match (keyword appears as a whole word)
        3. Substring match

        Returns at most 20 results.
        """
        await self.ensure_loaded()
        keyword_lower = keyword.lower()
        word_pattern = re.compile(r"\b" + re.escape(keyword_lower) + r"\b", re.IGNORECASE)

        exact: list[Rule] = []
        word_boundary: list[Rule] = []
        substring: list[Rule] = []

        for rule in self._rules.values():
            text_lower = rule.text.lower()
            if keyword_lower not in text_lower:
                continue
            if text_lower.strip() == keyword_lower:
                exact.append(rule)
            elif word_pattern.search(rule.text):
                word_boundary.append(rule)
            else:
                substring.append(rule)

        combined = exact + word_boundary + substring
        return combined[:20]

    async def glossary_lookup(self, term: str) -> GlossaryEntry | None:
        """Look up a glossary term. Case-insensitive exact match."""
        await self.ensure_loaded()
        return self._glossary.get(term.lower())

    async def list_keywords(self) -> list[dict[str, str]]:
        """Return all glossary entries that are keywords (702.x rules).

        A glossary entry is considered a keyword if its definition references
        a 702.x rule number.
        """
        await self.ensure_loaded()
        result: list[dict[str, str]] = []
        for entry in self._glossary.values():
            if _is_keyword_glossary_entry(entry):
                result.append({"term": entry.term, "definition": entry.definition})
        return sorted(result, key=lambda d: d["term"])

    async def list_sections(self) -> list[dict[str, str]]:
        """Return the section index as a list of dicts with number and name."""
        await self.ensure_loaded()
        return [
            {"number": num, "name": name}
            for num, name in sorted(self._sections.items(), key=lambda x: int(x[0]))
        ]

    async def section_rules(self, section_prefix: str) -> list[Rule]:
        """Return all rules whose number starts with the given prefix."""
        await self.ensure_loaded()
        prefix = section_prefix.rstrip(".")
        results: list[Rule] = []
        for number, rule in self._rules.items():
            if number.startswith(prefix):
                results.append(rule)
        return sorted(results, key=lambda r: _rule_sort_key(r.number))

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _is_stale(self) -> bool:
        """Check if the loaded data has exceeded the refresh interval."""
        if not self._loaded:
            return True
        return (time.monotonic() - self._loaded_at) >= self._refresh_seconds

    async def _download(self) -> str:
        """Download the Comprehensive Rules text file.

        Returns the file content as a string with BOM stripped.
        """
        try:
            async with httpx.AsyncClient(
                timeout=60.0,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            ) as http:
                response = await http.get(self._rules_url)
                if response.status_code != 200:
                    raise RulesDownloadError(
                        f"HTTP {response.status_code} downloading rules from {self._rules_url}"
                    )
                # Decode as UTF-8 and strip BOM if present
                text = response.content.decode("utf-8-sig")
                return text
        except httpx.RequestError as exc:
            raise RulesDownloadError(f"Network error downloading rules: {exc}") from exc

    def _parse(self, text: str) -> None:
        """Parse the Comprehensive Rules text into indexed data structures.

        Populates ``_rules``, ``_glossary``, and ``_sections``.
        """
        lines = text.splitlines()

        rules: dict[str, Rule] = {}
        glossary: dict[str, GlossaryEntry] = {}
        sections: dict[str, str] = {}

        # Parse into three regions: pre-rules, rules, glossary
        state = "preamble"
        current_rule_number: str | None = None
        current_rule_lines: list[str] = []
        in_contents = False

        glossary_term: str | None = None
        glossary_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Detect Contents section for section index
            if stripped == "Contents":
                in_contents = True
                continue

            if in_contents:
                if stripped == "":
                    continue
                # Section headers: "1. Game Concepts", "7. Additional Rules"
                section_match = _SECTION_HEADER_RE.match(stripped)
                if section_match:
                    sections[section_match.group(1)] = section_match.group(2)
                    continue
                # End of contents: hit "Glossary" or a numbered rule
                if _RULE_NUMBER_RE.match(stripped) or stripped == "Glossary":
                    in_contents = False
                    # Fall through to process this line
                else:
                    continue

            # Detect transition to glossary
            if stripped == "Glossary" and state != "glossary":
                # Flush current rule
                if current_rule_number is not None:
                    rules[current_rule_number] = Rule(
                        number=current_rule_number,
                        text=" ".join(current_rule_lines),
                    )
                state = "glossary"
                continue

            # Detect end of glossary (final Credits section)
            if state == "glossary" and stripped == "Credits":
                # Flush last glossary entry
                if glossary_term is not None:
                    glossary[glossary_term.lower()] = GlossaryEntry(
                        term=glossary_term,
                        definition=" ".join(glossary_lines).strip(),
                    )
                break

            # --- Rules parsing ---
            if state != "glossary":
                rule_match = _RULE_NUMBER_RE.match(stripped)
                if rule_match:
                    # Flush previous rule
                    if current_rule_number is not None:
                        rules[current_rule_number] = Rule(
                            number=current_rule_number,
                            text=" ".join(current_rule_lines),
                        )
                    current_rule_number = rule_match.group(1)
                    # Text after the rule number
                    rest = stripped[rule_match.end() :].strip()
                    current_rule_lines = [rest] if rest else []
                    state = "rules"
                elif state == "rules" and stripped and current_rule_number is not None:
                    # Continuation line for current rule
                    current_rule_lines.append(stripped)
                continue

            # --- Glossary parsing ---
            if state == "glossary":
                if stripped == "":
                    # Blank line separates glossary entries
                    if glossary_term is not None and glossary_lines:
                        glossary[glossary_term.lower()] = GlossaryEntry(
                            term=glossary_term,
                            definition=" ".join(glossary_lines).strip(),
                        )
                        glossary_term = None
                        glossary_lines = []
                elif glossary_term is None:
                    # This line is a new term
                    glossary_term = stripped
                    glossary_lines = []
                else:
                    # Definition continuation
                    glossary_lines.append(stripped)

        # Build subrule hierarchy: "704.5a" is a subrule of "704.5"
        for number, rule in rules.items():
            parent_number = _parent_rule_number(number)
            if parent_number and parent_number in rules:
                rules[parent_number].subrules.append(rule)

        # Assign parsed data
        self._rules = rules
        self._glossary = glossary
        self._sections = sections


def _parent_rule_number(number: str) -> str | None:
    """Return the parent rule number, or None if this is a top-level rule.

    ``"704.5k"`` -> ``"704.5"``, ``"704.5"`` -> ``"704"``, ``"704"`` -> ``None``.
    """
    if "." not in number:
        return None
    parts = number.split(".", 1)
    rest = parts[1]
    # If rest ends with letter(s), parent is the numeric portion
    if rest and rest[-1].isalpha():
        parent_rest = rest.rstrip("abcdefghijklmnopqrstuvwxyz")
        if parent_rest:
            return f"{parts[0]}.{parent_rest}"
        return parts[0]
    return parts[0]


_KEYWORD_RULE_RE = re.compile(r"\brule 702\.")


def _is_keyword_glossary_entry(entry: GlossaryEntry) -> bool:
    """Check if a glossary entry references a 702.x rule (keyword ability)."""
    return bool(_KEYWORD_RULE_RE.search(entry.definition))


def _rule_sort_key(number: str) -> tuple[int, int, str]:
    """Create a sort key from a rule number for natural ordering.

    ``"704.5k"`` -> ``(704, 5, "k")``.
    """
    # Split on the dot
    parts = number.split(".", 1)
    major = int(parts[0]) if parts[0].isdigit() else 0
    if len(parts) > 1:
        rest = parts[1]
        # Separate numeric part from letter suffix
        digits = ""
        suffix = ""
        for char in rest:
            if char.isdigit():
                digits += char
            else:
                suffix += char
        minor = int(digits) if digits else 0
    else:
        minor = 0
        suffix = ""
    return (major, minor, suffix)
