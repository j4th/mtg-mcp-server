# Spec 3: Comprehensive v2.0 — Rules Engine, Structured Output, Format Workflows

> **Status:** Design approved
> **Date:** 2026-03-27
> **Scope:** Comprehensive Rules engine, structured output, CodeMode readiness, deck building, Commander depth, Limited expansion, Constructed workflows
> **Prerequisite:** Spec 2 (Cross-Format Tools) complete
> **Target:** v2.0 release

This spec is part of a 3-spec expansion:
- **Spec 1:** Infrastructure Modernization — Scryfall bulk data *(complete)*, remaining items folded into this spec
- **Spec 2:** Cross-Format Tools & Utilities — validation, card discovery, format info, mana base *(complete)*
- **Spec 3 (this):** Everything else — rules engine, structured output, CodeMode, format-specific workflows

---

## Context & Prerequisites

After Spec 2, the server has:
- **Scryfall bulk data** with prices, legalities, color identity (~32K cards in memory)
- **35 tools** across 5 backends + workflows, 8 prompts, tagged taxonomy
- **Validation tools** (`deck_validate`, `format_legality`, `ban_list`, `card_in_formats`)
- **Card discovery** (`format_search`, `format_staples`, `similar_cards`, `random_card`)
- **Mana base analysis** (`suggest_mana_base`, `price_comparison`)
- **Cross-format utilities** (color identity parser, format rules, query parser)

This spec completes the v2.0 vision with four major additions:
1. **Comprehensive Rules Engine** — turns the server from a card database into a rules judge capable of answering interaction questions, explaining keywords with real card examples, and walking through game scenarios
2. **Structured Output + CodeMode** — machine-readable JSON alongside markdown, response_format parameter, CodeMode for tool discovery at scale
3. **Format-specific workflow tools** — "intent-level" tools for deck building, Commander depth, Limited, and Constructed
4. **Rules integration across existing tools** — rules-aware enhancements to `similar_cards`, `format_search`, `deck_validate`, and new workflow tools

---

## Comprehensive Rules Engine

### Service: `services/rules.py`

**What:** Download the MTG Comprehensive Rules text file (~943 KB), parse into a searchable index, and serve rule lookups from memory. This is the foundation that turns the server into a rules judge.

Not a `BaseClient` subclass (file-based, same pattern as Scryfall bulk data).

**Data source:**
- URL is not stable (date embedded in filename, e.g., `MagicCompRules 20260227.txt`)
- Strategy: configurable URL in settings with a known-good default. Updated manually when new rules drop (~4x/year with set releases). Env override via `MTG_MCP_RULES_URL`.
- Default URL: `https://media.wizards.com/2026/downloads/MagicCompRules%2020260227.txt`
- File is ~943 KB plain text, UTF-8 with BOM

**Parsing:**
- ~9,274 lines, ~3,490 numbered rule entries
- Structure: table of contents, then numbered rules (e.g., `100.1`, `704.5k`), then glossary
- Parse into: `dict[str, Rule]` keyed by rule number, `dict[str, GlossaryEntry]` keyed by term
- `Rule` model: `number: str`, `text: str`, `subrules: list[Rule]`
- `GlossaryEntry` model: `term: str`, `definition: str`
- Section index: map section ranges (e.g., `7xx` = "Additional Rules") for browsing

**Lifecycle:**
- Lazy-load on first access (same pattern as bulk data — keeps stdio instant)
- `rules_refresh_hours: int = 168` (weekly check — rules update ~4x/year)
- On refresh failure: serve stale data
- `enable_rules: bool = True` — feature flag

**Search capabilities:**
- Lookup by rule number: O(1) dict access (e.g., `704.5k`)
- Keyword search: scan rule text for substring/regex matches, ranked by relevance
- Glossary lookup: exact term match + case-insensitive fuzzy matching
- Section browsing: return all rules in a section (e.g., all `7xx` rules)
- Cross-reference: rules that cite other rules (e.g., `704.5k` references `704.5`)

---

### Rules Tools

Registered on the workflow server (no separate namespace — these are cross-cutting utilities).

#### `rules_lookup`

