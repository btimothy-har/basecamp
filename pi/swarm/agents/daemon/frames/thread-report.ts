import type { PROTOCOL_VERSION } from "./version.ts";

/** One pi session entry, envelope extracted extension-side; `entry_json` is opaque to the daemon. */
export interface ThreadReportNode {
	id: string;
	parent_id: string | null;
	entry_json: string;
}

/**
 * Raw session thread pushed by a top-level session at end of turn. The extension
 * splits `getBranch()` into per-entry `nodes` so the daemon stores immutable
 * nodes (keyed by `id`) without parsing pi content. `session_id`/`session_file`
 * are pi's own id and `.jsonl` transcript path (see
 * docs/design/companion-daemon-broker.md).
 */
export interface ThreadReportFrame {
	type: "thread_report";
	v: typeof PROTOCOL_VERSION;
	node_id: string;
	session_id: string;
	session_file: string | null;
	leaf_id: string | null;
	nodes: ThreadReportNode[];
}
