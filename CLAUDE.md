# MTG MCP Server — Claude Code entry point

Single source of truth for agent instructions is AGENTS.md. This file imports it so Claude Code reads the same rules as every other agent. Do not duplicate content here — edit AGENTS.md.

@AGENTS.md

## Claude Code specifics (not portable to other harnesses)

- Skills, hooks, and agents for Claude Code live in `.claude/` (the pi equivalents are `.pi/` and `.agents/`). The `.claude/` tree is kept for the Claude Code subscription and is intentionally untouched by other agents.
- smoke-test checklist path for Claude sessions: `.claude/skills/smoke-test/SKILL.md` (pi uses `.agents/skills/smoke-test/SKILL.md`).
- Worktree agent workflow: commit all changes and verify you're on the correct feature branch before launching agents — they branch from the last COMMITTED state of the CURRENT branch. Never blindly `cp` files out of a worktree over scaffolded files (agents rewrite entire files — diff first). Cherry-pick agent commits back, then `git diff <prior-commit>..HEAD -- <shared-files>` to catch silent clobbers.
- Cancel stale CI runs on the branch before pushing new commits.
- Dispatch hierarchy: parallel agents (independent file domains) → subagent-driven development (sequential tasks needing review gates) → sequential only when tightly coupled.

## PR workflow (Claude review bot)

- Create PRs as drafts (`gh pr create --draft`) — automated review triggers on `ready_for_review`, not `opened`.
- Fetch comments via `gh api /repos/{owner}/{repo}/pulls/{number}/comments`, reply via `.../comments/{id}/replies`, fix, run `mise run check`, commit referencing the PR, push, resolve threads via GraphQL `resolveReviewThread`.
