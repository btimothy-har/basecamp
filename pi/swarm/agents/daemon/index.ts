import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getAgentMode } from "#core/agent-mode/index.ts";
import { resolveAgentRoleOverride } from "#core/agent-role.ts";
import { processScoped } from "#core/platform/global-registry.ts";
import { resolveModelAlias } from "#core/platform/model-aliases.ts";
import { hasInvokedSkill } from "#core/platform/skill-tracker.ts";
import { getWorkspaceState } from "#core/platform/workspace.ts";
import { shortSessionId as defaultShortSessionId } from "#core/session/session-id.ts";
import { formatTitle } from "#core/ui/index.ts";
import { errorMessage } from "../errors.ts";
import { basecampExtensionRoot } from "../extension-root.ts";
import { resolveAgentDepthState } from "../types.ts";
import { connect, type DaemonConnection, type DaemonIdentity, ensureDaemon, fetchRunSummary } from "./client.ts";
import { type PeerDeliveryState, registerPeerMessageDeliveryHandler, sanitizeDisplayLabel } from "./delivery.ts";
import { buildDeterministicAgentHandle } from "./handles.ts";
import { resolveDaemonPaths } from "./paths.ts";
import { registerDaemonReporter } from "./reporter.ts";
import { publishDaemonStatus } from "./status.ts";
import type { DaemonToolDeps } from "./tools.ts";
import {
	registerAskAgentTool,
	registerCancelAgentTool,
	registerDaemonTools,
	registerPeerMessageTools,
} from "./tools.ts";
import { type ActiveAgentsWidgetController, clearActiveAgentsWidget, startActiveAgentsWidget } from "./widget.ts";

interface DaemonClientState extends PeerDeliveryState {
	connection: DaemonConnection | null;
	connecting: Promise<void> | null;
}

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

// Surviving state: the live daemon WebSocket outlives /reload.
const getDaemonClientState = processScoped<DaemonClientState>("basecamp.daemonClient", () => ({
	connection: null,
	connecting: null,
}));

export function getActiveDaemonConnection(): DaemonConnection | null {
	return getDaemonClientState().connection;
}

export async function awaitDaemonConnection(): Promise<DaemonConnection | null> {
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
 * - agent_handle = spawned agents use BASECAMP_AGENT_HANDLE; top-level sessions always derive a
 *   deterministic adjective-noun-hash from node_id so the session handle is stable across reload/resume
 * - session_name = BASECAMP_AGENT_TITLE (+ session-id suffix) ?? BASECAMP_SESSION_NAME ?? node_id
 * - cwd = process.cwd()
 * - session_file = ctx.sessionManager.getSessionFile() when available
 */
/** Host-session capabilities the daemon client wires into tools/identity (injectable for tests). */
export interface DaemonClientDeps extends DaemonToolDeps {
	formatTitle: (title: string, tag: string) => string;
	shortSessionId: (sessionId: string) => string;
}

function defaultDaemonClientDeps(): DaemonClientDeps {
	return {
		hasInvokedSkill,
		getWorkspaceState,
		basecampExtensionRoot: basecampExtensionRoot(),
		resolveModelAlias,
		formatTitle,
		shortSessionId: defaultShortSessionId,
	};
}

export function deriveDaemonIdentity(
	ctx: ExtensionContext,
	deps?: Pick<DaemonClientDeps, "formatTitle" | "shortSessionId">,
): DaemonIdentity {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? 0);
	const safeDepth = Number.isFinite(depth) && depth >= 0 ? depth : 0;
	const nodeId = process.env.BASECAMP_AGENT_ID ?? ctx.sessionManager.getSessionId();
	const explicitHandle = safeDepth > 0 ? process.env.BASECAMP_AGENT_HANDLE?.trim() : undefined;
	const role = safeDepth > 0 ? "agent" : "session";
	return {
		node_id: nodeId,
		agent_handle: explicitHandle || buildDeterministicAgentHandle(nodeId),
		role,
		parent_id: process.env.BASECAMP_PARENT_SESSION ?? null,
		sibling_group: process.env.BASECAMP_SIBLING_GROUP ?? null,
		depth: safeDepth,
		session_name:
			resolveDaemonAgentTitle(ctx, {
				formatTitle: deps?.formatTitle ?? ((title, suffix) => `${title} [${suffix}]`),
				shortSessionId: deps?.shortSessionId ?? defaultShortSessionId,
			}) ??
			process.env.BASECAMP_SESSION_NAME ??
			nodeId,
		cwd: process.cwd(),
		session_file: resolveSessionFile(ctx),
		product_role: resolveAgentRole(role),
	};
}

