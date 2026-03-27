# Spec 3: Format-Specific Workflows

> **Status:** Design approved
> **Date:** 2026-03-26
> **Scope:** Deck building, Commander depth, Limited expansion, and Constructed format workflows
> **Prerequisite:** Spec 1 (Infrastructure Modernization) and Spec 2 (Cross-Format Tools) must be complete

This spec is part of a 3-spec expansion:
- **Spec 1:** Infrastructure Modernization — Scryfall bulk data, rules engine, structured output, CodeMode readiness
- **Spec 2:** Cross-Format Tools & Utilities — validation, card discovery, format info, mana base
- **Spec 3 (this):** Format-Specific Workflows — deck building, Commander depth, Limited expansion

---

## Context & Prerequisites

After Specs 1 and 2, the server has:
- **Scryfall bulk data** with prices, legalities, color identity (~32K cards in memory)
- **Comprehensive Rules** searchable engine
- **Validation tools** (`deck_validate`, `format_legality`)
- **Card discovery** (`format_search`, `format_staples`, `similar_cards`)
- **Mana base analysis** (`suggest_mana_base`)
- **Structured output** and **response_format** on all tools
- **~36 tools**, strong tag taxonomy, CodeMode available

This spec adds the highest-level workflow tools — the "intent-level" tools that compose multiple backends and lower-level tools to answer complex questions like "build me a deck" or "help me with this sealed pool."

---

## Deck Building Workflows

### `theme_search`

Find cards matching a theme — mechanical (aristocrats, voltron, tokens), tribal (samurai, merfolk, dragons), or abstract/flavorful (music, death, chaos, ocean). This is the creative discovery tool.

| Field | Detail |
|---|---|
| Input | `theme: str`, `color_identity: str \| None = None`, `format: str \| None = None`, `max_price: float \| None = None`, `limit: int = 20` |
| Output | Themed card list with name, mana cost, type, relevance reason, price. Grouped by relevance tier (strong match, moderate match, flavor match). |
| Backends | Scryfall bulk (oracle text, type line, subtypes, keywords) + EDHREC (synergy data for mechanical themes, optional) |
| Tags | `search`, `build`, `all-formats`, `stable` |

Theme resolution strategy — the key challenge of this tool:

**Tribal themes** (samurai, merfolk, elf, dragon, etc.):
- Primary: search type line for the creature type
- Secondary: search oracle text for "Samurai" / tribal synergies ("whenever a Samurai", "each Samurai you control")
- Include tribal support cards (e.g., "Kindred Discovery" for any tribe)

**Mechanical themes** (aristocrats, voltron, tokens, reanimator, storm, stax, etc.):
- Map theme name to oracle text patterns:
  - "aristocrats" → "whenever a creature dies" OR "sacrifice a creature" OR "when this creature dies"
  - "voltron" → "equipped creature" OR "enchanted creature gets" OR "attach" (plus auras/equipment type)
  - "tokens" → "create" AND "token" in oracle text
  - "reanimator" → "return.*from.*graveyard to the battlefield"
  - "storm" → "storm" keyword OR "whenever you cast" OR "for each spell cast"
  - "stax" → "can't" OR "don't untap" OR "each opponent sacrifices"
  - "blink" → "exile.*return.*to the battlefield"
  - "mill" → "mill" keyword OR "put.*from.*library into.*graveyard"
  - "landfall" → "landfall" keyword OR "whenever a land enters"
  - "spellslinger" → "whenever you cast an instant or sorcery" OR "magecraft"
- These mappings are maintained as a config/dict in the service, not hardcoded per-query. New themes can be added by extending the mapping.

**Abstract/flavor themes** (music, death, ocean, fire, chaos, etc.):
- Search oracle text AND card names for the term and related words
- "music" → "song", "sing", "melody", "instrument", "bard", "perform"
- "death" → "die", "dies", "destroy", "graveyard", "mortality", "kill", "lethal"
- "ocean" → "sea", "island", "fish", "merfolk", "whale", "tide", "deep"
- These synonym maps are best-effort. The tool is honest in its output about what it searched for.
- Future enhancement: use LLM sampling (MCP sampling capability) to expand theme → keyword mappings. Not in this spec.

