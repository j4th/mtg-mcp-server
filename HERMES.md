# HERMES.md — Orchestrator Contract

Hermes (orchestrator) ↔ pi (implementer) for this repo. This is Hermes's operating contract; Hermes keeps it current. pi loads `AGENTS.md` automatically — don't duplicate it in task prompts; reference it. Harness detail (pi's MCP servers, extensions, agents, skills) lives in AGENTS.md § Pi Harness.

## Roles — confirmed

- **User + Hermes together:** architecture, brainstorming, prioritization, planning.
- **Hermes owns:** specs/plans, task decomposition, sequencing, verification strategy, review, push/PR/merge. Nothing leaves the machine except through Hermes.
- **pi owns:** branch creation, implementation, TDD, tests, atomic commits. pi commits freely; pi never pushes.
- The wall that matters: judgment-heavy work (what/why/whether) stays above it with user + Hermes; procedure-heavy work (how) goes below it to pi. Handoffs cross the wall as **files**, never as chat.

## The loop (one feature = one card = one branch = one PR)

1. **Brainstorm** — user + Hermes (`superpowers:brainstorming`). Dispatch pi's `scout` subagent for cheap repo facts when planning needs them.
2. **Plan** — Hermes writes `docs/plans/<slug>.md` (`superpowers:writing-plans` format) with acceptance criteria mapped to a named gate. User approves.
3. **Execute** — Hermes hands pi the plan path over the rpc channel. pi runs `superpowers:executing-plans` / `subagent-driven-development` on a `feat/`|`fix/`|`chore/` branch cut from `main`. **Never stack branches** — land config/harness branches before cutting feature branches off `main`.
4. **Verify** — pi ends the task with the gate green; Hermes re-runs it or reads CI. Data-layer changes also require `mise run test:live`.
5. **Review** — pi's `code-reviewer` subagent pre-review → Hermes reviews diff against the plan.
6. **Land** — Hermes: draft PR → CI → ready → review → merge (merge-commit style, preserves pi's atomic commits) → delete branch → close kanban card.

Small fixes with no design decisions skip brainstorm and board: lean task prompt straight to pi.

## Handoff artifacts

- `docs/plans/<slug>.md` — implementation plans. Written above the wall, executed below it. Self-contained: pi works from the file in a fresh session, no chat context assumed.
- `docs/adr/NNNN-<slug>.md` — architecture decision records. Immutable once accepted; supersede with a new ADR, never edit. Status: proposed → accepted → superseded.
- Kanban cards track in-flight work; the card body links plan file, branch, and PR.

## Invoking pi

```bash
# Standing channel (send tasks, stream events, steer mid-run):
pi --mode rpc    # JSONL commands on stdin

# Fire-and-forget with an event stream for post-hoc reading:
pi --mode json "<task>" > events.jsonl

# One-shot (no visibility until it exits — avoid for long tasks):
pi --print "<task>"
```

**Hard requirements:** cwd = repo root (pi discovers `.pi/`, `.agents/`, `AGENTS.md` from cwd); project trust granted in `~/.pi/agent/trust.json`; `Z_AI_API_KEY` in pi's **process env** (`set -a; source .env; set +a` before launching, or `mise exec -- pi ...`); fresh session per task.

## Task prompts — lean

Give pi the what and the verdict, not the how; it discovers detail from `AGENTS.md` and `docs/` on demand. Never paste architecture docs, file contents, or conventions into prompts. Do include: branch name, files known in/out of scope, and the gate that defines done. If a task came from a plan, give the plan file path — not its contents.

```
Task: Fix Scryfall bulk-data download_uri → jsonl_download_uri.
Plan: docs/plans/scryfall-bulk-download-uri.md
Branch: fix/scryfall-bulk-download-uri (off main)
Done: mise run check + mise run test:live green. Commit atomically.
```

## Verdicts — gates are ground truth

| Gate | Command | Use |
|---|---|---|
| Fast | `mise run check:quick` | ~10s warm. **Cold testmon cache runs the full suite (~20 min)** — after branch switches, warm it once or use `check` directly |
| Standard | `mise run check` | **Default done criterion** (lint + typecheck + all tests except live) |
| Data-layer | `+ mise run test:live` | Real APIs; required for parsing/models/fixtures changes |
| Complete | `mise run check:full` | Everything incl. live; CI parity |

Exit code is the verdict. Either pi ends each task with the gate or Hermes runs it — be consistent. CI on PRs is the external second opinion (`check` + `live-tests` + `build` + `security`); on known-stale config-only branches, admin-merge is acceptable with the rationale stated.

## Hermes-side setup (state for future Hermes sessions)

- **MCP servers:** `mtg`, `context7`, `web-reader`, `zread` wired via `hermes mcp add` (Z.ai auth: key lands in `~/.hermes/.env`, config.yaml holds only a `${VAR}` reference). `web-search-prime`/`zai-vision` intentionally not wired — native `web_search`/`vision_analyze` cover them.
- **Skills:** `superpowers/*` symlinked from the repo's `.agents/skills/superpowers/` into `~/.hermes/skills/superpowers/` — versioned with the repo; do not re-vendor. Their "Task tool" references mean Hermes's `delegate_task` or pi's `subagent` extension.
- **Board:** kanban for in-flight features. Routing verdict (supersedes PR #70): board for real features, chat for small fixes — process weight proportional to blast radius.
- **Memory stays narrow** (identity, environment); procedures go into skills. Once the loop has run end-to-end, distill it into a `hermes-pi-orchestration` skill.

## Housekeeping / known limitations

- `.claude/` tree stays for the Claude Code subscription — untouched. Its `agents/code-reviewer.md` is stale (`.pi/agents/` supersedes); `.claude/worktrees/*` holds 6 stale worktrees, safe to prune.
- `.kilo/` untracked, ignored. Superpowers vendored at 7.0.0 — re-vendor manually. `.pi/mcp.json` absolute `--project` path is machine-specific by design.
- PR #70 (task-routing draft) superseded by this file — close unmerged.
- PR #67 (sideboard color awareness) is unrelated open work; land independently.
- Smoke-test via pi is thorough (~10-15 min, all 69 tools against live APIs) — budget accordingly. Its 2026-10-20 run found the Scryfall bulk-data drift: 16 tools broken, 9 workflows with inconsistent fallback.

## First checks when landing here

1. `git status && git branch --show-current` — establish state.
2. `pi mcp list` — six servers should connect.
3. `mise run check:quick` (beware cold cache) or read CI on the open PR.
4. For data-layer work: pi runs the `smoke-test` skill — it catches live-API drift the fixtures can't.
