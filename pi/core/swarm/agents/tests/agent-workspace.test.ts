import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { WORKTREES_ROOT } from "../../../git/constants.ts";
import type { WorkspaceState } from "../../../project/workspace/state.ts";
import { agentBranchName, provisionAgentWorkspace } from "../agent-workspace.ts";

type ExecResult = { code: number; stdout: string; stderr: string };
type Call = { cmd: string; args: string[] };
type Rule = [(call: Call) => boolean, ExecResult];

const REPO_ROOT = "/repo";
const PARENT_WT = "/worktrees/repo/abc";
const ok = (stdout = ""): ExecResult => ({ code: 0, stdout, stderr: "" });
const fail = (stderr = "nope"): ExecResult => ({ code: 1, stdout: "", stderr });

function has(call: Call, ...parts: string[]): boolean {
	return parts.every((part) => call.args.includes(part));
}

function scripted(rules: Rule[], calls: Call[] = []): ExtensionAPI {
	return {
		async exec(cmd: string, args: string[]): Promise<ExecResult> {
			const call = { cmd, args };
			calls.push(call);
			for (const [match, result] of rules) if (match(call)) return result;
			if (has(call, "worktree", "list")) return ok(`worktree ${REPO_ROOT}\nbranch refs/heads/main\n\n`);
			return ok();
		},
	} as unknown as ExtensionAPI;
}

function workspace(repoName: string, overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: REPO_ROOT,
		effectiveCwd: PARENT_WT,
		scratchDir: "/tmp/pi/repo",
		repo: { isRepo: true, name: repoName, root: REPO_ROOT, remoteUrl: "git@github.com:o/repo.git" },
		protectedRoot: REPO_ROOT,
		activeWorktree: { kind: "git-worktree", label: "abc", path: PARENT_WT, branch: "wt-bt/feat", created: false },
		unsafeEdit: false,
		...overrides,
	};
}

function uniqueRepo(t: { after(fn: () => void): void }, tag: string): string {
	const name = `basecamp-ws-test/${tag}-${process.pid}-${Date.now()}`;
	t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, "basecamp-ws-test"), { recursive: true, force: true }));
	return name;
}

const branchTipRule = (branch: string, result: ExecResult): Rule => [
	(c) => has(c, "rev-parse", "--verify", `refs/heads/${branch}`),
	result,
];
const statusRule = (stdout: string): Rule => [(c) => has(c, "-C", PARENT_WT, "status", "--porcelain"), ok(stdout)];
const headRule = (oid: string): Rule => [
	(c) => has(c, "-C", PARENT_WT, "rev-parse", "HEAD") && !c.args.includes("--verify"),
	ok(`${oid}\n`),
];

describe("provisionAgentWorkspace — deliverable", () => {
	it("returns null without a repo-backed session", async () => {
		const pi = scripted([]);
		const request = {
			kind: "deliverable",
			agentHandle: "h1",
			isRetask: false,
			runToken: "aaaaaa",
			agentName: "worker",
		} as const;
		assert.equal(await provisionAgentWorkspace(pi, request, null), null);
		assert.equal(await provisionAgentWorkspace(pi, request, workspace("r", { repo: null })), null);
	});

	it("mints agent/<handle> at a clean parent HEAD", async (t) => {
		const repoName = uniqueRepo(t, "fresh");
		const branch = agentBranchName("quiet-badger-3dc450");
		const calls: Call[] = [];
		const pi = scripted([branchTipRule(branch, fail()), statusRule(""), headRule("headoid")], calls);

		const provision = await provisionAgentWorkspace(
			pi,
			{
				kind: "deliverable",
				agentHandle: "quiet-badger-3dc450",
				isRetask: false,
				runToken: "3f9a2c",
				agentName: "worker",
			},
			workspace(repoName),
		);

		assert.ok(provision);
		assert.deepEqual(
			{ ...provision, worktreeDir: undefined },
			{
				kind: "deliverable",
				branch,
				label: "agent-3f9a2c/worker",
				baseOid: "headoid",
				branchCreated: true,
				repoRoot: REPO_ROOT,
				worktreeDir: undefined,
			},
		);
		const add = calls.find((c) => has(c, "worktree", "add"));
		assert.ok(add);
		assert.deepEqual(add.args.slice(-4), ["-b", branch, provision.worktreeDir, "headoid"]);
	});

	it("rejects minting from a dirty parent with commit-first guidance", async (t) => {
		const repoName = uniqueRepo(t, "dirty");
		const branch = agentBranchName("h2");
		const pi = scripted([branchTipRule(branch, fail()), statusRule(" M file.ts\n")]);

		await assert.rejects(
			() =>
				provisionAgentWorkspace(
					pi,
					{ kind: "deliverable", agentHandle: "h2", isRetask: false, runToken: "aaaaaa", agentName: "worker" },
					workspace(repoName),
				),
			/commit your WIP first/,
		);
	});

	it("rejects a fresh dispatch whose branch already exists", async (t) => {
		const repoName = uniqueRepo(t, "stale");
		const branch = agentBranchName("h3");
		const pi = scripted([branchTipRule(branch, ok("tipoid\n"))]);

		await assert.rejects(
			() =>
				provisionAgentWorkspace(
					pi,
					{ kind: "deliverable", agentHandle: "h3", isRetask: false, runToken: "aaaaaa", agentName: "worker" },
					workspace(repoName),
				),
			/already exists but this is not a retask/,
		);
	});

	it("continues an outstanding branch on retask even when the parent is dirty", async (t) => {
		const repoName = uniqueRepo(t, "continue");
		const branch = agentBranchName("h4");
		const calls: Call[] = [];
		const pi = scripted(
			[
				branchTipRule(branch, ok("tipoid\n")),
				statusRule(" M wip.ts\n"),
				[(c) => has(c, "branch", "--show-current"), ok("wt-bt/feat\n")],
				[(c) => has(c, "merge-base", "--is-ancestor"), fail()],
			],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "deliverable", agentHandle: "h4", isRetask: true, runToken: "bbbbbb", agentName: "worker" },
			workspace(repoName),
		);

		assert.equal(provision?.branch, branch);
		assert.equal(provision?.baseOid, "tipoid");
		assert.equal(provision?.branchCreated, false);
		const add = calls.find((c) => has(c, "worktree", "add"));
		assert.ok(add);
		assert.equal(add.args.includes("-b"), false, "checks out the existing branch");
		assert.deepEqual(add.args.at(-1), branch);
	});

	it("deletes a merged branch on retask and re-mints from a clean parent", async (t) => {
		const repoName = uniqueRepo(t, "merged");
		const branch = agentBranchName("h5");
		const calls: Call[] = [];
		const pi = scripted(
			[
				branchTipRule(branch, ok("tipoid\n")),
				[(c) => has(c, "branch", "--show-current"), ok("wt-bt/feat\n")],
				[(c) => has(c, "merge-base", "--is-ancestor", branch, "wt-bt/feat"), ok()],
				statusRule(""),
				headRule("headoid"),
			],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "deliverable", agentHandle: "h5", isRetask: true, runToken: "cccccc", agentName: "worker" },
			workspace(repoName),
		);

		assert.equal(provision?.branchCreated, true);
		assert.equal(provision?.baseOid, "headoid");
		const deleteIdx = calls.findIndex((c) => has(c, "branch", "-D", branch));
		const addIdx = calls.findIndex((c) => has(c, "worktree", "add"));
		assert.ok(deleteIdx !== -1 && deleteIdx < addIdx, "deletes the integrated branch before re-minting");
		assert.ok(calls[addIdx]?.args.includes("-b"), "re-mints the branch fresh");
	});
});