Search comprehensive rules by keyword, rule number, or concept.

| Field | Detail |
|---|---|
| Input | `query: str`, `section: str \| None = None` |
| Output | Matching rules with full text and context (parent rule, subrules). Section filter narrows scope (e.g., "combat", "stack", "lands", "state-based"). |
| Backend | `RulesService` |
| Tags | `rules`, `all-formats`, `stable` |

Examples:
- `rules_lookup("deathtouch")` → rules 702.2a-d + glossary entry
- `rules_lookup("704.5k")` → exact rule with subrules
- `rules_lookup("legend rule")` → finds 704.5j via keyword search
- `rules_lookup("when can I cast", section="stack")` → priority/timing rules

#### `keyword_explain`

Explain what a keyword or ability word does, with rules citations and real card examples.

| Field | Detail |
|---|---|
| Input | `keyword: str` |
| Output | Rules definition, reminder text, rules section citation, up to 5 example cards from bulk data that have this keyword (with their oracle text showing the keyword in context). For evergreen keywords, notes about interactions (e.g., "Deathtouch interacts with Trample — see rule 702.2b"). |
| Backends | `RulesService` + Scryfall bulk data (card examples) |
| Tags | `rules`, `all-formats`, `stable` |

This is the "what does Ward do?" tool. Connects abstract rules to concrete cards. Searches the `keywords` field on bulk data cards, so "Flying" returns real Flying creatures, not just the rule text.

#### `rules_interaction`

Analyze how two cards or mechanics interact according to the rules.

| Field | Detail |
|---|---|
| Input | `mechanic_a: str`, `mechanic_b: str` |
| Output | Relevant rules explaining the interaction, step-by-step resolution, common misconceptions, rules citations. If cards are named, looks them up for context. |
| Backends | `RulesService` + Scryfall bulk data (card lookup for context) |
| Tags | `rules`, `all-formats`, `stable` |

Examples:
- `rules_interaction("Deathtouch", "Trample")` → explains you only need to assign 1 lethal damage to each blocker (702.2b + 702.19c)
- `rules_interaction("Doubling Season", "Planeswalkers")` → explains why loyalty counters are doubled on ETB but not on activation (replacement effect vs cost)
- `rules_interaction("Humility", "+1/+1 counters")` → layer system explanation (layer 6 vs layer 7d)
- `rules_interaction("First Strike", "Double Strike")` → combat damage steps

Resolution strategy:
- Look up both mechanics/cards in rules + glossary
- Find rules that reference both (or closely related concepts)
- Identify the governing rule section (combat damage, replacement effects, layers, state-based actions, stack)
- Explain step-by-step with citations

#### `rules_scenario`

Walk through a game scenario step by step with rules citations.

| Field | Detail |
|---|---|
| Input | `scenario: str` |
| Output | Step-by-step resolution: what happens, in what order, with rule citations for each step. Covers priority, stack resolution, state-based actions, triggers. |
| Backends | `RulesService` |
| Tags | `rules`, `all-formats`, `stable` |

Examples:
- `rules_scenario("I cast Lightning Bolt targeting a creature, opponent casts Counterspell targeting my Bolt, I cast another Lightning Bolt targeting the same creature")` → stack resolution order
- `rules_scenario("A 2/2 creature with three +1/+1 counters is affected by Humility")` → layer-by-layer P/T calculation
- `rules_scenario("I attack with a 1/1 Deathtouch Trample creature and it's blocked by a 5/5")` → combat damage assignment rules
- `rules_scenario("Two players each have a Blood Artist when a creature dies")` → triggered ability ordering (APNAP)

This is the most ambitious rules tool — it parses natural language scenarios and maps them to rule sequences. The tool provides the rules framework; the LLM does the reasoning about how the rules apply to the specific scenario.

#### `combat_calculator`

Resolve a combat scenario with keyword interactions.

