import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { reportThread, type ThreadReport } from "#swarm/index.ts";

function isTopLevelSession(): boolean {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	return !Number.isFinite(depth) || depth <= 0;
}

/**
 * Ships the top-level session's raw thread to the daemon at each `agent_end`, for
 * the companion analyzer. Splits `getBranch()` into per-entry nodes (envelope
 * extracted here; `entry_json` opaque to the daemon) and carries pi's session id +
 * `.jsonl` transcript path. Prefers `BASECAMP_AGENT_ID` for `node_id`, falling back
 * to the session id (unset for a top-level session, so it reports under its own id).
 *
 * Companion owns the policy (what/when); the transport ({@link reportThread}, from
 * `#swarm`) owns the connection + frame. Gated to top-level sessions and
 * fire-and-forget — a reporter hook never throws.
 */
export function registerThreadReporter(
	pi: ExtensionAPI,
	report: (r: ThreadReport) => Promise<void> = reportThread,
): void {
	if (!isTopLevelSession()) return;

	pi.on("agent_end", async (_event, ctx) => {
		try {
			const sm = ctx.sessionManager;
			const withSessionFile = sm as typeof sm & { getSessionFile?: () => string | null | undefined };
			const nodes = sm.getBranch().map((entry) => ({
				id: entry.id,
				parent_id: entry.parentId,
				entry_json: JSON.stringify(entry),
			}));
			await report({
				node_id: process.env.BASECAMP_AGENT_ID ?? sm.getSessionId(),
				session_id: sm.getSessionId(),
				session_file: withSessionFile.getSessionFile?.() ?? null,
				leaf_id: sm.getLeafId(),
				nodes,
			});
		} catch {
			// never throw from reporter hooks
		}
	});
}
