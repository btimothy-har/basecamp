import assert from "node:assert/strict";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	forgetCheckpoint,
	getCheckpoint,
	lastCheckpointOrHead,
	recordCheckpoint,
	validateCheckpoint,
} from "#diff/checkpoints.ts";

/**
 * The checkpoint store is process-global: every test pins its own worktree dir
 * and forgets it afterwards, or a leaked checkpoint would bleed into the next
 * test (and into lastCheckpointOrHead's no-exec assertions).
 */
function worktree(t: TestContext, name: string): string {
	const dir = `/wt/checkpoints-${name}`;
	t.after(() => forgetCheckpoint(dir));
	return dir;
}

function recordingPi(stdout: string, calls: string[][]): ExtensionAPI {
	return {
		exec: async (_command: string, args: string[]) => {
			calls.push(args);
			return { code: 0, stdout, stderr: "", killed: false };
		},
	} as unknown as ExtensionAPI;
}

const THROWING_PI = {
	exec: async () => {
		throw new Error("exec must not be called when a checkpoint is recorded");
	},
} as unknown as ExtensionAPI;

describe("checkpoints", () => {
	it("record + get round-trips {base, last}", (t) => {
		const dir = worktree(t, "round-trip");
		const checkpoint = { base: "base1234", last: "head5678" };
		recordCheckpoint(dir, checkpoint);
		assert.deepEqual(getCheckpoint(dir), checkpoint);
	});

	it("get returns undefined for an unknown worktree", (t) => {
		const dir = worktree(t, "unknown");
		assert.equal(getCheckpoint(dir), undefined);
	});

	it("record overwrites an existing checkpoint", (t) => {
		const dir = worktree(t, "overwrite");
		recordCheckpoint(dir, { base: "base1234", last: "first" });
		recordCheckpoint(dir, { base: "base1234", last: "second" });
		assert.deepEqual(getCheckpoint(dir), { base: "base1234", last: "second" });
	});

	it("forget drops the checkpoint", (t) => {
		const dir = worktree(t, "forget");
		recordCheckpoint(dir, { base: "base1234", last: "head5678" });
		forgetCheckpoint(dir);
		assert.equal(getCheckpoint(dir), undefined);
	});

	it("validate keeps a checkpoint whose base matches currentBase", (t) => {
		const dir = worktree(t, "validate-keep");
		const checkpoint = { base: "base1234", last: "head5678" };
		recordCheckpoint(dir, checkpoint);
		assert.deepEqual(validateCheckpoint(dir, "base1234"), checkpoint);
		assert.deepEqual(getCheckpoint(dir), checkpoint);
	});

	it("validate drops and returns undefined when base differs from currentBase", (t) => {
		const dir = worktree(t, "validate-drop");
		recordCheckpoint(dir, { base: "base1234", last: "head5678" });
		assert.equal(validateCheckpoint(dir, "other9999"), undefined);
		assert.equal(getCheckpoint(dir), undefined);
	});

	it("lastCheckpointOrHead returns checkpoint.last without execing", async (t) => {
		const dir = worktree(t, "head-recorded");
		recordCheckpoint(dir, { base: "base1234", last: "head5678" });
		assert.equal(await lastCheckpointOrHead(THROWING_PI, dir), "head5678");
	});

	it("lastCheckpointOrHead execs `git -C <dir> rev-parse HEAD` when no checkpoint", async (t) => {
		const dir = worktree(t, "head-exec");
		const calls: string[][] = [];
		const pi = recordingPi("  deadbeefcafe\n", calls);
		assert.equal(await lastCheckpointOrHead(pi, dir), "deadbeefcafe");
		assert.deepEqual(calls, [["-C", dir, "rev-parse", "HEAD"]]);
	});

	it("two worktree dirs hold independent checkpoints", (t) => {
		const a = worktree(t, "isolation-a");
		const b = worktree(t, "isolation-b");
		recordCheckpoint(a, { base: "base1234", last: "aaaa" });
		recordCheckpoint(b, { base: "base5678", last: "bbbb" });
		forgetCheckpoint(a);
		assert.equal(getCheckpoint(a), undefined);
		assert.deepEqual(getCheckpoint(b), { base: "base5678", last: "bbbb" });
	});
});