| Field | Detail |
|---|---|
| Input | `attackers: list[str]`, `blockers: list[str]`, `keywords: list[str] \| None = None` |
| Output | Step-by-step combat: declare attackers → declare blockers → first strike damage step (if applicable) → regular damage step → state-based actions. Notes keyword interactions (deathtouch+trample, first strike+double strike, lifelink, indestructible, menace blocking requirements). |
| Backends | `RulesService` + Scryfall bulk data (look up attackers/blockers for keywords if card names provided) |
| Tags | `rules`, `all-formats`, `stable` |

If card names are provided, looks up their P/T and keywords from bulk data. If generic descriptions used ("a 3/3 with flying"), parses the description.

### Rules Resources

| URI | Provider | Description |
|---|---|---|
| `mtg://rules/{number}` | workflow | Rule text by number (e.g., `mtg://rules/704.5k`) |
| `mtg://rules/glossary/{term}` | workflow | Glossary definition by term |
| `mtg://rules/keywords` | workflow | All keywords with brief definitions |
| `mtg://rules/sections` | workflow | Section index (100s = Game Concepts, 200s = Parts of a Card, etc.) |

### Rules Prompts

| Prompt | Arguments | What it guides |
|---|---|---|
| `rules_question` | `question: str` | Guide for answering a rules question: look up relevant rules, check glossary, look up card details if referenced, explain in plain language with rule citations |

### Rules Integration Points

The rules engine enhances existing tools and powers new ones across all three specs:

**Existing Spec 2 tool enhancements:**
- **`similar_cards`** — find cards with similar *mechanical* effects, not just keyword overlap. Understanding what "whenever a creature dies" means (via rules) enables finding all aristocrats-pattern cards, not just ones that share the keyword "dies"
- **`format_search`** — rules-aware queries: "cards with replacement effects", "cards with mana abilities", "cards with state-based triggers" become parseable because the rules define these ability categories
- **`deck_validate`** — rules-aware warnings beyond legality: "this deck has Companion cards but no companion declared", "this card's color identity doesn't match its mana cost (hybrid rules)"
- **`keyword_explain`** complements `bulk_card_lookup` — one gives you the card, the other explains its mechanics

**New Spec 3 tool enhancements:**
- **`theme_search`** — mechanical theme resolution backed by rules (what IS an "aristocrats" strategy? → rules define triggers on creature death)
- **`build_around`** — synergy detection powered by rules understanding (Feather triggers on "target" → rules define targeting)
- **`sealed_pool_build`** — keyword evaluation (how good is First Strike in this format? → rules define first strike combat advantage)
- **`draft_signal_read`** — keyword-aware pick evaluation

**Cross-cutting value:**
- Turns the AI from a card database into a **rules judge** that can reason about whether interactions actually work
- Every tool that mentions a keyword can link to its rules definition
- Combo validation becomes possible: "does this Spellbook combo actually work by the rules?"

---

## Structured Output Pattern

**What:** Return `ToolResult` with both human-readable markdown (`content`) and machine-readable JSON (`structured_content`) from all tools. Backward-compatible — existing clients see markdown, future clients can consume JSON.

**Pattern:**

```python
from fastmcp.tools.tool import ToolResult

@scryfall_mcp.tool(annotations=TOOL_ANNOTATIONS)
async def card_details(name: str, response_format: str = "detailed") -> ToolResult:
    client = _get_client()
    card = await client.get_card_by_name(name)
    return ToolResult(
        content=format_card_markdown(card, response_format),
        structured_content=card.model_dump(mode="json"),
    )
```

**Scope:** All 35+ existing tools + all new tools in this spec.

**Helpers to create:**
- `format_card_markdown(card: Card, format: str = "detailed") -> str` — shared formatter
- `format_combo_markdown(combo: Combo, format: str = "detailed") -> str`
- Similar formatters for each data type
- These likely already exist inline in tools — extract and share

---

## Response Format Parameter

**What:** Per Anthropic's best practice, add a `response_format` parameter to workflow tools so LLMs can control token consumption.

**Values:**
- `"detailed"` (default) — current verbose output with full card text, all metrics, explanations
- `"concise"` — compact tables, key metrics only, no explanations. Useful when the LLM is chaining multiple tool calls and doesn't need prose.

**Scope:** All workflow tools + backend tools that return significant text.

