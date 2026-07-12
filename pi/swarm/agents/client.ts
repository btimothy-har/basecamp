/**
 * Daemon client façade (agent-side). The connection/transport primitives are
 * core-owned (#core/hub); this barrel re-exports the connection types plus the
 * agent request client (`rpc.ts`) and observability views (`view/`) as one
 * import surface — used by workstreams, review, tests, and intra-domain callers
 * that want types without reaching into each implementation module.
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
