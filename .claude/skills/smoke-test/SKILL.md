---
name: smoke-test
description: Use when interactively verifying the MTG MCP server works end-to-end by calling its MCP tools against real APIs
disable-model-invocation: true
argument-hint: "[horizon]"
---

# Interactive MCP Server Smoke Test

Exercise every tool category on the MTG MCP server via real MCP tool calls and validate results.

## Target Server

- **Default:** local server — tools prefixed `mcp__mtg__`
- **`/smoke-test horizon`:** production Horizon server — tools prefixed `mcp__claude_ai_mtg-mcp-server-horizon__`

Use `$ARGUMENTS` to select. If empty or not "horizon", use local.

## Execution

**Parallelize aggressively.** Batch independent tool calls in the same message. Only serialize when a later call depends on an earlier result (e.g., combo detail needs an ID from combo search).

For each call: note PASS / FAIL (with detail) / SKIP (tool unavailable or feature-flagged).

## Test Sequence

### 1. Health + Scryfall API (parallel batch)

| Call | Validate |
|------|----------|
| `ping()` | Returns "pong" |
| `scryfall_card_details(name="Sol Ring")` | Artifact, mana cost `{1}`, commander legal |
| `scryfall_search_cards(query="t:creature id:sultai cmc<=3")` | Multiple creature results |
| `scryfall_card_rulings(name="Muldrotha, the Gravetide")` | At least one ruling (Sol Ring has 0 rulings; Muldrotha reliably has 8+) |

### 2. Bulk Data (parallel batch)

| Call | Validate |
|------|----------|
| `bulk_card_lookup(name="Sol Ring")` | **Regression check:** type_line = "Artifact" (NOT "Card // Card"), set NOT "acmm", commander "legal" (NOT "not_legal"), EDHREC rank present. Note: Oracle Cards printing (SOC) may lack USD prices — this is expected, not a failure |
| `bulk_card_lookup(name="Delver of Secrets")` | DFC lookup works, oracle text present |
| `bulk_card_search(query="Lightning", search_field="name")` | Lightning Bolt in results |
| `bulk_card_search(query="Creature", search_field="type", limit=3)` | Creature type lines |

If bulk tools unavailable (older server), try `bulk_card_lookup` / `bulk_card_search` and SKIP the regression check.

### 3. Bulk Format Staples — Ranking Modes (parallel batch)

| Call | Validate |
|------|----------|
| `bulk_format_staples(format="commander", limit=5)` | EDHREC mode: header contains "Rank", Sol Ring likely in top 5 |
| `bulk_format_staples(format="modern", limit=5)` | Tournament or competitive mode: header contains "% Decks" or "Score" (NOT "Rank #") |
| `bulk_format_staples(format="pauper", limit=5)` | Tournament or competitive mode: header contains "% Decks" or "Score", results should be commons (Lightning Bolt, Counterspell typical) |

Commander uses EDHREC rank (singleton format). Modern and Pauper auto-select tournament mode (MTGGoldfish data) or competitive heuristic (fallback). Verify no Commander staples like Sol Ring appear in Modern/Pauper results.

### 4. Spellbook (sequential — need combo ID from search)

1. `spellbook_find_combos(card_name="Muldrotha, the Gravetide")` — expect combos with card lists
2. `spellbook_combo_details(combo_id=<first ID from above>)` — expect step-by-step description

### 5. Draft / 17Lands

`draft_card_ratings(set_code="FDN")` — expect card ratings with GIH WR data. If no data for FDN, try BLB, MKM, or OTJ.

### 6. EDHREC (may fail)

`edhrec_commander_staples(commander_name="Muldrotha, the Gravetide")` — expect synergy scores. EDHREC scrapes undocumented endpoints; SKIP on error, don't fail the overall test.

### 7. Rules Engine (parallel batch)

| Call | Validate |
|------|----------|
| `rules_lookup(query="704.5k")` | Rule number 704.5k present, "world rule" in text |
| `keyword_explain(keyword="deathtouch")` | Glossary definition, rules section, interactions section (trample listed) |
| `rules_interaction(mechanic_a="deathtouch", mechanic_b="trample")` | Both mechanics have rules, interaction note present |
| `rules_scenario(scenario="A 1/1 creature with deathtouch and trample is blocked by a 5/5 creature")` | Rule citations present, scenario analysis |
| `combat_calculator(attackers=["Typhoid Rats"], blockers=["Grizzly Bears"], keywords=["deathtouch"])` | Combat steps, damage assignment, outcome |

### 8. Core Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `commander_overview(commander_name="Muldrotha, the Gravetide")` | Card header + combos section + data sources |
| `evaluate_upgrade(card_name="Spore Frog", commander_name="Muldrotha, the Gravetide")` | Card details + synergy data |
| `price_comparison(cards=["Lightning Bolt", "Counterspell"])` | USD prices for both cards (avoid Sol Ring — Oracle Cards printing lacks prices) |
| `deck_validate(decklist=["4 Lightning Bolt", "4 Sol Ring", "52 Island"], format="modern")` | INVALID — Sol Ring not modern-legal |

