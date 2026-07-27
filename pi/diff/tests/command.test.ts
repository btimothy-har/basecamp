import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDiffCommand } from "#diff/command.ts";
import { attachSession, ownedReview, rememberTab } from "#diff/session-state.ts";
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

	it("refuses when hunk is missing, before opening a tab", async (t) => {
		herdrEnv(t);
		const h = harness({ hunkAvailable: false });

		await h.run();

		assert.equal(h.notices[0]?.type, "error");
		assert.equal(argsFor(h.calls, "herdr", "tab create"), undefined);
	});

	it("opens a labelled tab in this workspace and launches hunk on the merge-base", async (t) => {
		herdrEnv(t);
		const h = harness();

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "tab create"), [
			"tab",
			"create",
			"--workspace",
			"w9",
			"--cwd",
			WORKTREE,
			"--label",
			"diff: feature",
			"--no-focus",
			"--env",
			"HUNK_DISABLE_UPDATE_NOTICE=1",
		]);
		assert.deepEqual(argsFor(h.calls, "herdr", "pane run"), ["pane", "run", "w9:p2", "'hunk'", "'diff'", `'${BASE}'`]);
		assert.deepEqual(argsFor(h.calls, "herdr", "tab close"), ["tab", "close", "w9:t2"]);
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

	it("sends line-anchored annotations back into the session", async (t) => {
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

		assert.equal(argsFor(h.calls, "herdr", "tab close"), undefined, "a failed read must not destroy the notes");
		assert.match(h.notices.at(-1)?.message ?? "", /still open/);
		assert.equal(ownedReview(WORKTREE)?.tabId, "w9:t2", "the tab must stay reclaimable");
	});

	it("reports rather than blocking when hunk never registers a session", async (t) => {
		herdrEnv(t);
		const h = harness({ neverRegisters: true });

		await h.run();

		assert.match(h.notices.at(-1)?.message ?? "", /never registered a session/);
		assert.equal(h.sent.length, 0);
	});

	it("delivers carried notes when the tab fails to open", async (t) => {
		herdrEnv(t);
		rememberTab(WORKTREE, "w9:tStale");
		attachSession(WORKTREE, STALE_SESSION);
		const h = harness({
			preexisting: [STALE_SESSION],
			tabCreateCode: 3,
			noteReads: [[{ filePath: "old.ts", newRange: [4, 4], body: "earlier" }]],
		});

		await h.run();

		assert.match(h.notices.at(-1)?.message ?? "", /could not open a Herdr tab/);
		assert.match(h.sent[0]?.content ?? "", /earlier/, "drained notes must not be discarded on failure");
	});

	it("closes the tab and delivers carried notes when hunk fails to launch", async (t) => {
		herdrEnv(t);
		const h = harness({ paneRunCode: 4 });

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "tab close"), ["tab", "close", "w9:t2"]);
		assert.match(h.notices.at(-1)?.message ?? "", /could not start hunk/);
	});

	it("drains an owned stale review by session id before replacing it", async (t) => {
		herdrEnv(t);
		rememberTab(WORKTREE, "w9:tStale");
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
		const staleClose = seq.indexOf("herdr tab close w9:tStale");
		const create = seq.findIndex((c) => c.startsWith("herdr tab create"));
		assert.ok(staleRead >= 0 && staleClose >= 0, "the stale review must be read and its tab closed");
		assert.ok(staleRead < staleClose, "notes must be read before the window that holds them is closed");
		assert.ok(staleClose < create, "the stale tab must go before a replacement opens");
		assert.match(h.sent[0]?.content ?? "", /from the abandoned review/);
		assert.match(h.sent[0]?.content ?? "", /from this review/);
	});

	it("leaves a foreign hunk session alone", async (t) => {
		herdrEnv(t);
		const h = harness({ preexisting: ["not-ours"], noteReads: [[]] });

		await h.run();

		const reads = h.calls.filter((c) => c.args.join(" ").startsWith("session comment list"));
		assert.equal(reads.length, 1, "only the session /diff launched may be read");
		assert.deepEqual(argsFor(h.calls, "herdr", "tab close"), ["tab", "close", "w9:t2"]);
	});

	it("keeps the tab id when the close fails so a later run can reclaim it", async (t) => {
		herdrEnv(t);
		const h = harness({ tabCloseCode: 7, noteReads: [[]] });

		await h.run();

		assert.equal(ownedReview(WORKTREE)?.tabId, "w9:t2");
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
