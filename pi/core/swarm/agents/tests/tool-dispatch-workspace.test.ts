import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { WORKTREES_ROOT } from "../../../git/constants.ts";
import type { Frame } from "../../../hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "../../../hub/protocol/index.ts";
import { registerDaemonTools } from "../tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	setCurrentWorkspaceState,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("dispatch_agent workspace provisioning", () => {
	installDaemonToolTestHooks();

	it("dispatch_agent gives a worker a deliverable branch spec from a clean parent", async (t) => {
		trackSkillInvocation("agents");
		const repoName = `bc-tool-test/r-${process.pid}-${Date.now()}`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "bc-tool-test"), { recursive: true, force: true }));
		setCurrentWorkspaceState(repoWorkspaceState(repoName));

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			pi.execScript = gitProvisionScript();
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "hello world", agent: "worker" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			assert.equal(outbound.spec.owned_worktree?.includes("agent-"), true, "own workspace provisioned");
			assert.equal(outbound.spec.cwd, outbound.spec.owned_worktree, "spawns inside its own workspace");
			assert.equal(outbound.spec.owned_branch, `agent/${outbound.agent_handle}`);
			assert.equal(outbound.spec.branch_base, "headoid");
			assert.equal(outbound.spec.branch_created, true);
			assert.equal(outbound.spec.argv.includes("--read-only"), false);
			assert.equal(outbound.spec.argv.includes("--worktree-dir"), false);
			assert.equal(outbound.spec.env.BASECAMP_WORKTREE_DIR, outbound.spec.owned_worktree);

			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.match(result.content[0].text, /git merge/);
			assert.equal(
				pi.execCalls.some((call: { args: string[] }) => call.args.includes("remove")),
				false,
				"accepted dispatch keeps the workspace",
			);
		} finally {
			setCurrentWorkspaceState(null);
		}
	});

	it("dispatch_agent gives report personas a branchless detached workspace", async (t) => {
		trackSkillInvocation("agents");
		const repoName = `bc-tool-test/r-${process.pid}-${Date.now()}-rep`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "bc-tool-test"), { recursive: true, force: true }));
		setCurrentWorkspaceState(repoWorkspaceState(repoName));

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			// A configured setup hook that fails: the dispatch proceeds and surfaces the warning.
			fs.mkdirSync(path.join(process.env.HOME as string, ".pi", "basecamp"), { recursive: true });
			fs.writeFileSync(
				path.join(process.env.HOME as string, ".pi", "basecamp", "config.json"),
				JSON.stringify({ environments: { [repoName]: { setup: "exit 3" } } }),
			);
			const baseScript = gitProvisionScript();
			pi.execScript = (cmd: string, args: string[]) => {
				if (cmd === "env" && args.includes("bash")) return { code: 3, stdout: "", stderr: "no deps" };
				return baseScript(cmd, args);
			};
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "map the code", agent: "scout" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			assert.equal(outbound.spec.owned_worktree?.includes("agent-"), true);
			assert.equal(outbound.spec.owned_branch, null, "report runs never mint a branch");
			assert.equal(outbound.spec.branch_created, false);
			const addCall = pi.execCalls.find((call: { args: string[] }) => call.args.includes("add"));
			assert.ok(addCall?.args.includes("--detach"), "report workspace is detached");

			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			const result = await executePromise;
			assert.doesNotMatch(result.content[0].text, /git merge/, "no merge hint for branchless runs");
			assert.match(result.content[0].text, /⚠ Workspace setup hook exited 3/, "setup warning surfaces in the result");
		} finally {
			setCurrentWorkspaceState(null);
		}
	});

	it("dispatch_agent discards the minted workspace and branch when the daemon rejects", async (t) => {
		trackSkillInvocation("agents");
		const repoName = `bc-tool-test/r-${process.pid}-${Date.now()}-rej`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "bc-tool-test"), { recursive: true, force: true }));
		setCurrentWorkspaceState(repoWorkspaceState(repoName));

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			pi.execScript = gitProvisionScript();
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "hello world", agent: "worker" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "rejected",
				reason: "boom",
			});
			const result = await executePromise;
			assert.equal(result.isError, true);

			const removeCall = pi.execCalls.find((call: { args: string[] }) => call.args.includes("remove"));
			assert.ok(removeCall?.args.includes("--force"), "rejected dispatch force-discards the workspace");
			assert.ok(
				pi.execCalls.some((call: { args: string[] }) => call.args.includes("-D")),
				"rejected dispatch deletes the branch it minted",
			);
		} finally {
			setCurrentWorkspaceState(null);
		}
	});

	it("dispatch_agent discards and re-mints under a new handle on duplicate-handle retry", async (t) => {
		trackSkillInvocation("agents");
		const repoName = `bc-tool-test/r-${process.pid}-${Date.now()}-retry`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "bc-tool-test"), { recursive: true, force: true }));
		setCurrentWorkspaceState(repoWorkspaceState(repoName));

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			pi.execScript = gitProvisionScript();
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "hello world", agent: "worker" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const first = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: first.run_id,
				status: "rejected",
				reason: "duplicate_agent_handle",
			});

			await new Promise((resolve) => setTimeout(resolve, 20));
			const second = connection.sent[1] as Extract<Frame, { type: "dispatch" }>;
			assert.ok(second, "second attempt dispatched");
			assert.notEqual(second.agent_handle, first.agent_handle, "new handle minted");
			assert.equal(second.spec.owned_branch, `agent/${second.agent_handle}`, "branch re-keyed to the new handle");
			assert.notEqual(second.spec.owned_worktree, first.spec.owned_worktree, "fresh per-attempt worktree token");
			const discardIdx = pi.execCalls.findIndex(
				(call: { args: string[] }) => call.args.includes("remove") && call.args.includes("--force"),
			);
			assert.notEqual(discardIdx, -1, "first attempt's workspace discarded before re-mint");
			assert.ok(
				pi.execCalls.some(
					(call: { args: string[] }) => call.args.includes("-D") && call.args.includes(`agent/${first.agent_handle}`),
				),
				"first attempt's minted branch deleted",
			);

			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: second.run_id,
				status: "spawned",
				reason: null,
			});
			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.match(result.content[0].text, new RegExp(String(second.agent_handle)));
		} finally {
			setCurrentWorkspaceState(null);
		}
	});

	it("dispatch_agent keeps the workspace when the connection drops after the frame is sent", async (t) => {
		trackSkillInvocation("agents");
		const repoName = `bc-tool-test/r-${process.pid}-${Date.now()}-drop`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "bc-tool-test"), { recursive: true, force: true }));
		setCurrentWorkspaceState(repoWorkspaceState(repoName));

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			pi.execScript = gitProvisionScript();
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "hello world", agent: "worker" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			assert.equal(connection.sent.length, 1, "frame was sent");
			// Transport drops before the ack arrives — ambiguous, the daemon may own the run.
			connection.emitClose(1006, "transport dropped");
			const result = await executePromise;

			assert.equal(result.isError, true);
			assert.equal(
				pi.execCalls.some((call: { args: string[] }) => call.args.includes("remove")),
				false,
				"a post-send failure does not force-remove the possibly-live workspace",
			);
			assert.equal(
				pi.execCalls.some((call: { args: string[] }) => call.args.includes("-D")),
				false,
				"a post-send failure does not delete the minted branch",
			);
		} finally {
			setCurrentWorkspaceState(null);
		}
	});

	it("dispatch_agent surfaces commit-first guidance when a worker is dispatched from a dirty parent", async (t) => {
		trackSkillInvocation("agents");
		const repoName = `bc-tool-test/r-${process.pid}-${Date.now()}-dirty`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "bc-tool-test"), { recursive: true, force: true }));
		setCurrentWorkspaceState(repoWorkspaceState(repoName));

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			pi.execScript = (_cmd: string, args: string[]) => {
				if (args.includes("--verify")) return { code: 1, stdout: "", stderr: "" };
				if (args.includes("status")) return { code: 0, stdout: " M wip.ts\n", stderr: "" };
				return null;
			};
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const result = await dispatchTool.execute(
				"1",
				{ task: "implement it", agent: "worker" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			assert.equal(result.isError, true);
			assert.match(result.content[0].text, /commit your WIP first/);
			assert.equal(connection.sent.length, 0, "nothing reaches the daemon");
		} finally {
			setCurrentWorkspaceState(null);
		}
	});
});

function repoWorkspaceState(repoName: string) {
	return {
		launchCwd: "/wt",
		effectiveCwd: "/wt",
		scratchDir: "/tmp/pi/repo",
		unsafeEdit: false,
		repo: { root: "/repo-root", isRepo: true, name: repoName, remoteUrl: null },
		protectedRoot: "/repo-root",
		activeWorktree: { path: "/wt", kind: "git-worktree" as const, label: "wt", branch: null, created: false },
	};
}

/** Answers the provisioning git sequence: no existing branch, clean parent at `headoid`. */
function gitProvisionScript() {
	return (_cmd: string, args: string[]): { code: number; stdout: string; stderr: string } | null => {
		if (args.includes("--verify")) return { code: 1, stdout: "", stderr: "" };
		if (args.includes("status")) return { code: 0, stdout: "", stderr: "" };
		if (args.includes("rev-parse") && args.includes("HEAD")) return { code: 0, stdout: "headoid\n", stderr: "" };
		if (args.includes("list"))
			return { code: 0, stdout: "worktree /repo-root\nbranch refs/heads/main\n\n", stderr: "" };
		return null;
	};
}