describe("provisionAgentWorkspace — report and ask", () => {
	it("gives a report run a detached workspace at the parent HEAD when clean", async (t) => {
		const repoName = uniqueRepo(t, "report-clean");
		const calls: Call[] = [];
		const pi = scripted([statusRule(""), headRule("headoid")], calls);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "report", runToken: "dddddd", agentName: "scout" },
			workspace(repoName),
		);

		assert.equal(provision?.kind, "report");
		assert.equal(provision?.branch, null);
		assert.equal(provision?.baseOid, "headoid");
		const add = calls.find((c) => has(c, "worktree", "add"));
		assert.ok(add?.args.includes("--detach"), "report workspaces are detached");
	});

	it("detaches a report run at a snapshot when the parent is dirty (index seeded from HEAD)", async (t) => {
		const repoName = uniqueRepo(t, "report-dirty");
		const calls: Call[] = [];
		const pi = scripted(
			[
				statusRule(" M file.ts\n?? scratch.txt\n"),
				[(c) => c.cmd === "env" && has(c, "write-tree"), ok("treeoid\n")],
				[(c) => c.cmd === "env" && has(c, "commit-tree"), ok("snapoid\n")],
			],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "report", runToken: "eeeeee", agentName: "scout" },
			workspace(repoName),
		);

		assert.equal(provision?.baseOid, "snapoid");
		const envCalls = calls.filter((c) => c.cmd === "env");
		assert.deepEqual(
			envCalls.map((c) => c.args.filter((a) => ["read-tree", "add", "write-tree", "commit-tree"].includes(a))[0]),
			["read-tree", "add", "write-tree", "commit-tree"],
			"snapshot seeds the throwaway index from HEAD before add -A",
		);
		for (const call of envCalls) assert.match(call.args[0] ?? "", /^GIT_INDEX_FILE=/);
		assert.ok(calls.find((c) => has(c, "worktree", "add"))?.args.includes("--detach"));
	});

	it("detaches an ask at the target agent's branch tip when it exists", async (t) => {
		const repoName = uniqueRepo(t, "ask-tip");
		const calls: Call[] = [];
		const pi = scripted([branchTipRule(agentBranchName("target-1"), ok("targettip\n"))], calls);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "ask", targetHandle: "target-1", runToken: "ffffff", agentName: "ask" },
			workspace(repoName),
		);

		assert.equal(provision?.branch, null);
		assert.equal(provision?.baseOid, "targettip");
		assert.ok(calls.find((c) => has(c, "worktree", "add"))?.args.includes("--detach"));
	});

	it("falls back to the parent HEAD when the ask target has no branch", async (t) => {
		const repoName = uniqueRepo(t, "ask-head");
		const calls: Call[] = [];
		const pi = scripted(
			[branchTipRule(agentBranchName("target-2"), fail()), statusRule(""), headRule("headoid")],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "ask", targetHandle: "target-2", runToken: "abcdef", agentName: "ask" },
			workspace(repoName),
		);

		assert.equal(provision?.baseOid, "headoid");
	});

	it("maps an unborn-HEAD failure to a friendly error", async (t) => {
		const repoName = uniqueRepo(t, "unborn");
		const pi = scripted([
			statusRule(""),
			[
				(c) => has(c, "-C", PARENT_WT, "rev-parse", "HEAD") && !c.args.includes("--verify"),
				fail("fatal: ambiguous argument 'HEAD': unknown revision"),
			],
		]);

		await assert.rejects(
			() =>
				provisionAgentWorkspace(pi, { kind: "report", runToken: "beefed", agentName: "scout" }, workspace(repoName)),
			/no commits yet/,
		);
	});
});
