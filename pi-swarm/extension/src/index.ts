import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDaemonClient } from "./agents/daemon/index.ts";
import { registerAgents } from "./agents/index.ts";
import type { PiSwarmDependencies } from "./dependencies.ts";
import { createLocalPiSwarmDependencies } from "./local-adapters.ts";

const defaultPiSwarmDependencies = createLocalPiSwarmDependencies();

export default function (pi: ExtensionAPI): void {
	registerDaemonClient(pi, defaultPiSwarmDependencies);
}

export function registerPiSwarm(pi: ExtensionAPI, deps: PiSwarmDependencies = defaultPiSwarmDependencies): void {
	registerAgents(pi, deps);
	registerDaemonClient(pi, deps);
}

export type { PiSwarmDependencies } from "./dependencies.ts";
