import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { DaemonConnection } from "./client.ts";
import { PROTOCOL_VERSION } from "./frames/index.ts";

/**
 * Ships the top-level session's raw thread to the daemon at the end of each turn
 * (`agent_end`), for the companion analyzer. Splits `getBranch()` into per-entry
 * nodes (envelope extracted here so the daemon stores content opaquely) and
 * carries pi's session id + `.jsonl` transcript path.
 *
 * Resolves the *current* daemon connection on every send: a `/fork` fires
 * `session_shutdown` + `session_start`, reconnecting under the new session id,
 * so a per-send lookup keeps reports landing under the live owner. A plain
 * rewind (`branch()`) keeps the same session id and only moves the leaf.
 * Fire-and-forget.
 */
export function registerRawThreadReporter(
	pi: ExtensionAPI,
	options: { awaitConnection: () => Promise<DaemonConnection | null> },
): void {
	const { awaitConnection } = options;

	pi.on("agent_end", async (_event, ctx) => {
		try {
			const connection = await awaitConnection();
			if (!connection) return;
			const sm = ctx.sessionManager;
			const withSessionFile = sm as typeof sm & { getSessionFile?: () => string | null | undefined };
			const nodes = sm.getBranch().map((entry) => ({
				id: entry.id,
				parent_id: entry.parentId,
				entry_json: JSON.stringify(entry),
			}));
			connection.send({
				type: "thread_report",
				v: PROTOCOL_VERSION,
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
