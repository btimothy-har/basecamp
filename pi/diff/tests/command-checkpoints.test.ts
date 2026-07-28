import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { getCheckpoint } from "#diff/checkpoints.ts";
import { BASE, HEAD_SHA, harness, herdrEnv, PREV_SHA, WORKTREE } from "./support/diff-harness.ts";

function argsFor(calls: { command: string; args: string[] }[], command: string, prefix: string): string[] | undefined {
	return calls.find((c) => c.command === command && c.args.join(" ").startsWith(prefix))?.args;
}

/** The quoted argv handed to the pane's shell: 'hunk' 'diff' '<target>' [...]. */
function hunkArgvOf(calls: { command: string; args: string[] }[]): string[] | undefined {
	return argsFor(calls, "herdr", "pane run")?.slice(3);
}

describe("/diff checkpoints", () => {
	it("rejects an unknown argument without touching the shell", async (t) => {
		herdrEnv(t);
		const h = harness({ args: "frobnicate" });

		await h.run();

		assert.equal(h.calls.length, 0);
		assert.equal(h.notices[0]?.type, "error");
		assert.match(h.notices[0]?.message ?? "", /Unknown \/diff argument/);
	});

	it("records HEAD as the checkpoint after a completed review", async (t) => {
		herdrEnv(t);
		const h = harness();

		assert.equal(getCheckpoint(WORKTREE), undefined);
		await h.run();

		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: HEAD_SHA });
	});

	it("/diff last launches hunk on the recorded checkpoint and keeps it", async (t) => {
		herdrEnv(t);
		const h = harness({ args: "last", checkpoint: { base: BASE, last: PREV_SHA } });

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${PREV_SHA}'`]);
		assert.deepEqual(argsFor(h.calls, "herdr", "tab create")?.slice(6, 8), ["--label", "diff: feature (last)"]);
		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: PREV_SHA }, "last never advances");
	});

	it("/diff last without a checkpoint falls back to the full diff and records", async (t) => {
		herdrEnv(t);
		const h = harness({ args: "last" });

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${BASE}'`]);
		assert.ok(h.notices.some((n) => /no checkpoint recorded yet/.test(n.message)));
		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: HEAD_SHA });
	});

	it("drops a checkpoint whose base no longer resolves, then /diff last falls back", async (t) => {
		// Worktree directories are reused across branches; a checkpoint taken on
		// the previous branch must not anchor a diff on this one.
		herdrEnv(t);
		const h = harness({ args: "last", checkpoint: { base: "some-older-base", last: PREV_SHA } });

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${BASE}'`]);
		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: HEAD_SHA });
	});

	it("a second /diff last repeats the same incremental diff", async (t) => {
		herdrEnv(t);
		const first = harness();
		await first.run();
		const second = harness({ args: "last" });

		await second.run();

		assert.deepEqual(hunkArgvOf(second.calls), ["'hunk'", "'diff'", `'${HEAD_SHA}'`]);
		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: HEAD_SHA });
	});

	it("does not record a checkpoint when the review never completed", async (t) => {
		herdrEnv(t);
		const h = harness({ noteReads: [{ fail: "daemon gone" }] });

		await h.run();

		assert.equal(getCheckpoint(WORKTREE), undefined);
	});

	it("re-records idempotently when HEAD has not moved", async (t) => {
		herdrEnv(t);
		const h = harness({ checkpoint: { base: BASE, last: HEAD_SHA } });

		await h.run();

		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: HEAD_SHA });
		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${BASE}'`]);
	});
});
