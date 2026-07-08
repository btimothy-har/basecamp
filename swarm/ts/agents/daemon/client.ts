/**
 * Daemon client façade — the public surface of the daemon-client subsystem.
 * Implementation lives in the sibling modules (process, spawn, http, view/,
 * connection, rpc); internal modules import each other directly, never
 * through this barrel.
 */

export { type ConnectOptions, connect, type DaemonConnection, type DaemonIdentity } from "./connection.ts";
export { type HealthPingFail, type HealthPingOk, type HealthPingResult, healthPing } from "./http.ts";
export {
	type AttachWorkstreamAgentResult,
	type CancelAgentResult,
	type CreateWorkstreamResult,
	createDaemonClient,
	type DaemonClient,
	type DaemonDispatchFrameOptions,
	type DaemonDispatchResult,
	type MessageStatusOptions,
	type MessageStatusResult,
	type SendPeerMessageOptions,
	type SendPeerMessageResult,
	type UpdateWorkstreamResult,
} from "./rpc.ts";
export { type EnsureDaemonOptions, ensureDaemon, spawnDaemonProcess } from "./spawn.ts";
export {
	buildRunSummaryPath,
	fetchRunSummary,
	parseRunSummaryResponse,
	type RunSummaryActivity,
	type RunSummaryAgent,
	type RunSummaryResult,
	type RunSummaryTaskInfo,
	type RunSummaryTaskPlanItem,
} from "./view/summary.ts";
export {
	buildWorkstreamsPath,
	getWorkstream,
	listWorkstreams,
	parseWorkstreamDetailResponse,
	parseWorkstreamsResponse,
	type WorkstreamAgentView,
	type WorkstreamDetail,
	type WorkstreamSummary,
} from "./view/workstream.ts";
