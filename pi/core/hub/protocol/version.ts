// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
// v18: cancel-agent request/ack frames.
// v19: workstream create/attach/update frames + /workstreams HTTP reads.
// v20: thread_report frame — top-level session raw-thread upload (removed in v24).
// v21: register frame gains repo + worktree_label identity facets.
// v22: revise_workstream content-versioning frames + /workstreams detail carries version history.
// v23: dispatch spec gains owned_worktree — the reaper removes a mutative agent's worktree on run exit.
// v24: removes the retired thread_report frame.
// v25: register metadata facets + self-scoped session_metadata frame; read-only dashboard HTTP surface.
// v26: removes /runs/messages and narrows /runs/summary to compact-widget fields.
export const PROTOCOL_VERSION = 26;

/**
 * The version envelope every wire frame carries. Frame interfaces `extends` this
 * instead of redeclaring `v`; `encodeFrame` stamps the value at serialization so
 * construction sites never pass it.
 */
export interface ProtocolEnvelope {
	v: typeof PROTOCOL_VERSION;
}
