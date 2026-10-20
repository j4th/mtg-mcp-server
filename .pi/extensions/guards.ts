/**
 * guards.ts — port of .claude/settings.json hooks for pi
 *
 * 1. Blocks direct edits to .env (use .env.example; .env is local-only)
 * 2. ruff-formats any .py file touched by edit/write
 *
 * The real formatting gate is `mise run check`; this just keeps the
 * working tree tidy between gate runs.
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const run = promisify(execFile);

function touchedPyFile(event: { toolName: string; input?: { path?: unknown } }): string | undefined {
	const path = event.input?.path;
	return (event.toolName === "edit" || event.toolName === "write") &&
		typeof path === "string" &&
		path.endsWith(".py")
		? path
		: undefined;
}

export default function (pi: ExtensionAPI) {
	// PreToolUse equivalent: deny .env edits (any .env* path at repo root)
	pi.on("tool_call", async (event) => {
		const path = event.input?.path;
		if (
			(event.toolName === "edit" || event.toolName === "write") &&
			typeof path === "string" &&
			/(^|\/)\.env(\..+)?$/.test(path)
		) {
			return { block: true, reason: "Do not edit .env directly. Use .env.example instead." };
		}
		return undefined;
	});

	// PostToolUse equivalent: format touched Python files
	pi.on("tool_result", async (event) => {
		const file = touchedPyFile(event);
		if (!file) return undefined;
		try {
			await run("ruff", ["format", "--quiet", file]);
		} catch {
			// Not fatal — `mise run check` is the authoritative gate.
		}
		return undefined;
	});
}
