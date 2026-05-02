import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { SessionState } from "../../platform/config.ts";
import { registerWorktreeGuards } from "../src/runtime/worktree.ts";

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

function baseSessionState(overrides: Partial<SessionState> = {}): SessionState {
	return {
		projectName: "test-project",
		project: null,
		launchCwd: REPO_ROOT,
		repoRoot: REPO_ROOT,
		additionalDirs: [],
		repoName: "repo",
		isRepo: true,
		remoteUrl: "git@github.com:test/repo.git",
		scratchDir: "/tmp/pi/repo",
		workingStyle: "engineering",
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
		contextContent: null,
		projectWarnings: [],
		unsafeEdit: false,
		...overrides,
	};
}

function activeWorktreeState(overrides: Partial<SessionState> = {}): SessionState {
	return baseSessionState({
		launchCwd: REPO_ROOT,
		worktreeDir: WORKTREE_DIR,
		worktreeLabel: "feature",
		worktreeBranch: "bh/feature",
		...overrides,
	});
}

function createGuard(state: SessionState): GuardHandler {
	let handler: GuardHandler | null = null;

	registerWorktreeGuards(
		{
			on(name: string, fn: GuardHandler) {
				if (name === "tool_call") handler = fn;
			},
		} as never,
		() => state,
	);

	assert.ok(handler, "tool_call guard should be registered");
	return handler;
}

async function runGuard(
	state: SessionState,
	toolName: string,
	inputPath: string,
): Promise<{ event: GuardEvent; result: GuardResult }> {
	const event: GuardEvent = {
		type: "tool_call",
		toolCallId: "tool-1",
		toolName,
		input: { path: inputPath },
	};
	const result = await createGuard(state)(event);
	return { event, result };
}

describe("worktree guards unsafe-edit", () => {
	it("blocks protected checkout edit by default without worktree", async () => {
		const { result } = await runGuard(baseSessionState(), "edit", "file.ts");

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("allows protected checkout edit without worktree when unsafe-edit is active", async () => {
		const { result } = await runGuard(baseSessionState({ unsafeEdit: true }), "edit", "file.ts");

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