**Relevance scoring:**
- Strong match: oracle text contains theme keyword in a mechanically relevant way
- Moderate match: type line or subtypes match, or partial oracle text match
- Flavor match: card name contains theme term, or flavor-adjacent mechanics

### `build_around`

Given 1-5 "build around" cards, find synergistic cards for a deck. The "I opened this mythic, what goes with it?" tool.

| Field | Detail |
|---|---|
| Input | `cards: list[str]` (1-5 card names), `format: str`, `budget: float \| None = None`, `limit: int = 20` |
| Output | Synergistic cards grouped by role (enablers, payoffs, support), with name, mana cost, type, synergy explanation, price |
| Backends | Scryfall bulk (oracle text analysis) + Spellbook (combos involving these cards) + EDHREC (synergy scores, Commander only, optional) |
| Tags | `build`, `all-formats`, `stable` |

Synergy detection:
- Parse build-around cards' oracle text for key mechanics (keywords, triggers, conditions)
- Search bulk data for cards that: trigger off the same conditions, provide what the build-around needs, benefit from the same strategy
- Example: build around "Feather, the Redeemed" → find cheap instant/sorcery cards that target your own creatures
- Spellbook data adds combo potential (if the build-around enables known combos)
- Filter by format legality and budget

### `complete_deck`

Given a partial decklist (any number of cards) and a format, identify what's missing and suggest cards to fill gaps.

| Field | Detail |
|---|---|
| Input | `decklist: list[str]`, `format: str`, `commander: str \| None = None`, `budget: float \| None = None` |
| Output | Gap analysis (how many cards needed, what roles are missing), suggested cards by role (removal, card draw, ramp, win conditions, lands), with mana base suggestions |
| Backends | Scryfall bulk (card data + legalities) + EDHREC (staples for Commander, optional) |
| Tags | `build`, `all-formats`, `stable` |

Gap analysis:
- Calculate target size (60 for constructed, 100 for Commander, 40 for limited)
- Categorize existing cards by role: creatures, removal, card draw, ramp/mana, protection, win conditions, lands, other
- Compare to healthy deck ratios for the format:
  - Commander typical: 36-38 lands, 10+ ramp, 8-10 card draw, 8-10 removal, 25-30 creatures/threats
  - Constructed typical: 22-26 lands, 4-8 removal, varies heavily by archetype
  - Limited typical: 17 lands, 14-18 creatures, 5-8 spells
- Identify underrepresented categories and search for cards to fill them
- For Commander: leverage EDHREC staples data for the commander (if available)
- Suggest mana base using `suggest_mana_base` logic

---

## Commander Depth

### `commander_comparison`

Compare 2-5 commanders head-to-head. Useful for choosing which commander to build.

| Field | Detail |
|---|---|
| Input | `commanders: list[str]` (2-5 commander names) |
| Output | Side-by-side comparison table: mana cost, color identity, type, power/toughness, EDHREC rank/popularity, combo count, top 3 shared staples, top 3 unique staples per commander, average deck price |
| Backends | Scryfall bulk (card data) + EDHREC (staples/popularity, optional) + Spellbook (combo count) |
| Tags | `commander`, `analyze`, `stable` |
| Progress | Reports progress (1/3 resolving, 2/3 fetching data, 3/3 formatting) |

### `tribal_staples`

Best cards for a creature type within a color identity. Goes beyond `theme_search` by specifically pulling tribal synergy data.

| Field | Detail |
|---|---|
| Input | `tribe: str` (e.g., "Goblin", "Merfolk", "Samurai"), `color_identity: str \| None = None`, `format: str \| None = None`, `limit: int = 20` |
| Output | Cards grouped by: lords/anthems, tribal synergy, best members, tribal support (e.g., Kindred cards). With synergy score if EDHREC data available. |
| Backends | Scryfall bulk (type line + oracle text search) + EDHREC (synergy, optional) |
| Tags | `commander`, `search`, `build`, `stable` |

