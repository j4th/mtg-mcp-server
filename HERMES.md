# HERMES.md — Orchestrator Interface

You are the orchestrating agent (Hermes). This document is the contract between you and **pi**, your implementation agent for this repo. pi has its own instruction file (`AGENTS.md`) loaded automatically in every session here — do not duplicate its contents in task prompts; reference it.

**Role split:** You own task decomposition, sequencing, git push/PR/review/merge, and verification strategy. pi owns implementation: branching, TDD, code, tests, atomic commits. You call; pi executes; the mise gates judge.

## Quick orientation

- **Repo:** MTG MCP server — Python 3.12, FastMCP 3.2.x, httpx, Pydantic v2, structlog. Tooling via mise/uv.
- **Truth lives in:** `AGENTS.md` (conventions, gotchas), `docs/ARCHITECTURE.md` and siblings (design), `HERMES.md` (this file).
- **Current state:** 69 tools, 19 prompts, ~1336 tests, 88% coverage. See "Implementation Status" in `AGENTS.md`.

## Invoking pi

```bash
# One-shot task (fire and forget):
cd /home/j4th/Code/create/mtg-mcp && pi --print "<task prompt>"

# Structured event stream (if you want progress events):
pi --mode json "<task prompt>" > events.jsonl

# Multi-turn control (steering mid-run):
pi --mode rpc   # JSONL commands on stdin
```

**Hard requirements:**
- `cwd` must be the repo root — pi discovers `.pi/`, `.agents/skills/`, `AGENTS.md` from cwd.
- Project trust is already granted (`~/.pi/agent/trust.json`). Do not remove.
- `Z_AI_API_KEY` must be in pi's **process env** (not just `.env` — that only loads for mise tasks). Either `set -a; source .env; set +a` before launching, or use `mise exec -- pi ...`.
- Fresh session per task for predictable, reproducible runs. Resume a session only to iterate on the same task.

## Task prompt format (keep prompts lean)

Give pi the **what** and the **verdict**, not the how — it discovers implementation detail from `AGENTS.md` and `docs/` on demand.

Good shape:

```
Task: Add a "pauper staples" tool to the Spicerack provider.
Scope: src/mtg_mcp_server/providers/spicerack.py + service + tests + docs entry.
Done: mise run check passes. Commit atomically on feat/pauper-staples.
```

Do **not** paste architecture docs, file contents, or conventions into prompts. Do include: branch name, any files known to be in/out of scope, and which gate defines done. If a task came from a spec/plan, reference the plan file path instead of inlining it.

## Verdicts — gates are ground truth

| Gate | Command | Use |
|---|---|---|
| Fast | `mise run check:quick` | ~10s; quick validation between small steps |
| Standard | `mise run check` | ~3min; **default done criterion** (lint + typecheck + all tests except live) |
| Data-layer | `+ mise run test:live` | Real APIs; require for changes to parsing/models/fixtures |
| Complete | `mise run check:full` | Everything including live; CI parity |

Treat the exit code as the verdict. Run the gate yourself, or require pi to end every task with it — either works; be consistent.

## Git landing contract

- pi works on `feat/` or `chore/` branches off `main`, committing atomically per logical unit.
- **Recommendation (pending your decision):** pi owns branch + commits; you own push, PR (`gh pr create --draft` — automated review triggers on `ready_for_review`, not `opened`), review cycle, merge. Nothing leaves the machine until you push. Alternative: pi leaves a dirty-but-green tree and you slice commits — workable but weaker (loses commit-as-checkpoint safety mid-task).
- This branch (`chore/pi-harness`) is config-only (new paths: `.pi/`, `.agents/`, `AGENTS.md`, `HERMES.md`) — near-zero conflict risk with concurrent code branches. Land by diffing/merging the tip; no commit-hash pinning needed.
- Open draft PR #67 (`fix/sideboard-color-awareness`) is unrelated work; land independently.

## Task routing: kanban board vs ad-hoc chat

