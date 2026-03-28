# Branch A: Structured Output + Rules Engine

> **Branch:** `feat/structured-output-rules`
> **Base:** `main`
> **Prerequisite:** Specs 1-2 complete (34 tools, 8 prompts, 11+ resources)
> **Goal:** Machine-readable output on all tools + Comprehensive Rules engine + CodeMode readiness
> **Result:** ~40 tools, all returning `ToolResult` with markdown + JSON

## Context

The server has 34 tools across 5 backends + workflows. All return markdown strings. This branch adds:

1. **Structured output** — all tools return `ToolResult` with both human-readable `content` and machine-readable `structured_content` (JSON). Backward-compatible: existing clients see markdown, future clients consume JSON.
2. **`response_format` parameter** — workflow tools and key provider tools accept `"detailed"` (default) or `"concise"` to control verbosity. JSON is always full; only markdown varies. Must be wired end-to-end: parameter accepted, passed to impl functions, used by formatters, tested for behavioral difference.
3. **Comprehensive Rules Engine** — `RulesService` downloads and indexes the MTG Comprehensive Rules (~943KB text, ~3,490 rules + glossary). Five new rules tools turn the server into a rules judge.
4. **CodeMode readiness** — feature flag for `fastmcp[code-mode]`, tag taxonomy verification, tool description clarity at 40+ tools.

This is part of a 2-branch plan for Spec 3. Branch B (format workflow tools) depends on this branch.

---

## Phase 1: Structured Output Retrofit

Phase 1 has 4 sub-steps. Each ends with a commit. Do not proceed to the next sub-step without committing.

### Phase 1a: ToolResult on providers (serial)

**What:** Convert all 23 provider tools to return `ToolResult(content=markdown, structured_content=json)`. No behavior change — same markdown, just wrapped in ToolResult with a JSON dict alongside it.

**Scope:** 5 provider files + their test files. Tests verify both `.content[0].text` (markdown) and `.structured_content` (JSON keys/types).

**Pattern:**
```python
from fastmcp.tools.tool import ToolResult

async def card_details(...) -> ToolResult:
    # ... existing logic unchanged ...
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION,
        structured_content=card.model_dump(mode="json"),
    )
```

**Commit gate:** `mise run check:quick`. Commit: "feat: return ToolResult from all provider tools"

### Phase 1b: WorkflowResult on workflow functions (serial)

**What:** Add `WorkflowResult` NamedTuple to `workflows/__init__.py`. Convert all 11 workflow pure functions to return `WorkflowResult(markdown, data)`. Update `server.py` wrappers to unwrap into `ToolResult`. Update workflow unit tests for `.markdown` / `.data` assertions.

**Why separate from 1a:** Workflows use a different pattern (pure functions return WorkflowResult, server.py wraps to ToolResult). Keeps the commit focused.

**Commit gate:** `mise run check:quick`. Commit: "feat: return WorkflowResult from all workflow functions"

### Phase 1c: Shared formatters + response_format (parallel agents, worktree-isolated)

**What:** Create `utils/formatters.py` with shared card formatting helpers. Add `response_format` parameter end-to-end: provider tools accept it and use formatters, workflow impl functions accept it and vary markdown output. "concise" = compact tables, key metrics only, no explanations. "detailed" = current verbose output unchanged. JSON is always full.

**CRITICAL prerequisite:** Phases 1a and 1b MUST be committed before launching agents. Agents branch from committed state — uncommitted work is invisible to them and will be lost.

**Parallel: 2 agents (worktree-isolated)**

| Agent | Exclusive Files | What |
|-------|----------------|------|
| **Provider format** | `utils/formatters.py`, `providers/scryfall.py`, `providers/scryfall_bulk.py`, `tests/providers/test_scryfall_provider.py`, `tests/providers/test_scryfall_bulk_provider.py` | Create shared formatters. Add `response_format` to `card_details`, `search_cards`, `card_lookup`, `card_search`. Concise mode uses one-line summaries. Tests verify concise < detailed length. |
| **Workflow format** | All `workflows/*.py`, all `tests/workflows/test_*.py` | Add `response_format` param to all 11 impl functions. Pass from server.py wrappers. Concise mode omits footers/explanations, uses compact formatting. Tests verify concise < detailed length and same `.data`. |

**Cherry-pick, then commit gate:** `mise run check`. Commit: "feat: wire response_format end-to-end with shared formatters"

### Phase 1d: Review checkpoint

**What:** Run `mise run check:full`. Verify all tools return ToolResult in integration tests. Verify response_format="concise" produces shorter output. This is the Phase 1 review point before Phase 2.

