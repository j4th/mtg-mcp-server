# mtg-mcp-server v3.0.0

**69 tools across 8 data sources -- card data, combos, draft analytics, Commander metagame, competitive constructed, sideboard strategy, rules engine, and deck sharing. Works with Claude Code, Claude Desktop, or any MCP client.**

## TL;DR

mtg-mcp-server now covers competitive constructed. Ask Claude about the Modern metagame and get a tiered breakdown with deck prices. Request a stock Boros Energy list and get the full 75. Say "build me a sideboard for this deck in Pioneer" and get a categorized 15-card sideboard with format staple markers. Ask for a sideboard guide against Azorius Control and get an in/out plan. Or generate a full sideboard matrix across all your common matchups.

Plus Moxfield deck search, tournament results from Spicerack, and fuzzy archetype matching so you don't need exact names. 69 tools across 8 data sources. Just point Claude at it and ask.

## Why v3.0.0

This release marks the constructed metagame milestone. It is not a breaking change. Every tool from v2.x retains its parameters and behavior. The major version reflects the scope: the server now covers every major MTG domain, with new tools for competitive metagame analysis, sideboard strategy, and deck discovery.

If you are upgrading from v2.x, no migration is needed. Install the new version and the additional tools appear automatically.

## What's New

### Competitive Metagame

Four tools that give AI assistants access to competitive format metagames. `metagame_snapshot` provides a tiered breakdown (Tier 1/2/3) with archetype names, meta share percentages, deck counts, and estimated prices -- sourced from MTGGoldfish with Spicerack tournament frequency as a fallback. `archetype_decklist` fetches the stock 75 for any archetype with fuzzy name matching (so "boros energy" finds "Boros Energy" without exact casing). `archetype_comparison` puts 2-4 archetypes side-by-side across meta share, price, and shared staples. `format_entry_guide` combines metagame data with budget sorting and cross-archetype staples for players entering a format.

### Sideboard Strategy

Three tools that generate sideboard plans. `suggest_sideboard` takes a mainboard and format, then suggests a categorized 15-card sideboard (graveyard hate, removal, counterspells, etc.) with format staple markers. `sideboard_guide` takes a full 75 and a matchup name, then generates an in/out plan with per-card reasoning. `sideboard_matrix` generates a full matrix: rows are sideboard cards, columns are matchups, cells are IN/OUT/FLEX.

### Moxfield Deck Search

Two new tools for discovering decks on Moxfield. `moxfield_search_decks` searches public decks by format, keyword, or sort order (updated, created, views). `moxfield_user_decks` lists a user's public decks. These join the existing `moxfield_decklist` and `moxfield_deck_info` tools for a complete Moxfield integration.

### Fuzzy Matching

Archetype names no longer need to be exact. "boros energy", "Boros Energy", and "boros-energy" all resolve to the same archetype. Matchup names in sideboard tools use the same fuzzy matching. The utility (`utils/fuzzy.py`) uses normalized string comparison with configurable thresholds.

## By the Numbers

| | v2.2.0 | v3.0.0 |
|---|---|---|
| Tools | 60 | 69 |
| Prompts | 17 | 19 |
| Resources | 18 | 21 |
| Data sources | 6 | 8 |
| Tests | ~1200 | 1340 |
| Coverage | 88% | 88% |

## Getting Started

The fastest way to try the server:

**FastMCP Horizon** (no install required):
```
https://mtg-mcp-server.fastmcp.app/mcp
```

Point any MCP client at that URL and all 69 tools are available immediately.

**Claude Code:**
```bash
claude mcp add mtg -- uvx mtg-mcp-server
```

For local installation and other methods, see the [README](../README.md).

## Data Sources

mtg-mcp-server composes data from eight public sources:

- [Scryfall](https://scryfall.com/) -- Card data, prices, rulings, sets, bulk data
- [Commander Spellbook](https://commanderspellbook.com/) -- Combo search and bracket estimation
- [17Lands](https://www.17lands.com/) -- Draft and sealed win rate analytics
- [EDHREC](https://edhrec.com/) -- Commander metagame data and synergy scores
- [Moxfield](https://www.moxfield.com/) -- Public decklists and deck search
- [Spicerack](https://spicerack.gg/) -- Tournament results and standings
- [MTGGoldfish](https://www.mtggoldfish.com/) -- Competitive metagame data, archetypes, format staples
- Magic Comprehensive Rules -- Local parser, no external API

## Full Changelog

See [CHANGELOG.md](../CHANGELOG.md) for the complete list of changes.
