/**
 * Observer Integration
 *
 * Triggers the observer pipeline (ingest + optional processing) at key
 * session lifecycle points so transcripts are indexed for semantic recall.
 *
 * Hooks:
 *   session_before_compact / session_shutdown → full pipeline (ingest --process)
 *   tool_call (worker tool dispatch) → ingest only (no --process)
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const OBSERVER_CONFIG = path.join(os.homedir(), ".basecamp", "observer", "config.json");

function isObserverEnabled(): boolean {
	if (process.env.BASECAMP_REFLECT === "1") return false;
	try {
		const config = JSON.parse(fs.readFileSync(OBSERVER_CONFIG, "utf8"));
		return !!config.pg_url;
	} catch {
		return false;
	}
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
		if (event.toolName !== "worker") return;

		const input = event.input as { action?: string; task?: string };
		if (input.task && !input.action) {
			triggerIngest(pi, ctx, false);
		}
	});
}
