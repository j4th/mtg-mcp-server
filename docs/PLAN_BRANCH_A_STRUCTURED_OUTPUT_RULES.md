# Branch A: Structured Output + Rules Engine

> **Branch:** `feat/structured-output-rules` (exists, has docs commit on `main`)
> **Goal:** Machine-readable output on all tools + Comprehensive Rules engine + CodeMode readiness
> **Result:** ~40 tools, all returning `ToolResult` with markdown + JSON

## Context

The server has 34 tools (23 provider, 11 workflow) across 5 backends + 7 workflow modules. All return markdown strings. This branch adds:

1. **Structured output** — all tools return `ToolResult` with `content` (markdown) and `structured_content` (JSON). Backward-compatible.
2. **`response_format` parameter** — `"detailed"` (default) or `"concise"`. JSON always full; only markdown varies. Must be wired end-to-end and tested for behavioral difference.
3. **Comprehensive Rules Engine** — `RulesService` downloads and indexes MTG Comprehensive Rules. Five new rules tools.
4. **CodeMode readiness** — feature flag for `fastmcp[code-mode]`, tag taxonomy verification.

Branch B (format workflow tools) depends on this branch.

---

## Phase 1: Structured Output Retrofit

Each sub-step ends with a commit. Do not proceed without committing.

### Phase 1a: ToolResult on providers (2 parallel worktree agents)

**What:** Convert all 23 provider tools to return `ToolResult(content=markdown, structured_content=json)`. No behavior change — same markdown, plus a JSON dict.

**Pattern** (new — include in agent prompts):
```python
from fastmcp.tools.tool import ToolResult

async def card_details(...) -> ToolResult:
    # ... existing logic unchanged ...
    return ToolResult(
        content="\n".join(lines) + ATTRIBUTION,
        structured_content=card.model_dump(mode="json"),
    )
```

Tests verify both `.content[0].text` (markdown unchanged) and `.structured_content` (JSON keys/types).

| Agent | Exclusive Files | Scope |
|-------|----------------|-------|
| **Providers A** | `providers/scryfall.py`, `providers/spellbook.py`, `providers/seventeen_lands.py`, `tests/providers/test_scryfall_provider.py`, `tests/providers/test_spellbook_provider.py`, `tests/providers/test_seventeen_lands_provider.py` | 12 tools: Scryfall (6), Spellbook (4), 17Lands (2) |
| **Providers B** | `providers/edhrec.py`, `providers/scryfall_bulk.py`, `tests/providers/test_edhrec_provider.py`, `tests/providers/test_scryfall_bulk_provider.py` | 11 tools: EDHREC (2), Bulk (9) |

**Commit gate:** Cherry-pick. `mise run check:quick`. Commit: "feat: return ToolResult from all provider tools"

### Phase 1b: WorkflowResult on workflow functions (serial)

**What:** Add `WorkflowResult` NamedTuple to `workflows/__init__.py`. Convert all 11 workflow functions (across 7 modules) to return `WorkflowResult(markdown, data)`. Update `server.py` wrappers to unwrap into `ToolResult`. Update workflow tests for `.markdown` / `.data` assertions.

**Why serial:** `server.py` wraps all 11 workflows — can't be split across agents.

**Commit gate:** `mise run check:quick`. Commit: "feat: return WorkflowResult from all workflow functions"

### Phase 1c: Shared formatters + response_format (2 parallel worktree agents)

**What:** Create `utils/formatters.py` with shared card formatting helpers. Add `response_format` parameter end-to-end. "concise" = compact tables, key metrics only. "detailed" = current output unchanged. JSON always full.

**CRITICAL:** Phases 1a and 1b MUST be committed before launching agents.

| Agent | Exclusive Files | Scope |
|-------|----------------|-------|
| **Provider format** | `utils/formatters.py`, `providers/scryfall.py`, `providers/scryfall_bulk.py`, `tests/providers/test_scryfall_provider.py`, `tests/providers/test_scryfall_bulk_provider.py` | Create formatters. Add `response_format` to card/search tools. Tests verify concise < detailed length. |
| **Workflow format** | All `workflows/*.py` (except `card_resolver.py`), `workflows/server.py`, all `tests/workflows/test_*.py` | Add `response_format` to all 11 impl functions + server.py wrappers. Tests verify concise < detailed and same `.data`. |

**Commit gate:** Cherry-pick. `mise run check`. Commit: "feat: wire response_format end-to-end with shared formatters"

### Phase 1d: Review checkpoint

