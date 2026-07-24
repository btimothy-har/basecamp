import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../../../git/constants.ts";
import { useTempWorktreesRoot } from "../../../git/tests/worktree-root.ts";
import { collectPruneCandidates, confirmAndPrune, type PruneCandidate, pruneWorktree } from "../prune.ts";

useTempWorktreesRoot();

const IDENTITY = "org/repo";
const REPO_ROOT = "/repo";

type ExecResult = { code: number; stdout: string; stderr: string };

function wt(label: string): string {
	return path.join(worktreesRoot(), IDENTITY, label);
}

interface Spec {
	label: string;
	branch: string;
	dirty?: boolean;
	/** Raw `git worktree lock` reason to present for this worktree. */
	lock?: string;
}

function listPi(specs: Spec[]): { pi: ExtensionAPI; calls: string[][] } {
	const calls: string[][] = [];
	const dirtyByPath = new Map(specs.map((s) => [wt(s.label), s.dirty === true]));
	const blocks = [`worktree ${REPO_ROOT}`, "branch refs/heads/main", ""];
	for (const s of specs) {
		blocks.push(`worktree ${wt(s.label)}`, `branch refs/heads/${s.branch}`);
		if (s.lock !== undefined) blocks.push(`locked ${s.lock}`);
		blocks.push("");
	}
	const pi = {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			calls.push(args);
			assert.equal(command, "git");
			if (args.includes("list")) return { code: 0, stdout: blocks.join("\n"), stderr: "" };
			if (args.includes("status")) {
				const dir = args[args.indexOf("-C") + 1] ?? "";
				return { code: 0, stdout: dirtyByPath.get(dir) ? " M f\n" : "", stderr: "" };
			}
			return { code: 0, stdout: "", stderr: "" };
		},
	} as ExtensionAPI;
	return { pi, calls };
}

describe("collectPruneCandidates", () => {
	it("lists non-active session worktrees and excludes agent + active", async () => {
		const { pi } = listPi([
			{ label: "wt-bt/feature", branch: "bt/feature" },
			{ label: "copilot/slug", branch: "bt/slug", dirty: true },
			{ label: "agent-3f9a2c/worker", branch: "agent/x" },
			{ label: "wt-bt/active", branch: "bt/active" },
		]);

		const candidates = await collectPruneCandidates(pi, REPO_ROOT, IDENTITY, wt("wt-bt/active"));
		const labels = candidates.map((c) => c.label).sort();

		assert.deepEqual(labels, ["copilot/slug", "wt-bt/feature"]);
		assert.equal(candidates.find((c) => c.label === "copilot/slug")?.dirty, true);
		assert.equal(candidates.find((c) => c.label === "wt-bt/feature")?.dirty, false);
	});

	it("marks live-leased and foreign-locked worktrees as in use; cold and unlocked as not", async () => {
		const fresh = new Date().toISOString();
		const expired = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
		const { pi } = listPi([
			{ label: "wt-bt/live", branch: "bt/live", lock: `basecamp session sess-other ${fresh}` },
			{ label: "wt-bt/expired", branch: "bt/expired", lock: `basecamp session sess-gone ${expired}` },
			{ label: "wt-bt/manual", branch: "bt/manual", lock: "keep out" },
			{ label: "wt-bt/unlocked", branch: "bt/unlocked" },
		]);

		const candidates = await collectPruneCandidates(pi, REPO_ROOT, IDENTITY, null);
		const inUseByLabel = new Map(candidates.map((c) => [c.label, c.inUse]));

		assert.equal(inUseByLabel.get("wt-bt/live"), true, "a fresh session lease means a live session");
		assert.equal(inUseByLabel.get("wt-bt/expired"), false, "an expired lease is cold — plain candidate");
		assert.equal(inUseByLabel.get("wt-bt/manual"), true, "a foreign lock is not ours to break silently");
		assert.equal(inUseByLabel.get("wt-bt/unlocked"), false);
	});
});