**Implementation:** The `response_format` parameter is passed to markdown formatting helpers. The `structured_content` JSON is always full — only the human-readable text varies.

---

## CodeMode Readiness

**What:** Make the server ready to serve via CodeMode for efficient tool discovery at 50+ tools.

**Implementation:**
- Add `fastmcp[code-mode]` as an optional dependency (extra in pyproject.toml)
- `MTG_MCP_ENABLE_CODE_MODE: bool = False` feature flag
- When enabled, wrap the server: `mcp.add_transform(CodeMode())`
- Document in README how to enable CodeMode

**What makes us "ready" (no CodeMode dependency required):**
- All tools have clear, descriptive names and docstrings
- All tools are tagged (CodeMode `GetTags` uses them)
- No tools with ambiguous overlap
- Tool descriptions explain when to use THIS tool vs. similar ones

**Serving strategy:** Feature flag that transforms the single server. Simpler than maintaining two entry points. Can revisit if CodeMode graduates from experimental.

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
| `rules_question` | `question: str` | Rules Q&A: look up relevant rules, check glossary, look up cards if referenced, explain in plain language with citations |
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
| `mtg://rules/{number}` | workflow | Rule text by number (e.g., `mtg://rules/704.5k`) |
| `mtg://rules/glossary/{term}` | workflow | Glossary definition by term |
| `mtg://rules/keywords` | workflow | All keywords with brief definitions |
| `mtg://rules/sections` | workflow | Section index (100s = Game Concepts, 200s = Parts of a Card, etc.) |
| `mtg://theme/{theme}` | workflow | Theme keyword mappings as JSON (what oracle text patterns define "aristocrats", "voltron", etc.) |
| `mtg://tribe/{tribe}/staples` | scryfall_bulk | Top cards for a creature type as JSON |
| `mtg://draft/{set_code}/signals` | workflow | Color openness heuristics for a set |

---

## Tool Count Impact

This spec adds 16 new tools, bringing the total from 35 (post Spec 2) to 51.

| Category | New tools | Count |
|---|---|---|
| Rules | 5 (rules_lookup, keyword_explain, rules_interaction, rules_scenario, combat_calculator) | 5 |
| Deck building | 3 (theme_search, build_around, complete_deck) | 3 |
| Commander | 4 (commander_comparison, tribal_staples, precon_upgrade, color_identity_staples) | 4 |
| Limited | 3 (sealed_pool_build, draft_signal_read, draft_log_review) | 3 |
| Constructed | 1 (rotation_check) | 1 |

Additionally: structured output retrofit on all 35 existing tools, response_format parameter on all workflow tools, CodeMode integration.

At 51 tools, CodeMode becomes genuinely valuable. The tag taxonomy ensures discovery remains functional:
- `rules` tag: 5 tools
- `build` tag: 4 tools (theme_search, build_around, complete_deck, precon_upgrade)
- `commander` tag: 11 tools
- `draft`/`limited` tag: 7 tools
- `constructed` tag: 5 tools
- `all-formats` tag: ~20 tools (rules tools + cross-format utilities)

---

## Implementation Notes for Fresh Session

**Key patterns established in Specs 1-2:**

1. **Scryfall bulk:** `ScryfallBulkClient` for offline card lookups (~32K cards in memory). Available in workflow lifespan.
2. **Card resolver:** Resolves names to `Card` objects from bulk data with Scryfall API fallback.
3. **Tags:** Format + function tag constants in `providers/__init__.py`.
4. **Error handling:** `ToolError` from `fastmcp.exceptions` with actionable messages. `from exc` in except blocks.
5. **Partial failure:** Workflows use `asyncio.gather(return_exceptions=True)` for optional backends. EDHREC/17Lands data is always optional.
6. **Progress reporting:** Multi-step workflows accept `on_progress` callback; `server.py` bridges to `ctx.report_progress()`.
7. **Testing:** `AsyncMock` for workflow tests (pure functions). `fastmcp.Client(transport=server)` for provider tests. `respx` for HTTP mocking.
8. **Module-level clients:** Lifespan creates clients, stores in module-level vars. `_get_client()` helpers. `Depends()` doesn't work through `mount()`.

