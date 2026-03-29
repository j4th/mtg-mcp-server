# mtg-mcp-server v2.0.0

**A complete Magic: The Gathering toolkit for AI assistants -- 51 tools spanning card data, rules, deckbuilding, draft analytics, and Commander across five data sources.**

## Why v2.0.0

This release marks the feature-complete milestone for the MTG MCP server. It is not a breaking change. Every tool from v1.x retains its parameters and behavior. The major version reflects the scope of what was added: the server grew from 23 tools to 51, with new domains (rules, deck building, limited, constructed) and deeper coverage of existing ones (Commander, draft).

If you are upgrading from v1.x, no migration is needed. Install the new version and the additional tools appear automatically.

## What's New

### Rules Engine

Five tools that give AI assistants direct access to the Magic Comprehensive Rules. `rules_lookup` finds rules by number or keyword. `keyword_explain` provides the glossary definition, governing rules, and example cards for any keyword. `rules_interaction` explains how two mechanics interact with full rule citations. `rules_scenario` and `combat_calculator` provide structured rules frameworks for resolving game situations.

The rules are parsed locally -- no API calls, no rate limits, instant responses.

### Deck Building

`theme_search` finds cards matching a mechanical or tribal theme by scanning oracle text across the entire card pool. `build_around` takes 1-5 key cards, detects their shared mechanics, and finds synergy candidates. `complete_deck` performs gap analysis on a partial decklist and suggests cards to fill each missing category (removal, card draw, ramp, etc.).

These tools compose with `deck_validate` (format legality checking) and `suggest_mana_base` (land distribution from pip analysis) for a full deck construction pipeline.

### Commander Depth

`commander_comparison` puts 2-5 commanders side-by-side across card data, combo counts, and EDHREC popularity. `tribal_staples` finds the best cards for a creature type within a color identity, organized into lords, synergy pieces, and support cards. `precon_upgrade` pairs the weakest cards in a precon with upgrade candidates, ranked by synergy improvement. `color_identity_staples` surfaces the most-played cards across all commanders sharing a color identity.

### Limited

`sealed_pool_build` evaluates every two-color pair from a sealed pool and ranks the top builds. `draft_signal_read` analyzes pick history to detect which colors are open based on ALSA signals from 17Lands. `draft_log_review` grades a completed draft pick-by-pick against GIH WR data.

### Scryfall Bulk Data

The MTGJSON backend was replaced with Scryfall Oracle Cards bulk data. The result is richer card information (prices, legalities, images, EDHREC rank) with the same rate-limit-free access pattern. Nine `bulk_` tools cover card lookup, search, format legality, ban lists, format staples, cross-format legality, random cards, and similar card discovery.

### Structured Output

All tools now return structured data alongside their markdown output. The `data` dict in each response contains parsed, machine-readable fields that AI assistants can use for follow-up reasoning without re-parsing markdown.

### Prompts

Thirteen new prompts guide multi-step workflows: building decks from scratch, upgrading precons, preparing for draft formats, evaluating collections, planning for Standard rotation, and more. These are user-invocable templates that chain multiple tool calls into a coherent analysis session.

## By the Numbers

| | v1.2.3 | v2.0.0 |
|---|---|---|
| Tools | 23 | 51 |
| Prompts | 4 | 17 |
| Resources | 6 | 18 |
| Tests | 374 | 989 |
| Coverage | 92% | 88% |

## Getting Started

The fastest way to try the server:

**FastMCP Horizon** (no install required):
```
https://mtg-mcp-server.fastmcp.app/mcp
```

Point any MCP client at that URL and all 51 tools are available immediately.

For local installation and other methods, see the [README](../README.md).

## Data Sources

mtg-mcp-server composes data from five public sources:

- [Scryfall](https://scryfall.com/) -- Card data, prices, rulings, sets, bulk data
- [Commander Spellbook](https://commanderspellbook.com/) -- Combo search and bracket estimation
- [17Lands](https://www.17lands.com/) -- Draft and sealed win rate analytics
- [EDHREC](https://edhrec.com/) -- Commander metagame data and synergy scores
- Magic Comprehensive Rules -- Local parser, no external API

## Full Changelog

See [CHANGELOG.md](../CHANGELOG.md) for the complete list of changes.
