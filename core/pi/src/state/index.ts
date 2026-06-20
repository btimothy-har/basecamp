import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";

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
	currentStateDir = stateDir;
	currentState = loadSessionState(sessionIdentityFromContext(ctx), stateDir);
	return currentState;
}

export function initializeCurrentSessionStateForEvent(
	event: SessionStartEvent,
	ctx: ExtensionContext,
	stateDir?: string,
): BasecampSessionState {
	if (event.reason !== "fork") return initializeCurrentSessionState(ctx, stateDir);

	currentStateDir = stateDir;
	const childState = createDefaultSessionState(sessionIdentityFromContext(ctx));
	const parentSessionFile = resolveParentSessionFile(event, ctx);
	const inheritedFields = parentSessionFile ? loadForkInheritedFields(parentSessionFile, stateDir) : null;
	currentState = saveSessionState({ ...childState, ...inheritedFields }, stateDir);
	return currentState;
}

export function getCurrentSessionState(): Readonly<BasecampSessionState> {
	if (!currentState) throw new Error("Basecamp session state is not initialized.");
	return currentState;
}

export function getCurrentSessionStateIfInitialized(): Readonly<BasecampSessionState> | null {
	return currentState;
}

export function updateCurrentSessionState(updater: SessionStateUpdater): BasecampSessionState {
	const existing = getCurrentSessionState();
	const patch = typeof updater === "function" ? updater(existing) : updater;
	currentState = saveSessionState({ ...existing, ...patch }, currentStateDir);
	return currentState;
}

export function updateCurrentSessionStateIfInitialized(updater: SessionStateUpdater): BasecampSessionState | null {
	if (!currentState) return null;
	return updateCurrentSessionState(updater);
}

export function resetCurrentSessionState(): void {
	currentState = null;
	currentStateDir = undefined;
}

export function registerState(pi: ExtensionAPI): void {
	pi.on("session_start", async (event, ctx) => {
		initializeCurrentSessionStateForEvent(event, ctx);
	});

	pi.on("session_shutdown", async () => {
		resetCurrentSessionState();
	});
}

export default registerState;
