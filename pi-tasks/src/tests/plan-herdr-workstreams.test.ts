import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import {
	buildHerdrWorkstreamOpenArgs,
	HERDR_WORKSTREAM_OPEN_TIMEOUT_MS,
	type HerdrWorkstreamEnv,
	openWorkstreamInHerdr,
	shouldOpenWorkstreamInHerdr,
} from "../planning/herdr-workstreams.ts";

function workspace(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: "/launch",
		effectiveCwd: "/launch",
		scratchDir: "/scratch",
		repo: { isRepo: true, name: "org/repo", root: "/repo", remoteUrl: "git@example.com:org/repo.git" },
		protectedRoot: "/protected",
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	};
}

function herdrEnv(overrides: HerdrWorkstreamEnv = {}): HerdrWorkstreamEnv {
	return {
		BASECAMP_AGENT_DEPTH: "0",
		HERDR_ENV: "1",
		HERDR_PANE_ID: "pane-1",
		HERDR_SOCKET_PATH: "/tmp/herdr.sock",
		...overrides,
	};
}

describe("Herdr workstream worktree opening", () => {
	it("gates opening to primary Herdr sessions with pane and socket", () => {
		assert.equal(shouldOpenWorkstreamInHerdr(herdrEnv()), true);
		assert.equal(shouldOpenWorkstreamInHerdr(herdrEnv({ HERDR_ENV: undefined })), false);
		assert.equal(shouldOpenWorkstreamInHerdr(herdrEnv({ HERDR_ENV: "0" })), false);
		assert.equal(shouldOpenWorkstreamInHerdr(herdrEnv({ HERDR_SOCKET_PATH: undefined })), false);
		assert.equal(shouldOpenWorkstreamInHerdr(herdrEnv({ HERDR_PANE_ID: undefined })), false);
		assert.equal(shouldOpenWorkstreamInHerdr(herdrEnv({ BASECAMP_AGENT_DEPTH: "1" })), false);
	});

	it("builds worktree open args with Herdr workspace id when available", () => {
		assert.deepEqual(
			buildHerdrWorkstreamOpenArgs(
				workspace(),
				{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
				herdrEnv({ HERDR_WORKSPACE_ID: "workspace-1" }),
			),
			[
				"worktree",
				"open",
				"--workspace",
				"workspace-1",
				"--path",
				"/worktrees/wt-te/1234-core",
				"--label",
				"wt-te/1234-core",
				"--no-focus",
				"--json",
			],
		);
	});

	it("builds worktree open args with cwd fallback when Herdr workspace id is absent", () => {
		assert.deepEqual(
			buildHerdrWorkstreamOpenArgs(
				workspace(),
				{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
				herdrEnv(),
			),
			[
				"worktree",
				"open",
				"--cwd",
				"/protected",
				"--path",
				"/worktrees/wt-te/1234-core",
				"--label",
				"wt-te/1234-core",
				"--no-focus",
				"--json",
			],
		);

		assert.deepEqual(
			buildHerdrWorkstreamOpenArgs(
				workspace({ protectedRoot: null }),
				{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
				herdrEnv(),
			)?.slice(0, 4),
			["worktree", "open", "--cwd", "/repo"],
		);

		assert.deepEqual(
			buildHerdrWorkstreamOpenArgs(
				workspace({ protectedRoot: null, repo: null }),
				{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
				herdrEnv(),
			)?.slice(0, 4),
			["worktree", "open", "--cwd", "/launch"],
		);
	});

	it("returns null args when gated off", () => {
		assert.equal(
			buildHerdrWorkstreamOpenArgs(
				workspace(),
				{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
				herdrEnv({ HERDR_SOCKET_PATH: undefined }),
			),
			null,
		);
	});

	it("execs Herdr with a timeout and swallows command failures", async () => {
		const execCalls: { command: string; args: string[]; opts: { timeout?: number } }[] = [];
		const pi = {
			async exec(command: string, args: string[], opts: { timeout?: number }) {
				execCalls.push({ command, args, opts });
				throw new Error("herdr unavailable");
			},
		} as unknown as ExtensionAPI;

		await openWorkstreamInHerdr(
			pi,
			workspace(),
			{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
			herdrEnv({ HERDR_WORKSPACE_ID: "workspace-1" }),
		);

		assert.equal(execCalls.length, 1);
		assert.equal(execCalls[0]?.command, "herdr");
		assert.deepEqual(execCalls[0]?.args.slice(0, 4), ["worktree", "open", "--workspace", "workspace-1"]);
		assert.deepEqual(execCalls[0]?.opts, { timeout: HERDR_WORKSTREAM_OPEN_TIMEOUT_MS });
	});

	it("does not exec Herdr when gated off", async () => {
		let execCalls = 0;
		const pi = {
			async exec() {
				execCalls++;
			},
		} as unknown as ExtensionAPI;

		await openWorkstreamInHerdr(
			pi,
			workspace(),
			{ label: "wt-te/1234-core", path: "/worktrees/wt-te/1234-core" },
			herdrEnv({ BASECAMP_AGENT_DEPTH: "1" }),
		);

		assert.equal(execCalls, 0);
	});
});