### 9. Deck Building Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `theme_search(theme="sacrifice", format="commander", limit=5)` | Cards with sacrifice-related oracle text |
| `tribal_staples(tribe="Elf", format="commander")` | Elf creature cards with oracle text |
| `color_identity_staples(color_identity="simic")` | Cards in UG color identity |
| `rotation_check()` | Standard-legal sets listed with release dates |

### 10. MTGGoldfish (sequential — need archetype from metagame)

1. `goldfish_metagame(format="Modern")` — expect archetypes with meta share %, deck count, prices
2. `goldfish_format_staples(format="Modern", limit=5)` — expect card names with % of decks and avg copies
3. `goldfish_archetype_list(format="Modern", archetype=<first archetype name from step 1>)` — expect mainboard card list
4. `goldfish_deck_price(format="Modern", archetype=<same archetype>)` — expect price estimate

MTGGoldfish scrapes HTML — SKIP on error, don't fail the overall test.

### 11. Spicerack (sequential — need tournament ID from first call)

1. `spicerack_recent_tournaments(format="Legacy", num_days=30)` — expect at least one tournament, format = "Legacy"
2. `spicerack_tournament_results(tournament_id=<first ID from above>)` — expect standings with player names and records
3. `spicerack_format_decklists(format="Legacy", num_days=30, limit=5)` — expect decklists with card text or Moxfield URLs

### 12. Moxfield (may fail — reverse-engineered API, parallel batch)

| Call | Validate |
|------|----------|
| `moxfield_decklist(deck_id="DuXYtaJFEkScp1U1dxvAmw")` | Deck name, commander board, mainboard with card names and quantities |
| `moxfield_search_decks(query="modern", format="modern", page_size=3)` | At least 1 deck summary with name, format, author |
| `moxfield_user_decks(username="j4th")` | User's public decks listed (or ToolError if user not found) |

Moxfield uses undocumented endpoints; SKIP on error, don't fail the overall test.

### 13. Metagame Workflows (sequential — need format data)

1. `metagame_snapshot(format="modern")` — expect tiered archetype list with meta shares, T1/T2/T3 labels
2. `archetype_decklist(format="modern", archetype=<first T1 archetype from step 1>)` — expect mainboard + sideboard card list
3. `format_entry_guide(format="modern")` — expect format rules, budget-sorted archetypes

If MTGGoldfish unavailable, metagame_snapshot should fall back to Spicerack data. SKIP section on error.

### 14. Sideboard Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `suggest_sideboard(decklist=["4 Lightning Bolt", "4 Goblin Guide", "4 Eidolon of the Great Revel", "4 Monastery Swiftspear", "4 Searing Blaze", "4 Lava Spike", "4 Rift Bolt", "4 Skullcrack", "12 Mountain", "4 Inspiring Vantage", "4 Sacred Foundry", "4 Sunbaked Canyon"], format="modern")` | Categorized sideboard suggestions (15 cards max) |
| `sideboard_guide(decklist=["4 Lightning Bolt", "4 Goblin Guide", "12 Mountain"], sideboard=["2 Rest in Peace", "2 Smash to Smithereens"], format="modern", matchup="control")` | IN/OUT plan with reasoning |
| `sideboard_matrix(decklist=["4 Lightning Bolt", "4 Goblin Guide", "12 Mountain"], sideboard=["2 Rest in Peace", "2 Smash to Smithereens"], format="modern", matchups=["aggro", "control", "combo"])` | Matrix table with IN/OUT/FLEX per matchup |

### 15. Commander Depth Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `commander_comparison(commanders=["Muldrotha, the Gravetide", "Meren of Clan Nel Toth"])` | Both commanders compared, color identity shown |
| `color_identity_staples(color_identity="sultai", category="creatures")` | Creature cards in BUG identity |

### 16. Cross-Tool Consistency

Compare results from step 1 (`scryfall_card_details("Sol Ring")`) and step 2 (`bulk_card_lookup("Sol Ring")`):
- Names match
- Type lines match
- Both show commander: legal
- Scryfall API returns prices (latest printing); bulk data may lack prices (Oracle Cards printing may be a set without retail pricing like SOC)

## Report Format

```
## Smoke Test Results — [local/horizon] — [date]

| Category | Tests | Pass | Fail | Skip |
|----------|-------|------|------|------|
| Health | 1 | | | |
| Scryfall API | 3 | | | |
| Bulk Data | 4 | | | |
| Format Staples | 3 | | | |
| Spellbook | 2 | | | |
| Draft | 1 | | | |
| EDHREC | 1 | | | |
| Rules | 5 | | | |
| Core Workflows | 4 | | | |
| Deck Building | 4 | | | |
| MTGGoldfish | 4 | | | |
| Spicerack | 3 | | | |
| Moxfield | 3 | | | |
| Metagame | 3 | | | |
| Sideboard | 3 | | | |
| Commander Depth | 2 | | | |
| Consistency | 1 | | | |
| **Total** | **47** | | | |

### Failures
[Details for each FAIL — what was expected vs actual]

### Skips
[Reason for each SKIP — feature flag, tool unavailable, etc.]

### Verdict
[HEALTHY / DEGRADED (skips only) / FAILING (any fails)]
```
