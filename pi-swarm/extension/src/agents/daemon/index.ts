import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerAgentIdentityProvider } from "pi-core/platform/agent-identity.ts";
import { resolveSessionProductRoleOverride } from "pi-core/platform/product-role.ts";
import { getAgentMode } from "pi-core/session/agent-mode.ts";
import { shortSessionId as defaultShortSessionId } from "pi-core/session/session-id.ts";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import { errorMessage } from "../errors.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "../types.ts";
import { connect, type DaemonConnection, type DaemonIdentity, ensureDaemon, fetchRunSummary } from "./client.ts";
import { type PeerMessageDeliveryFrame, PROTOCOL_VERSION } from "./frames.ts";
import { buildDeterministicAgentHandle } from "./handles.ts";
import { resolveDaemonPaths } from "./paths.ts";
import { registerDaemonReporter } from "./reporter.ts";
import { registerAskAgentTool, registerDaemonTools, registerPeerMessageTools } from "./tools.ts";
import { type ActiveAgentsWidgetController, clearActiveAgentsWidget, startActiveAgentsWidget } from "./widget.ts";

type ThemeFg = (color: Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

interface DaemonClientState {
	connection: DaemonConnection | null;
	connecting: Promise<void> | null;
	peerDeliveryConnection?: DaemonConnection | null;
	peerDeliveryUnsubscribe?: (() => void) | null;
}

type DaemonStatusKind = "idle" | "starting" | "connected" | "unavailable" | "disconnected";

export interface DaemonStatusInfo {
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

export function previewDaemonMessage(message: string | undefined): string | null {
	const sanitized = message?.replace(/[\r\n\t]/g, " ").trim();
	if (!sanitized) return null;
	if (sanitized.length <= DAEMON_MESSAGE_TRUNCATE_LENGTH) return sanitized;
	return `${sanitized.slice(0, DAEMON_MESSAGE_TRUNCATE_LENGTH - 1)}…`;
}

export function renderDaemonStatus(fg: ThemeFg, status: DaemonStatusInfo): string {
	if (status.kind === "connected") return fg("success", "swarm ✓");
	if (status.kind === "starting") return `${fg("warning", "swarm …")} ${fg("dim", "starting")}`;
	if (status.kind === "disconnected") return `${fg("warning", "swarm ⚠")} ${fg("dim", "disconnected")}`;
	if (status.kind === "unavailable") {
		const message = previewDaemonMessage(status.message);
		return message ? `${fg("error", "swarm ✗")} ${fg("error", message)}` : fg("error", "swarm ✗ unavailable");
	}
	return fg("muted", "swarm idle");
}

export function publishDaemonStatus(ctx: ExtensionContext, status: DaemonStatusInfo): void {
	if (!ctx.hasUI) return;
	const fg: ThemeFg = (color, text) => ctx.ui.theme.fg(color, text);
	ctx.ui.setStatus(DAEMON_STATUS_ID, renderDaemonStatus(fg, status));
}

export function getActiveDaemonConnection(): DaemonConnection | null {
	return getDaemonClientState().connection;
}

export function formatPeerMessageDeliveryContent(frame: PeerMessageDeliveryFrame): string {
	const sender = sanitizeDisplayLabel(frame.from_handle, 80) ?? "a peer";
	const label = sanitizeDisplayLabel(frame.from_product_role, 48) ?? relationDisplayLabel(frame.from_relation);
	const suffix = label ? ` (${label})` : "";
	return `Message from ${sender}${suffix}:\n\n${frame.message}`;
}

function sanitizeDisplayLabel(value: string | null | undefined, maxLength: number): string | null {
	const withoutControls = Array.from(value ?? "", (char) => {
		const code = char.charCodeAt(0);
		return code <= 31 || code === 127 ? " " : char;
	}).join("");
	const sanitized = withoutControls.replace(/\s+/g, " ").trim();
	if (!sanitized) return null;
	return sanitized.length <= maxLength ? sanitized : `${sanitized.slice(0, maxLength - 1).trimEnd()}…`;
}

function relationDisplayLabel(relation: PeerMessageDeliveryFrame["from_relation"]): string | null {
	return relation === "unknown" ? null : relation;
}

export function handlePeerMessageDelivery(
	pi: Pick<ExtensionAPI, "sendUserMessage">,
	connection: Pick<DaemonConnection, "send">,
	frame: PeerMessageDeliveryFrame,
): void {
	const deliverAs = frame.interrupt ? "steer" : "followUp";
	let delivery: ReturnType<ExtensionAPI["sendUserMessage"]>;
	try {
		delivery = pi.sendUserMessage(formatPeerMessageDeliveryContent(frame), { deliverAs });
	} catch (error) {
		try {
			connection.send({
				type: "peer_message_delivery_ack",
				v: PROTOCOL_VERSION,
				message_id: frame.message_id,
				status: "failed",
				error: errorMessage(error),
			});
		} catch {
			// Transport failure prevents reporting the failed scheduling attempt; delivery status should not be inferred here.
		}
		return;
	}

	try {
		connection.send({
			type: "peer_message_delivery_ack",
			v: PROTOCOL_VERSION,
			message_id: frame.message_id,
			status: "queued",
		});
	} catch {
		// sendUserMessage already accepted the delivery; do not convert an ack transport failure into delivery failure.
	}
	void Promise.resolve(delivery).catch(() => {
		// Delivery has already been accepted by Pi; avoid unhandled rejections without overwriting queued status.
	});
}

function registerPeerMessageDeliveryHandler(
	pi: Pick<ExtensionAPI, "sendUserMessage">,
	state: DaemonClientState,
	connection: DaemonConnection,
): void {
	state.peerDeliveryUnsubscribe?.();
	state.peerDeliveryUnsubscribe = connection.on("peer_message_delivery", (frame) => {
		handlePeerMessageDelivery(pi, connection, frame);
	});
	state.peerDeliveryConnection = connection;
	connection.onClose(() => {
		if (state.peerDeliveryConnection === connection) {
			state.peerDeliveryUnsubscribe = null;
			state.peerDeliveryConnection = null;
		}
	});
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
 * - agent_handle = spawned agents use BASECAMP_AGENT_HANDLE; top-level sessions always derive a
 *   deterministic adjective-noun-hash from node_id so the session handle is stable across reload/resume
 * - session_name = BASECAMP_AGENT_TITLE (+ session-id suffix) ?? BASECAMP_SESSION_NAME ?? node_id
 * - cwd = process.cwd()
 * - session_file = ctx.sessionManager.getSessionFile() when available
 */
export function deriveDaemonIdentity(
	ctx: ExtensionContext,
	deps?: Pick<PiSwarmDependencies, "formatTitle" | "shortSessionId">,
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
		product_role: resolveProductRole(role),
	};
}

function resolveProductRole(role: "session" | "agent"): string | null {
	if (role !== "session") return null;
	const providerOverride = sanitizeDisplayLabel(resolveSessionProductRoleOverride(), 64);
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

export function registerDaemonClient(pi: ExtensionAPI, deps: PiSwarmDependencies): void {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const runId = process.env.BASECAMP_RUN_ID;
	const isTopLevel = Number.isFinite(depth) ? depth <= 0 : true;
	const isDaemonSpawnedAgent = !isTopLevel && Boolean(runId);
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	const atMaxDepth = depth >= maxDepth;

	// Expose this session's public daemon handle so consumers (e.g. pi-tasks workstream startup)
	// can bind the running session to a launch record. Pure derivation from ctx; safe for any session.
	registerAgentIdentityProvider({
		// The seam's ExtensionContext originates from pi-core's bundled types; only sessionManager/env
		// are read for handle derivation, so bridging the structurally-compatible context is safe.
		deriveHandle: (identityCtx) => deriveDaemonIdentity(identityCtx as unknown as ExtensionContext, deps).agent_handle,
	});

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
