/** Session-state document model: schema types, agent modes, state-dir defaults. */

import * as os from "node:os";
import { basecampCorePaths } from "../../host/paths.ts";

export const SESSION_STATE_VERSION = 1;

export function defaultSessionStateDir(homeDir = os.homedir()): string {
	return basecampCorePaths(homeDir).sessionStateDir;
}

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