---

## Phase 2: Rules Engine

### Serial Scaffold

**What:** Prepare shared files for parallel agent work.

- `Rule(number, text, subrules)` and `GlossaryEntry(term, definition)` models in `types.py`
- Rules settings in `config.py`: `rules_url` (default: known-good Wizards URL), `rules_refresh_hours = 168` (weekly), `enable_rules = True`, `enable_code_mode = False`
- `TAGS_RULES` tag constant in `providers/__init__.py`
- `RulesService` client wired into workflow `AsyncExitStack` lifespan (behind `enable_rules` flag), with `_rules` module-level variable and `_require_rules()` helper
- `get_sets() -> list[SetInfo]` method on `ScryfallClient` (GET `/sets` endpoint) — needed by Branch B's `rotation_check`, added now while modifying shared files
- CodeMode: `fastmcp[code-mode]` optional dependency in `pyproject.toml`, conditional `CodeMode()` transform in `server.py` behind feature flag
- Tool stubs for all 5 rules tools in `workflows/server.py`
- Empty `services/rules.py`, `workflows/rules.py`, test stubs, `tests/fixtures/rules/` directory

**Why:** All shared file modifications happen once in a serial step. Parallel agents only touch their exclusive files.

**CRITICAL:** Commit scaffold before launching agents.

### Parallel: 2 Agents (worktree-isolated)

Dispatch via `Agent` tool with `isolation: "worktree"`. Each agent gets a self-contained prompt with relevant spec sections and project conventions from CLAUDE.md.

| Agent | Exclusive Files | What |
|-------|----------------|------|
| **Rules Service** | `services/rules.py`, `tests/services/test_rules.py`, `tests/fixtures/rules/` | Download and parse MTG Comprehensive Rules text. Lazy-load, same lifecycle as `ScryfallBulkClient`. Index by rule number (O(1) lookup), glossary by term, section ranges for browsing. Keyword search with relevance ranking. Cross-reference tracking. Fixture: representative subset of rules text, not full 943KB. |
| **Rules Tools** | `workflows/rules.py`, `tests/workflows/test_rules.py` | 5 pure async functions: `rules_lookup`, `keyword_explain`, `rules_interaction`, `rules_scenario`, `combat_calculator`. Accept `RulesService` + optional `ScryfallBulkClient` as params. Return `WorkflowResult`. Tests use `AsyncMock`. See Spec 3 "Rules Tools" section for input/output specs. Also export rules prompt (`rules_question`) and 4 rules resources (`mtg://rules/{number}`, `mtg://rules/glossary/{term}`, `mtg://rules/keywords`, `mtg://rules/sections`) for `server.py` to register. |

**Review checkpoint:** Cherry-pick agent work. `mise run check:full`. Manually test `rules_lookup` and `keyword_explain` via `mise run dev` (MCP Inspector).

---

## Phase 3: CodeMode + Integration

**What:** Verify CodeMode works with feature flag. Verify all ~40 tools have clear descriptions and proper tags. Update server instructions string. Run complete gate.

**Review checkpoint:** `mise run check:full` passes. Create draft PR.

---

## Execution Rules

These rules are non-negotiable and override any instinct to "move fast":

1. **Commit before agents.** Worktree agents branch from committed state. Uncommitted changes are invisible to them and WILL be lost. Always `git status` clean before `Agent` with `isolation: "worktree"`.
2. **Commit after each sub-step.** Never accumulate more than one sub-step of uncommitted work. If it passes `check:quick`, commit it.
3. **Agents always use worktrees.** Every `Agent` call that writes code uses `isolation: "worktree"`. No exceptions. Cherry-pick commits back.
4. **Wait for agents before continuing.** Do not start new work or run final gate checks while agents are still running. Their output must be integrated first.
5. **Verify agent output before integrating.** After cherry-pick, run tests on the combined result before declaring success.

---

## Key References

- **Spec 3:** `docs/SPEC_FORMAT_WORKFLOWS.md` — "Comprehensive Rules Engine", "Structured Output Pattern", "Response Format Parameter", "CodeMode Readiness" sections
- **Spec 1 (original design):** `docs/SPEC_INFRASTRUCTURE_MODERNIZATION.md` — Rules engine was originally Spec 1; the design reference remains there
- **Architecture:** `docs/ARCHITECTURE.md` — FastMCP patterns, lifespan/client wiring, testing conventions
- **Conventions:** `CLAUDE.md` — TDD, ToolError handling, module-level client pattern, testing tiers
