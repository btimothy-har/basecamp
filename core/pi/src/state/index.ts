import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { basecampCorePaths } from "../platform/paths.ts";

export const SESSION_STATE_VERSION = 1;

export function defaultSessionStateDir(homeDir = os.homedir()): string {
	return basecampCorePaths(homeDir).sessionStateDir;
}

export const DEFAULT_SESSION_STATE_DIR = defaultSessionStateDir();
export const SESSION_STATE_AGENT_MODES = ["analysis", "planning", "copilot", "supervisor", "executor"] as const;

export type SessionStateAgentMode = (typeof SESSION_STATE_AGENT_MODES)[number];

export interface SessionStateWorktree {
	kind: string;
	label: string;
	path: string;
	branch: string | null;
	created: boolean;
}

export interface SessionStateActiveWorktree {
	// Guard the nested worktree schema separately from the outer session-state document.
	version: 1;
	repoName: string;
	repoRoot: string;
	remoteUrl: string | null;
	worktree: SessionStateWorktree;
	updatedAt: string;
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
	activeWorktree: SessionStateActiveWorktree | null;
	agentMode: SessionStateAgentMode | null;
	title: string | null;
}

export type SessionStatePatch = Partial<
	Omit<BasecampSessionState, "version" | "sessionId" | "sessionFile" | "updatedAt">
>;
export type SessionStateUpdater = SessionStatePatch | ((state: Readonly<BasecampSessionState>) => SessionStatePatch);
export type SessionTitleChangeListener = (title: string | null, state: Readonly<BasecampSessionState>) => void;

// Process-scoped via globalThis so `/reload` preserves a single shared
// session-state instance. Extensions are re-imported with fresh module
// instances on reload (and each extension may receive its own instance of
// this module), so module-level state would not be shared across consumers.
const sessionStateKey = Symbol.for("basecamp.sessionState");

interface SessionStateRuntime {
	current: BasecampSessionState | null;
	stateDir: string | undefined;
	titleListeners: Set<SessionTitleChangeListener>;
}

type GlobalWithSessionState = typeof globalThis & {
	[sessionStateKey]?: SessionStateRuntime;
};

function getSessionStateRuntime(): SessionStateRuntime {
	const globalObject = globalThis as GlobalWithSessionState;
	globalObject[sessionStateKey] ??= { current: null, stateDir: undefined, titleListeners: new Set() };
	globalObject[sessionStateKey].titleListeners ??= new Set();
	return globalObject[sessionStateKey];
}

function sessionStateFileName(sessionId: string): string {
	return `${sessionId.replace(/[^A-Za-z0-9_-]/g, "_")}.json`;
}

