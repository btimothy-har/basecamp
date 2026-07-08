import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { awaitDaemonConnection, registerDaemonClient } from "./agents/daemon/index.ts";
import { registerAgentCatalog } from "./agents/index.ts";
import { registerReviewCommand } from "./agents/review/command.ts";
import { resolveAgentDepthState } from "./agents/types.ts";
import type { PiSwarmDependencies } from "./dependencies.ts";
import { createLocalPiSwarmDependencies } from "./local-adapters.ts";
import { registerWorkstreamStartup } from "./workstreams/start.ts";
import { registerWorkstreamTools } from "./workstreams/tools.ts";

const defaultPiSwarmDependencies = createLocalPiSwarmDependencies();

function registerWorkstreams(pi: ExtensionAPI): void {
	const { isTopLevel, atMaxDepth } = resolveAgentDepthState();

	if (isTopLevel && !atMaxDepth) {
		registerWorkstreamTools(pi, awaitDaemonConnection);
	}
	if (isTopLevel) {
		registerWorkstreamStartup(pi, awaitDaemonConnection);
	}
}

export default function (pi: ExtensionAPI): void {
	registerAgentCatalog(defaultPiSwarmDependencies);
	registerDaemonClient(pi, defaultPiSwarmDependencies);
	registerReviewCommand(pi, defaultPiSwarmDependencies);
	registerWorkstreams(pi);
}

export function registerPiSwarm(pi: ExtensionAPI, deps: PiSwarmDependencies = defaultPiSwarmDependencies): void {
	registerAgentCatalog(deps);
	registerDaemonClient(pi, deps);
	registerReviewCommand(pi, deps);
	registerWorkstreams(pi);
}

export type { PiSwarmDependencies } from "./dependencies.ts";
