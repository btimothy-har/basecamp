/**
 * Observer Integration
 *
 * Triggers the observer pipeline (ingest + optional processing) at key
 * session lifecycle points so transcripts are indexed for semantic recall.
 *
 * Hooks:
 *   session_before_compact / session_shutdown → full pipeline (ingest --process)
 *   tool_call (agent tool dispatch) → ingest only (no --process)
 *
 * Tool:
 *   recall — semantic search over past sessions (spawns Python CLI)
 */

import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { getWorkspaceState } from "../../platform/workspace";
import { registerRecallTool } from "./recall-tool.js";

/** Sessions with fewer turns than this are not worth indexing for recall. */
const MIN_TURNS_FOR_INGEST = 1;

let notifiedFailure = false;
let turnCount = 0;

/**
 * Fire-and-forget observer ingest. Pipes session JSON to stdin.
 * Logs to ~/.pi/observer/observer.log on the Python side.
 * Extension-side failures (e.g. observer not installed) notify once.
 */
function triggerIngest(pi: ExtensionAPI, ctx: ExtensionContext, processFlag: boolean): void {
	const sessionId = ctx.sessionManager.getSessionId();
	const sessionFile = ctx.sessionManager.getSessionFile();
	if (!sessionId || !sessionFile) return;

	const workspace = getWorkspaceState();
	const executionTarget = workspace?.executionTarget
		? {
				kind: workspace.executionTarget.kind,
				label: workspace.executionTarget.label,
				path: workspace.executionTarget.path,
				branch: workspace.executionTarget.branch,
			}
		: null;
	const payload = JSON.stringify({
		session_id: sessionId,
		transcript_path: sessionFile,
		cwd: workspace?.effectiveCwd ?? path.resolve(ctx.cwd),
		repo_name: workspace?.repo?.name ?? null,
		repo_root: workspace?.repo?.root ?? null,
		repo_remote_url: workspace?.repo?.remoteUrl ?? null,
		execution_target: executionTarget,
	});

	const observerCmd = processFlag ? "observer ingest --process" : "observer ingest";
	const b64 = Buffer.from(payload).toString("base64");
	const shellCmd = `echo ${b64} | base64 -d | ${observerCmd}`;

	pi.exec("bash", ["-c", shellCmd], { timeout: 300_000 }).catch(() => {
		if (!notifiedFailure) {
			notifiedFailure = true;
			ctx.ui.notify("observer: ingest failed — check ~/.pi/observer/observer.log", "warning");
		}
	});
}

export default function (pi: ExtensionAPI): void {
	registerObserver(pi);
	registerRecallTool(pi);
}

export function registerObserver(pi: ExtensionAPI): void {
	pi.on("turn_end", async () => {
		turnCount++;
	});

	pi.on("session_before_compact", async (_event, ctx) => {
		if (turnCount < MIN_TURNS_FOR_INGEST) return;
		triggerIngest(pi, ctx, true);
	});

	pi.on("session_shutdown", async (_event, ctx) => {
		if (turnCount < MIN_TURNS_FOR_INGEST) return;
		triggerIngest(pi, ctx, true);
	});

	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "agent") return;
		const input = event.input as { action?: string; task?: string };
		if (input.task && !input.action) {
			triggerIngest(pi, ctx, false);
		}
	});
}