Search strategy:
- Lords/anthems: oracle text contains "other {Tribe}" or "{Tribe} creatures you control get"
- Tribal synergy: oracle text references the tribe by name
- Best members: creatures of that type, sorted by EDHREC rank or mana efficiency
- Support: "Kindred", "Tribal" type cards + "choose a creature type" effects

### `precon_upgrade`

Analyze and upgrade an official Commander precon. The "I just bought a precon, now what?" tool.

| Field | Detail |
|---|---|
| Input | `precon_name: str` OR `decklist: list[str]` + `commander: str`, `budget: float = 50.0`, `num_upgrades: int = 10` |
| Output | Analysis of the precon (strengths, weaknesses, theme), then ranked upgrade suggestions with: card in → card out, synergy improvement, price, reasoning |
| Backends | Scryfall bulk (card data) + EDHREC (staples + synergy) + Spellbook (combos) |
| Tags | `commander`, `build`, `stable` |

Strategy:
- Analyze the existing deck (mana curve, theme, win conditions) using `deck_analysis` logic
- Identify weakest cards using `suggest_cuts` logic
- Find upgrades within budget using `budget_upgrade` logic
- Pair each upgrade with a specific cut, explaining the improvement
- Precon name resolution: maintain a lookup table of recent precon names → decklists, OR accept a decklist directly

Note on precon name resolution: official precon decklists change with each set release. Rather than maintaining a database of all precons, the preferred approach is to accept decklists directly. The `precon_name` parameter is a future convenience — the MVP accepts `decklist + commander`. The prompt `upgrade_precon` (below) guides users to provide their decklist.

### `color_identity_staples`

Top cards across ALL commanders in a color identity. "What are the best Sultai cards regardless of commander?"

| Field | Detail |
|---|---|
| Input | `color_identity: str` (e.g., "sultai", "BUG", "WR"), `category: str \| None = None` (e.g., "creatures", "instants", "lands"), `limit: int = 20` |
| Output | Ranked cards with name, synergy (averaged across commanders), inclusion %, price |
| Backends | Scryfall bulk (color identity filter) + EDHREC (aggregated staples, optional) |
| Tags | `commander`, `search`, `stable` |

Without EDHREC: falls back to EDHREC rank from Scryfall bulk data as a popularity proxy, filtered by color identity.

---

## Limited Expansion

### `sealed_pool_build`

Given a sealed pool (typically 84-90 cards from 6 packs), suggest the best 40-card deck builds.

| Field | Detail |
|---|---|
| Input | `pool: list[str]`, `set_code: str` |
| Output | 1-3 suggested builds, each with: colors, decklist (23 nonland + 17 land), mana curve, bomb identification, key synergies, cards to watch for in the sideboard. If 17Lands data available, includes win rate data for the chosen colors/archetype. |
| Backends | Scryfall bulk (card data) + 17Lands (card ratings + archetype win rates, optional) |
| Tags | `limited`, `build`, `draft`, `stable` |

Build algorithm:
1. Score each card in the pool using 17Lands GIH WR (if available) or heuristic evaluation (bombs, removal, creatures, filler)
2. Evaluate each possible 2-color pair:
   - Count playable cards (non-land cards worth running)
   - Sum card quality scores
   - Check mana curve distribution
   - Bonus for bombs, removal density, synergy
3. Rank color pairs by overall deck quality
4. For top 1-3 builds: select best cards, suggest land split based on color pip ratios
5. Identify splash opportunities (powerful off-color cards with easy mana requirements)

### `draft_signal_read`

Analyze draft picks so far and recommend a direction. "What's open based on what I've been passed?"

| Field | Detail |
|---|---|
| Input | `picks: list[str]`, `set_code: str`, `current_pack: list[str] \| None = None` |
| Output | Analysis: color commitment level, identified signals (what colors are open based on late picks), archetype fit, picks that support multiple directions, recommended direction with reasoning |
| Backends | 17Lands (ALSA data — cards with low ALSA that you see late = signal that color is open) + Scryfall bulk (card colors) |
| Tags | `limited`, `draft`, `analyze`, `stable` |

