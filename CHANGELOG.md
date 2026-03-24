# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-03-24

### Added
- Smithery Python SDK integration for proper config schema discovery and session configuration
- `smithery` dependency for Smithery platform deployment support
- `[tool.smithery]` configuration in pyproject.toml pointing to server factory

### Changed
- `smithery.yaml` simplified to `runtime: "python"` (replaces old `startCommand`/`commandFunction` format)

[1.2.0]: https://github.com/j4th/mtg-mcp-server/compare/v1.1.1...v1.2.0

## [1.1.1] - 2026-03-24

### Fixed
- Smithery `startCommand` and `commandFunction` for proper server launch and configuration UX
- Server `website_url` metadata for Smithery homepage detection
- Prompt parameter descriptions (all 4 prompts now have `Field(description=...)` on every argument)

[1.1.1]: https://github.com/j4th/mtg-mcp-server/compare/v1.1.0...v1.1.1

## [1.1.0] - 2026-03-24

### Added
- smithery.yaml with configSchema for Smithery registry integration
- Server icon via MCP `icons` field for Smithery and client display
- Parameter descriptions on all 22 parameterized tools for MCP schema compliance

[1.1.0]: https://github.com/j4th/mtg-mcp-server/compare/v1.0.1...v1.1.0

## [1.0.0] - 2026-03-23

### Added

#### Backend Tools (14 tools across 5 data sources)

**Scryfall** (namespace: `scryfall`)
- `scryfall_search_cards` -- Search for cards using Scryfall's full query syntax
- `scryfall_card_details` -- Get full card data by exact or fuzzy name
- `scryfall_card_price` -- Get current USD, EUR, and foil prices
- `scryfall_card_rulings` -- Get official rulings and clarifications

**Commander Spellbook** (namespace: `spellbook`)
- `spellbook_find_combos` -- Search for combos by card name or color identity
- `spellbook_combo_details` -- Get step-by-step combo instructions by ID
- `spellbook_find_decklist_combos` -- Find combos present in a decklist
- `spellbook_estimate_bracket` -- Estimate Commander bracket for a decklist

**17Lands** (namespace: `draft`)
- `draft_card_ratings` -- Get draft win rates and pick data for a set
- `draft_archetype_stats` -- Get win rates by color pair/archetype

**EDHREC** (namespace: `edhrec`)
- `edhrec_commander_staples` -- Get most-played cards with synergy scores
- `edhrec_card_synergy` -- Get synergy data for a card with a commander

**MTGJSON** (namespace: `mtgjson`)
- `mtgjson_card_lookup` -- Rate-limit-free card lookup from bulk data
- `mtgjson_card_search` -- Rate-limit-free card search by name, type, or text

#### Workflow Tools (8 cross-backend composition tools)

- `commander_overview` -- Comprehensive commander profile from all sources
- `evaluate_upgrade` -- Assess whether a card is worth adding to a deck
- `draft_pack_pick` -- Rank cards in a draft pack using 17Lands data
- `suggest_cuts` -- Identify weakest cards to cut from a decklist
- `card_comparison` -- Compare 2-5 cards side-by-side for a commander
- `budget_upgrade` -- Suggest budget-friendly upgrades ranked by synergy/$
- `deck_analysis` -- Full decklist health check (curve, colors, combos, bracket, budget)
- `set_overview` -- Draft format overview with top commons/uncommons and trap rares

#### Prompts (4 guided analysis workflows)

- `evaluate_commander_swap` -- Guide for evaluating a card swap
- `deck_health_check` -- Guide for comprehensive deck assessment
- `draft_strategy` -- Guide for draft format preparation
- `find_upgrades` -- Guide for budget upgrade sessions

#### Resources (6 `mtg://` URI endpoints)

- `mtg://card/{name}` -- Card data as JSON
- `mtg://card/{name}/rulings` -- Card rulings as JSON
- `mtg://combo/{combo_id}` -- Combo details as JSON
- `mtg://draft/{set_code}/ratings` -- Draft card ratings as JSON
- `mtg://commander/{name}/staples` -- Commander staples as JSON
- `mtg://card-data/{name}` -- MTGJSON card data as JSON

#### Infrastructure

- TTL caching on all service methods (1-24 hour TTLs per method)
- Feature flags for optional backends (`MTG_MCP_ENABLE_EDHREC`, `MTG_MCP_ENABLE_17LANDS`, `MTG_MCP_ENABLE_MTGJSON`)
- Partial failure handling in all workflow tools
- Rate limiting with exponential backoff for all HTTP clients
- MTGJSON-first card resolution with Scryfall fallback
- Progress reporting for long-running workflow tools
- Tool tagging for categorization and filtering
- stdio and streamable HTTP transport support
- Error detail masking on all provider servers (`mask_error_details`)
- Response size limiting (500KB max) to protect LLM context windows
- structlog JSON logging to stderr
- Configuration via `MTG_MCP_`-prefixed environment variables

[1.0.0]: https://github.com/j4th/mtg-mcp-server/releases/tag/v1.0.0
