import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { getCheckpoint } from "#diff/checkpoints.ts";
import { sidecarPath } from "#diff/sidecar.ts";
import { BASE, HEAD_SHA, harness, herdrEnv, PREV_SHA, WORKTREE } from "./support/diff-harness.ts";

/** A sidecar as `annotate_changeset` writes it: stamped with the review base. */
function writeSidecarStamped(base: string): string {
	const target = sidecarPath(WORKTREE);
	fs.mkdirSync(path.dirname(target), { recursive: true });
	fs.writeFileSync(
		target,
		JSON.stringify({
			version: 1,
			basecampBase: base,
			summary: "why",
			files: [{ path: "a.ts", annotations: [{ newRange: [1, 2], summary: "s" }] }],
		}),
	);
	return target;
}

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
		// The label names the command the user ran, so a degraded run is still
		// distinguishable from a plain /diff tab opened beside it.
		assert.deepEqual(argsFor(h.calls, "herdr", "tab create")?.slice(6, 8), ["--label", "diff: feature (last)"]);
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

	it("drops a checkpoint that is no longer in this branch's history", async (t) => {
		// Sibling branches share a merge-base, and amend/rebase orphans the recorded
		// commit; diffing against it would present rewritten work as reversals.
		herdrEnv(t);
		const h = harness({
			args: "last",
			checkpoint: { base: BASE, last: PREV_SHA },
			checkpointIsAncestor: false,
		});

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${BASE}'`]);
		assert.ok(h.notices.some((n) => /no longer in this branch's history/.test(n.message)));
		assert.deepEqual(getCheckpoint(WORKTREE), { base: BASE, last: HEAD_SHA }, "the stale checkpoint is replaced");
	});
});

describe("/diff agent rationale", () => {
	it("attaches a base-stamped sidecar to a full review and consumes it", async (t) => {
		// The regression this guards: annotations were stamped with one anchor and
		// attached on another, so a full /diff rendered nothing and cleared anyway.
		herdrEnv(t);
		const target = writeSidecarStamped(BASE);
		const h = harness();

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${BASE}'`, "'--agent-context'", `'${target}'`]);
		assert.equal(fs.existsSync(target), false, "a rendered sidecar is consumed at review close");
	});

	it("attaches the same sidecar to an incremental review", async (t) => {
		// Ranges are on the new side (the working tree), so span-matched rationale
		// is valid whichever target the review uses.
		herdrEnv(t);
		const target = writeSidecarStamped(BASE);
		const h = harness({ args: "last", checkpoint: { base: BASE, last: PREV_SHA } });

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${PREV_SHA}'`, "'--agent-context'", `'${target}'`]);
		assert.equal(fs.existsSync(target), false);
	});

	it("never clears a sidecar it could not render", async (t) => {
		// A stamp from another branch must not be shown — and must not be destroyed
		// unread either, or the agent's rationale is lost with no signal.
		herdrEnv(t);
		const target = writeSidecarStamped("a-different-branches-base");
		const h = harness();

		await h.run();

		assert.deepEqual(hunkArgvOf(h.calls), ["'hunk'", "'diff'", `'${BASE}'`], "stale rationale is not rendered");
		assert.equal(fs.existsSync(target), true, "an unrendered sidecar survives the review");
	});

	it("keeps the sidecar when the review never completed", async (t) => {
		herdrEnv(t);
		const target = writeSidecarStamped(BASE);
		const h = harness({ noteReads: [{ fail: "daemon gone" }] });

		await h.run();

		assert.equal(fs.existsSync(target), true);
	});
});