Signal analysis:
- For each card in picks: note color, expected pick position (ALSA), actual pick position
- Cards seen significantly later than their ALSA → that color is likely open
- Aggregate signals by color pair to recommend archetype direction
- If `current_pack` provided: rank current pack cards with signal context ("this is on-color and the color appears open")

### `draft_log_review`

Review a completed draft — what went right, what went wrong, where were the pivot points?

| Field | Detail |
|---|---|
| Input | `picks: list[str]` (in order, pack 1 pick 1 through pack 3 pick 14), `set_code: str`, `final_deck: list[str] \| None = None` |
| Output | Pick-by-pick analysis: was this the highest GIH WR card? Was it on-color? Key decision points identified. Overall draft grade. If final_deck provided: what % of picks made the deck, sideboard value assessment. |
| Backends | 17Lands (card ratings for comparison) + Scryfall bulk (card data) |
| Tags | `limited`, `draft`, `analyze`, `stable` |

---

## Constructed Format Tools

### `rotation_check`

What's rotating out of Standard? Which of your cards are losing legality?

| Field | Detail |
|---|---|
| Input | `cards: list[str] \| None = None` |
| Output | Sets currently in Standard with rotation dates. If cards provided: which of your cards are in rotating sets, suggested replacements from non-rotating sets. |
| Backends | Scryfall API (set data — release dates and rotation info) + Scryfall bulk (card set membership) |
| Tags | `constructed`, `standard`, `analyze`, `stable` |

Note: Standard rotation follows a fixed schedule (oldest sets rotate when fall set releases). The tool calculates rotation based on set release dates from the Scryfall sets API.

---

## New Prompts

| Prompt | Arguments | What it guides |
|---|---|---|
| `build_tribal_deck` | `tribe: str, commander: str \| None, format: str, budget: float \| None` | Tribal deck building: tribal_staples → build_around → suggest_mana_base → deck_validate |
| `build_theme_deck` | `theme: str, format: str, color_identity: str \| None, budget: float \| None` | Theme deck building: theme_search → build_around → complete_deck → deck_validate |
| `upgrade_precon` | `commander: str, budget: float` | Precon upgrade: commander_overview → deck_analysis → suggest_cuts → budget_upgrade → validate |
| `sealed_session` | `set_code: str` | Sealed session: enter pool → sealed_pool_build → review builds → sideboard planning |
| `draft_review` | `set_code: str` | Post-draft review: enter picks → draft_log_review → analyze decisions → identify improvement areas |
| `compare_commanders` | `commanders: str` | Commander comparison: commander_comparison → combo analysis → staple overlap → budget comparison → recommendation |
| `rotation_plan` | `(no args)` | Standard rotation prep: rotation_check → identify expiring cards → find replacements → evaluate new options |

---

## New Resources

| URI | Provider | Description |
|---|---|---|
| `mtg://theme/{theme}` | workflow | Theme keyword mappings as JSON (what oracle text patterns define "aristocrats", "voltron", etc.) |
| `mtg://tribe/{tribe}/staples` | scryfall_bulk | Top cards for a creature type as JSON |
| `mtg://draft/{set_code}/signals` | workflow | Color openness heuristics for a set |

---

## Tool Count Impact

This spec adds 11 new tools, bringing the total from ~37 (post Spec 2) to ~48.

| Category | New tools | Running total |
|---|---|---|
| Deck building | 3 (theme_search, build_around, complete_deck) | ~12 build/analyze tools |
| Commander | 4 (commander_comparison, tribal_staples, precon_upgrade, color_identity_staples) | ~12 commander tools |
| Limited | 3 (sealed_pool_build, draft_signal_read, draft_log_review) | ~7 limited tools |
| Constructed | 1 (rotation_check) | ~5 constructed tools |

At 48 tools, CodeMode (from Spec 1) becomes genuinely valuable. The tag taxonomy ensures discovery remains functional:
- `build` tag: 4 tools (theme_search, build_around, complete_deck, precon_upgrade)
- `commander` tag: 11 tools
- `draft`/`limited` tag: 7 tools
- `constructed` tag: 5 tools
- `all-formats` tag: ~15 tools

---

## Implementation Notes for Fresh Session

