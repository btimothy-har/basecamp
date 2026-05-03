import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { UserBashEvent, UserBashEventResult } from "@mariozechner/pi-coding-agent";
import type { WorkspaceState as BasecampWorkspaceState } from "../../platform/workspace.ts";
import { registerWorkspaceGuards } from "../src/guards.ts";

interface GuardEvent {
	type: "tool_call";
	toolCallId: string;
	toolName: string;
	input: { path?: string; command?: string };
}

type GuardResult = { block?: boolean; reason?: string } | undefined;
type GuardHandler = (event: GuardEvent) => GuardResult | Promise<GuardResult>;
type UserBashHandler = (
	event: UserBashEvent,
) => UserBashEventResult | Promise<UserBashEventResult | undefined> | undefined;

const REPO_ROOT = "/repo";
const WORKTREE_DIR = "/worktrees/repo/feature";
const ALLOWED_ROOT = "/allowed";

function baseWorkspaceState(overrides: Partial<BasecampWorkspaceState> = {}): BasecampWorkspaceState {
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

function activeWorktreeState(overrides: Partial<BasecampWorkspaceState> = {}): BasecampWorkspaceState {
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

function createGuards(
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

function createGuard(state: BasecampWorkspaceState, allowedRoots: string[] = []): GuardHandler {
	return createGuards(state, allowedRoots).toolCall;
}

async function runToolCallGuard(
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

async function runGuard(
	state: BasecampWorkspaceState,
	toolName: string,
	inputPath: string,
	allowedRoots: string[] = [],
): Promise<{ event: GuardEvent; result: GuardResult }> {
	return runToolCallGuard(state, toolName, { path: inputPath }, allowedRoots);
}

describe("worktree guards bash cwd", () => {
	it("prefixes bash tool calls with the effective cwd when a worktree is active", async () => {
		const { event, result } = await runToolCallGuard(activeWorktreeState(), "bash", { command: "pwd" });

		assert.equal(result, undefined);
		assert.equal(event.input.command, `cd '${WORKTREE_DIR}' && pwd`);
	});

	it("leaves bash tool calls unchanged when no worktree is active", async () => {
		const { event, result } = await runToolCallGuard(baseWorkspaceState(), "bash", { command: "pwd" });

		assert.equal(result, undefined);
		assert.equal(event.input.command, "pwd");
	});

	it("does not double-prefix unquoted cd commands", async () => {
		const command = `cd ${WORKTREE_DIR} && pwd`;
		const { event, result } = await runToolCallGuard(activeWorktreeState(), "bash", { command });

		assert.equal(result, undefined);
		assert.equal(event.input.command, command);
	});

	it("does not double-prefix quoted cd commands", async () => {
		const command = `cd '${WORKTREE_DIR}' && pwd`;
		const { event, result } = await runToolCallGuard(activeWorktreeState(), "bash", { command });

		assert.equal(result, undefined);
		assert.equal(event.input.command, command);
	});

	it("shell-quotes effective cwd paths with spaces and single quotes", async () => {
		const effectiveCwd = "/tmp/pi/work tree/it's feature";
		const { event, result } = await runToolCallGuard(
			activeWorktreeState({
				effectiveCwd,
				executionTarget: {
					kind: "git-worktree",
					label: "it's feature",
					path: effectiveCwd,
					branch: "bh/its-feature",
					created: false,
				},
			}),
			"bash",
			{ command: "pwd" },
		);

		assert.equal(result, undefined);
		assert.equal(event.input.command, "cd '/tmp/pi/work tree/it'\\''s feature' && pwd");
	});
});

describe("worktree guards optional path cwd", () => {
	for (const toolName of ["grep", "find", "ls"]) {
		it(`sets omitted ${toolName} path to effective cwd when a worktree is active`, async () => {
			const { event, result } = await runToolCallGuard(activeWorktreeState(), toolName, {});

			assert.equal(result, undefined);
			assert.equal(event.input.path, WORKTREE_DIR);
		});

		it(`does not set omitted ${toolName} path when no worktree is active`, async () => {
			const { event, result } = await runToolCallGuard(baseWorkspaceState(), toolName, {});

			assert.equal(result, undefined);
			assert.equal(event.input.path, undefined);
			assert.equal("path" in event.input, false);
		});

		it(`does not overwrite an existing ${toolName} path with effective cwd`, async () => {
			const inputPath = path.join(WORKTREE_DIR, "src");
			const { event, result } = await runToolCallGuard(activeWorktreeState(), toolName, { path: inputPath });

			assert.equal(result, undefined);
			assert.equal(event.input.path, inputPath);
		});
	}
});

describe("worktree guards user bash cwd", () => {
	it("executes user bash commands from the effective cwd", async () => {
		const tempRoot = await fs.mkdtemp(path.join(await fs.realpath(os.tmpdir()), "basecamp-guards-"));
		try {
			const repoRoot = path.join(tempRoot, "repo");
			const effectiveCwd = path.join(tempRoot, "worktree");
			await fs.mkdir(repoRoot);
			await fs.mkdir(effectiveCwd);

			const { userBash } = createGuards(
				activeWorktreeState({
					launchCwd: repoRoot,
					effectiveCwd,
					protectedRoot: repoRoot,
					repo: {
						isRepo: true,
						name: "repo",
						root: repoRoot,
						remoteUrl: "git@github.com:test/repo.git",
					},
					executionTarget: {
						kind: "git-worktree",
						label: "feature",
						path: effectiveCwd,
						branch: "bh/feature",
						created: false,
					},
				}),
			);
			const result = await userBash({ type: "user_bash", command: "pwd", excludeFromContext: false, cwd: repoRoot });

			assert.ok(result?.operations, "user_bash should return bash operations for an active worktree");

			let output = "";
			const execResult = await result.operations.exec("pwd", repoRoot, {
				onData: (data) => {
					output += data.toString();
				},
				timeout: 5_000,
			});

			assert.equal(execResult.exitCode, 0);
			assert.equal(output.trim(), effectiveCwd);
		} finally {
			await fs.rm(tempRoot, { recursive: true, force: true });
		}
	});
});

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
