import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDaemonClient } from "./agents/daemon/index.ts";
import { registerAgentCatalog } from "./agents/index.ts";
import type { PiSwarmDependencies } from "./dependencies.ts";
import { createLocalPiSwarmDependencies } from "./local-adapters.ts";

const defaultPiSwarmDependencies = createLocalPiSwarmDependencies();

export default function (pi: ExtensionAPI): void {
	registerAgentCatalog(defaultPiSwarmDependencies);
	registerDaemonClient(pi, defaultPiSwarmDependencies);
}

export function registerPiSwarm(pi: ExtensionAPI, deps: PiSwarmDependencies = defaultPiSwarmDependencies): void {
	registerAgentCatalog(deps);
	registerDaemonClient(pi, deps);
}

export type { PiSwarmDependencies } from "./dependencies.ts";
