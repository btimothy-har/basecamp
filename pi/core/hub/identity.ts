import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getAgentMode } from "../agent-mode/index.ts";
import { resolveAgentRoleOverride } from "../agent-role.ts";
import { shortSessionId as defaultShortSessionId } from "../session/session-id.ts";
import { formatTitle } from "../ui/index.ts";
import type { DaemonIdentity } from "./connection.ts";
import { buildDeterministicAgentHandle } from "./handles.ts";

/**
 * Node-identity derivation for the hub connection:
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

/** Host-session surfaces the identity derivation needs (injectable for tests). */
export interface DaemonIdentityDeps {
	formatTitle: (title: string, tag: string) => string;
	shortSessionId: (sessionId: string) => string;
}

export function defaultIdentityDeps(): DaemonIdentityDeps {
	return { formatTitle, shortSessionId: defaultShortSessionId };
}

/** Truncate + strip control characters from a display label; null when empty. */
export function sanitizeDisplayLabel(value: string | null | undefined, maxLength: number): string | null {
	const withoutControls = Array.from(value ?? "", (char) => {
		const code = char.charCodeAt(0);
		return code <= 31 || code === 127 ? " " : char;
	}).join("");
	const sanitized = withoutControls.replace(/\s+/g, " ").trim();
	if (!sanitized) return null;
	return sanitized.length <= maxLength ? sanitized : `${sanitized.slice(0, maxLength - 1).trimEnd()}…`;
}

export function deriveDaemonIdentity(ctx: ExtensionContext, deps?: Partial<DaemonIdentityDeps>): DaemonIdentity {
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

export function resolveDaemonAgentTitle(ctx: ExtensionContext, deps: DaemonIdentityDeps): string | null {
	const base = process.env.BASECAMP_AGENT_TITLE?.trim();
	if (!base) return null;
	return deps.formatTitle(base, deps.shortSessionId(ctx.sessionManager.getSessionId()));
}
