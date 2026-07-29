import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	isWorktreeClean,
	reapOwnedSessionWorktree,
	reapSessionWorktree,
	sessionLeaseReason,
} from "#core/git/worktrees/lease.ts";

type ExecResult = { code: number; stdout: string; stderr: string };

function recordingPi(handler: (args: string[]) => ExecResult): { pi: ExtensionAPI; calls: string[][] } {
	const calls: string[][] = [];
	const pi = {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			assert.equal(command, "git");
			calls.push(args);
			return handler(args);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

const OK: ExecResult = { code: 0, stdout: "", stderr: "" };

describe("isWorktreeClean", () => {
	it("is clean when status --porcelain is empty", async () => {
		const { pi } = recordingPi((args) => (args.includes("status") ? { code: 0, stdout: "\n", stderr: "" } : OK));
		assert.equal(await isWorktreeClean(pi, "/repo/wt"), true);
	});

	it("is dirty when status --porcelain has entries", async () => {
		const { pi } = recordingPi((args) =>
			args.includes("status") ? { code: 0, stdout: " M file.ts\n", stderr: "" } : OK,
		);
		assert.equal(await isWorktreeClean(pi, "/repo/wt"), false);
	});
});

describe("reapSessionWorktree", () => {
	it("reaps a clean worktree with --force and never deletes a branch", async () => {
		const { pi, calls } = recordingPi((args) => (args.includes("status") ? { code: 0, stdout: "", stderr: "" } : OK));

		const outcome = await reapSessionWorktree(pi, "/repo", "/repo/wt");

		assert.equal(outcome, "reaped");
		const removeCall = calls.find((c) => c.includes("remove"));
		assert.ok(removeCall?.includes("--force"), "clean reap uses --force after the clean check");
		assert.ok(!calls.some((c) => c.includes("branch")), "reap never touches the branch");
	});

	it("keeps a dirty worktree and never removes it", async () => {
		const { pi, calls } = recordingPi((args) =>
			args.includes("status") ? { code: 0, stdout: " M f\n", stderr: "" } : OK,
		);

		const outcome = await reapSessionWorktree(pi, "/repo", "/repo/wt");

		assert.equal(outcome, "kept-dirty");
		assert.ok(!calls.some((c) => c.includes("remove")), "dirty worktree is never removed");
	});

	it("reports error when status resolution fails", async () => {
		const { pi } = recordingPi(() => {
			throw new Error("git blew up");
		});
		assert.equal(await reapSessionWorktree(pi, "/repo", "/repo/wt"), "error");
	});
});

describe("reapOwnedSessionWorktree", () => {
	function leasePi(lockReason: string | null, dirty = false): { pi: ExtensionAPI; calls: string[][] } {
		const lockLine = lockReason === null ? "" : `locked ${lockReason}\n`;
		const listOut = `worktree /repo\nbranch refs/heads/main\n\nworktree /repo/wt\nbranch refs/heads/wt/x\n${lockLine}\n`;
		return recordingPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: listOut, stderr: "" };
			if (args.includes("status")) return { code: 0, stdout: dirty ? " M f\n" : "", stderr: "" };
			return OK;
		});
	}

	it("reaps a clean worktree this session owns", async () => {
		const { pi, calls } = leasePi(sessionLeaseReason("mine"));
		assert.equal(await reapOwnedSessionWorktree(pi, "/repo", "/repo/wt", "mine"), "reaped");
		assert.ok(calls.some((c) => c.includes("remove")));
	});

	it("does not reap a worktree owned by another session", async () => {
		const { pi, calls } = leasePi(sessionLeaseReason("someone-else"));
		assert.equal(await reapOwnedSessionWorktree(pi, "/repo", "/repo/wt", "mine"), "not-owned");
		assert.ok(!calls.some((c) => c.includes("remove")));
	});

	it("does not reap an unleased (unlocked) worktree", async () => {
		const { pi, calls } = leasePi(null);
		assert.equal(await reapOwnedSessionWorktree(pi, "/repo", "/repo/wt", "mine"), "not-owned");
		assert.ok(!calls.some((c) => c.includes("remove")));
	});

	it("keeps a dirty worktree even when owned", async () => {
		const { pi, calls } = leasePi(sessionLeaseReason("mine"), true);
		assert.equal(await reapOwnedSessionWorktree(pi, "/repo", "/repo/wt", "mine"), "kept-dirty");
		assert.ok(!calls.some((c) => c.includes("remove")));
	});
});
