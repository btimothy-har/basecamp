import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	acquireSessionLease,
	classifySessionWorktree,
	isWorktreeClean,
	leaseOwnedBy,
	parseSessionLease,
	reapSessionWorktree,
	SESSION_COLD_TTL_MS,
	sessionLeaseReason,
} from "../worktrees/lease.ts";

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

describe("session lease reason", () => {
	it("round-trips sessionId and timestamp", () => {
		const now = new Date("2026-07-23T10:00:00.000Z");
		const reason = sessionLeaseReason("sess-abc123", now);
		assert.equal(reason, "basecamp session sess-abc123 2026-07-23T10:00:00.000Z");

		const parsed = parseSessionLease(reason);
		assert.deepEqual(parsed, { sessionId: "sess-abc123", timestamp: now.getTime() });
	});

	it("returns null for non-session or malformed reasons", () => {
		assert.equal(parseSessionLease(null), null);
		assert.equal(parseSessionLease(undefined), null);
		assert.equal(parseSessionLease("basecamp agent run 2026-07-23T10:00:00.000Z"), null);
		assert.equal(parseSessionLease("basecamp session onlyid"), null);
		assert.equal(parseSessionLease("basecamp session id not-a-date"), null);
		assert.equal(parseSessionLease("basecamp session  2026-07-23T10:00:00.000Z"), null);
	});

	it("leaseOwnedBy matches only the owning session id", () => {
		const reason = sessionLeaseReason("mine");
		assert.equal(leaseOwnedBy(reason, "mine"), true);
		assert.equal(leaseOwnedBy(reason, "other"), false);
		assert.equal(leaseOwnedBy("basecamp agent run 2026-07-23T10:00:00.000Z", "mine"), false);
		assert.equal(leaseOwnedBy(null, "mine"), false);
	});
});

describe("classifySessionWorktree", () => {
	const now = Date.parse("2026-07-23T12:00:00.000Z");

	it("treats an unlocked worktree as cold (leaseless residue)", () => {
		assert.equal(classifySessionWorktree({ locked: false, lockReason: null }, now), "cold");
	});

	it("treats a fresh session lease as live", () => {
		const reason = sessionLeaseReason("s", new Date(now - 60_000));
		assert.equal(classifySessionWorktree({ locked: true, lockReason: reason }, now), "live");
	});

	it("treats a session lease past the TTL as cold", () => {
		const reason = sessionLeaseReason("s", new Date(now - SESSION_COLD_TTL_MS - 1));
		assert.equal(classifySessionWorktree({ locked: true, lockReason: reason }, now), "cold");
	});

	it("treats a non-session (agent) lock as foreign", () => {
		assert.equal(
			classifySessionWorktree({ locked: true, lockReason: "basecamp agent run 2026-07-23T10:00:00.000Z" }, now),
			"foreign",
		);
	});
});

describe("acquireSessionLease", () => {
	it("unlocks then locks with a fresh session reason", async () => {
		const { pi, calls } = recordingPi(() => OK);
		const now = new Date("2026-07-23T10:00:00.000Z");

		await acquireSessionLease(pi, "/repo", "/repo/wt", "sess-1", now);

		assert.deepEqual(calls[0], ["-C", "/repo", "worktree", "unlock", "/repo/wt"]);
		assert.deepEqual(calls[1], [
			"-C",
			"/repo",
			"worktree",
			"lock",
			"--reason",
			"basecamp session sess-1 2026-07-23T10:00:00.000Z",
			"/repo/wt",
		]);
	});
});

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
