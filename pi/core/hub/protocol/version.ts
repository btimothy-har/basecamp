// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
// v18: cancel-agent request/ack frames.
// v19: workstream create/attach/update frames + /workstreams HTTP reads.
// v20: thread_report frame — top-level session ships its raw thread to the daemon.
// v21: register frame gains repo + worktree_label identity facets.
export const PROTOCOL_VERSION = 21;
