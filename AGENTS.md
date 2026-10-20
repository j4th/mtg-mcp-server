# MTG MCP Server — Agent Instructions

Source of truth for AI coding agents (pi). `CLAUDE.md` is kept for Claude Code sessions; when both exist this file wins for pi. Do not let them drift — implementation rules live here, and changes here should be mirrored there when they affect conventions.

Unified MCP server providing Magic: The Gathering data to AI assistants. Composes Scryfall, Commander Spellbook, 17Lands, and EDHREC into one server using FastMCP 3.x's provider/mount architecture.

## Stack

Python 3.12+ · FastMCP 3.2.x · httpx · Pydantic v2 · structlog
Tooling: mise · uv · ruff · ty · pytest · respx

Prerequisites: [mise](https://mise.jdx.dev) must be installed. Then `mise install` gets everything else.

## Commands

```bash
mise run setup          # Install deps, create venv
mise run check          # Quality gate: lint + typecheck + all tests except live
mise run check:quick    # Fast gate: lint + typecheck + only tests affected by recent changes
mise run check:full     # Complete gate: lint + typecheck + all tests INCLUDING live
mise run test           # All tests except live, with coverage
mise run test:quick     # Only tests affected by recent changes (fastest iteration)
mise run test:unit      # Unit tests only (services + providers)
mise run test:integration # Integration tests (fixture-mocked, cross-component)
mise run test:live      # Live smoke tests (real server + real APIs, ~60s)
mise run lint           # ruff check + ruff format --check
mise run typecheck      # ty check
mise run dev            # fastmcp dev inspector (MCP Inspector on :6274)
mise run serve          # Run server via stdio
mise run fix            # Auto-fix lint and format issues
```

### Testing strategy

Four test tiers, ordered by speed. Use the fastest tier that covers your change:

| Tier | Command | Speed | When to use |
|------|---------|-------|-------------|
| Quick | `mise run test:quick` | ~5s* | Active iteration — only runs tests affected by your changes (pytest-testmon) |
| Integration | `mise run test:integration` | ~2s | Cross-component verification — full orchestrator with fixture-mocked backends |
| Unit | `mise run test:unit` | ~2.5min | Focused component testing — services + providers only |
| Live | `mise run test:live` | ~1-2min | Real-world smoke test — starts real server, hits real APIs |
| Fast gate | `mise run check:quick` | ~10s* | Quick validation — lint + typecheck + affected tests only |
| Quality gate | `mise run check` | ~3min | Before commits — lint + typecheck + all tests except live |
| Complete gate | `mise run check:full` | ~4-5min | Maximum confidence — full gate + live smoke tests. CI runs this on PRs |

*\*testmon is fast when no code changed; after changes it re-runs affected tests which may approach full suite time (~3min).*

**Rules of thumb:**
- **Editing a service or provider?** `test:quick` while iterating, `check` before commit.
- **Changing data parsing, models, or fixtures?** `test:quick` → `test:integration` → `test:live` (data bugs hide in real-world data).
- **Changing workflows?** `test:quick` is sufficient — workflows use AsyncMock, no HTTP.
- **Before any PR?** `mise run check`. For data-layer PRs, also `mise run test:live`.
- **Gates are the verdict.** Exit code of the mise task is ground truth for "done". Treat `check` passing as the default completion criterion for implementation tasks.

**CI/CD:** PRs to main run `check` + `live-tests` + `build` + `security` in parallel. Push to main runs `check` + `build` + `security` (live already validated on the PR).

## Architecture

See @docs/ARCHITECTURE.md for full details.

- **`src/mtg_mcp_server/services/`** — Pure async API clients. No MCP awareness. Return Pydantic models.
- **`src/mtg_mcp_server/providers/`** — FastMCP sub-servers. Each independently runnable. Register tools that call services.
- **`src/mtg_mcp_server/workflows/`** — Composed tools calling multiple services. Mounted without namespace.
- **`src/mtg_mcp_server/server.py`** — Orchestrator. Mounts providers with namespaces: `scryfall_`, `spellbook_`, `draft_`, `edhrec_`, `moxfield_`, `bulk_`, `spicerack_`, `goldfish_`.

## Conventions

- TDD: write failing test first, then implement. Tests use respx to mock httpx. Never hit live APIs.
- Fixtures in `tests/fixtures/` — captured JSON from real API responses.
- Modern typing: `list[str]` not `List[str]`, `str | None` not `Optional[str]`. Zero ty errors.
- structlog everywhere. Bound logger per service. Log to stderr (stdout is MCP transport in stdio mode).
- Services raise typed exceptions. Provider tools catch them and raise `ToolError` (from `fastmcp.exceptions`) with actionable messages. FastMCP handles `is_error` automatically.
- Workflows are pure async functions (no MCP imports). `workflows/server.py` wraps them as tools and converts exceptions to `ToolError`.
- Workflows handle partial failures — if one backend is down, return what you can from the rest.
- Workflow tests use `unittest.mock.AsyncMock` (not respx) since they test pure functions, not HTTP.
- EDHREC is behind a feature flag (`MTG_MCP_ENABLE_EDHREC`). It scrapes undocumented endpoints and will break.
- MTGGoldfish is behind a feature flag (`MTG_MCP_ENABLE_MTGGOLDFISH`). It scrapes HTML (no API). Uses selectolax for parsing.
- Integration tests (`tests/integration/`) test the full MCP pipeline with fixture-mocked backends. Marked `@pytest.mark.integration`. Included in `mise run check`.
- Live tests (`tests/live/`) start a real server subprocess and hit real APIs. Marked `@pytest.mark.live`, skipped by default. Run via `mise run test:live`. CI runs these on PRs to main.

## Git Workflow

- Always work on a feature branch (`feat/` or `chore/` + description). Never commit directly to main.
- Commit atomically after each logical unit of work — don't batch changes into one big commit.
- **Division of labor (orchestrated mode — confirmed):** pi owns branch creation and atomic commits; the orchestrator (Hermes, see @HERMES.md) owns push, PR creation, review cycle, and merge. Nothing leaves the machine until Hermes pushes. Brainstorming and planning happen above the wall (user + Hermes); pi executes from plan files, never from chat.
- Create PRs as drafts (`gh pr create --draft`). Automated review triggers on `ready_for_review`, not `opened`.
- When review comments come in: fetch via `gh api /repos/{owner}/{repo}/pulls/{number}/comments`, assess each, reply via `.../comments/{id}/replies`, fix, run `mise run check`, commit referencing the PR, push, resolve threads via GraphQL `resolveReviewThread`.

## Specs, Plans, and ADRs

- `docs/plans/<slug>.md` — implementation plans (superpowers `writing-plans` format). Authored by user + Hermes during brainstorming; pi executes from the file. Plans are the handoff contract: self-contained, acceptance criteria mapped to a named gate, no chat context assumed.
- `docs/adr/NNNN-<slug>.md` — architecture decision records. Immutable once accepted — supersede with a new ADR, never edit an accepted one. Status header: proposed → accepted → superseded.
- One feature = one plan = one branch = one PR. PR description links the plan file.
- Small fixes (no design decisions) skip the plan file; a lean task prompt is enough.

### PR Review Checklist

When reviewing PRs (automated CI or manual), verify these project-specific completeness checks:

**New provider/backend added:**
- [ ] `docs/TOOL_DESIGN.md` — tool specs, resource templates
- [ ] `docs/ARCHITECTURE.md` — system diagram, project structure, tool/resource counts, decisions log
- [ ] `docs/SERVICE_CONTRACTS.md` — endpoint, response shape, rate limits, caching, feature flag
- [ ] `docs/CACHING_DESIGN.md` — TTL table entry for new service methods
- [ ] `.agents/skills/smoke-test/SKILL.md` — new test steps, updated totals
- [ ] `tests/integration/conftest.py` — respx mocks for new HTTP backends
- [ ] `tests/integration/test_orchestrator_e2e.py` — tool count assertion updated
- [ ] `tests/test_parameter_descriptions.py` — new provider in parametrize list
- [ ] `server.py` — mount statement, instructions string with new tool category

**Error handling in changed code:**
- [ ] Service exceptions caught → `ToolError` raised with `from exc` (never bare `raise ToolError(...)`)
- [ ] No broad `except Exception` hiding specific service errors — catch typed exceptions
- [ ] Workflows handle partial failures — return available data if one backend is down
- [ ] No silent fallback to defaults without logging (structlog with bound context)

**Data integrity:**
- [ ] Optional numeric fields use `is not None`, never truthiness (`0` and `0.0` are valid)
- [ ] New caches: `@async_cached` with class-level `TTLCache`, clearing added to `tests/conftest.py`
- [ ] Pydantic v2: `.model_validate()` not `.parse_obj()`

## Pi Harness (this repo's agent setup)

Project is trusted; config lives in-repo and any pi session here picks it up automatically.

**MCP servers** (`.pi/mcp.json`; `pi mcp list` to verify):

| Server | Tools | Exposure | Purpose |
|---|---|---|---|
| `mtg` | 69 | codemode | This repo's own server — the system under development. Use for smoke tests/live verification |
| `context7` | 2 | direct | Version-pinned library docs (FastMCP, Pydantic, httpx) |
| `zai-vision` | 8 | deferred | Image analysis, screenshot OCR, diagram understanding, video |
| `web-search-prime` | 1 | direct | Web search (real-time info, releases) |
| `web-reader` | 1 | direct | Fetch any webpage as structured content |
| `zread` | 3 | deferred | Search docs/issues/PRs in any public GitHub repo |

**Extensions** (`.pi/extensions/`):
- `subagent/` — delegate to isolated agents (single/parallel/chain). Project agents in `.pi/agents/` require `agentScope: "both"` when calling.
- `git-checkpoint.ts` — stash checkpoint each turn; restore when forking.
- `guards.ts` — blocks `.env` edits; ruff-formats touched `.py` files.

**Agents** (`.pi/agents/`): `scout` (fast recon), `code-reviewer` (convention review before commit).

**Skills** (`.agents/skills/`, portable Agent Skills): `superpowers/*` (15 vendored from obra/superpowers 7.0.0, MIT — brainstorming → writing-plans → executing-plans workflow), `smoke-test`, `new-provider`, `capture-fixture`. Superpowers skills that say "Task tool" mean the `subagent` extension tool here.

**Codemode** is enabled (`+codemode`): batch MCP calls in scripts with `Promise.allSettled` — this is how you parallelize smoke tests.

**Context hygiene** (keep your context small and disposable — a task should succeed in a fresh session with only the plan file):
- Fresh session per task; resume only to iterate on the same task.
- Execute from the plan file, never from pasted chat or transcripts.
- Use the `scout` subagent for recon instead of reading files broadly yourself.
- Reference docs (`@docs/...`), zread, or context7 instead of pasting file contents into context.
- Write long outputs (smoke reports, research digests) to files, not stdout.

## Gotchas

- FastMCP 3.x import: `from fastmcp import FastMCP` (NOT `from mcp.server.fastmcp`).
- FastMCP 3.x CLI: `fastmcp dev inspector <file>` (NOT `fastmcp dev <file>` — the `inspector` subcommand is required).
- Tool annotations: use shared `TOOL_ANNOTATIONS` from `mtg_mcp_server.providers` (NOT inline `ToolAnnotations()` per tool).
- Error responses: raise `ToolError` from `fastmcp.exceptions`, don't manually construct `is_error` responses. Always use `from exc` in except blocks (B904).
- Service clients: managed via lifespan + module-level `_client` variable (NOT `Depends()`/`ctx.lifespan_context` — these don't propagate through `mount()`).
- Service clients are constructed with `Settings()` in the lifespan so `MTG_MCP_*_BASE_URL` env vars are honored.
- Workflow lifespan uses `AsyncExitStack` to manage multiple clients. Provider lifespans use `async with client:` directly.
- `BaseClient.__aenter__` returns `Self` (not `BaseClient`) so type-checkers infer the correct subclass through `AsyncExitStack.enter_async_context()`.
- Pydantic v2: `.model_validate()`, not `.parse_obj()`.
- Scryfall requires `User-Agent` and `Accept` headers on every request.
- 17Lands rate-limits aggressively. 1 req/sec max. Cache everything.
- Optional numeric fields: use `is not None` checks, not truthiness — `0` and `0.0` are valid values.
- Don't use `Any` type — use `Unknown` or proper types.
- Service caching: all service methods use `@async_cached` with class-level `TTLCache`. Tests must clear caches (autouse `_clear_caches` fixture in conftest.py).
- Scryfall bulk data is behind `MTG_MCP_ENABLE_BULK_DATA` feature flag. It's a file-based service (not BaseClient). Lazy-loads on first access. Returns full `Card` objects (same as Scryfall API).
- Always `uv run python3`, never bare `python3` — the venv may not be activated in shell.
- `Client.call_tool()` returns `CallToolResult` (not subscriptable). Access text via `.content[0].text`. For error tests, use `raise_on_error=False` then check `.is_error`.
- MCP tools are named `mcp__<server>__<tool>`. Tools under `codemode`/`deferred` exposure are not declared to you directly — reach them via codemode scripts or `tool_search`.
- `.env` is local-only and guard-blocked from edits. `.env.example` is the template. `Z_AI_API_KEY` must be exported in the environment that *launches* pi, not just present in `.env` (mise loads `.env` for tasks; MCP config expansion uses the process env).

## Implementation Status

- **Phase 0** (scaffold): Complete
- **Phase 1** (Scryfall): Complete — 4 tools (search_cards, card_details, card_price, card_rulings)
- **Phase 2** (Spellbook + 17Lands + EDHREC): Complete — 9 tools across 3 backends
- **Phase 3** (Workflow tools): Complete — 4 workflow tools (commander_overview, evaluate_upgrade, draft_pack_pick, suggest_cuts)
- **Phase 4** (Caching + Bulk Data): Complete — TTL caching on all 12 service methods, Scryfall bulk data provider (2 tools: card_lookup, card_search). Replaced MTGJSON with Scryfall Oracle Cards bulk data for richer card info (prices, legalities, images, EDHREC rank).
- **Phase 5** (Analysis + Comparison workflows): Complete — 4 new workflow tools (card_comparison, budget_upgrade, deck_analysis, set_overview), 4 prompts, 6 resources. Card resolver utility for bulk-data-first lookups with Scryfall fallback. Tool tagging via `tags` parameter.
- **Branch A** (Structured Output + Rules): Complete — All tools return `ToolResult` with structured `data` dict. Rules engine (5 tools: rules_lookup, keyword_explain, rules_interaction, rules_scenario, combat_calculator). Additional workflow tools: deck_validate, suggest_mana_base, price_comparison. Scryfall whats_new + set_info tools. 7 new bulk tools. 5 new prompts. 40 tools total.
- **Branch B** (Format Workflows): Complete — 11 new workflow tools across 4 domains: Deck Building (theme_search, build_around, complete_deck), Commander Depth (commander_comparison, tribal_staples, precon_upgrade, color_identity_staples), Limited (sealed_pool_build, draft_signal_read, draft_log_review), Constructed (rotation_check). 8 new prompts. 51 tools, 17 prompts, 18 resource templates. 989 tests, 88% coverage.
- **Spicerack** (Tournament Results): Complete — SpicerackClient service with get_tournaments() (TTLCache 4h). 3 tools (recent_tournaments, tournament_results, format_decklists), 1 resource template.
- **MTGGoldfish** (Metagame Data): Complete — MTGGoldfishClient service with HTML scraping (selectolax). 4 tools (metagame, archetype_list, format_staples, deck_price), 1 resource template. 60 tools total.
- **v2.3.0** (Metagame + Sideboard + Moxfield): Complete — 4 metagame workflow tools (metagame_snapshot, archetype_decklist, archetype_comparison, format_entry_guide), 3 sideboard workflow tools (suggest_sideboard, sideboard_guide, sideboard_matrix), 2 Moxfield provider tools (search_decks, user_decks), fuzzy matching utility. 69 tools, 19 prompts. 1336 tests, 88% coverage.

## Environment

Copy `.env.example` to `.env` to configure. All values have sensible defaults — no credentials required for the server itself (all APIs are public). `Z_AI_API_KEY` powers the Z.ai MCP servers (see Pi Harness above). See `MTG_MCP_` prefix for all server env vars.

## Key References

- @docs/ARCHITECTURE.md — Full architecture, stack decisions, FastMCP patterns, mise config
- @docs/TOOL_DESIGN.md — Tool naming, inputs/outputs, prompts, resources
- @docs/SERVICE_CONTRACTS.md — API endpoints, rate limits, response shapes, caching
- @docs/DATA_SOURCES.md — All data sources evaluated, auth methods, stability, access patterns
- @docs/CACHING_DESIGN.md — TTL cache strategy, per-method TTLs, Scryfall bulk data design
- @HERMES.md — Interface contract for the orchestrating agent (Hermes)
