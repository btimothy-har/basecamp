/**
 * Daemon tool registration — composition over the per-tool modules in tool/.
 * Registration order is part of the surface: dispatch, ask, peer messages,
 * cancel, list, wait.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { DaemonConnection } from "#core/hub/index.ts";
import { registerAskAgentTool } from "./tool/ask.ts";
import { registerCancelAgentTool } from "./tool/cancel.ts";
import { registerDispatchAgentTool } from "./tool/dispatch.ts";
import { registerListAgentsTool } from "./tool/list.ts";
import { registerPeerMessageTools } from "./tool/peer-messages.ts";
import type { DaemonToolDeps } from "./tool/support.ts";
import { registerWaitForAgentTool } from "./tool/wait.ts";

export { registerAskAgentTool } from "./tool/ask.ts";
export { registerCancelAgentTool } from "./tool/cancel.ts";
export { registerPeerMessageTools } from "./tool/peer-messages.ts";
export type { DaemonToolDeps } from "./tool/support.ts";

export function registerDaemonTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: DaemonToolDeps,
): void {
	registerDispatchAgentTool(pi, getConnection, deps);
	registerAskAgentTool(pi, getConnection, deps);
	registerPeerMessageTools(pi, getConnection, deps);
	registerCancelAgentTool(pi, getConnection, deps);
	registerListAgentsTool(pi, getConnection, deps);
	registerWaitForAgentTool(pi, getConnection, deps);
}
