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

### 3. Spellbook (sequential — need combo ID from search)

1. `spellbook_find_combos(card_name="Muldrotha, the Gravetide")` — expect combos with card lists
2. `spellbook_combo_details(combo_id=<first ID from above>)` — expect step-by-step description

### 4. Draft / 17Lands

`draft_card_ratings(set_code="FDN")` — expect card ratings with GIH WR data. If no data for FDN, try BLB, MKM, or OTJ.

### 5. EDHREC (may fail)

`edhrec_commander_staples(commander_name="Muldrotha, the Gravetide")` — expect synergy scores. EDHREC scrapes undocumented endpoints; SKIP on error, don't fail the overall test.

### 6. Rules Engine (parallel batch)

| Call | Validate |
|------|----------|
| `rules_lookup(query="704.5k")` | Rule number 704.5k present, "world rule" in text |
| `keyword_explain(keyword="deathtouch")` | Glossary definition, rules section, interactions section (trample listed) |
| `rules_interaction(mechanic_a="deathtouch", mechanic_b="trample")` | Both mechanics have rules, interaction note present |
| `rules_scenario(scenario="A 1/1 creature with deathtouch and trample is blocked by a 5/5 creature")` | Rule citations present, scenario analysis |
| `combat_calculator(attackers=["Typhoid Rats"], blockers=["Grizzly Bears"], keywords=["deathtouch"])` | Combat steps, damage assignment, outcome |

### 7. Core Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `commander_overview(commander_name="Muldrotha, the Gravetide")` | Card header + combos section + data sources |
| `evaluate_upgrade(card_name="Spore Frog", commander_name="Muldrotha, the Gravetide")` | Card details + synergy data |
| `price_comparison(cards=["Lightning Bolt", "Counterspell"])` | USD prices for both cards (avoid Sol Ring — Oracle Cards printing lacks prices) |
| `deck_validate(decklist=["4 Lightning Bolt", "4 Sol Ring", "52 Island"], format="modern")` | INVALID — Sol Ring not modern-legal |

### 8. Deck Building Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `theme_search(theme="sacrifice", format="commander", limit=5)` | Cards with sacrifice-related oracle text |
| `tribal_staples(tribe="Elf", format="commander")` | Elf creature cards with oracle text |
| `color_identity_staples(color_identity="simic")` | Cards in UG color identity |
| `rotation_check()` | Standard-legal sets listed with release dates |

### 9. Moxfield (may fail — reverse-engineered API)

`moxfield_decklist(deck_id="LDBm1gOVD0W8OMPgoYQJnw")` — expect deck name, commander board, mainboard with card names and quantities. Moxfield uses undocumented v3 endpoints; SKIP on error, don't fail the overall test.

### 10. Commander Depth Workflows (parallel batch)

| Call | Validate |
|------|----------|
| `commander_comparison(commanders=["Muldrotha, the Gravetide", "Meren of Clan Nel Toth"])` | Both commanders compared, color identity shown |
| `color_identity_staples(color_identity="sultai", category="creatures")` | Creature cards in BUG identity |

### 11. Cross-Tool Consistency

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
| Spellbook | 2 | | | |
| Draft | 1 | | | |
| EDHREC | 1 | | | |
| Rules | 5 | | | |
| Core Workflows | 4 | | | |
| Deck Building | 4 | | | |
| Moxfield | 1 | | | |
| Commander Depth | 2 | | | |
| Consistency | 1 | | | |
| **Total** | **29** | | | |

### Failures
[Details for each FAIL — what was expected vs actual]

### Skips
[Reason for each SKIP — feature flag, tool unavailable, etc.]

### Verdict
[HEALTHY / DEGRADED (skips only) / FAILING (any fails)]
```
