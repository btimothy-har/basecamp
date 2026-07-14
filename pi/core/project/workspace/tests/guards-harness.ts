import assert from "node:assert/strict";
import type { UserBashEvent, UserBashEventResult } from "@earendil-works/pi-coding-agent";
import { registerWorkspaceGuards } from "../guards.ts";
import type { WorkspaceState as BasecampWorkspaceState } from "../state.ts";

export interface GuardEvent {
	type: "tool_call";
	toolCallId: string;
	toolName: string;
	input: { path?: string; command?: string };
}

export type GuardResult = { block?: boolean; reason?: string } | undefined;
export type GuardHandler = (event: GuardEvent) => GuardResult | Promise<GuardResult>;
export type UserBashHandler = (
	event: UserBashEvent,
) => UserBashEventResult | Promise<UserBashEventResult | undefined> | undefined;

export const REPO_ROOT = "/repo";
export const WORKTREE_DIR = "/worktrees/repo/feature";
export const ALLOWED_ROOT = "/allowed";

export function baseWorkspaceState(overrides: Partial<BasecampWorkspaceState> = {}): BasecampWorkspaceState {
	return {
		launchCwd: REPO_ROOT,
		effectiveCwd: REPO_ROOT,
		scratchDir: "/tmp/pi/repo",
		repo: {
			isRepo: true,
			name: "repo",
			root: REPO_ROOT,
			remoteUrl: "git@github.com:test/repo.git",
		},
		protectedRoot: REPO_ROOT,
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	};
}

export function activeWorktreeState(overrides: Partial<BasecampWorkspaceState> = {}): BasecampWorkspaceState {
	return baseWorkspaceState({
		launchCwd: REPO_ROOT,
		effectiveCwd: WORKTREE_DIR,
		activeWorktree: {
			kind: "git-worktree",
			label: "feature",
			path: WORKTREE_DIR,
			branch: "bh/feature",
			created: false,
		},
		...overrides,
	});
}

export function createGuards(
	state: BasecampWorkspaceState,
	allowedRoots: string[] = [],
): { toolCall: GuardHandler; userBash: UserBashHandler } {
	let toolCallHandler: GuardHandler | null = null;
	let userBashHandler: UserBashHandler | null = null;

	registerWorkspaceGuards(
		{
			on(name: string, fn: GuardHandler | UserBashHandler) {
				if (name === "tool_call") toolCallHandler = fn as GuardHandler;
				if (name === "user_bash") userBashHandler = fn as UserBashHandler;
			},
		} as never,
		{
			getState: () => state,
			getAllowedRoots: () => allowedRoots,
		},
	);

	assert.ok(toolCallHandler, "tool_call guard should be registered");
	assert.ok(userBashHandler, "user_bash guard should be registered");
	return { toolCall: toolCallHandler, userBash: userBashHandler };
}

export function createGuard(state: BasecampWorkspaceState, allowedRoots: string[] = []): GuardHandler {
	return createGuards(state, allowedRoots).toolCall;
}

export async function runToolCallGuard(
	state: BasecampWorkspaceState,
	toolName: string,
	input: GuardEvent["input"],
	allowedRoots: string[] = [],
): Promise<{ event: GuardEvent; result: GuardResult }> {
	const event: GuardEvent = {
		type: "tool_call",
		toolCallId: "tool-1",
		toolName,
		input,
	};
	const result = await createGuard(state, allowedRoots)(event);
	return { event, result };
}

export async function runGuard(
	state: BasecampWorkspaceState,
	toolName: string,
	inputPath: string,
	allowedRoots: string[] = [],
): Promise<{ event: GuardEvent; result: GuardResult }> {
	return runToolCallGuard(state, toolName, { path: inputPath }, allowedRoots);
}
