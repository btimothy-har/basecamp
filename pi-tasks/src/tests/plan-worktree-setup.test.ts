import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { shouldRunWorktreeSetup, worktreeSetupSummary } from "../planning/worktree-setup.ts";

describe("shouldRunWorktreeSetup", () => {
	it("runs only for newly-created worktrees with a configured command", () => {
		assert.equal(shouldRunWorktreeSetup(true, "cmd"), true);
		assert.equal(shouldRunWorktreeSetup(false, "cmd"), false);
		assert.equal(shouldRunWorktreeSetup(true, null), false);
	});
});

describe("worktreeSetupSummary", () => {
	it("returns undefined when setup did not run", () => {
		assert.equal(worktreeSetupSummary(null), undefined);
	});

	it("summarizes successful setup without an empty stderr_tail key", () => {
		const summary = worktreeSetupSummary({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" });

		assert.deepEqual(summary, { ok: true, exit_code: 0, timed_out: false });
		assert.equal(Object.hasOwn(summary ?? {}, "stderr_tail"), false);
	});

	it("summarizes non-zero setup with stderr", () => {
		assert.deepEqual(worktreeSetupSummary({ ran: true, exitCode: 2, timedOut: false, stderrTail: "boom" }), {
			ok: false,
			exit_code: 2,
			timed_out: false,
			stderr_tail: "boom",
		});
	});

	it("summarizes timed-out setup", () => {
		const summary = worktreeSetupSummary({ ran: true, exitCode: 143, timedOut: true, stderrTail: "x" });

		assert.equal(summary?.ok, false);
		assert.equal(summary?.exit_code, 143);
		assert.equal(summary?.timed_out, true);
		assert.equal(summary?.stderr_tail, "x");
	});
});
