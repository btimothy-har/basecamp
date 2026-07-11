import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import { reportThread, type ThreadReport } from "#swarm/index.ts";

/**
 * Ships the top-level session's raw thread to the daemon at each `agent_end`, for
 * the companion analyzer. Splits `getBranch()` into per-entry nodes (envelope
 * extracted here; `entry_json` opaque to the daemon) and carries pi's session id +
 * `.jsonl` transcript path. Prefers `BASECAMP_AGENT_ID` for `node_id`, falling back
 * to the session id (unset for a top-level session, so it reports under its own id).
 *
 * Companion owns the policy (what/when); the transport ({@link reportThread}, from
 * `#swarm`) owns the connection + frame and invokes the builder lazily — only once a
 * live connection is confirmed — so a disconnected turn skips the `getBranch()` work.
 * Skipped for subagents; fire-and-forget — a reporter hook never throws.
 */
export function registerThreadReporter(
	pi: ExtensionAPI,
	report: (build: () => ThreadReport) => Promise<void> = reportThread,
): void {
	if (isSubagent()) return;

	pi.on("agent_end", async (_event, ctx) => {
		try {
			const sm = ctx.sessionManager;
			const withSessionFile = sm as typeof sm & { getSessionFile?: () => string | null | undefined };
			// Treat a blank/whitespace BASECAMP_AGENT_ID as unset (`??` only guards null/undefined).
			const agentId = process.env.BASECAMP_AGENT_ID?.trim();
			await report(() => ({
				node_id: agentId || sm.getSessionId(),
				session_id: sm.getSessionId(),
				session_file: withSessionFile.getSessionFile?.() ?? null,
				leaf_id: sm.getLeafId(),
				nodes: sm.getBranch().map((entry) => ({
					id: entry.id,
					parent_id: entry.parentId,
					entry_json: JSON.stringify(entry),
				})),
			}));
		} catch {
			// never throw from reporter hooks
		}
	});
}
