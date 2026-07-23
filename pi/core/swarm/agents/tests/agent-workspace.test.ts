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

describe("provisionAgentWorkspace — dispatch", () => {
	it("returns null without a repo-backed session", async () => {
		const pi = scripted([]);
		const request = {
			kind: "dispatch",
			agentHandle: "h1",
			isRetask: false,
			runToken: "aaaaaa",
			agentName: "scout",
		} as const;
		assert.equal(await provisionAgentWorkspace(pi, request, null), null);
		assert.equal(await provisionAgentWorkspace(pi, request, workspace("r", { repo: null })), null);
	});

	it("mints agent/<handle> at the parent HEAD when the parent is clean", async (t) => {
		const repoName = uniqueRepo(t, "fresh");
		const branch = agentBranchName("quiet-badger-3dc450");
		const calls: Call[] = [];
		const pi = scripted([branchTipRule(branch, fail()), statusRule(""), headRule("headoid")], calls);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "dispatch", agentHandle: "quiet-badger-3dc450", isRetask: false, runToken: "3f9a2c", agentName: "scout" },
			workspace(repoName),
		);

		assert.ok(provision);
		assert.deepEqual(
			{ ...provision, worktreeDir: undefined },
			{
				branch,
				label: "agent-3f9a2c/scout",
				baseOid: "headoid",
				branchCreated: true,
				repoRoot: REPO_ROOT,
				worktreeDir: undefined,
			},
		);
		assert.equal(provision.worktreeDir, path.join(WORKTREES_ROOT, repoName, "agent-3f9a2c", "scout"));
		const add = calls.find((c) => has(c, "worktree", "add"));
		assert.ok(add);
		assert.deepEqual(add.args.slice(-4), ["-b", branch, provision.worktreeDir, "headoid"]);
	});

	it("bases on a snapshot commit when the parent is dirty, via a throwaway index", async (t) => {
		const repoName = uniqueRepo(t, "dirty");
		const branch = agentBranchName("h2");
		const calls: Call[] = [];
		const pi = scripted(
			[
				branchTipRule(branch, fail()),
				statusRule(" M file.ts\n?? scratch.txt\n"),
				[(c) => c.cmd === "env" && has(c, "write-tree"), ok("treeoid\n")],
				[(c) => c.cmd === "env" && has(c, "commit-tree"), ok("snapoid\n")],
			],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "dispatch", agentHandle: "h2", isRetask: false, runToken: "aaaaaa", agentName: "scout" },
			workspace(repoName),
		);

		assert.equal(provision?.baseOid, "snapoid");
		const envCalls = calls.filter((c) => c.cmd === "env");
		assert.equal(envCalls.length, 3, "add -A, write-tree, commit-tree run via env(1)");
		for (const call of envCalls) {
			assert.match(call.args[0] ?? "", /^GIT_INDEX_FILE=/, "throwaway index for every snapshot step");
			assert.ok(has(call, "git", "-C", PARENT_WT));
		}
		assert.ok(has(envCalls[2] as Call, "commit-tree", "treeoid", "-p", "HEAD"));
		const add = calls.find((c) => has(c, "worktree", "add"));
		assert.ok(add?.args.includes("snapoid"), "worktree bases on the snapshot commit");
	});

	it("rejects a fresh dispatch whose branch already exists", async (t) => {
		const repoName = uniqueRepo(t, "stale");
		const branch = agentBranchName("h3");
		const pi = scripted([branchTipRule(branch, ok("tipoid\n"))]);

		await assert.rejects(
			() =>
				provisionAgentWorkspace(
					pi,
					{ kind: "dispatch", agentHandle: "h3", isRetask: false, runToken: "aaaaaa", agentName: "scout" },
					workspace(repoName),
				),
			/already exists but this is not a retask/,
		);
	});

	it("continues an outstanding branch on retask (no new branch, base = tip)", async (t) => {
		const repoName = uniqueRepo(t, "continue");
		const branch = agentBranchName("h4");
		const calls: Call[] = [];
		const pi = scripted(
			[
				branchTipRule(branch, ok("tipoid\n")),
				[(c) => has(c, "branch", "--show-current"), ok("wt-bt/feat\n")],
				[(c) => has(c, "merge-base", "--is-ancestor"), fail()],
			],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "dispatch", agentHandle: "h4", isRetask: true, runToken: "bbbbbb", agentName: "worker" },
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

	it("deletes a merged branch on retask and bases fresh from the parent", async (t) => {
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
			{ kind: "dispatch", agentHandle: "h5", isRetask: true, runToken: "cccccc", agentName: "worker" },
			workspace(repoName),
		);

		assert.equal(provision?.branchCreated, true);
		assert.equal(provision?.baseOid, "headoid");
		const deleteIdx = calls.findIndex((c) => has(c, "branch", "-D", branch));
		const addIdx = calls.findIndex((c) => has(c, "worktree", "add"));
		assert.notEqual(deleteIdx, -1, "deletes the integrated branch");
		assert.ok(deleteIdx < addIdx, "deletes before re-minting");
		assert.ok(calls[addIdx]?.args.includes("-b"), "re-mints the branch fresh");
	});
});

describe("provisionAgentWorkspace — ask", () => {
	it("detaches at the target agent's branch tip when it exists", async (t) => {
		const repoName = uniqueRepo(t, "ask-tip");
		const calls: Call[] = [];
		const pi = scripted([branchTipRule(agentBranchName("target-1"), ok("targettip\n"))], calls);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "ask", targetHandle: "target-1", runToken: "dddddd", agentName: "ask" },
			workspace(repoName),
		);

		assert.equal(provision?.branch, null);
		assert.equal(provision?.baseOid, "targettip");
		assert.equal(provision?.branchCreated, false);
		const add = calls.find((c) => has(c, "worktree", "add"));
		assert.ok(add?.args.includes("--detach"), "ask workspaces are detached");
		assert.equal(add?.args.includes("-b"), false);
	});

	it("falls back to the parent HEAD when the target has no branch", async (t) => {
		const repoName = uniqueRepo(t, "ask-head");
		const calls: Call[] = [];
		const pi = scripted(
			[branchTipRule(agentBranchName("target-2"), fail()), statusRule(""), headRule("headoid")],
			calls,
		);

		const provision = await provisionAgentWorkspace(
			pi,
			{ kind: "ask", targetHandle: "target-2", runToken: "eeeeee", agentName: "ask" },
			workspace(repoName),
		);

		assert.equal(provision?.baseOid, "headoid");
		assert.ok(calls.find((c) => has(c, "worktree", "add"))?.args.includes("--detach"));
	});
});
