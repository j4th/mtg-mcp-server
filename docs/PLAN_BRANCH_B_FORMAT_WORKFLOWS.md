# Branch B: Format Workflow Tools

> **Branch:** `feat/format-workflows`
> **Base:** `feat/structured-output-rules` (Branch A)
> **Prerequisite:** Branch A merged — all tools return `ToolResult`, Rules engine working, CodeMode ready
> **Goal:** 11 new workflow tools + 9 prompts + 7 resources + comprehensive codebase review
> **Result:** 51 tools total, completing the v2.0 vision

## Context

After Branch A, the server has ~40 tools with structured output, a rules engine, and CodeMode. This branch adds the remaining Spec 3 tools — "intent-level" workflow tools for deck building, Commander depth, Limited expansion, and Constructed formats.

These tools compose existing backends (Scryfall bulk, EDHREC, Spellbook, 17Lands) into higher-order analysis. They follow the established pure-function pattern: workflow modules export async functions, `server.py` wraps them as tools.

---

## Phase 1: Scaffold

**What:** Stub all 11 new workflow tools, 8 prompts, 7 resources. Wire into workflow server.

**Why:** All shared file modifications happen once. Parallel agents only touch exclusive files.

**New modules (stubs):**
- `workflows/building.py` — `theme_search`, `build_around`, `complete_deck`
- `workflows/commander_depth.py` — `commander_comparison`, `tribal_staples`, `precon_upgrade`, `color_identity_staples`
- `workflows/draft_limited.py` — `sealed_pool_build`, `draft_signal_read`, `draft_log_review`
- `workflows/constructed.py` — `rotation_check`

**Temporary file split:** New commander tools go in `commander_depth.py` and new limited tools in `draft_limited.py` during development. This avoids agents modifying existing files. The comprehensive review (Phase 3) consolidates these back into `commander.py` and `draft.py` if it makes sense — the reviewer decides based on module size and cohesion.

**Prompts/resources:** Each workflow module exports its own prompt and resource definitions as data. `server.py` imports and registers them. This gives each parallel agent ownership of their domain's prompts without touching shared files.

**Review checkpoint:** `mise run check:full` with stubs. Commit.

---

## Phase 2: Parallel Implementation (3 Agents)

Dispatch via `Agent` tool with `isolation: "worktree"`. Each agent gets a self-contained prompt with the relevant Spec 3 sections and project conventions.

| Agent | Exclusive Files | Tools |
|-------|----------------|-------|
| **Deck Building + Constructed** | `workflows/building.py`, `workflows/constructed.py`, `tests/workflows/test_building.py`, `tests/workflows/test_constructed.py` | `theme_search` (mechanical/tribal/abstract theme -> oracle text patterns), `build_around` (synergy detection from 1-5 cards), `complete_deck` (gap analysis + suggestions), `rotation_check` (Standard rotation tracking). Internal dependency: `build_around` and `complete_deck` call `theme_search`. |
| **Commander Depth** | `workflows/commander_depth.py`, `tests/workflows/test_commander_depth.py` | `commander_comparison` (2-5 commanders side-by-side), `tribal_staples` (best cards for a creature type), `precon_upgrade` (MVP: decklist + commander, not precon name), `color_identity_staples` (top cards in a color identity). Import formatting helpers from existing `commander.py`. |
| **Limited Expansion** | `workflows/draft_limited.py`, `tests/workflows/test_draft_limited.py` | `sealed_pool_build` (pool -> 1-3 deck builds), `draft_signal_read` (ALSA-based color openness signals), `draft_log_review` (pick-by-pick GIH WR analysis). Import helpers from existing `draft.py`. |

**Additional prompt (scaffold phase):** `build_around_deck` — format-agnostic "build a deck around these cards/concept" prompt. Routes through `theme_search` (if concept) → `build_around` → `rotation_check` (if Standard) → `complete_deck` → `deck_validate`. Covers the "build around a win con or card" use case for Standard, Pioneer, Modern, etc.

**Each agent must:**
- Follow TDD (failing test first, per CLAUDE.md)
- Return `ToolResult` (pattern established in Branch A)
- Use `AsyncMock` for workflow tests (no HTTP mocking — pure functions)
- Export prompt/resource definitions for `server.py` to register
- Run `mise run check` in their worktree before completing

**Review checkpoint:** Cherry-pick all agent work. `mise run check:full`. Fix integration issues.

---

## Phase 3: Comprehensive Codebase Review

**What:** Full review across all 3 specs' worth of work. This is the first holistic pass — Specs 1-2 branches didn't get one.

**Why:** Code built across multiple branches by multiple agents accumulates inconsistencies. Module splits expedient for parallel work may not be the right final organization.

**Evaluate:**
- Module organization — do file boundaries reflect domain logic, or agent logistics?
- Pattern consistency across early code (Phase 1-2) and late code (Specs 2-3)
- Redundant helpers, formatters, utilities that could be shared
- Dead code, unused imports, stale fixtures
- Test quality and organization
- Tag/annotation completeness across all 51 tools
- All documentation in `docs/` and `CLAUDE.md` reflecting current state

**Final gate:** `mise run check:full` passes. All 51 tools in `list_tools()`. Create draft PR.

---

## Tool Summary

| Category | Tools | Backends |
|----------|-------|----------|
| Deck Building | `theme_search`, `build_around`, `complete_deck` | Bulk + EDHREC + Spellbook |
| Commander Depth | `commander_comparison`, `tribal_staples`, `precon_upgrade`, `color_identity_staples` | Bulk + EDHREC + Spellbook |
| Limited Expansion | `sealed_pool_build`, `draft_signal_read`, `draft_log_review` | Bulk + 17Lands |
| Constructed | `rotation_check` | Scryfall API (sets) + Bulk |

## Existing Utilities to Reuse

| Utility | Location | Used by |
|---------|----------|---------|
| `card_resolver.resolve_cards()` | `workflows/card_resolver.py` | complete_deck, sealed_pool_build |
| `format_rules.get_format_rules()` | `utils/format_rules.py` | complete_deck, sealed_pool_build |
| `query_parser.parse_query()` | `utils/query_parser.py` | theme_search |
| Commander formatting helpers | `workflows/commander.py` | commander_depth tools |
| Draft formatting helpers | `workflows/draft.py` | limited tools |
| `suggest_mana_base` logic | `workflows/mana_base.py` | complete_deck, sealed_pool_build |

## Key References

- **Spec 3:** `docs/SPEC_FORMAT_WORKFLOWS.md` — "Deck Building Workflows", "Commander Depth", "Limited Expansion", "Constructed Format Tools", "New Prompts", "New Resources" sections
- **Architecture:** `docs/ARCHITECTURE.md` — workflow pure-function pattern, AsyncExitStack lifespan, testing conventions
- **Conventions:** `CLAUDE.md` — TDD, ToolResult, error handling, testing tiers, agent dispatch patterns