**New patterns in this spec:**

9. **Structured output:** All tools return `ToolResult(content=markdown, structured_content=json)`. This is a retrofit on all 35 existing tools + all new tools.
10. **Response format:** Workflow tools accept `response_format: str = "detailed"`. Passed to markdown formatters. JSON is always full.
11. **Rules service:** `RulesService` for rule/keyword/glossary lookups. File-based, lazy-loaded, same lifecycle pattern as bulk data.
12. **Rules + bulk data integration:** `keyword_explain`, `rules_interaction`, and `combat_calculator` combine rules text with real card data from bulk.

**Architecture decisions for this spec:**

- **Rules service** (`services/rules.py`) — file-based, not `BaseClient`. Same lifecycle pattern as `ScryfallBulkClient`.
- **Rules tools** go on the workflow server (cross-cutting, no namespace). They compose rules + bulk data.
- **Deck building tools** go on the workflow server (compose multiple backends)
- **Commander depth tools** go on the workflow server (compose EDHREC + Spellbook + bulk)
- **Limited tools** go on the workflow server (compose 17Lands + bulk)
- **`theme_search`** lives in `workflows/` as a pure function — it's composable and used by `build_around` and `complete_deck`
- **Theme mappings** (mechanical theme → oracle text patterns, flavor → synonym lists) live in a data file or dict in the theme_search module. They should be easy to extend without code changes.
- **`rotation_check`** needs Scryfall sets API — add `get_sets()` method to `ScryfallClient` service if not already present.
- **Structured output retrofit** happens tool-by-tool. Extract inline formatters into shared helpers first, then convert return types to `ToolResult`.

**Where to put new modules:**

| Module | Tools/Responsibility |
|---|---|
| `services/rules.py` (new) | `RulesService` — download, parse, search Comprehensive Rules |
| `workflows/rules.py` (new) | `rules_lookup`, `keyword_explain`, `rules_interaction`, `rules_scenario`, `combat_calculator` |
| `workflows/building.py` (new) | `theme_search`, `build_around`, `complete_deck` |
| `workflows/commander.py` (existing) | `commander_comparison`, `tribal_staples`, `precon_upgrade`, `color_identity_staples` |
| `workflows/draft.py` (existing) | `sealed_pool_build`, `draft_signal_read`, `draft_log_review` |
| `workflows/constructed.py` (new) | `rotation_check` |

---

## Testing Strategy

**Rules service:** Capture rules text as fixture (~943 KB, or a representative subset). Test: parsing (correct count of rules, glossary entries), rule number lookup (exact match, parent/subrule), keyword search (substring, ranked results), glossary lookup (exact + case-insensitive), section browsing (all 7xx rules), cross-reference detection.

**Rules tools:** Test `keyword_explain` returns rules text + real card examples from bulk data. Test `rules_interaction` with known interactions (Deathtouch+Trample, layers). Test `rules_scenario` with simple stack scenarios. Test `combat_calculator` with keyword-heavy combat.

**Structured output retrofit:** All existing tool tests updated to verify `ToolResult` return type with both `content` and `structured_content`. Test `response_format="concise"` produces shorter output than `"detailed"`. Test that `structured_content` is valid JSON matching expected schema.

**Theme search:** Test each theme type (tribal, mechanical, abstract) with fixture cards. Verify relevance grouping.

**Deck building:** Test `build_around` with known synergistic cards. Test `complete_deck` gap analysis with intentionally incomplete decks (missing removal, wrong land count, etc.).

**Sealed:** Test `sealed_pool_build` with a fixture pool (~84 cards). Verify builds have correct card count, reasonable mana curve, bombs identified.

**Draft signals:** Test with mock pick sequences. Verify signal detection (late high-ALSA cards → color open).

**Commander comparison:** Test with 2 commanders, verify side-by-side output includes all expected fields.

**Edge cases:**
- `rules_interaction("Deathtouch", "nonsense")` — one valid, one invalid → graceful partial result
- `rules_scenario` with ambiguous scenario → should identify ambiguity and cite relevant rules
- `keyword_explain("nonexistent keyword")` → clear "not found" message
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