Run `mise run check:full`. Verify all tools return ToolResult in integration tests. Verify `response_format="concise"` produces shorter output. This is the gate before Phase 2.

---

## Phase 2: Rules Engine

### Phase 2a: Scaffold shared files (serial)

**What:** Prepare shared files so parallel agents only touch exclusive files.

- `Rule`, `GlossaryEntry` models in `types.py`
- Rules settings in `config.py`: `rules_url`, `rules_refresh_hours = 168`, `enable_rules`, `enable_code_mode`
- `TAGS_RULES` constant in `providers/__init__.py`
- `RulesService` wired into workflow `AsyncExitStack` lifespan (behind `enable_rules`), module-level `_rules` + `_require_rules()` helper
- `get_sets() -> list[SetInfo]` on `ScryfallClient` — needed by Branch B's `rotation_check`
- 5 rules tool stubs in `workflows/server.py`
- Empty `services/rules.py`, `workflows/rules.py`, test stubs, `tests/fixtures/rules/`

**Commit gate:** `mise run check:quick`. Commit: "feat: scaffold rules engine types, config, and lifespan wiring"

### Phase 2b: Rules service + rules tools (2 parallel worktree agents)

**CRITICAL:** Phase 2a must be committed before launching agents.

| Agent | Exclusive Files | Scope |
|-------|----------------|-------|
| **Rules Service** | `services/rules.py`, `tests/services/test_rules.py`, `tests/fixtures/rules/` | Download/parse MTG Comprehensive Rules text. Lazy-load, same lifecycle as `ScryfallBulkClient`. Index by rule number (O(1)), glossary by term, section ranges. Keyword search with relevance ranking. Fixture: representative subset, not full 943KB. |
| **Rules Tools** | `workflows/rules.py`, `tests/workflows/test_rules.py` | 5 pure async functions: `rules_lookup`, `keyword_explain`, `rules_interaction`, `rules_scenario`, `combat_calculator`. Accept `RulesService` + optional `ScryfallBulkClient`. Return `WorkflowResult` (Phase 1b pattern). Export rules prompt + 4 rules resources for `server.py` to register. See Spec 3 "Rules Tools" section. |

**Commit gate:** Cherry-pick. `mise run check`. Commit: "feat: rules service and rules tools"

### Phase 2c: Review checkpoint

Run `mise run check:full`. Manually test `rules_lookup` and `keyword_explain` via `mise run dev` (MCP Inspector). Verify rules tools return ToolResult with structured_content. Verify rules resources resolve.

---

## Phase 3: CodeMode + Integration

### Phase 3a: CodeMode wiring (serial)

**What:** Add `fastmcp[code-mode]` optional dependency in `pyproject.toml`. Wire conditional `CodeMode()` transform in `server.py` behind `enable_code_mode` feature flag.

**Commit gate:** `mise run check:quick`. Commit: "feat: wire CodeMode transform behind feature flag"

### Phase 3b: Tool audit + server instructions (serial)

**What:** Audit all ~40 tools for clear descriptions and proper tags. Update server instructions string to reflect rules tools and structured output. Verify tag taxonomy is consistent. Use a subagent to inventory current state before making changes.

**Commit gate:** `mise run check`. Commit: "chore: audit tool descriptions, tags, and server instructions"

### Phase 3c: Final gate + PR

Run `mise run check:full`. Create draft PR (`gh pr create --draft`).

---

## Execution Rules

Non-negotiable:

1. **Commit before agents.** Worktree agents branch from committed state. Uncommitted changes are invisible to them and WILL be lost. `git status` must be clean before any `Agent` with `isolation: "worktree"`.
2. **Commit after each sub-step.** Never accumulate more than one sub-step of uncommitted work.
3. **Agents always use worktrees.** Every `Agent` call that writes code uses `isolation: "worktree"`. Cherry-pick commits back.
4. **Wait for agents before continuing.** Do not start new work while agents are running. Integrate their output first.
5. **Verify after cherry-pick.** Run tests on the combined result before declaring success.

---

## Key References

- **Spec 3:** `docs/SPEC_FORMAT_WORKFLOWS.md` — Rules Engine, Structured Output, Response Format, CodeMode sections
- **Spec 1:** `docs/SPEC_INFRASTRUCTURE_MODERNIZATION.md` — Original rules engine design reference
- **Architecture:** `docs/ARCHITECTURE.md` — FastMCP patterns, lifespan/client wiring, testing conventions
- **Conventions:** `CLAUDE.md` — TDD, ToolError, module-level client pattern, git workflow, testing tiers