function resolveAgentRole(role: "session" | "agent"): string | null {
	if (role !== "session") return null;
	const providerOverride = sanitizeDisplayLabel(resolveAgentRoleOverride(), 64);
	if (providerOverride) return providerOverride;
	const explicit = sanitizeDisplayLabel(process.env.BASECAMP_AGENT_PRODUCT_ROLE, 64);
	if (explicit) return explicit;
	return sanitizeDisplayLabel(getAgentMode(), 64);
}

function resolveSessionFile(ctx: ExtensionContext): string | null {
	try {
		const sessionManager = ctx.sessionManager as ExtensionContext["sessionManager"] & {
			getSessionFile?: () => string | null | undefined;
		};
		const sessionFile = sessionManager.getSessionFile?.();
		return typeof sessionFile === "string" && sessionFile.trim() ? sessionFile : null;
	} catch {
		return null;
	}
}

function resolveDaemonAgentTitle(
	ctx: ExtensionContext,
	deps: Pick<DaemonClientDeps, "formatTitle" | "shortSessionId">,
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
			if (state.peerDeliveryConnection === connection) {
				state.peerDeliveryUnsubscribe = null;
				state.peerDeliveryConnection = null;
			}
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
	return connect(identity, { socketPath });
}

async function connectSpawnedAgent(ctx: ExtensionContext): Promise<DaemonConnection> {
	const state = getDaemonClientState();
	if (state.connection) return state.connection;

	const identity = deriveDaemonIdentity(ctx);
	const socketPath = process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath;
	return connect(identity, { socketPath });
}

export function registerDaemonClient(pi: ExtensionAPI, deps: DaemonClientDeps = defaultDaemonClientDeps()): void {
	const { isTopLevel, atMaxDepth } = resolveAgentDepthState();
	const runId = process.env.BASECAMP_RUN_ID;
	const isDaemonSpawnedAgent = !isTopLevel && Boolean(runId);

	if (!isTopLevel && !isDaemonSpawnedAgent) {
		return;
	}

	if (isTopLevel && !atMaxDepth) {
		registerDaemonTools(pi, awaitDaemonConnection, {
			hasInvokedSkill: deps.hasInvokedSkill,
			getWorkspaceState: deps.getWorkspaceState,
			basecampExtensionRoot: deps.basecampExtensionRoot,
			resolveModelAlias: deps.resolveModelAlias,
		});
	}

	if (isDaemonSpawnedAgent && !atMaxDepth) {
		registerAskAgentTool(pi, awaitDaemonConnection, {
			hasInvokedSkill: deps.hasInvokedSkill,
			getWorkspaceState: deps.getWorkspaceState,
			basecampExtensionRoot: deps.basecampExtensionRoot,
			resolveModelAlias: deps.resolveModelAlias,
		});
		registerPeerMessageTools(pi, awaitDaemonConnection, {
			hasInvokedSkill: deps.hasInvokedSkill,
		});
		registerCancelAgentTool(pi, awaitDaemonConnection, {
			hasInvokedSkill: deps.hasInvokedSkill,
		});
	}

	const state = getDaemonClientState();
	const reporterConnection = isDaemonSpawnedAgent ? deferred<DaemonConnection>() : null;
	let sessionCtx: ExtensionContext | null = null;
	let connectionGeneration = 0;
	let activeAgentsWidget: ActiveAgentsWidgetController | null = null;

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
				registerPeerMessageDeliveryHandler(pi, state, activeConnection);
				if (isTopLevel && ctx.hasUI) {
					activeAgentsWidget?.stop();
					activeAgentsWidget = startActiveAgentsWidget(ctx, {
						rootId: deriveDaemonIdentity(ctx).node_id,
						socketPath: process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
						fetchSummary: fetchRunSummary,
					});
					activeConnection.onClose(() => {
						activeAgentsWidget?.stop();
						activeAgentsWidget = null;
					});
				}
				reporterConnection?.resolve(activeConnection);
			} catch (error) {
				if (generation !== connectionGeneration) return;
				const message = errorMessage(error);
				publishDaemonStatus(ctx, { kind: "unavailable", message });
				clearActiveAgentsWidget(ctx);
				reporterConnection?.reject(error);
				if (isTopLevel) {
					ctx.ui.notify(`basecamp swarm daemon unavailable: ${message}`, "warning");
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
		state.peerDeliveryUnsubscribe?.();
		state.peerDeliveryUnsubscribe = null;
		state.peerDeliveryConnection = null;
		activeAgentsWidget?.stop();
		activeAgentsWidget = null;
		if (ctx) {
			publishDaemonStatus(ctx, { kind: "idle" });
			clearActiveAgentsWidget(ctx);
		}
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
