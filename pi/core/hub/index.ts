import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getAgentDepth } from "../host/env.ts";
import { connect, type DaemonConnection } from "./connection.ts";
import {
	type DaemonIdentityDeps,
	defaultIdentityDeps,
	deriveDaemonIdentity,
	resolveDaemonAgentTitle,
} from "./identity.ts";
import { startSessionMetadataPublisher } from "./metadata.ts";
import { resolveDaemonPaths } from "./paths.ts";
import { ensureDaemon } from "./spawn.ts";
import {
	clearHubMetadataWiring,
	createHubMetadataWiring,
	getConnectListeners,
	getHubConnectionState,
	getHubMetadataPublisher,
	type HubConnectionState,
	replaceHubMetadataWiring,
} from "./state.ts";
import { publishDaemonStatus } from "./status.ts";

// The hub connection is core-owned: core/hub is the adapter for the hub daemon
// (a peer of core/git, core/host, core/model). Every Pi session plugs into the
// hub through here; swarm (agent tools/reporting/ui) rides on this connection
// via #core/hub. State + accessors live in state.ts; this file owns the connection
// lifecycle and the public barrel.

function trackDaemonConnection(
	state: HubConnectionState,
	connection: DaemonConnection,
	ctx: ExtensionContext,
): DaemonConnection {
	connection.onClose(() => {
		if (state.connection === connection) {
			state.connection = null;
			publishDaemonStatus(ctx, { kind: "disconnected" });
		}
	});
	state.connection = connection;
	publishDaemonStatus(ctx, { kind: "connected" });
	return connection;
}

async function ensureAndConnectTopLevel(ctx: ExtensionContext): Promise<DaemonConnection> {
	const state = getHubConnectionState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const { socketPath } = await ensureDaemon();
	return connect(identity, { socketPath });
}

async function connectSpawnedAgent(ctx: ExtensionContext): Promise<DaemonConnection> {
	const state = getHubConnectionState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const socketPath = process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath;
	return connect(identity, { socketPath });
}

export function registerHubConnection(pi: ExtensionAPI, deps: DaemonIdentityDeps = defaultIdentityDeps()): void {
	const depth = getAgentDepth();
	const isTopLevel = Number.isFinite(depth) ? depth <= 0 : true;
	const isDaemonSpawnedAgent = !isTopLevel && Boolean(process.env.BASECAMP_RUN_ID);

	// Only top-level sessions and daemon-spawned agents connect to the hub.
	if (!isTopLevel && !isDaemonSpawnedAgent) return;

	const state = getHubConnectionState();
	let sessionCtx: ExtensionContext | null = null;
	let connectionGeneration = 0;
	const cleanups: Array<() => void> = [];

	const runCleanups = (): void => {
		for (const cleanup of cleanups.splice(0)) {
			try {
				cleanup();
			} catch {
				// best effort
			}
		}
	};

	pi.on("session_info_changed", (event) => {
		getHubMetadataPublisher(state)?.updateSessionName(event.name);
	});

	pi.on("model_select", (event) => {
		getHubMetadataPublisher(state)?.updateModel(event.model.id);
	});

	pi.on("session_start", (_event, ctx) => {
		sessionCtx = ctx;

		if (isDaemonSpawnedAgent) {
			const agentTitle = resolveDaemonAgentTitle(ctx, deps);
			if (agentTitle) {
				pi.setSessionName(agentTitle);
				process.env.BASECAMP_SESSION_NAME = agentTitle;
			}
		}

		const generation = ++connectionGeneration;
		state.connecting = (async () => {
			try {
				publishDaemonStatus(ctx, { kind: "starting" });
				const connection = isTopLevel ? await ensureAndConnectTopLevel(ctx) : await connectSpawnedAgent(ctx);
				if (generation !== connectionGeneration) {
					connection.close();
					return;
				}
				const activeConnection =
					state.connection === connection ? connection : trackDaemonConnection(state, connection, ctx);
				runCleanups();
				// Reload-surviving source subscriptions must stop before the replacement subscribes.
				clearHubMetadataWiring(state);
				const publisher = startSessionMetadataPublisher(pi, activeConnection, ctx);
				let unsubscribeClose = () => {};
				const metadataWiring = createHubMetadataWiring(publisher, () => unsubscribeClose());
				unsubscribeClose = activeConnection.onClose(() => {
					if (clearHubMetadataWiring(state, metadataWiring)) runCleanups();
				});
				replaceHubMetadataWiring(state, metadataWiring);
				for (const listener of getConnectListeners()) {
					const cleanup = listener(activeConnection, ctx);
					if (cleanup) cleanups.push(cleanup);
				}
			} catch (error) {
				if (generation !== connectionGeneration) return;
				const message = error instanceof Error ? error.message : String(error);
				publishDaemonStatus(ctx, { kind: "unavailable", message });
				clearHubMetadataWiring(state);
				runCleanups();
				if (isTopLevel) {
					ctx.ui.notify(`basecamp hub unavailable: ${message}`, "warning");
				}
			} finally {
				if (generation === connectionGeneration) state.connecting = null;
			}
		})();
	});

	pi.on("session_shutdown", async () => {
		connectionGeneration++;
		const connection = state.connection;
		const connecting = state.connecting;
		const ctx = sessionCtx;
		state.connection = null;
		state.connecting = null;
		clearHubMetadataWiring(state);
		runCleanups();
		if (ctx) publishDaemonStatus(ctx, { kind: "idle" });
		try {
			connection?.close();
		} catch {
			// best effort
		}
		if (connecting) {
			try {
				await connecting;
			} catch {
				// best effort
			}
			const lateConnection = state.connection as DaemonConnection | null;
			if (lateConnection) {
				state.connection = null;
				try {
					lateConnection.close();
				} catch {
					// best effort
				}
			}
		}
	});
}

export { connect, type DaemonConnection, type DaemonIdentity, waitForFrame } from "./connection.ts";
export { buildAgentHandle, buildDeterministicAgentHandle } from "./handles.ts";
export {
	DEFAULT_HEALTH_TIMEOUT_MS,
	type HealthPingResult,
	healthPing,
	optionalBoolean,
	optionalNumber,
	optionalString,
	requestJsonOverUds,
} from "./http.ts";
export { deriveDaemonIdentity, sanitizeDisplayLabel } from "./identity.ts";
export { type DaemonPaths, ensureDaemonRuntimeDir, resolveDaemonPaths } from "./paths.ts";
export { ensureDaemon } from "./spawn.ts";
export {
	awaitDaemonConnection,
	type DaemonConnectListener,
	getActiveDaemonConnection,
	onDaemonConnect,
} from "./state.ts";
export { type DaemonStatusInfo, publishDaemonStatus } from "./status.ts";
