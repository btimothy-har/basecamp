import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDiffCommand } from "#diff/command.ts";
import { attachSession, ownedReview, rememberPane } from "#diff/session-state.ts";
import { sidecarPath } from "#diff/sidecar.ts";
import { BASE, harness, herdrEnv, NEW_SESSION, STALE_SESSION, WORKTREE } from "./support/diff-harness.ts";

function argsFor(calls: { command: string; args: string[] }[], command: string, prefix: string): string[] | undefined {
	return calls.find((c) => c.command === command && c.args.join(" ").startsWith(prefix))?.args;
}

function writeStubSidecar(base: string): string {
	const target = sidecarPath(WORKTREE);
	fs.mkdirSync(path.dirname(target), { recursive: true });
	fs.writeFileSync(target, JSON.stringify({ version: 1, basecampBase: base, summary: "s", files: [] }));
	return target;
}

function order(calls: { command: string; args: string[] }[]): string[] {
	return calls.map((c) => `${c.command} ${c.args.join(" ")}`);
}

describe("/diff", () => {
	it("refuses outside Herdr without touching the shell", async (t) => {
		herdrEnv(t, { HERDR_ENV: undefined });
		const h = harness();

		await h.run();

		assert.equal(h.calls.length, 0);
		assert.match(h.notices[0]?.message ?? "", /not running in Herdr/);
	});

	it("refuses when hunk is missing, before splitting a pane", async (t) => {
		herdrEnv(t);
		const h = harness({ hunkAvailable: false });

		await h.run();

		assert.equal(h.notices[0]?.type, "error");
		assert.equal(argsFor(h.calls, "herdr", "pane split"), undefined);
	});

	it("splits a pane in this tab and launches hunk on the merge-base", async (t) => {
		herdrEnv(t);
		const h = harness();

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane split"), [
			"pane",
			"split",
			"w9:p1",
			"--direction",
			"right",
			"--ratio",
			"0.5",
			"--cwd",
			WORKTREE,
			"--no-focus",
			"--env",
			"HUNK_DISABLE_UPDATE_NOTICE=1",
		]);
		assert.deepEqual(argsFor(h.calls, "herdr", "pane run"), ["pane", "run", "w9:p2", "'hunk'", "'diff'", `'${BASE}'`]);
		assert.deepEqual(argsFor(h.calls, "herdr", "pane close"), ["pane", "close", "w9:p2"]);
	});

	it("reads notes by the launched session id, never by repo", async (t) => {
		herdrEnv(t);
		const h = harness({ preexisting: ["someone-elses-session"], noteReads: [[]] });

		await h.run();

		const read = argsFor(h.calls, "hunk", "session comment list");
		assert.deepEqual(read, ["session", "comment", "list", NEW_SESSION, "--type", "user", "--json"]);
	});

	it("passes the sidecar when it was stamped against this base", async (t) => {
		herdrEnv(t);
		const target = writeStubSidecar(BASE);
		const h = harness();

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane run")?.slice(4), [
			"'diff'",
			`'${BASE}'`,
			"'--agent-context'",
			`'${target}'`,
		]);
	});

	it("ignores a sidecar left behind for a different base", async (t) => {
		// Worktree directories are reused across branches, so an unstamped match
		// would render one branch's rationale against another branch's lines.
		herdrEnv(t);
		writeStubSidecar("some-older-base");
		const h = harness();

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane run")?.slice(4), ["'diff'", `'${BASE}'`]);
	});

	it("sends line-anchored annotations back as a user prompt", async (t) => {
		herdrEnv(t);
		const h = harness({
			noteReads: [
				[
					{ filePath: "pi/diff/hunk.ts", newRange: [12, 20], body: "narrow this type" },
					{ filePath: "README.md", newRange: [3, 3], body: "typo" },
				],
			],
		});

		await h.run();

		assert.equal(h.sent.length, 1);
		assert.match(h.sent[0]?.content ?? "", /pi\/diff\/hunk\.ts:12-20/);
		assert.match(h.sent[0]?.content ?? "", /2 annotations/);
	});

	it("still reads annotations when the confirm is cancelled", async (t) => {
		herdrEnv(t);
		const h = harness({ confirm: false, noteReads: [[{ filePath: "a.ts", newRange: [1, 1], body: "keep me" }]] });

		await h.run();

		assert.match(h.sent[0]?.content ?? "", /keep me/);
	});

	it("keeps the hunk window open and reports when the note read fails", async (t) => {
		herdrEnv(t);
		const h = harness({ noteReads: [{ fail: "Multiple active sessions match repoRoot" }] });

		await h.run();

		assert.equal(argsFor(h.calls, "herdr", "pane close"), undefined, "a failed read must not destroy the notes");
		assert.match(h.notices.at(-1)?.message ?? "", /still open/);
		assert.equal(ownedReview(WORKTREE)?.paneId, "w9:p2", "the pane must stay reclaimable");
	});

	it("reports rather than blocking when hunk never registers a session", async (t) => {
		herdrEnv(t);
		const h = harness({ neverRegisters: true });

		await h.run();

		assert.match(h.notices.at(-1)?.message ?? "", /never registered a session/);
		assert.equal(h.sent.length, 0);
	});

	it("delivers carried notes when the pane fails to split", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pStale");
		attachSession(WORKTREE, STALE_SESSION);
		const h = harness({
			preexisting: [STALE_SESSION],
			paneSplitCode: 3,
			noteReads: [[{ filePath: "old.ts", newRange: [4, 4], body: "earlier" }]],
		});

		await h.run();

		assert.match(h.notices.at(-1)?.message ?? "", /could not split a Herdr pane/);
		assert.match(h.sent[0]?.content ?? "", /earlier/, "drained notes must not be discarded on failure");
	});

	it("closes the pane and delivers carried notes when hunk fails to launch", async (t) => {
		herdrEnv(t);
		const h = harness({ paneRunCode: 4 });

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane close"), ["pane", "close", "w9:p2"]);
		assert.match(h.notices.at(-1)?.message ?? "", /could not start hunk/);
	});

	it("drains an owned stale review by session id before replacing it", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pStale");
		attachSession(WORKTREE, STALE_SESSION);
		const h = harness({
			preexisting: [STALE_SESSION],
			noteReads: [
				[{ filePath: "old.ts", newRange: [7, 7], body: "from the abandoned review" }],
				[{ filePath: "new.ts", newRange: [9, 9], body: "from this review" }],
			],
		});

		await h.run();

		const seq = order(h.calls);
		const staleRead = seq.findIndex((c) => c.includes(STALE_SESSION));
		const staleClose = seq.indexOf("herdr pane close w9:pStale");
		const split = seq.findIndex((c) => c.startsWith("herdr pane split"));
		assert.ok(staleRead >= 0 && staleClose >= 0, "the stale review must be read and its pane closed");
		assert.ok(staleRead < staleClose, "notes must be read before the pane that holds them is closed");
		assert.ok(staleClose < split, "the stale pane must go before a replacement opens");
		assert.match(h.sent[0]?.content ?? "", /from the abandoned review/);
		assert.match(h.sent[0]?.content ?? "", /from this review/);
	});

	it("recovers when the remembered session died with its pane", async (t) => {
		// Quitting hunk without confirming loses that review; the id left behind must
		// not then fail every future /diff for the lifetime of the process.
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pDead");
		attachSession(WORKTREE, STALE_SESSION);
		const h = harness({ preexisting: [], noteReads: [{ fail: "No active session matches sessionId" }, []] });

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane split")?.slice(0, 2), ["pane", "split"], "must still open a diff");
		assert.match(h.notices[0]?.message ?? "", /previous review/);
		assert.equal(ownedReview(WORKTREE)?.sessionId, NEW_SESSION, "the dead id must be replaced, not retained");
	});

	it("recovers when a pane that never registered a session can no longer be closed", async (t) => {
		// `herdr pane close` exits 1 for a pane that is already gone, so retrying it
		// forever would strand /diff exactly as the dead-session case did. No session
		// ever attached here, so there are no notes to protect by stopping.
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pGone");
		const h = harness({ paneCloseCode: 7, noteReads: [[]] });

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane split")?.slice(0, 2), ["pane", "split"], "must still open a diff");
		assert.equal(ownedReview(WORKTREE)?.paneId, "w9:p2", "the unclosable pane must not keep displacing new ones");
	});

	it("leaves a foreign hunk session alone", async (t) => {
		herdrEnv(t);
		const h = harness({ preexisting: ["not-ours"], noteReads: [[]] });

		await h.run();

		const reads = h.calls.filter((c) => c.args.join(" ").startsWith("session comment list"));
		assert.equal(reads.length, 1, "only the session /diff launched may be read");
		assert.deepEqual(argsFor(h.calls, "herdr", "pane close"), ["pane", "close", "w9:p2"]);
	});

	it("keeps the pane id when the close fails so a later run can reclaim it", async (t) => {
		herdrEnv(t);
		const h = harness({ paneCloseCode: 7, noteReads: [[]] });

		await h.run();

		assert.equal(ownedReview(WORKTREE)?.paneId, "w9:p2");
	});

	it("is not registered in a subagent process", async (t) => {
		herdrEnv(t, { BASECAMP_AGENT_DEPTH: "1" });
		let registered = false;
		const pi = {
			registerCommand: () => {
				registered = true;
			},
		} as unknown as ExtensionAPI;

		registerDiffCommand(pi);

		assert.equal(registered, false);
	});
});
