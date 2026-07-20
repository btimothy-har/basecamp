/** Session-state file persistence: path building, schema guards, load/save. */

import * as fs from "node:fs";
import * as path from "node:path";
import { isRecord, writeJsonFileAtomic } from "../../host/files.ts";
import {
	type BasecampSessionState,
	defaultSessionStateDir,
	SESSION_STATE_AGENT_MODES,
	SESSION_STATE_VERSION,
	type SessionStateActiveWorktree,
	type SessionStateAgentMode,
	type SessionStateIdentity,
	type SessionStateWorktree,
} from "./model.ts";

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
		// Tolerate any string agentMode here; a retired mode (e.g. legacy "executor"/"supervisor")
		// is coerced to null on load rather than invalidating the whole document.
		(value.agentMode === null || typeof value.agentMode === "string") &&
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
			// Retired modes fall back to the default (null → DEFAULT_AGENT_MODE on restore).
			agentMode: isAgentMode(parsed.agentMode) ? parsed.agentMode : null,
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
	writeJsonFileAtomic(filePath, next);
	return next;
}