**Verdict (pilot, 2026-10-20): implementation work flows through the kanban board; chat stays the cockpit. Rule of thumb: if it needs a branch, it needs a card.**

Both gates the pilot required are proven: pi's six MCP servers verified live, and the first dispatched loop (smoke-test skill, real APIs, `pi --print`) ran unattended and surfaced a real upstream breakage — Scryfall bulk metadata now ships `jsonl_download_uri` instead of `download_uri`, breaking the bulk tools. The pipeline doesn't just work; it finds real work. The board supplies what chat can't: durable task state, parallel isolated workers, review gating, retries/reclaims, and completion notifications. Chat supplies what cards can't: live steering and zero ceremony.

| Route | Use for |
|---|---|
| **Chat (ad-hoc)** | Spec/plan phase (pi: `brainstorming` → `writing-plans`), questions, smoke checks, quick probes — anything finished in one `pi --print` with no branch, or needing the user steering mid-task |
| **Board (card)** | Anything whose done-state is "gate green + commits on a branch": features, fixes, chores. One card = one pi task = one branch |

Card mechanics:

- **Card body = the task prompt**, in the Task/Scope/Done shape above, plus branch name and gate. Self-contained — the spawned worker sees nothing else. Reference plan files by path; never inline docs.
- **Division of labor:** the card worker (a Hermes profile) verifies scope, dispatches pi per "Invoking pi", runs the gate itself, and lands per the git contract above. pi never touches the board; the user never herds pi directly for card work.
- **Create cards from the user's chat** (kanban toolset enabled) so the thread auto-subscribes to completion/block events. Cards created by workers notify nobody — subscribe explicitly or expect silence.
- **Serialize per repo:** at most one active card dispatching pi into this checkout — pi branch-switches in cwd, so parallel implementation cards here collide on git state. Chain follow-ups with card dependencies (`parents`); parallel across repos is fine. If same-repo parallelism becomes real, give each card a git-worktree workspace and export `Z_AI_API_KEY` from the main checkout's `.env`.
- **Long runs are normal:** real-API tasks run 10+ min. The worker heartbeats; `pi --print`'s final output is the report. Steering mid-card is coarse (comments land between dispatch and landing) — if a task needs live steering, keep it in chat.
- **Sizing:** one card per branch-shaped unit. The Scryfall bulk fix (provider + service + fixtures, live gate) is the archetype — and the right first routed card.

Board lives in `~/.hermes/kanban.db`; inspect via the dashboard Kanban tab or `hermes kanban`.

## MCP servers available to pi (verified live)

All auto-load for any pi session here. Tools are named `mcp__<server>__<tool>`.

| Server | Tools | Exposure | Auth | Purpose |
|---|---|---|---|---|
| `mtg` | 69 | codemode | none | **This repo's own server.** First-check target; use for smoke tests |
| `context7` | 2 | direct | none | Version-pinned library docs (FastMCP, Pydantic, httpx) |
| `web-search-prime` | 1 | direct | `Z_AI_API_KEY` | Web search — current releases, real-time info |
| `web-reader` | 1 | direct | `Z_AI_API_KEY` | Fetch any webpage as structured content |
| `zread` | 3 | deferred | `Z_AI_API_KEY` | Search docs/issues/PRs in any public GitHub repo |
| `zai-vision` | 8 | deferred | `Z_AI_API_KEY` | Image/video analysis, screenshot OCR, diagram reading |

Config: `.pi/mcp.json` (committed). A local (gitignored) `.mcp.json` mirrors the Z.ai entries for Claude Code. Verify anytime: `pi mcp list`.

If you need these servers yourself, wire them from the manifest above — entries are Claude-compatible (`mcpServers` format); remote ones are streamable HTTP + `Authorization: Bearer $Z_AI_API_KEY`.

## pi's extensions and agents

