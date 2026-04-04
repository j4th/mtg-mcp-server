# v3.0.0 Release — Design Spec

## Summary

v3.0.0 is a scope milestone release (not a breaking change). It signals that the server now covers all major MTG domains: Commander, draft/limited, constructed metagame, sideboard strategy, and deck sharing. The jump from 60 to 69 tools with 3 new data sources (Spicerack, MTGGoldfish, Moxfield search) is the headline.

No code changes beyond version bumps and ~5 PEP 8 comment capitalization fixes.

## Scope

### New since v2.2.0 (last tagged release)

**Metagame Workflows (4 tools)**
- `metagame_snapshot` — tiered metagame breakdown with MTGGoldfish primary, Spicerack fallback
- `archetype_decklist` — stock decklist for a competitive archetype with fuzzy matching
- `archetype_comparison` — side-by-side comparison of 2-4 archetypes
- `format_entry_guide` — beginner guide for entering a competitive format

**Sideboard Workflows (3 tools)**
- `suggest_sideboard` — 15-card sideboard suggestions for a competitive deck
- `sideboard_guide` — in/out plan for a specific matchup
- `sideboard_matrix` — full sideboard matrix across common matchups

**Moxfield Provider (2 new tools)**
- `moxfield_search_decks` — search public Moxfield decks by format, keyword, sort
- `moxfield_user_decks` — list a user's public decks

**Infrastructure**
- Fuzzy matching utility (`utils/fuzzy.py`) for archetype and matchup name resolution
- `parse_decklist` utility consolidated from duplicated code
- 2 new prompts: `explore_format`, `build_constructed_deck`
- 2 new resource templates: `mtg://metagame/{format}` (already existed), `mtg://moxfield/{deck_id}` (already existed from v2.2.0)
- Pygments CVE-2026-4539 fix (dependency upgrade)

### By the Numbers

| | v2.2.0 | v3.0.0 |
|---|---|---|
| Tools | 60 | 69 |
| Prompts | 17 | 19 |
| Resources | 18 | 21 |
| Data sources | 6 | 8 |
| Tests | ~1200 | 1340 |
| Coverage | 88% | 88% |

## Deliverables

### 1. Version bumps
- `pyproject.toml` — version → "3.0.0"
- `server.json` — version → "3.0.0", add missing env vars for Moxfield/Spicerack/MTGGoldfish

### 2. CHANGELOG.md
Single `[3.0.0]` entry covering everything since v2.2.0. Sections: Added, Changed, Fixed, Security.

### 3. docs/RELEASE_NOTES_v3.md
New file. Structure:
- Friend-friendly opening paragraph (copy-pasteable to a message)
- "What's New" sections: Constructed Metagame, Sideboard Strategy, Moxfield Search, Fuzzy Matching
- By the Numbers comparison table
- Getting Started (Horizon URL, install methods)
- Data Sources (now 8)
- Link to full changelog

### 4. README.md updates
- Tool/prompt/resource counts: 51→69, 17→19, 18→21
- Data sources section: add Spicerack, MTGGoldfish, Moxfield
- Architecture diagram: add Spicerack, MTGGoldfish, Moxfield mounts
- Status table: add Spicerack, MTGGoldfish, v2.3.0 rows
- FastMCP version: 3.1.x → 3.2.x
- Stack table: add selectolax
- "What You Can Do" section: add constructed/metagame examples
- Tools tables: add metagame, sideboard, Moxfield search tools

### 5. docs/COOKBOOK.md updates
- Add "Constructed" section with metagame/sideboard recipes
- Add "Moxfield" recipe for deck search/import
- Update "What's Next" footer: 51→69 tools, 17→19 prompts, 18→21 resources
- Verify existing recipes still accurate

### 6. CONTRIBUTING.md updates
- Tool/prompt/resource counts in doc table
- Verify code examples still accurate

### 7. docs/README.md
- Add RELEASE_NOTES_v3.md link

### 8. docs/ARCHITECTURE.md
- Tool/prompt/resource counts in overview comment
- Verify project structure tree is current (should be from v2.3.0 PR)

### 9. Verify-only documents
- `docs/TOOL_DESIGN.md` — already updated in v2.3.0 PR
- `docs/SERVICE_CONTRACTS.md` — already updated
- `docs/DATA_SOURCES.md` — already updated
- `docs/CACHING_DESIGN.md` — already updated

### 10. PEP 8 comment fixes
~5-6 inline comments with lowercase starts. Fix to sentence case.

## What is NOT in scope

- No code changes beyond version bumps and comment fixes
- No dependency bumps
- No test changes (issue #56 stays separate)
- No new features or tools

## Release notes — friend-friendly opener

> mtg-mcp-server now covers competitive constructed. Ask Claude about the Modern metagame and get a tiered breakdown with deck prices. Request a stock Boros Energy list and get the full 75. Say "build me a sideboard for this deck in Pioneer" and get a categorized 15-card sideboard with format staple markers. Ask for a sideboard guide against Azorius Control and get an in/out plan. Or generate a full sideboard matrix across all your common matchups. Plus Moxfield deck search, tournament results from Spicerack, and fuzzy archetype matching so you don't need exact names. 69 tools across 8 data sources.
