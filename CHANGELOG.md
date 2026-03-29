# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-03-29

v2.0.0 marks the feature-complete milestone for the MTG MCP server. This is not a
breaking change -- all existing tools retain their parameters and behavior. The major
version signals the scope of new capabilities added since v1.0.0.

### Added

#### Scryfall Bulk Data Provider (9 tools, namespace: `bulk`)
- `bulk_card_lookup` -- Rate-limit-free card lookup from Scryfall Oracle Cards bulk data
- `bulk_card_search` -- Rate-limit-free card search by name, type, or oracle text
- `bulk_format_legality` -- Check card legality in a format
- `bulk_format_search` -- Search for cards legal in a specific format
- `bulk_format_staples` -- Top-played cards in a format by EDHREC rank
- `bulk_ban_list` -- Banned/restricted cards for a format
- `bulk_card_in_formats` -- Card legality across all formats
- `bulk_random_card` -- Random card with optional format/type filter
- `bulk_similar_cards` -- Find cards similar by type, keywords, or mana cost

#### Scryfall Tools
- `scryfall_whats_new` -- Recently released or previewed cards
- `scryfall_set_info` -- Set metadata by set code

#### Rules Engine (5 tools)
- `rules_lookup` -- Look up rules by number or keyword search
- `keyword_explain` -- Explain a keyword with rules, glossary, and example cards
- `rules_interaction` -- How two mechanics interact with rule citations
- `rules_scenario` -- Resolve a game scenario with relevant rules framework
- `combat_calculator` -- Step-by-step combat phases with keyword interactions
- Local Comprehensive Rules parser service (RulesService)

#### Deck Building Workflows (3 tools)
- `theme_search` -- Search for cards matching a mechanical or tribal theme via oracle text
- `build_around` -- Detect synergies from key cards and find cards that work with them
- `complete_deck` -- Gap analysis and card suggestions to fill out a partial decklist

#### Commander Depth Workflows (4 tools)
- `commander_comparison` -- Compare 2-5 commanders head-to-head across data, combos, popularity
- `tribal_staples` -- Best cards for a creature type within a color identity
- `precon_upgrade` -- Analyze a precon decklist and suggest swap pairs
- `color_identity_staples` -- Top-played cards across all commanders in a color identity

#### Limited Workflows (3 tools)
- `sealed_pool_build` -- Suggest best 40-card sealed deck builds from a card pool
- `draft_signal_read` -- Analyze draft picks to detect open color signals
- `draft_log_review` -- Review a completed draft with pick-by-pick GIH WR analysis and grade

#### Constructed Workflow
- `rotation_check` -- Check Standard rotation status and which cards are in rotating sets

#### Cross-Format Tools (3 tools)
- `deck_validate` -- Validate a decklist against format construction rules
- `suggest_mana_base` -- Suggest lands based on color pip distribution
- `price_comparison` -- Compare prices across multiple cards

#### Prompts (13 new, 17 total)
- `build_deck` -- Guide building a deck from scratch for any format
- `evaluate_collection` -- Evaluate a card collection for trade and deck-building value
- `format_intro` -- Introduction to a Magic format with key cards and strategies
- `card_alternatives` -- Find alternatives to a card for budget or format reasons
- `rules_question` -- Ask a rules question with Comprehensive Rules citations
- `build_around_deck` -- Build a deck around specific cards or a win condition
- `build_tribal_deck` -- Build a tribal deck for any format
- `build_theme_deck` -- Build a themed deck around a strategy or archetype
- `upgrade_precon` -- Upgrade a precon Commander deck with a budget
- `sealed_session` -- Guide a sealed deck building session
- `draft_review` -- Review a completed draft with analysis and grade
- `compare_commanders` -- Compare commanders to choose between them
- `rotation_plan` -- Plan for Standard rotation with replacements

#### Resources (12 new templates, 18 total)
- `mtg://set/{code}` -- Set metadata as JSON
- `mtg://format/{format}/legal-cards` -- Legal cards in a format
- `mtg://format/{format}/banned` -- Banned cards in a format
- `mtg://card/{name}/formats` -- Format legality for a card
- `mtg://card/{name}/similar` -- Similar cards by type, keywords, or mana cost
- `mtg://rules/{number}` -- Rule text by number
- `mtg://rules/glossary/{term}` -- Glossary definition for a term
- `mtg://rules/keywords` -- List of all keywords with rule references
- `mtg://rules/sections` -- List of all rule sections
- `mtg://theme/{theme}` -- Cards matching a theme
- `mtg://tribe/{tribe}/staples` -- Staple cards for a creature type
- `mtg://draft/{set_code}/signals` -- Draft color openness signals

#### Infrastructure
- Structured output: all tools return `ToolResult` with structured `data` dict alongside markdown
- `ResponseFormat` support (markdown/json) via shared formatters
- Utility modules: color identity parser, format rules, query parser, mana cost parser, decklist parser
- CodeMode transform behind feature flag (`MTG_MCP_ENABLE_CODE_MODE`)
- Live smoke tests in CI on pull requests
- Claude Code review integration
- Dependabot enabled

### Changed
- Replaced MTGJSON with Scryfall Oracle Cards bulk data (~30MB) for richer card info including prices, legalities, images, and EDHREC rank. The `mtgjson_` namespace is replaced by `bulk_`. The `MTG_MCP_ENABLE_MTGJSON` flag is replaced by `MTG_MCP_ENABLE_BULK_DATA`.
- `mtg://card-data/{name}` resource now backed by Scryfall bulk data instead of MTGJSON
- Card resolver utility uses Scryfall bulk data first (instead of MTGJSON) with Scryfall API fallback

[2.0.0]: https://github.com/j4th/mtg-mcp-server/compare/v1.2.3...v2.0.0

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
