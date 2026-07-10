// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
// v18: cancel-agent request/ack frames.
// v19: workstream create/attach/update frames + /workstreams HTTP reads.
export const PROTOCOL_VERSION = 19;
