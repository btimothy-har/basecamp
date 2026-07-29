import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	acquireSessionLease,
	classifySessionWorktree,
	leaseOwnedBy,
	parseSessionLease,
	parseStagedLock,
	SESSION_COLD_TTL_MS,
	SESSION_STAGED_TTL_MS,
	sessionLeaseReason,
	stagedLockReason,
	stageWorktreeLock,
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

describe("staged lock reason", () => {
	it("round-trips the timestamp", () => {
		const now = new Date("2026-07-23T10:00:00.000Z");
		const reason = stagedLockReason(now);
		assert.equal(reason, "basecamp staged 2026-07-23T10:00:00.000Z");
		assert.equal(parseStagedLock(reason), now.getTime());
	});

	it("returns null for non-staged or malformed reasons", () => {
		assert.equal(parseStagedLock(null), null);
		assert.equal(parseStagedLock(undefined), null);
		assert.equal(parseStagedLock(sessionLeaseReason("s")), null);
		assert.equal(parseStagedLock("basecamp agent run 2026-07-23T10:00:00.000Z"), null);
		assert.equal(parseStagedLock("basecamp staged not-a-date"), null);
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

	it("treats a fresh staged lock as live (staged, awaiting its session)", () => {
		const reason = stagedLockReason(new Date(now - 60_000));
		assert.equal(classifySessionWorktree({ locked: true, lockReason: reason }, now), "live");
	});

	it("treats a staged lock past the staged TTL as cold (never launched)", () => {
		const reason = stagedLockReason(new Date(now - SESSION_STAGED_TTL_MS - 1));
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
	function lockStatePi(lockReason: string | null): { pi: ExtensionAPI; calls: string[][] } {
		const lockLine = lockReason === null ? "" : `locked ${lockReason}\n`;
		const listOut = `worktree /repo\nbranch refs/heads/main\n\nworktree /repo/wt\nbranch refs/heads/wt/x\n${lockLine}\n`;
		return recordingPi((args) => (args.includes("list") ? { code: 0, stdout: listOut, stderr: "" } : OK));
	}

	it("unlocks then locks an unleased worktree with a fresh session reason", async () => {
		const { pi, calls } = lockStatePi(null);
		const now = new Date("2026-07-23T10:00:00.000Z");

		await acquireSessionLease(pi, "/repo", "/repo/wt", "sess-1", now);

		assert.deepEqual(calls[1], ["-C", "/repo", "worktree", "unlock", "/repo/wt"]);
		assert.deepEqual(calls[2], [
			"-C",
			"/repo",
			"worktree",
			"lock",
			"--reason",
			"basecamp session sess-1 2026-07-23T10:00:00.000Z",
			"/repo/wt",
		]);
	});

	it("re-leases over an existing session lease (ownership takeover)", async () => {
		const { pi, calls } = lockStatePi(sessionLeaseReason("previous-session"));

		await acquireSessionLease(pi, "/repo", "/repo/wt", "sess-1");

		assert.ok(calls.some((c) => c.includes("unlock")));
		const lock = calls.find((c) => c.includes("lock") && c.includes("--reason"));
		assert.ok(lock, "expected a lock call");
		assert.equal(parseSessionLease(lock[lock.indexOf("--reason") + 1])?.sessionId, "sess-1");
	});

	it("never clobbers a foreign (agent) lock — the worktree stays the other tier's", async () => {
		const { pi, calls } = lockStatePi("basecamp agent run 2026-07-23T09:00:00.000Z");

		await acquireSessionLease(pi, "/repo", "/repo/wt", "sess-1");

		assert.ok(!calls.some((c) => c.includes("unlock")), "a foreign lock must never be unlocked");
		assert.ok(
			!calls.some((c) => c.includes("lock") && c.includes("--reason")),
			"a session lease must never overwrite a foreign lock",
		);
	});

	it("takes over a staged lock — the session the worktree was staged for re-leases it", async () => {
		const { pi, calls } = lockStatePi(stagedLockReason(new Date("2026-07-23T09:00:00.000Z")));

		await acquireSessionLease(pi, "/repo", "/repo/wt", "sess-1");

		assert.ok(
			calls.some((c) => c.includes("unlock")),
			"a staged lock is breakable by the attaching session",
		);
		const lock = calls.find((c) => c.includes("lock") && c.includes("--reason"));
		assert.ok(lock, "expected a lock call");
		assert.equal(parseSessionLease(lock[lock.indexOf("--reason") + 1])?.sessionId, "sess-1");
	});
});

describe("stageWorktreeLock", () => {
	// Models git lock state across calls: lock/unlock mutate it, list reports it. With
	// failUnlock the unlock leg errors (swallowed by stageWorktreeLock) and the lock leg hits
	// git's tolerated "already locked", so the old reason survives — the masked-refresh case.
	function lockStatePi(lockReason: string | null, failUnlock = false): { pi: ExtensionAPI; calls: string[][] } {
		let current = lockReason;
		const calls: string[][] = [];
		const pi = {
			async exec(command: string, args: string[]): Promise<ExecResult> {
				assert.equal(command, "git");
				calls.push(args);
				if (args.includes("list")) {
					const lockLine = current === null ? "" : `locked ${current}\n`;
					return {
						code: 0,
						stdout: `worktree /repo\nbranch refs/heads/main\n\nworktree /repo/wt\nbranch refs/heads/wt/x\n${lockLine}\n`,
						stderr: "",
					};
				}
				if (args.includes("unlock")) {
					if (failUnlock) return { code: 1, stdout: "", stderr: "fatal: cannot unlock" };
					current = null;
					return OK;
				}
				if (args.includes("lock") && args.includes("--reason")) {
					if (failUnlock) return { code: 1, stdout: "", stderr: "fatal: '/repo/wt' is already locked" };
					current = args[args.indexOf("--reason") + 1] ?? null;
				}
				return OK;
			},
		} as ExtensionAPI;
		return { pi, calls };
	}

	const now = new Date("2026-07-23T12:00:00.000Z");
	const freshReason = "basecamp staged 2026-07-23T12:00:00.000Z";

	function stagedLockCall(calls: string[][]): string[] | undefined {
		return calls.find((c) => c.includes("lock") && c.includes("--reason"));
	}

	it("locks an unlocked worktree with a staged reason", async () => {
		const { pi, calls } = lockStatePi(null);

		await stageWorktreeLock(pi, "/repo", "/repo/wt", now);

		const lock = stagedLockCall(calls);
		assert.ok(lock, "expected a lock call");
		assert.equal(lock[lock.indexOf("--reason") + 1], freshReason);
	});

	it("leaves a fresh staged lock in place — re-stamping gains no TTL headroom", async () => {
		const { pi, calls } = lockStatePi(stagedLockReason(new Date(now.getTime() - 60_000)));

		await stageWorktreeLock(pi, "/repo", "/repo/wt", now);

		assert.ok(!calls.some((c) => c.includes("unlock")), "a fresh staged lock is left alone");
		assert.equal(stagedLockCall(calls), undefined);
	});

	it("refreshes a staged lock past its TTL", async () => {
		const stale = stagedLockReason(new Date(now.getTime() - SESSION_STAGED_TTL_MS - 1));
		const { pi, calls } = lockStatePi(stale);

		await stageWorktreeLock(pi, "/repo", "/repo/wt", now);

		assert.ok(
			calls.some((c) => c.includes("unlock")),
			"refresh unlocks before re-locking",
		);
		const lock = stagedLockCall(calls);
		assert.equal(lock?.[lock.indexOf("--reason") + 1], freshReason);
	});

	it("never clobbers a live session lease — re-staging an adopted worktree leaves the owner's lease", async () => {
		const { pi, calls } = lockStatePi(sessionLeaseReason("owner", new Date(now.getTime() - 60_000)));

		await stageWorktreeLock(pi, "/repo", "/repo/wt", now);

		assert.ok(!calls.some((c) => c.includes("unlock")), "a session lease must not be unlocked by staging");
		assert.equal(stagedLockCall(calls), undefined);
	});

	it("re-stamps a worktree held by a cold session lease (killed-session residue)", async () => {
		const staleLease = sessionLeaseReason("dead", new Date(now.getTime() - SESSION_COLD_TTL_MS - 1));
		const { pi, calls } = lockStatePi(staleLease);

		await stageWorktreeLock(pi, "/repo", "/repo/wt", now);

		const lock = stagedLockCall(calls);
		assert.ok(lock, "a cold lease must not block re-staging");
		assert.equal(lock[lock.indexOf("--reason") + 1], freshReason);
	});

	it("never clobbers a foreign (agent) lock", async () => {
		const { pi, calls } = lockStatePi("basecamp agent run 2026-07-23T09:00:00.000Z");

		await stageWorktreeLock(pi, "/repo", "/repo/wt", now);

		assert.ok(!calls.some((c) => c.includes("unlock")), "a foreign lock must never be unlocked");
		assert.equal(stagedLockCall(calls), undefined);
	});

	it("throws when the stamp cannot be confirmed (failed unlock masked by 'already locked')", async () => {
		const stale = stagedLockReason(new Date(now.getTime() - SESSION_STAGED_TTL_MS - 1));
		const { pi } = lockStatePi(stale, true);

		await assert.rejects(stageWorktreeLock(pi, "/repo", "/repo/wt", now), /Failed to take the staged lock/);
	});
});
