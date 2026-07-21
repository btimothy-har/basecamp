// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
// v18: cancel-agent request/ack frames.
// v19: workstream create/attach/update frames + /workstreams HTTP reads.
// v20: thread_report frame — top-level session ships its raw thread to the daemon.
// v21: register frame gains repo + worktree_label identity facets.
// v22: revise_workstream content-versioning frames + /workstreams detail carries version history.
// v23: dispatch spec gains owned_worktree — the reaper removes a mutative agent's worktree on run exit.
// v24: removes the retired companion-analysis thread_report frame.
export const PROTOCOL_VERSION = 24;

/**
 * The version envelope every wire frame carries. Frame interfaces `extends` this
 * instead of redeclaring `v`; `encodeFrame` stamps the value at serialization so
 * construction sites never pass it.
 */
export interface ProtocolEnvelope {
	v: typeof PROTOCOL_VERSION;
}
