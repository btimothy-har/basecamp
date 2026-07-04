import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	buildHerdrWorkstreamOpenArgs,
	HERDR_WORKSTREAM_OPEN_TIMEOUT_MS,
	type HerdrWorkstreamEnv,
	type HerdrWorkstreamWorkspaceInput,
	type HerdrWorkstreamWorktreeInput,
	openWorkstreamInHerdr,
	shouldOpenWorkstreamInHerdr,
} from "../workstreams/herdr.ts";

interface ExecResult {
	code: number;
	stdout: string;
	stderr: string;
	killed: boolean;
}

interface ExecCall {
	command: string;
	args: string[];
	options?: { timeout?: number };
}

interface MockPi {
	execCalls: ExecCall[];
	exec(command: string, args: string[], options?: { timeout?: number }): Promise<ExecResult>;
}

const baseEnv: HerdrWorkstreamEnv = {
	HERDR_ENV: "1",
	HERDR_SOCKET_PATH: "/tmp/herdr.sock",
	HERDR_PANE_ID: "wmain:proot",
	BASECAMP_AGENT_DEPTH: "0",
};

const baseWorkspace: HerdrWorkstreamWorkspaceInput = {
	protectedRoot: "/repo/protected",
	repo: { root: "/repo/root" },
	launchCwd: "/repo/launch",
	hasUI: true,
};

const baseWorktree: HerdrWorkstreamWorktreeInput = {
	path: "/worktrees/org/repo/bt/workstream",
	label: "bt/workstream",
};

function createMockPi(
	handler: (command: string, args: string[], options?: { timeout?: number }) => Promise<ExecResult>,
): MockPi {
	const execCalls: ExecCall[] = [];
	return {
		execCalls,
		async exec(command, args, options) {
			execCalls.push({ command, args, options });
			return await handler(command, args, options);
		},
	};
}

function assertSkippedReason(result: ReturnType<typeof buildHerdrWorkstreamOpenArgs>, reason: string): void {
	assert.equal(result.args, null);
	if (result.args !== null) throw new Error("expected skipped Herdr result");
	assert.equal(result.reason, reason);
}

describe("buildHerdrWorkstreamOpenArgs", () => {
	it("builds Herdr worktree open args with HERDR_WORKSPACE_ID", () => {
		const result = buildHerdrWorkstreamOpenArgs(baseWorkspace, baseWorktree, {
			...baseEnv,
			HERDR_WORKSPACE_ID: "workspace-1",
		});

		assert.deepEqual(result, {
			args: [
				"worktree",
				"open",
				"--workspace",
				"workspace-1",
				"--path",
				"/worktrees/org/repo/bt/workstream",
				"--label",
				"bt/workstream",
				"--no-focus",
				"--json",
			],
		});
	});

	it("builds Herdr worktree open args with protectedRoot as the preferred cwd fallback", () => {
		const result = buildHerdrWorkstreamOpenArgs(baseWorkspace, baseWorktree, baseEnv);

		assert.deepEqual(result, {
			args: [
				"worktree",
				"open",
				"--cwd",
				"/repo/protected",
				"--path",
				"/worktrees/org/repo/bt/workstream",
				"--label",
				"bt/workstream",
				"--no-focus",
				"--json",
			],
		});
	});

	it("falls back from protectedRoot to repo.root and then launchCwd", () => {
		assert.deepEqual(
			buildHerdrWorkstreamOpenArgs(
				{ repo: { root: "/repo/root" }, launchCwd: "/repo/launch", hasUI: true },
				baseWorktree,
				baseEnv,
			),
			{
				args: [
					"worktree",
					"open",
					"--cwd",
					"/repo/root",
					"--path",
					"/worktrees/org/repo/bt/workstream",
					"--label",
					"bt/workstream",
					"--no-focus",
					"--json",
				],
			},
		);
		assert.deepEqual(buildHerdrWorkstreamOpenArgs({ launchCwd: "/repo/launch", hasUI: true }, baseWorktree, baseEnv), {
			args: [
				"worktree",
				"open",
				"--cwd",
				"/repo/launch",
				"--path",
				"/worktrees/org/repo/bt/workstream",
				"--label",
				"bt/workstream",
				"--no-focus",
				"--json",
			],
		});
	});

	it("skips when Herdr env is incomplete", () => {
		assert.deepEqual(
			buildHerdrWorkstreamOpenArgs(baseWorkspace, baseWorktree, {
				...baseEnv,
				HERDR_ENV: undefined,
			}),
			{
				args: null,
				status: "skipped",
				reason: "missing-herdr-env",
				message: "Herdr workstream open skipped: not running in Herdr.",
			},
		);
		assertSkippedReason(
			buildHerdrWorkstreamOpenArgs(baseWorkspace, baseWorktree, {
				...baseEnv,
				HERDR_SOCKET_PATH: undefined,
			}),
			"missing-herdr-socket-path",
		);
		assertSkippedReason(
			buildHerdrWorkstreamOpenArgs(baseWorkspace, baseWorktree, {
				...baseEnv,
				HERDR_PANE_ID: undefined,
			}),
			"missing-herdr-pane-id",
		);
	});

	it("skips for subagents, non-UI sessions, and missing cwd", () => {
		assert.equal(shouldOpenWorkstreamInHerdr({ env: { ...baseEnv, BASECAMP_AGENT_DEPTH: "1" } })?.reason, "subagent");
		assert.equal(shouldOpenWorkstreamInHerdr({ env: baseEnv, hasUI: false })?.reason, "headless");
		assertSkippedReason(buildHerdrWorkstreamOpenArgs({ hasUI: true }, baseWorktree, baseEnv), "missing-cwd");
	});

	it("treats an unset agent depth as a primary session", () => {
		assert.equal(shouldOpenWorkstreamInHerdr({ env: { ...baseEnv, BASECAMP_AGENT_DEPTH: undefined } }), null);
	});
});