describe("pruneWorktree", () => {
	const target: PruneCandidate = {
		label: "wt-bt/feature",
		path: wt("wt-bt/feature"),
		branch: "bt/feature",
		dirty: false,
		inUse: false,
	};

	it("removes the worktree and keeps the branch by default", async () => {
		const { pi, calls } = listPi([]);
		await pruneWorktree(pi, REPO_ROOT, target, false);
		assert.ok(calls.some((c) => c.includes("remove") && c.includes("--force")));
		assert.ok(!calls.some((c) => c.includes("branch")));
	});

	it("deletes the branch on explicit opt-in", async () => {
		const { pi, calls } = listPi([]);
		await pruneWorktree(pi, REPO_ROOT, target, true);
		assert.ok(calls.some((c) => c.includes("remove")));
		const branchCall = calls.find((c) => c.includes("branch"));
		assert.deepEqual(branchCall, ["-C", REPO_ROOT, "branch", "-D", "bt/feature"]);
	});

	it("never deletes a null branch even when opted in", async () => {
		const { pi, calls } = listPi([]);
		await pruneWorktree(pi, REPO_ROOT, { ...target, branch: null }, true);
		assert.ok(!calls.some((c) => c.includes("branch")));
	});
});

describe("confirmAndPrune dirty-confirmation gate", () => {
	const dirty: PruneCandidate = {
		label: "wt-bt/wip",
		path: wt("wt-bt/wip"),
		branch: "bt/wip",
		dirty: true,
		inUse: false,
	};

	function ctxWithConfirms(answers: boolean[]): { ctx: ExtensionContext; notes: string[] } {
		const notes: string[] = [];
		const queue = [...answers];
		const ctx = {
			ui: {
				confirm: async () => queue.shift() ?? false,
				notify: (m: string) => notes.push(m),
			},
		} as unknown as ExtensionContext;
		return { ctx, notes };
	}

	it("does not remove a dirty worktree when the confirmation is declined", async () => {
		const { pi, calls } = listPi([]);
		const { ctx, notes } = ctxWithConfirms([false]);
		const removed = await confirmAndPrune(pi, ctx, REPO_ROOT, dirty);
		assert.equal(removed, false);
		assert.ok(!calls.some((c) => c.includes("remove")), "declined dirty prune must not remove");
		assert.ok(notes.some((n) => /cancelled/i.test(n)));
	});

	it("removes a dirty worktree only after explicit confirmation (branch kept by default)", async () => {
		const { pi, calls } = listPi([]);
		// first confirm = remove-anyway (true), second confirm = delete-branch (false)
		const { ctx } = ctxWithConfirms([true, false]);
		const removed = await confirmAndPrune(pi, ctx, REPO_ROOT, dirty);
		assert.equal(removed, true);
		assert.ok(calls.some((c) => c.includes("remove") && c.includes("--force")));
		assert.ok(!calls.some((c) => c.includes("branch")), "branch kept unless delete is confirmed");
	});

	const inUse: PruneCandidate = {
		label: "wt-bt/other",
		path: wt("wt-bt/other"),
		branch: "bt/other",
		dirty: false,
		inUse: true,
	};

	it("does not remove a clean in-use worktree when the confirmation is declined", async () => {
		const { pi, calls } = listPi([]);
		const { ctx, notes } = ctxWithConfirms([false]);
		const removed = await confirmAndPrune(pi, ctx, REPO_ROOT, inUse);
		assert.equal(removed, false);
		assert.ok(!calls.some((c) => c.includes("remove")), "another live session's worktree must never go silently");
		assert.ok(notes.some((n) => /cancelled/i.test(n)));
	});

	it("removes an in-use worktree only after explicit confirmation", async () => {
		const { pi, calls } = listPi([]);
		// first confirm = in-use remove-anyway (true), second confirm = delete-branch (false)
		const { ctx } = ctxWithConfirms([true, false]);
		const removed = await confirmAndPrune(pi, ctx, REPO_ROOT, inUse);
		assert.equal(removed, true);
		assert.ok(calls.some((c) => c.includes("remove") && c.includes("--force")));
	});
});
