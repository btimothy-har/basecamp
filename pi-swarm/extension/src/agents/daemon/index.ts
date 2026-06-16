import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "../types.ts";
import { connect, type DaemonConnection, type DaemonIdentity, ensureDaemon } from "./client.ts";
import { resolveDaemonPaths } from "./paths.ts";
import { registerDaemonReporter } from "./reporter.ts";
import { registerDaemonTools } from "./tools.ts";

type ThemeFg = Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0];

interface DaemonClientState {
	connection: DaemonConnection | null;
	connecting: Promise<void> | null;
}

type DaemonStatusKind = "idle" | "starting" | "connected" | "unavailable" | "disconnected";

interface DaemonStatus {
	kind: DaemonStatusKind;
	message?: string;
}

const DAEMON_STATUS_ID = "basecamp.daemon";
const DAEMON_MESSAGE_TRUNCATE_LENGTH = 80;

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

function previewDaemonMessage(message: string | undefined): string | null {
	const sanitized = message?.replace(/[\r\n\t]/g, " ").trim();
	if (!sanitized) return null;
	if (sanitized.length <= DAEMON_MESSAGE_TRUNCATE_LENGTH) return sanitized;
	return `${sanitized.slice(0, DAEMON_MESSAGE_TRUNCATE_LENGTH - 1)}…`;
}

function renderDaemonStatus(fg: ThemeFg, status: DaemonStatus): string {
	if (status.kind === "connected") return fg("success", "daemon ✓");
	if (status.kind === "starting") return `${fg("warning", "daemon …")} ${fg("dim", "starting")}`;
	if (status.kind === "disconnected") return `${fg("warning", "daemon ⚠")} ${fg("dim", "disconnected")}`;
	if (status.kind === "unavailable") {
		const message = previewDaemonMessage(status.message);
		return message ? `${fg("error", "daemon ✗")} ${fg("error", message)}` : fg("error", "daemon ✗ unavailable");
	}
	return fg("muted", "daemon idle");
}

function publishDaemonStatus(ctx: ExtensionContext, status: DaemonStatus): void {
	if (!ctx.hasUI) return;
	ctx.ui.setStatus(DAEMON_STATUS_ID, renderDaemonStatus(ctx.ui.theme.fg, status));
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
 * - session_name = BASECAMP_AGENT_TITLE (+ session-id suffix) ?? BASECAMP_SESSION_NAME ?? node_id
 * - cwd = process.cwd()
 */
export function deriveDaemonIdentity(
	ctx: ExtensionContext,
	deps?: Pick<PiSwarmDependencies, "formatTitle" | "shortSessionId">,
): DaemonIdentity {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? 0);
	const safeDepth = Number.isFinite(depth) && depth >= 0 ? depth : 0;
	const nodeId = process.env.BASECAMP_AGENT_ID ?? ctx.sessionManager.getSessionId();
	return {
		node_id: nodeId,
		role: safeDepth > 0 ? "agent" : "session",
		parent_id: process.env.BASECAMP_PARENT_SESSION ?? null,
		sibling_group: process.env.BASECAMP_SIBLING_GROUP ?? null,
		depth: safeDepth,
		session_name:
			resolveDaemonAgentTitle(ctx, {
				formatTitle: deps?.formatTitle ?? ((title, suffix) => `${title} [${suffix}]`),
				shortSessionId: deps?.shortSessionId ?? ((sessionId) => sessionId.replace(/-/g, "").slice(-4)),
			}) ??
			process.env.BASECAMP_SESSION_NAME ??
			nodeId,
		cwd: process.cwd(),
	};
}

function resolveDaemonAgentTitle(
	ctx: ExtensionContext,
	deps: Pick<PiSwarmDependencies, "formatTitle" | "shortSessionId">,
): string | null {
	const base = process.env.BASECAMP_AGENT_TITLE?.trim();
	if (!base) return null;
	return deps.formatTitle(base, deps.shortSessionId(ctx.sessionManager.getSessionId()));
}

function trackDaemonConnection(
	state: DaemonClientState,
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
	const state = getDaemonClientState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const { socketPath } = await ensureDaemon();
	const connection = await connect(identity, { socketPath });
	return trackDaemonConnection(state, connection, ctx);
}

async function connectSpawnedAgent(ctx: ExtensionContext): Promise<DaemonConnection> {
	const state = getDaemonClientState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const socketPath = process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath;
	const connection = await connect(identity, { socketPath });
	return trackDaemonConnection(state, connection, ctx);
}

export function registerDaemonClient(pi: ExtensionAPI, deps: PiSwarmDependencies): void {
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
		registerDaemonTools(pi, awaitDaemonConnection, {
			hasInvokedSkill: deps.hasInvokedSkill,
			getWorkspaceState: deps.getWorkspaceState,
			basecampExtensionRoot: deps.basecampExtensionRoot,
			resolveModelAlias: deps.resolveModelAlias,
			readSkillContent: deps.readSkillContent,
			buildSkillBlock: deps.buildSkillBlock,
		});
	}

	const state = getDaemonClientState();
	const reporterConnection = isDaemonSpawnedAgent ? deferred<DaemonConnection>() : null;
	let sessionCtx: ExtensionContext | null = null;

	if (reporterConnection && runId && process.env.BASECAMP_AGENT_ID) {
		registerDaemonReporter(pi, {
			connectionPromise: reporterConnection.promise,
			runId,
			agentId: process.env.BASECAMP_AGENT_ID,
		});
	}

	pi.on("session_start", (_event, ctx) => {
		sessionCtx = ctx;

		if (isDaemonSpawnedAgent) {
			const agentTitle = resolveDaemonAgentTitle(ctx, {
				formatTitle: deps.formatTitle,
				shortSessionId: deps.shortSessionId,
			});
			if (agentTitle) {
				pi.setSessionName(agentTitle);
				process.env.BASECAMP_SESSION_NAME = agentTitle;
			}
		}

		state.connecting = (async () => {
			try {
				publishDaemonStatus(ctx, { kind: "starting" });
				const connection = isTopLevel
					? await ensureAndConnectTopLevel(ctx)
					: await connectSpawnedAgent(ctx);
				reporterConnection?.resolve(connection);
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				publishDaemonStatus(ctx, { kind: "unavailable", message });
				reporterConnection?.reject(error);
				if (isTopLevel) {
					ctx.ui.notify(`bc-swarm daemon unavailable: ${message}`, "warning");
				}
			} finally {
				state.connecting = null;
			}
		})();
	});

	pi.on("session_shutdown", () => {
		const connection = state.connection;
		const ctx = sessionCtx;
		state.connection = null;
		state.connecting = null;
		if (ctx) {
			publishDaemonStatus(ctx, { kind: "idle" });
		}
		try {
			connection?.close();
		} catch {
			// best effort
		}
	});
}
