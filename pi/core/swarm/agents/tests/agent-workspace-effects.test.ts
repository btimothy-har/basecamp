import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../../../git/constants.ts";
import { useTempWorktreesRoot } from "../../../git/tests/worktree-root.ts";
import type { WorkspaceState } from "../../../project/workspace/state.ts";
import { type AgentWorkspaceProvision, discardAgentWorkspace, provisionAgentWorkspace } from "../agent-workspace.ts";

useTempWorktreesRoot();

type ExecResult = { code: number; stdout: string; stderr: string };
type Call = { cmd: string; args: string[]; opts?: { cwd?: string } };

const REPO_ROOT = "/repo";

function fakePi(handler: (call: Call) => ExecResult | null, calls: Call[] = []): ExtensionAPI {
	return {
		async exec(cmd: string, args: string[], opts?: { cwd?: string }): Promise<ExecResult> {
			const call = { cmd, args, opts };
			calls.push(call);
			const result = handler(call);
			if (result) return result;
			if (args.includes("list")) {
				return { code: 0, stdout: `worktree ${REPO_ROOT}\nbranch refs/heads/main\n\n`, stderr: "" };
			}
			return { code: 0, stdout: "", stderr: "" };
		},
	} as unknown as ExtensionAPI;
}

function workspace(repoName: string): WorkspaceState {
	return {
		launchCwd: REPO_ROOT,
		effectiveCwd: REPO_ROOT,
		scratchDir: "/tmp/pi/repo",
		repo: { isRepo: true, name: repoName, root: REPO_ROOT, remoteUrl: null },
		protectedRoot: REPO_ROOT,
		activeWorktree: null,
		unsafeEdit: false,
	};
}

/** Point os.homedir() at a temp HOME whose basecamp config configures a setup hook. */
function withTempHome(t: { after(fn: () => void): void }, repoName: string, setup: string): void {
	const home = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-home-"));
	fs.mkdirSync(path.join(home, ".pi", "basecamp"), { recursive: true });
	fs.writeFileSync(
		path.join(home, ".pi", "basecamp", "config.json"),
		JSON.stringify({ environments: { [repoName]: { setup } } }),
	);
	const prev = process.env.HOME;
	process.env.HOME = home;
	t.after(() => {
		if (prev === undefined) delete process.env.HOME;
		else process.env.HOME = prev;
		fs.rmSync(home, { recursive: true, force: true });
	});
}

function cleanupWorktrees(t: { after(fn: () => void): void }): void {
	t.after(() => fs.rmSync(path.join(worktreesRoot(), "basecamp-ws-fx"), { recursive: true, force: true }));
}

function repoName(tag: string): string {
	return `basecamp-ws-fx/${tag}-${process.pid}-${Date.now()}`;
}

const deliverableRequest = {
	kind: "deliverable",
	agentHandle: "h1",
	isRetask: false,
	runToken: "abc123",
	agentName: "worker",
} as const;

describe("provisionAgentWorkspace — setup hook", () => {
	it("runs the configured setup hook via env(1) in the new workspace (blocking, ok)", async (t) => {
		const repo = repoName("setup-ok");
		withTempHome(t, repo, "make setup");
		cleanupWorktrees(t);
		const calls: Call[] = [];
		const pi = fakePi((call) => (call.args.includes("--verify") ? { code: 1, stdout: "", stderr: "" } : null), calls);

		const provision = await provisionAgentWorkspace(pi, deliverableRequest, workspace(repo));

		const setup = calls.find((call) => call.cmd === "env" && call.args.includes("bash"));
		assert.ok(setup, "setup hook runs");
		assert.deepEqual(setup.args, [`BASECAMP_REPO_ROOT=${REPO_ROOT}`, "bash", "-lc", "make setup"]);
		assert.equal(setup.opts?.cwd, provision?.worktreeDir, "hook runs inside the agent workspace");
		assert.equal(provision?.setupWarning, undefined);
	});

	it("runs the setup hook for report runs too (reviewers need environments)", async (t) => {
		const repo = repoName("setup-report");
		withTempHome(t, repo, "make setup");
		cleanupWorktrees(t);
		const calls: Call[] = [];
		const pi = fakePi(() => null, calls);

		await provisionAgentWorkspace(pi, { kind: "report", runToken: "cafe12", agentName: "scout" }, workspace(repo));

		assert.ok(calls.some((call) => call.cmd === "env" && call.args.includes("bash")));
	});

	it("surfaces a nonfatal warning when the setup hook fails", async (t) => {
		const repo = repoName("setup-fail");
		withTempHome(t, repo, "make setup");
		cleanupWorktrees(t);
		const pi = fakePi((call) => {
			if (call.cmd === "env" && call.args.includes("bash")) return { code: 2, stdout: "", stderr: "boom" };
			if (call.args.includes("--verify")) return { code: 1, stdout: "", stderr: "" };
			return null;
		});

		const provision = await provisionAgentWorkspace(pi, deliverableRequest, workspace(repo));

		assert.ok(provision, "dispatch proceeds despite the failed hook");
		assert.match(provision.setupWarning ?? "", /exited 2/);
		assert.match(provision.setupWarning ?? "", /boom/);
	});

	it("skips the setup hook for ask workspaces", async (t) => {
		const repo = repoName("setup-ask");
		withTempHome(t, repo, "make setup");
		cleanupWorktrees(t);
		const calls: Call[] = [];
		const pi = fakePi((call) => (call.args.includes("--verify") ? { code: 1, stdout: "", stderr: "" } : null), calls);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "ask", targetHandle: "t1", runToken: "def456", agentName: "ask" },
			workspace(repo),
		);

		assert.ok(provision);
		assert.equal(
			calls.some((call) => call.args.includes("bash")),
			false,
			"asks pay no setup latency",
		);
	});
});

describe("discardAgentWorkspace", () => {
	const provision = (branchCreated: boolean): AgentWorkspaceProvision => ({
		kind: "deliverable",
		worktreeDir: "/worktrees/repo/agent-abc123/scout",
		label: "agent-abc123/scout",
		branch: "agent/h1",
		baseOid: "baseoid",
		branchCreated,
		repoRoot: REPO_ROOT,
	});

	it("force-removes the worktree and deletes a branch it minted", async () => {
		const calls: Call[] = [];
		await discardAgentWorkspace(
			fakePi(() => null, calls),
			provision(true),
		);

		const remove = calls.find((call) => call.args.includes("remove"));
		assert.ok(remove?.args.includes("--force"));
		assert.ok(
			calls.some((call) => call.args.includes("-D") && call.args.includes("agent/h1")),
			"deletes the branch this provision minted",
		);
	});

	it("preserves an outstanding branch from a prior run", async () => {
		const calls: Call[] = [];
		await discardAgentWorkspace(
			fakePi(() => null, calls),
			provision(false),
		);

		assert.ok(calls.some((call) => call.args.includes("remove")));
		assert.equal(
			calls.some((call) => call.args.includes("-D")),
			false,
			"a continued branch survives a failed dispatch",
		);
	});

	it("is a no-op for a null provision", async () => {
		const calls: Call[] = [];
		await discardAgentWorkspace(
			fakePi(() => null, calls),
			null,
		);
		assert.equal(calls.length, 0);
	});
});
