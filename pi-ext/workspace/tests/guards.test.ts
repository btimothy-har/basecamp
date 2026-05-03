import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { WorkspaceState } from "../../platform/workspace.ts";
import { registerWorkspaceGuards } from "../src/guards.ts";

interface GuardEvent {
	type: "tool_call";
	toolCallId: string;
	toolName: string;
	input: { path?: string; command?: string };
}

type GuardResult = { block?: boolean; reason?: string } | undefined;
type GuardHandler = (event: GuardEvent) => GuardResult | Promise<GuardResult>;

const REPO_ROOT = "/repo";
const WORKTREE_DIR = "/worktrees/repo/feature";
const ALLOWED_ROOT = "/allowed";

function baseWorkspaceState(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
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
		executionTarget: null,
		unsafeEdit: false,
		...overrides,
	};
}

function activeWorktreeState(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return baseWorkspaceState({
		launchCwd: REPO_ROOT,
		effectiveCwd: WORKTREE_DIR,
		executionTarget: {
			kind: "git-worktree",
			label: "feature",
			path: WORKTREE_DIR,
			branch: "bh/feature",
			created: false,
		},
		...overrides,
	});
}

function createGuard(state: WorkspaceState, allowedRoots: string[] = []): GuardHandler {
	let handler: GuardHandler | null = null;

	registerWorkspaceGuards(
		{
			on(name: string, fn: GuardHandler) {
				if (name === "tool_call") handler = fn;
			},
		} as never,
		{
			getState: () => state,
			getAllowedRoots: () => allowedRoots,
		},
	);

	assert.ok(handler, "tool_call guard should be registered");
	return handler;
}

async function runGuard(
	state: WorkspaceState,
	toolName: string,
	inputPath: string,
	allowedRoots: string[] = [],
): Promise<{ event: GuardEvent; result: GuardResult }> {
	const event: GuardEvent = {
		type: "tool_call",
		toolCallId: "tool-1",
		toolName,
		input: { path: inputPath },
	};
	const result = await createGuard(state, allowedRoots)(event);
	return { event, result };
}

describe("worktree guards unsafe-edit", () => {
	it("blocks protected checkout edit by default without worktree", async () => {
		const { result } = await runGuard(baseWorkspaceState(), "edit", "file.ts");

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("allows protected checkout edit without worktree when unsafe-edit is active", async () => {
		const { result } = await runGuard(baseWorkspaceState({ unsafeEdit: true }), "edit", "file.ts");

		assert.equal(result, undefined);
	});

	it("allows absolute protected checkout edit with active worktree when unsafe-edit is active", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"write",
			path.join(REPO_ROOT, "file.ts"),
		);

		assert.equal(result, undefined);
	});

	it("blocks relative protected checkout edits with active worktree", async () => {
		const relativeProtectedPath = path.relative(WORKTREE_DIR, path.join(REPO_ROOT, "file.ts"));
		const { result } = await runGuard(activeWorktreeState({ unsafeEdit: true }), "edit", relativeProtectedPath);

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("still blocks relative paths that escape the active worktree", async () => {
		const { result } = await runGuard(activeWorktreeState({ unsafeEdit: true }), "edit", "../outside.ts");

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /escapes the active worktree/);
	});

	it("allows paths under allowed roots to bypass active worktree confinement", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"edit",
			path.join(ALLOWED_ROOT, "outside.ts"),
			[ALLOWED_ROOT],
		);

		assert.equal(result, undefined);
	});

	it("does not allow allowed roots to bypass protected checkout checks", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"read",
			path.join(REPO_ROOT, "file.ts"),
			[REPO_ROOT],
		);

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("does not allow read tools to target protected checkout with active worktree", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"read",
			path.join(REPO_ROOT, "file.ts"),
		);

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("continues to retarget relative worktree edits", async () => {
		const { event, result } = await runGuard(activeWorktreeState({ unsafeEdit: true }), "edit", "src/file.ts");

		assert.equal(result, undefined);
		assert.equal(event.input.path, path.join(WORKTREE_DIR, "src/file.ts"));
	});
});
