import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDaemonClient } from "./agents/daemon/index.ts";
import { registerAgents } from "./agents/index.ts";
import type { PiSwarmDependencies } from "./dependencies.ts";

export function registerPiSwarm(pi: ExtensionAPI, deps: PiSwarmDependencies): void {
	registerAgents(pi, deps);
	registerDaemonClient(pi, deps);
}

export type { PiSwarmDependencies } from "./dependencies.ts";
