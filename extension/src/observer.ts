/**
 * Observer Integration
 *
 * Triggers the observer pipeline (ingest + optional processing) at key
 * session lifecycle points so transcripts are indexed for semantic recall.
 *
 * Hooks:
 *   session_before_compact / session_shutdown → full pipeline (ingest --process)
 *   tool_call (bash, worker create --dispatch) → ingest only (no --process)
 *
 * Ported from:
 *   - plugins/companion/scripts/hook-process.sh (PreCompact / SessionEnd)
 *   - plugins/companion/scripts/pretool-ingest.sh (PreToolUse dispatch detection)
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

function isObserverEnabled(): boolean {
	return (
		process.env.BASECAMP_OBSERVER_ENABLED === "1" &&
		process.env.BASECAMP_REFLECT !== "1"
	);
}

/**
 * Build the JSON payload that `observer ingest` expects on stdin.
 * Returns undefined if required session info is unavailable.
 */
function buildHookInput(ctx: ExtensionContext): string | undefined {
	const sessionId = ctx.sessionManager.getSessionId();
	const sessionFile = ctx.sessionManager.getSessionFile();
	const cwd = ctx.cwd;

	if (!sessionId || !sessionFile) return undefined;

	return JSON.stringify({
		session_id: sessionId,
		transcript_path: sessionFile,
		cwd,
	});
}

/**
 * Background the observer pipeline. Fire-and-forget — errors are swallowed
 * (observer logs to its own log file).
 *
 * Uses `bash -c` to pipe the hook JSON to stdin since pi.exec() doesn't
 * support stdin directly.
 */
function triggerIngest(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	processFlag: boolean,
): void {
	const payload = buildHookInput(ctx);
	if (!payload) return;

	const observerCmd = processFlag ? "observer ingest --process" : "observer ingest";

	// Escape single quotes in JSON for safe shell embedding
	const escaped = payload.replace(/'/g, "'\\''");
	const shellCmd = `echo '${escaped}' | ${observerCmd}`;

	// Fire and forget — don't await, don't block the session
	pi.exec("bash", ["-c", shellCmd], { timeout: 300_000 }).catch(() => {});
}

export function registerObserver(pi: ExtensionAPI): void {
	// Trigger full pipeline on compaction
	pi.on("session_before_compact", async (_event, ctx) => {
		if (!isObserverEnabled()) return;
		triggerIngest(pi, ctx, true);
	});

	// Trigger full pipeline on session shutdown
	pi.on("session_shutdown", async (_event, ctx) => {
		if (!isObserverEnabled()) return;
		triggerIngest(pi, ctx, true);
	});

	// Pre-ingest before dispatch so workers have recall access
	pi.on("tool_call", async (event, ctx) => {
		if (!isObserverEnabled()) return;
		if (!isToolCallEventType("bash", event)) return;

		const cmd = event.input.command || "";
		if (/worker\s+create\s+.*--dispatch/.test(cmd)) {
			triggerIngest(pi, ctx, false);
		}
	});
}
