/**
 * Daemon client façade — the public surface of the daemon-client subsystem.
 * Implementation lives in the sibling modules (process, spawn, http, view/,
 * connection, rpc); internal modules import each other directly, never
 * through this barrel.
 */

export { connect, type DaemonConnection, type DaemonIdentity } from "./connection.ts";
export {
	createDaemonClient,
	type DaemonClient,
	type DaemonDispatchFrameOptions,
	type DaemonDispatchResult,
} from "./rpc.ts";
export { ensureDaemon } from "./spawn.ts";
export { fetchRunSummary, type RunSummaryAgent, type RunSummaryResult } from "./view/summary.ts";
export {
	getWorkstream,
	listWorkstreams,
	type WorkstreamAgentView,
	type WorkstreamDetail,
	type WorkstreamSummary,
} from "./view/workstream.ts";
