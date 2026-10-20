# Scryfall Bulk-Data download_uri Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the 16 bulk-dependent tools broken by Scryfall's bulk-data API field rename (`download_uri` → `jsonl_download_uri`), clear the lint error blocking the gate, and confirm consistent fallback in the 9 affected workflows.

**Architecture:** The break is a single parse point — `src/mtg_mcp_server/services/scryfall_bulk.py:173` reads `metadata.get("download_uri")`, which no longer exists in live responses. Fix at the service layer (prefer the new field, fall back to the old name for API stability), re-capture fixtures from the real current API, and verify workflow fallback behavior downstream. No tool signatures change.

**Tech Stack:** Python 3.12, httpx, Pydantic v2, pytest + respx.

**Spec:** pi smoke-test findings, 2026-10-20 (session 01a15ba4): 20/47 tool checks failing; ① bulk-data field rename (16 tools) + inconsistent Scryfall fallback in 9 workflows; ② Spicerack outage, ③ 17Lands data vacuum (both external, out of scope). CI logs pin the lint failure to a None-first type union.

## Global Constraints

- TDD: failing test first; respx-mocked HTTP in unit/integration tests. Never hit live APIs from tests except `test:live`.
- Fixtures must be re-captured from the REAL current API response (use the `capture-fixture` skill) — not hand-edited.
- No MCP tool signature changes.
- structlog (bound logger) on any fallback path — never silent.
- Done = `mise run check` AND `mise run test:live` exit 0.
- Commit atomically per task on `fix/scryfall-bulk-download-uri` (already created, already checked out). Do not push.

## Review Focus

- Old-shape responses (`download_uri` present, `jsonl_download_uri` absent): must still parse — backward compatibility.
- Bulk data disabled (`MTG_MCP_ENABLE_BULK_DATA` off) or bulk fetch failing: tools must degrade to Scryfall fallback gracefully with a log line.
- Empty/monetary-zero numeric fields still use `is not None` semantics (project convention).
- None-last type unions everywhere (`X | BaseException | None`, never `X | None | BaseException`).
- Live bulk file is ~300MB JSONL — do not change download/caching strategy, only the field read.

---

### Task 1: Unblock the gate — lint fix

**Files:**
- Modify: `src/mtg_mcp_server/workflows/commander.py:574`

**Test:** `mise run lint` (gate itself is the test)

**Steps:**
- [ ] Run `mise run lint` — confirm the single RUF036-class failure (`synergy_results: list[EDHRECCard | None | BaseException]`)
- [ ] Change to `list[EDHRECCard | BaseException | None]`
- [ ] `mise run lint` green
- [ ] Commit: `fix: None-last type union in commander workflow (unblocks lint gate)`

### Task 2: Service fix — read the renamed field

**Files:**
- Modify: `src/mtg_mcp_server/services/scryfall_bulk.py:173-176`
- Test: `tests/services/test_scryfall_bulk.py` (esp. `test_missing_download_uri_raises` at :682)
- Modify: `tests/integration/conftest.py:54`
- Fixtures: bulk metadata fixture(s) under `tests/fixtures/` — re-capture with the `capture-fixture` skill from `https://api.scryfall.io/bulk-data`

**Steps:**
- [ ] Recon: `curl -s https://api.scryfall.io/bulk-data` (with project User-Agent/Accept headers) — record the exact current keys in the task notes
- [ ] Failing test: metadata with only `jsonl_download_uri` → service resolves the download URL (currently raises `ScryfallBulkError`)
- [ ] Failing test: metadata with only legacy `download_uri` → still resolves (backward compat)
- [ ] Update error message + `test_missing_download_uri_raises` for the new dual-field reality (both keys missing → error listing available keys)
- [ ] Implement: prefer `jsonl_download_uri`, fall back to `download_uri`
- [ ] Re-capture the bulk-metadata fixture from the live API; update `tests/integration/conftest.py` accordingly
- [ ] `mise run test:quick` green, then `mise run test:integration` green
- [ ] Commit: `fix(bulk): read jsonl_download_uri after Scryfall field rename, keep download_uri fallback`

### Task 3: Workflow fallback consistency (9 workflows)

**Files:**
- Verify/modify: workflows using the card resolver with Scryfall fallback (`src/mtg_mcp_server/workflows/` — smoke report named 9: commander_overview, evaluate_upgrade, card_comparison, budget_upgrade, deck_analysis, complete_deck, precon_upgrade, tribal_staples, color_identity_staples)
- Test: existing workflow tests (`AsyncMock`)

**Steps:**
- [ ] Establish current behavior: with bulk lookup erroring, do all 9 degrade identically (log + Scryfall fallback) or do some propagate?
- [ ] If inconsistent, normalize to the single resolver code path — do not hand-roll fallbacks per workflow
- [ ] Tests covering the fallback path per workflow (bulk errors → still returns Scryfall-sourced data)
- [ ] `mise run test:quick` green
- [ ] Commit: `fix(workflows): consistent bulk→Scryfall fallback via shared resolver`

### Task 4: Full verification + docs

**Steps:**
- [ ] `mise run check` — exit 0
- [ ] `mise run test:live` — exit 0 (real APIs; bulk tools must return real data)
- [ ] Spot-check 3 previously-broken tools via the running server (e.g. `bulk_card_lookup`, `card_comparison`, `commander_overview`)
- [ ] Update `docs/SERVICE_CONTRACTS.md` bulk-data section if it names `download_uri`
- [ ] Commit: `docs: bulk-data field rename in service contracts` (if applicable)
- [ ] Report: per-task results, gate output tails, anything discovered outside plan scope (do NOT fix out-of-scope findings — report them)
