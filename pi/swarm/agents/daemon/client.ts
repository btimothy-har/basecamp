/**
 * Daemon client façade (agent-side). The connection/transport primitives are
 * core-owned (#core/hub); this barrel re-exports the connection types for swarm
 * consumers and composes the agent request client + observability views.
 * Internal modules import each other directly, never through this barrel.
 */

export type { DaemonConnection, DaemonIdentity } from "#core/hub/index.ts";
export {
	createDaemonClient,
	type DaemonClient,
	type DaemonDispatchFrameOptions,
	type DaemonDispatchResult,
} from "./rpc.ts";
export { fetchRunSummary, type RunSummaryAgent, type RunSummaryResult } from "./view/summary.ts";
export {
	getWorkstream,
	listWorkstreams,
	type WorkstreamAgentView,
	type WorkstreamDetail,
	type WorkstreamSummary,
} from "./view/workstream.ts";
