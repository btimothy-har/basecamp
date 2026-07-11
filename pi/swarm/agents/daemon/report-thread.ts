import type { DaemonConnection } from "./client.ts";
import { PROTOCOL_VERSION } from "./frames/index.ts";
import type { ThreadReportNode } from "./frames/thread-report.ts";
import { awaitDaemonConnection } from "./index.ts";

// `connection.send()` only buffers into the ws sender; the frame flushes on the event
// loop. Yield briefly after the final send so a session that exits right after
// `agent_end` (e.g. a headless `pi -p` one-shot) still flushes its last report.
const FLUSH_DELAY_MS = 50;

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

/** A computed raw-thread report, ready to wrap in the `thread_report` frame. */
export interface ThreadReport {
	node_id: string;
	session_id: string;
	session_file: string | null;
	leaf_id: string | null;
	nodes: ThreadReportNode[];
}

/**
 * Transport for the companion analyzer: wrap a computed thread report in the
 * `thread_report` frame and ship it over the primary session's daemon connection.
 *
 * Resolves the *current* connection on every call (a `/fork` reconnects the daemon
 * client under a new session id, so a per-send lookup keeps reports landing under
 * the live owner), no-ops if unconnected, and yields a short flush window. The frame
 * codec stays daemon-owned here; the companion owns the policy (what/when) — see
 * docs/design/companion-daemon-broker.md.
 */
export async function reportThread(
	report: ThreadReport,
	awaitConnection: () => Promise<DaemonConnection | null> = awaitDaemonConnection,
): Promise<void> {
	const connection = await awaitConnection();
	if (!connection) return;
	connection.send({ type: "thread_report", v: PROTOCOL_VERSION, ...report });
	await sleep(FLUSH_DELAY_MS);
}
