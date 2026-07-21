import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { processScoped } from "../global-registry.ts";
import type { DaemonConnection } from "./connection.ts";

// Connection state + accessors + the connect seam. Split out of index.ts so
// consumers can depend on connection state without importing registration wiring.

export interface HubConnectionState {
	connection: DaemonConnection | null;
	connecting: Promise<void> | null;
}

// Surviving state: the live daemon WebSocket outlives /reload. Key unchanged
// across the swarm→core relocation (processScoped keys are location-independent).
export const getHubConnectionState = processScoped<HubConnectionState>("basecamp.daemonClient", () => ({
	connection: null,
	connecting: null,
}));

export function getActiveDaemonConnection(): DaemonConnection | null {
	return getHubConnectionState().connection;
}

export async function awaitDaemonConnection(): Promise<DaemonConnection | null> {
	const state = getHubConnectionState();
	if (state.connection) return state.connection;
	if (state.connecting) {
		try {
			await state.connecting;
		} catch {
			// connection failures are surfaced by null result at callsites
		}
	}
	return state.connection;
}

/**
 * Connect seam: consumers (swarm peer-delivery + active-agents widget) register a
 * listener that runs when the connection is (re)established and returns an optional
 * cleanup run on disconnect/shutdown. Plain module state — wiring re-established by
 * each domain's registration on every load.
 */
export type DaemonConnectListener = (connection: DaemonConnection, ctx: ExtensionContext) => (() => void) | undefined;
const connectListeners: DaemonConnectListener[] = [];

export function onDaemonConnect(listener: DaemonConnectListener): () => void {
	connectListeners.push(listener);
	return () => {
		const index = connectListeners.indexOf(listener);
		if (index >= 0) connectListeners.splice(index, 1);
	};
}

export function getConnectListeners(): readonly DaemonConnectListener[] {
	return connectListeners;
}
