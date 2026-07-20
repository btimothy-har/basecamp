import { sleep } from "../async.ts";
import type { DaemonConnection } from "./connection.ts";
import type { ThreadReportNode } from "./protocol/thread-report.ts";
import { awaitDaemonConnection } from "./state.ts";

// `connection.send()` only buffers into the ws sender; the frame flushes on the event
// loop. Yield briefly after the final send so a session that exits right after
// `agent_end` (e.g. a headless `pi -p` one-shot) still flushes its last report.
const FLUSH_DELAY_MS = 50;

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
 * client under a new session id, so a per-send lookup keeps reports landing under the
 * live owner) and no-ops if unconnected. `buildReport` is invoked lazily — only once a
 * live connection is confirmed — so a disconnected turn skips the (potentially large)
 * `getBranch()` serialization. Yields a short flush window after send. The frame codec
 * stays daemon-owned; the companion owns the policy (what/when) — see
 * docs/design/companion-daemon-broker.md.
 */
export async function reportThread(
	buildReport: () => ThreadReport,
	awaitConnection: () => Promise<DaemonConnection | null> = awaitDaemonConnection,
): Promise<void> {
	const connection = await awaitConnection();
	if (!connection) return;
	connection.send({ type: "thread_report", ...buildReport() });
	await sleep(FLUSH_DELAY_MS);
}
