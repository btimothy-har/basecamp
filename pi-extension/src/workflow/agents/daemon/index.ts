import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { formatTitle, shortSessionId } from "../../../session/ui/title.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "../types.ts";
import { connect, type DaemonConnection, type DaemonIdentity, ensureDaemon } from "./client.ts";
import { resolveDaemonPaths } from "./paths.ts";
import { registerDaemonReporter } from "./reporter.ts";
import { registerDaemonTools } from "./tools.ts";

interface DaemonClientState {
	connection: DaemonConnection | null;
	connecting: Promise<void> | null;
}

const daemonClientKey = Symbol.for("basecamp.daemonClient");

type GlobalWithDaemonClient = typeof globalThis & {
	[daemonClientKey]?: DaemonClientState;
};

interface Deferred<T> {
	promise: Promise<T>;
	resolve: (value: T) => void;
	reject: (error?: unknown) => void;
}

function deferred<T>(): Deferred<T> {
	let resolve!: (value: T) => void;
	let reject!: (error?: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

function getDaemonClientState(): DaemonClientState {
	const globalObject = globalThis as GlobalWithDaemonClient;
	globalObject[daemonClientKey] ??= { connection: null, connecting: null };
	return globalObject[daemonClientKey];
}

export function getActiveDaemonConnection(): DaemonConnection | null {
	return getDaemonClientState().connection;
}

async function awaitDaemonConnection(): Promise<DaemonConnection | null> {
	const state = getDaemonClientState();
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
 * Identity derivation:
 * - node_id = BASECAMP_AGENT_ID ?? session id
 * - role = BASECAMP_AGENT_DEPTH > 0 ? "agent" : "session"
 * - parent_id = BASECAMP_PARENT_SESSION ?? null
 * - sibling_group = BASECAMP_SIBLING_GROUP ?? null
 * - session_name = BASECAMP_SESSION_NAME ?? node_id
 * - cwd = process.cwd()
 */
function resolveDaemonAgentTitle(ctx: ExtensionContext): string | null {
	const base = process.env.BASECAMP_AGENT_TITLE?.trim();
	if (!base) return null;
	return formatTitle(base, shortSessionId(ctx.sessionManager.getSessionId()));
}

export function deriveDaemonIdentity(ctx: ExtensionContext): DaemonIdentity {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? 0);
	const safeDepth = Number.isFinite(depth) && depth >= 0 ? depth : 0;
	const nodeId = process.env.BASECAMP_AGENT_ID ?? ctx.sessionManager.getSessionId();
	return {
		node_id: nodeId,
		role: safeDepth > 0 ? "agent" : "session",
		parent_id: process.env.BASECAMP_PARENT_SESSION ?? null,
		sibling_group: process.env.BASECAMP_SIBLING_GROUP ?? null,
		depth: safeDepth,
		session_name: resolveDaemonAgentTitle(ctx) ?? process.env.BASECAMP_SESSION_NAME ?? nodeId,
		cwd: process.cwd(),
	};
}

async function ensureAndConnectTopLevel(ctx: ExtensionContext): Promise<DaemonConnection> {
	const state = getDaemonClientState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const { socketPath } = await ensureDaemon();
	const connection = await connect(identity, { socketPath });
	connection.onClose(() => {
		if (state.connection === connection) {
			state.connection = null;
		}
	});
	state.connection = connection;
	return connection;
}

async function connectSpawnedAgent(ctx: ExtensionContext): Promise<DaemonConnection> {
	const state = getDaemonClientState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const socketPath = process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath;
	const connection = await connect(identity, { socketPath });
	connection.onClose(() => {
		if (state.connection === connection) {
			state.connection = null;
		}
	});
	state.connection = connection;
	return connection;
}

export function registerDaemonClient(pi: ExtensionAPI): void {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const runId = process.env.BASECAMP_RUN_ID;
	const isTopLevel = Number.isFinite(depth) ? depth <= 0 : true;
	const isDaemonSpawnedAgent = !isTopLevel && Boolean(runId);
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	const atMaxDepth = depth >= maxDepth;

	if (!isTopLevel && !isDaemonSpawnedAgent) {
		return;
	}

	if (isTopLevel && !atMaxDepth) {
		registerDaemonTools(pi, awaitDaemonConnection);
	}

	const state = getDaemonClientState();
	const reporterConnection = isDaemonSpawnedAgent ? deferred<DaemonConnection>() : null;

	if (reporterConnection && runId && process.env.BASECAMP_AGENT_ID) {
		registerDaemonReporter(pi, {
			connectionPromise: reporterConnection.promise,
			runId,
			agentId: process.env.BASECAMP_AGENT_ID,
		});
	}

	pi.on("session_start", (_event, ctx) => {
		if (isDaemonSpawnedAgent) {
			const agentTitle = resolveDaemonAgentTitle(ctx);
			if (agentTitle) pi.setSessionName(agentTitle);
		}

		state.connecting = (async () => {
			try {
				const connection = isTopLevel ? await ensureAndConnectTopLevel(ctx) : await connectSpawnedAgent(ctx);
				reporterConnection?.resolve(connection);
			} catch (error) {
				reporterConnection?.reject(error);
				if (isTopLevel) {
					const message = error instanceof Error ? error.message : String(error);
					ctx.ui.notify(`basecamp daemon unavailable: ${message}`, "warning");
				}
			} finally {
				state.connecting = null;
			}
		})();
	});

	pi.on("session_shutdown", () => {
		try {
			state.connection?.close();
		} catch {
			// best effort
		}
		state.connection = null;
		state.connecting = null;
	});
}
