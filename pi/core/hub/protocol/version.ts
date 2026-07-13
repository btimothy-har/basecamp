// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
// v18: cancel-agent request/ack frames.
// v19: workstream create/attach/update frames + /workstreams HTTP reads.
// v20: thread_report frame — top-level session ships its raw thread to the daemon.
// v21: register frame gains repo + worktree_label identity facets.
// v22: revise_workstream content-versioning frames + /workstreams detail carries version history.
export const PROTOCOL_VERSION = 22;

/**
 * The version envelope every wire frame carries. Frame interfaces `extends` this
 * instead of redeclaring `v`; `encodeFrame` stamps the value at serialization so
 * construction sites never pass it.
 */
export interface ProtocolEnvelope {
	v: typeof PROTOCOL_VERSION;
}
