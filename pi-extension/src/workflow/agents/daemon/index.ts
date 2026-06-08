import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { connect, type DaemonConnection, type DaemonIdentity, ensureDaemon } from "./client.ts";

interface DaemonClientState {
	connection: DaemonConnection | null;
	connecting: Promise<void> | null;
}

const daemonClientKey = Symbol.for("basecamp.daemonClient");

type GlobalWithDaemonClient = typeof globalThis & {
	[daemonClientKey]?: DaemonClientState;
};

function getDaemonClientState(): DaemonClientState {
	const globalObject = globalThis as GlobalWithDaemonClient;
	globalObject[daemonClientKey] ??= { connection: null, connecting: null };
	return globalObject[daemonClientKey];
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
		session_name: process.env.BASECAMP_SESSION_NAME ?? nodeId,
		cwd: process.cwd(),
	};
}

async function ensureAndConnect(ctx: ExtensionContext): Promise<void> {
	const state = getDaemonClientState();
	if (state.connection) return;

	const identity = deriveDaemonIdentity(ctx);
	const { socketPath } = await ensureDaemon();
	const connection = await connect(identity, { socketPath });
	connection.onClose(() => {
		if (state.connection === connection) {
			state.connection = null;
		}
	});
	state.connection = connection;
}

export function registerDaemonClient(pi: ExtensionAPI): void {
	if (Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0) return;

	const state = getDaemonClientState();

	pi.on("session_start", (_event, ctx) => {
		state.connecting = (async () => {
			try {
				await ensureAndConnect(ctx);
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				ctx.ui.notify(`basecamp daemon unavailable: ${message}`, "warning");
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