describe("openWorkstreamInHerdr", () => {
	it("executes herdr with the worktree open args and timeout, returning opened on code 0", async () => {
		const pi = createMockPi(async () => ({ code: 0, stdout: '{"ok":true}\n', stderr: "", killed: false }));

		const result = await openWorkstreamInHerdr(pi, baseWorkspace, baseWorktree, baseEnv);

		assert.equal(result.status, "opened");
		assert.deepEqual(pi.execCalls, [
			{
				command: "herdr",
				args: [
					"worktree",
					"open",
					"--cwd",
					"/repo/protected",
					"--path",
					"/worktrees/org/repo/bt/workstream",
					"--label",
					"bt/workstream",
					"--no-focus",
					"--json",
				],
				options: { timeout: HERDR_WORKSTREAM_OPEN_TIMEOUT_MS },
			},
		]);
	});

	it("returns failed on nonzero exit without throwing", async () => {
		const pi = createMockPi(async () => ({ code: 2, stdout: "", stderr: "nope", killed: false }));

		const result = await openWorkstreamInHerdr(pi, baseWorkspace, baseWorktree, baseEnv);

		assert.equal(result.status, "failed");
		assert.equal(result.exitCode, 2);
		assert.equal(result.stderr, "nope");
	});

	it("returns failed when exec throws without throwing", async () => {
		const pi = createMockPi(async () => {
			throw new Error("spawn failed");
		});

		const result = await openWorkstreamInHerdr(pi, baseWorkspace, baseWorktree, baseEnv);

		assert.equal(result.status, "failed");
		assert.equal(result.error, "spawn failed");
	});

	it("returns skipped without executing when the session is not eligible", async () => {
		const pi = createMockPi(async () => {
			throw new Error("exec should not run");
		});

		const result = await openWorkstreamInHerdr(pi, baseWorkspace, baseWorktree, {
			...baseEnv,
			BASECAMP_AGENT_DEPTH: "2",
		});

		assert.deepEqual(result, {
			status: "skipped",
			reason: "subagent",
			message: "Herdr workstream open skipped: only primary sessions can open workstreams in Herdr.",
		});
		assert.deepEqual(pi.execCalls, []);
	});
});