**Extensions** (`.pi/extensions/`, project-trusted):
- `subagent` — isolated-context delegation: single `{agent, task}`, parallel `{tasks:[...]}` (≤8, 4 concurrent), or chained `{chain:[... {previous} ...]}`. Project agents need `agentScope: "both"` in the call.
- `git-checkpoint` — per-turn stash checkpoints for fork/restore.
- `guards` — blocks `.env` edits; ruff-formats touched `.py` files (port of the old Claude hooks; code below).

**Subagents** (`.pi/agents/`): `scout` (fast recon), `code-reviewer` (project-convention review — run it as a review gate before requesting PRs).

**Codemode** is on: pi can batch MCP calls in JS scripts (`Promise.allSettled`) — that's how the 69-tool smoke test stays fast.

## Skills (`.agents/skills/`, portable — you can use them too)

- `superpowers/` — 15 skills vendored from obra/superpowers 7.0.0 (MIT): `brainstorming`, `writing-plans`, `executing-plans`, `subagent-driven-development`, `dispatching-parallel-agents`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `using-git-worktrees`, `finishing-a-development-branch`, `requesting-code-review`, `receiving-code-review`, `writing-skills`, `using-superpowers`, `diagnosing-superpowers`.
- Repo skills: `smoke-test` (end-to-end MCP verification against real APIs), `new-provider` (scaffold a backend following project patterns), `capture-fixture` (capture live API response as test fixture).

**Spec → plan → execution mapping:** hand pi `brainstorming` → `writing-plans` → `executing-plans`/`subagent-driven-development`. When those skills reference a "Task tool" or dispatching to subagents, that means pi's `subagent` extension tool. `requesting/receiving-code-review` assumed a Claude PR bot — that loop is **yours** now; substitute your review process or pi's `code-reviewer` subagent.

## First checks when landing here

1. `git status && git branch --show-current` — establish state
2. `pi mcp list` — all six servers should connect (if Z.ai ones fail: `Z_AI_API_KEY` missing from your env)
3. `mise run check:quick` — repo health in ~10s
4. End-to-end sanity of the system under development: ask pi to run the `smoke-test` skill against the `mtg` server (real APIs, ~1-2 min)

## guards.ts (extension source, for reference/review)

```ts
// .pi/extensions/guards.ts — port of .claude/settings.json hooks for pi
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const run = promisify(execFile);

function touchedPyFile(event: { toolName: string; input?: { path?: unknown } }): string | undefined {
	const path = event.input?.path;
	return (event.toolName === "edit" || event.toolName === "write") &&
		typeof path === "string" && path.endsWith(".py") ? path : undefined;
}

export default function (pi: ExtensionAPI) {
	// Block .env edits (local-only file; .env.example is the template)
	pi.on("tool_call", async (event) => {
		const path = event.input?.path;
		if ((event.toolName === "edit" || event.toolName === "write") &&
			typeof path === "string" && /(^|\/)\.env(\..+)?$/.test(path)) {
			return { block: true, reason: "Do not edit .env directly. Use .env.example instead." };
		}
		return undefined;
	});

	// ruff-format touched Python files (real gate is `mise run check`)
	pi.on("tool_result", async (event) => {
		const file = touchedPyFile(event);
		if (file) {
			try { await run("ruff", ["format", "--quiet", file]); } catch { /* gate catches */ }
		}
		return undefined;
	});
}
```

## Known limitations & housekeeping

- `zai-vision` is semi-redundant if pi's driving model is multimodal (pi's `read` tool attaches images natively) — kept for OCR/diagram/video tooling and GLM vision routing; costs nothing at deferred exposure.
- `.claude/` tree (skills, agents, hooks, settings) remains for the Claude Code subscription — intentionally untouched. `.claude/agents/code-reviewer.md` has stale conventions (superseded by `.pi/agents/code-reviewer.md`); `.claude/worktrees/*` holds 6 stale agent worktrees — safe to prune whenever.
- `.kilo/` is untracked (another harness's data); ignored here.
- Superpowers skills are vendored at 7.0.0 — upstream updates require manual re-vendor.
- `mtg` server env in `.pi/mcp.json` uses an absolute `--project` path — machine-specific by design (matches the existing local `.mcp.json` precedent).