**Key patterns from Specs 1 and 2:**

1. **Structured output:** All tools return `ToolResult(content=markdown, structured_content=json)`
2. **Response format:** Workflow tools accept `response_format: str = "detailed"`
3. **Tags:** Format + function tags from expanded taxonomy
4. **Scryfall bulk:** `ScryfallBulkClient` for offline card lookups. Available in workflow lifespan.
5. **Card resolver:** Resolves names to `Card` objects from bulk data with API fallback.
6. **Rules service:** `RulesService` for keyword/rule lookups.
7. **Error handling:** `ToolError` from `fastmcp.exceptions` with actionable messages. `from exc` in except blocks.
8. **Partial failure:** Workflows use `asyncio.gather(return_exceptions=True)` for optional backends. EDHREC/17Lands data is always optional.
9. **Progress reporting:** Multi-step workflows accept `on_progress` callback; `server.py` bridges to `ctx.report_progress()`.
10. **Testing:** `AsyncMock` for workflow tests (pure functions). `fastmcp.Client(transport=server)` for provider tests.

**Architecture decisions for this spec:**

- **Deck building tools** go on the workflow server (compose multiple backends)
- **Commander depth tools** go on the workflow server (compose EDHREC + Spellbook + bulk)
- **Limited tools** go on the workflow server (compose 17Lands + bulk)
- **`theme_search`** lives in `workflows/` as a pure function — it's composable and used by `build_around` and `complete_deck`
- **Theme mappings** (mechanical theme → oracle text patterns, flavor → synonym lists) live in a data file or dict in the theme_search module. They should be easy to extend without code changes.
- **`rotation_check`** needs Scryfall sets API — add `get_sets()` method to `ScryfallClient` service if not already present.

**Where to put new workflow modules:**

| Module | Tools |
|---|---|
| `workflows/building.py` | `theme_search`, `build_around`, `complete_deck` |
| `workflows/commander.py` (existing) | `commander_comparison`, `tribal_staples`, `precon_upgrade`, `color_identity_staples` |
| `workflows/draft.py` (existing) | `sealed_pool_build`, `draft_signal_read`, `draft_log_review` |
| `workflows/constructed.py` (new) | `rotation_check` |

---

## Testing Strategy

**Theme search:** Test each theme type (tribal, mechanical, abstract) with fixture cards. Verify relevance grouping.

**Deck building:** Test `build_around` with known synergistic cards. Test `complete_deck` gap analysis with intentionally incomplete decks (missing removal, wrong land count, etc.).

**Sealed:** Test `sealed_pool_build` with a fixture pool (~84 cards). Verify builds have correct card count, reasonable mana curve, bombs identified.

**Draft signals:** Test with mock pick sequences. Verify signal detection (late high-ALSA cards → color open).

**Commander comparison:** Test with 2 commanders, verify side-by-side output includes all expected fields.

**Edge cases:**
- `theme_search("chaos")` — abstract theme with broad matches, should still return useful results
- `sealed_pool_build` with a pool that's clearly one color — should build mono-color
- `build_around` with cards that have no synergies in the database — should return "no strong synergies found" with general format staples as fallback
- `draft_signal_read` with only 3 picks (early draft) — should say "too early for strong signals"
- `commander_comparison` with commanders in different color identities — should note the color difference prominently
- `rotation_check` called when no rotation is imminent — should say "next rotation: {date}"

---

## Future Considerations (Not In This Spec)

These came up during brainstorming but are deferred:

- **Metagame data** (MTGTop8, MTGGoldfish) — would power "what's the Standard meta?" tools. Requires new scraping backends, fragile like EDHREC.
- **Collection management** (Moxfield integration) — "which upgrades do I already own?" Requires auth and unreliable API.
- **Cube support** — custom card pool draft advice. Needs a way to define cube contents.
- **Matchup analysis** — "how does my deck match up against X archetype?" Needs metagame data.
- **AI-powered theme expansion** — use MCP sampling to have the LLM expand "music" into search terms. Interesting but adds complexity.
- **Tournament deck tracking** (Spicerack) — competitive paper results. Niche audience.
