import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

export const SESSION_STATE_VERSION = 1;
export const DEFAULT_SESSION_STATE_DIR = path.join(os.homedir(), ".pi", "session-state");
export const SESSION_STATE_AGENT_MODES = ["analysis", "planning", "supervisor", "executor"] as const;

export type SessionStateAgentMode = (typeof SESSION_STATE_AGENT_MODES)[number];

export interface SessionStateWorktree {
	kind: string;
	label: string;
	path: string;
	branch: string | null;
	created: boolean;
}

export interface SessionStateIdentity {
	sessionId: string;
	sessionFile?: string | null;
}

export interface BasecampSessionState {
	version: typeof SESSION_STATE_VERSION;
	sessionId: string;
	sessionFile: string | null;
	updatedAt: string;
	activeWorktree: SessionStateWorktree | null;
	agentMode: SessionStateAgentMode | null;
	title: string | null;
}

export type SessionStatePatch = Partial<
	Omit<BasecampSessionState, "version" | "sessionId" | "sessionFile" | "updatedAt">
>;
export type SessionStateUpdater = SessionStatePatch | ((state: Readonly<BasecampSessionState>) => SessionStatePatch);

let currentState: BasecampSessionState | null = null;
let currentStateDir: string | undefined;

function sessionStateFileName(sessionId: string): string {
	return `${sessionId.replace(/[^A-Za-z0-9_-]/g, "_")}.json`;
}

export function buildSessionStatePath(sessionId: string, stateDir = DEFAULT_SESSION_STATE_DIR): string {
	return path.join(stateDir, sessionStateFileName(sessionId));
}

export function createDefaultSessionState(identity: SessionStateIdentity): BasecampSessionState {
	return {
		version: SESSION_STATE_VERSION,
		sessionId: identity.sessionId,
		sessionFile: identity.sessionFile ?? null,
		updatedAt: new Date().toISOString(),
		activeWorktree: null,
		agentMode: null,
		title: null,
	};
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSessionStateWorktree(value: unknown): value is SessionStateWorktree {
	return (
		isRecord(value) &&
		typeof value.kind === "string" &&
		typeof value.label === "string" &&
		typeof value.path === "string" &&
		(typeof value.branch === "string" || value.branch === null) &&
		typeof value.created === "boolean"
	);
}

function isAgentMode(value: unknown): value is SessionStateAgentMode {
	return typeof value === "string" && SESSION_STATE_AGENT_MODES.includes(value as SessionStateAgentMode);
}

function isSessionState(value: unknown): value is BasecampSessionState {
	return (
		isRecord(value) &&
		value.version === SESSION_STATE_VERSION &&
		typeof value.sessionId === "string" &&
		(typeof value.sessionFile === "string" || value.sessionFile === null) &&
		typeof value.updatedAt === "string" &&
		(value.activeWorktree === null || isSessionStateWorktree(value.activeWorktree)) &&
		(value.agentMode === null || isAgentMode(value.agentMode)) &&
		(typeof value.title === "string" || value.title === null)
	);
}

export function loadSessionState(identity: SessionStateIdentity, stateDir?: string): BasecampSessionState {
	const defaults = createDefaultSessionState(identity);
	const expectedSessionFile = identity.sessionFile ?? null;

	try {
		const raw = fs.readFileSync(buildSessionStatePath(identity.sessionId, stateDir), "utf8");
		const parsed: unknown = JSON.parse(raw);
		if (!isSessionState(parsed)) return defaults;
		if (parsed.sessionId !== identity.sessionId) return defaults;
		if (parsed.sessionFile !== expectedSessionFile) return defaults;
		return parsed;
	} catch {
		return defaults;
	}
}

export function saveSessionState(state: BasecampSessionState, stateDir?: string): BasecampSessionState {
	const next: BasecampSessionState = {
		...state,
		version: SESSION_STATE_VERSION,
		updatedAt: new Date().toISOString(),
	};
	const filePath = buildSessionStatePath(next.sessionId, stateDir);
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	fs.writeFileSync(tmp, JSON.stringify(next, null, 2));
	fs.renameSync(tmp, filePath);
	return next;
}

function sessionIdentityFromContext(ctx: ExtensionContext): SessionStateIdentity {
	return {
		sessionId: ctx.sessionManager.getSessionId(),
		sessionFile: ctx.sessionManager.getSessionFile() ?? null,
	};
}

export function initializeCurrentSessionState(ctx: ExtensionContext, stateDir?: string): BasecampSessionState {
	currentStateDir = stateDir;
	currentState = loadSessionState(sessionIdentityFromContext(ctx), stateDir);
	return currentState;
}

export function getCurrentSessionState(): Readonly<BasecampSessionState> {
	if (!currentState) throw new Error("Basecamp session state is not initialized.");
	return currentState;
}

export function updateCurrentSessionState(updater: SessionStateUpdater): BasecampSessionState {
	const existing = getCurrentSessionState();
	const patch = typeof updater === "function" ? updater(existing) : updater;
	currentState = saveSessionState({ ...existing, ...patch }, currentStateDir);
	return currentState;
}

export function resetCurrentSessionState(): void {
	currentState = null;
	currentStateDir = undefined;
}

export function registerState(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		initializeCurrentSessionState(ctx);
	});

	pi.on("session_shutdown", async () => {
		resetCurrentSessionState();
	});
}

export default registerState;