export function buildSessionStatePath(sessionId: string, stateDir = defaultSessionStateDir()): string {
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

function isSessionStateActiveWorktree(value: unknown): value is SessionStateActiveWorktree {
	return (
		isRecord(value) &&
		value.version === 1 &&
		typeof value.repoName === "string" &&
		typeof value.repoRoot === "string" &&
		(typeof value.remoteUrl === "string" || value.remoteUrl === null) &&
		isSessionStateWorktree(value.worktree) &&
		typeof value.updatedAt === "string"
	);
}

function isSessionState(value: unknown): value is BasecampSessionState {
	return (
		isRecord(value) &&
		value.version === SESSION_STATE_VERSION &&
		typeof value.sessionId === "string" &&
		(typeof value.sessionFile === "string" || value.sessionFile === null) &&
		typeof value.updatedAt === "string" &&
		(value.activeWorktree === null || isSessionStateActiveWorktree(value.activeWorktree)) &&
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
		return {
			version: SESSION_STATE_VERSION,
			sessionId: parsed.sessionId,
			sessionFile: parsed.sessionFile,
			updatedAt: parsed.updatedAt,
			activeWorktree: parsed.activeWorktree ?? null,
			agentMode: parsed.agentMode ?? null,
			title: parsed.title ?? null,
		};
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

function readFirstJsonlLine(filePath: string): string | null {
	// Transcripts can be large; read only until the header newline instead of loading the whole file.
	let fd: number | null = null;
	try {
		fd = fs.openSync(filePath, "r");
		const buffer = Buffer.alloc(4096);
		const chunks: string[] = [];
		let totalBytes = 0;
		const maxHeaderBytes = 64 * 1024;

		while (totalBytes < maxHeaderBytes) {
			const bytesRead = fs.readSync(fd, buffer, 0, Math.min(buffer.length, maxHeaderBytes - totalBytes), null);
			if (bytesRead === 0) break;

			const chunk = buffer.subarray(0, bytesRead).toString("utf8");
			const newlineIndex = chunk.indexOf("\n");
			if (newlineIndex >= 0) {
				chunks.push(chunk.slice(0, newlineIndex));
				return chunks.join("");
			}

			chunks.push(chunk);
			totalBytes += bytesRead;
		}

		return chunks.length > 0 ? chunks.join("") : null;
	} catch {
		return null;
	} finally {
		if (fd !== null) fs.closeSync(fd);
	}
}

export function readSessionIdFromTranscriptHeader(sessionFile: string): string | null {
	const line = readFirstJsonlLine(sessionFile);
	if (!line) return null;

	try {
		const parsed: unknown = JSON.parse(line);
		if (!isRecord(parsed)) return null;
		if (parsed.type !== "session") return null;
		return typeof parsed.id === "string" ? parsed.id : null;
	} catch {
		return null;
	}
}

function getParentSessionFileFromHeader(ctx: ExtensionContext): string | null {
	try {
		const parentSession = ctx.sessionManager.getHeader()?.parentSession;
		return typeof parentSession === "string" && parentSession.length > 0 ? parentSession : null;
	} catch {
		return null;
	}
}

function resolveParentSessionFile(event: SessionStartEvent, ctx: ExtensionContext): string | null {
	if (typeof event.previousSessionFile === "string" && event.previousSessionFile.length > 0) {
		return event.previousSessionFile;
	}
	return getParentSessionFileFromHeader(ctx);
}

function loadForkInheritedFields(
	parentSessionFile: string,
	stateDir?: string,
): Pick<BasecampSessionState, "activeWorktree" | "agentMode" | "title"> | null {
	const parentSessionId = readSessionIdFromTranscriptHeader(parentSessionFile);
	if (!parentSessionId) return null;

	const parentState = loadSessionState({ sessionId: parentSessionId, sessionFile: parentSessionFile }, stateDir);
	return {
		activeWorktree: parentState.activeWorktree
			? { ...parentState.activeWorktree, worktree: { ...parentState.activeWorktree.worktree } }
			: null,
		agentMode: parentState.agentMode,
		title: parentState.title,
	};
}

export function initializeCurrentSessionState(ctx: ExtensionContext, stateDir?: string): BasecampSessionState {
	const runtime = getSessionStateRuntime();
	runtime.stateDir = stateDir;
	runtime.current = loadSessionState(sessionIdentityFromContext(ctx), stateDir);
	return runtime.current;
}

export function initializeCurrentSessionStateForEvent(
	event: SessionStartEvent,
	ctx: ExtensionContext,
	stateDir?: string,
): BasecampSessionState {
	if (event.reason !== "fork") return initializeCurrentSessionState(ctx, stateDir);

	const runtime = getSessionStateRuntime();
	runtime.stateDir = stateDir;
	const childState = createDefaultSessionState(sessionIdentityFromContext(ctx));
	const parentSessionFile = resolveParentSessionFile(event, ctx);
	const inheritedFields = parentSessionFile ? loadForkInheritedFields(parentSessionFile, stateDir) : null;
	runtime.current = saveSessionState({ ...childState, ...inheritedFields }, stateDir);
	return runtime.current;
}

/**
 * Initialize session state for `event` if it is not already initialized for the
 * current session, otherwise return the existing state. This makes consumers
 * that read session state during their own `session_start` handler independent
 * of cross-extension handler ordering: whichever handler runs first performs
 * the (identical, event-aware) initialization, and later callers reuse it.
 */
export function ensureCurrentSessionStateForEvent(
	event: SessionStartEvent,
	ctx: ExtensionContext,
	stateDir?: string,
): BasecampSessionState {
	const { current } = getSessionStateRuntime();
	const identity = sessionIdentityFromContext(ctx);
	if (
		current &&
		current.sessionId === identity.sessionId &&
		(current.sessionFile ?? null) === (identity.sessionFile ?? null)
	) {
		return current;
	}
	return initializeCurrentSessionStateForEvent(event, ctx, stateDir);
}

export function getCurrentSessionState(): Readonly<BasecampSessionState> {
	const { current } = getSessionStateRuntime();
	if (!current) throw new Error("Basecamp session state is not initialized.");
	return current;
}

export function getCurrentSessionStateIfInitialized(): Readonly<BasecampSessionState> | null {
	return getSessionStateRuntime().current;
}

function notifyTitleChange(state: BasecampSessionState): void {
	for (const listener of getSessionStateRuntime().titleListeners) {
		try {
			listener(state.title, state);
		} catch {
			// best effort
		}
	}
}

export function onCurrentSessionTitleChange(listener: SessionTitleChangeListener): () => void {
	const runtime = getSessionStateRuntime();
	runtime.titleListeners.add(listener);
	return () => {
		runtime.titleListeners.delete(listener);
	};
}

export function updateCurrentSessionState(updater: SessionStateUpdater): BasecampSessionState {
	const runtime = getSessionStateRuntime();
	const existing = getCurrentSessionState();
	const previousTitle = existing.title;
	const patch = typeof updater === "function" ? updater(existing) : updater;
	runtime.current = saveSessionState({ ...existing, ...patch }, runtime.stateDir);
	if (runtime.current.title !== previousTitle) notifyTitleChange(runtime.current);
	return runtime.current;
}

export function updateCurrentSessionStateIfInitialized(updater: SessionStateUpdater): BasecampSessionState | null {
	if (!getSessionStateRuntime().current) return null;
	return updateCurrentSessionState(updater);
}

export function resetCurrentSessionState(): void {
	const runtime = getSessionStateRuntime();
	runtime.current = null;
	runtime.stateDir = undefined;
}

export function registerState(pi: ExtensionAPI): void {
	pi.on("session_start", async (event, ctx) => {
		ensureCurrentSessionStateForEvent(event, ctx);
	});

	pi.on("session_shutdown", async () => {
		resetCurrentSessionState();
	});
}

export default registerState;
