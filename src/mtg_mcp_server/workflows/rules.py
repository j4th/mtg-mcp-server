"""Rules engine workflow functions — pure async, no MCP imports.

Each function accepts a ``RulesService`` (and optionally ``ScryfallBulkClient``)
and returns a ``WorkflowResult(markdown, data)``.  The wiring layer in
``server.py`` wraps these as MCP tools, converting to ``ToolResult``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_mcp_server.services.rules import RulesService
    from mtg_mcp_server.services.scryfall_bulk import ScryfallBulkClient
    from mtg_mcp_server.utils.formatters import ResponseFormat
    from mtg_mcp_server.workflows import WorkflowResult


async def rules_lookup(
    query: str,
    *,
    rules: RulesService,
    section: str | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Look up rules by number or keyword search."""
    raise NotImplementedError  # Phase 2b agent implements


async def keyword_explain(
    keyword: str,
    *,
    rules: RulesService,
    bulk: ScryfallBulkClient | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Explain a keyword with rules text, examples, and interactions."""
    raise NotImplementedError  # Phase 2b agent implements


async def rules_interaction(
    mechanic_a: str,
    mechanic_b: str,
    *,
    rules: RulesService,
    bulk: ScryfallBulkClient | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Explain how two mechanics interact under MTG rules."""
    raise NotImplementedError  # Phase 2b agent implements


async def rules_scenario(
    scenario: str,
    *,
    rules: RulesService,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Resolve a game scenario step-by-step with rule citations."""
    raise NotImplementedError  # Phase 2b agent implements


async def combat_calculator(
    attackers: list[str],
    blockers: list[str],
    *,
    rules: RulesService,
    bulk: ScryfallBulkClient | None = None,
    keywords: list[str] | None = None,
    response_format: ResponseFormat = "detailed",
) -> WorkflowResult:
    """Calculate combat step-by-step with keyword interactions."""
    raise NotImplementedError  # Phase 2b agent implements
