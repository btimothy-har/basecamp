import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { getCheckpoint } from "#diff/checkpoints.ts";
import { attachSession, ownedReview, rememberPane } from "#diff/session-state.ts";
import { sidecarPath } from "#diff/sidecar.ts";
import { BASE, harness, herdrEnv, NEW_SESSION, PREV_SHA, STALE_SESSION, WORKTREE } from "./support/diff-harness.ts";

const SKEW_ERROR = "The running Hunk session daemon is missing required support for list. Restart Hunk.";

function paneMutations(calls: { command: string; args: string[] }[]): string[] {
	return calls.filter((call) => call.command === "herdr" && call.args[1] !== "get").map((call) => call.args.join(" "));
}

function writeSidecar(): string {
	const target = sidecarPath(WORKTREE);
	fs.mkdirSync(path.dirname(target), { recursive: true });
	fs.writeFileSync(target, JSON.stringify({ version: 1, basecampBase: BASE, summary: "why", files: [] }));
	return target;
}

describe("/diff hunk discovery", () => {
	it("pins the absolute executable even when PATH changes after launch", async (t) => {
		herdrEnv(t);
		const h = harness({
			onPaneRun: () => {
				process.env.PATH = "/different/pane/path";
			},
		});

		await h.run();

		const launch = h.calls.find((call) => call.args.slice(0, 2).join(" ") === "pane run");
		assert.equal(launch?.args[3], `'${h.hunkExecutable}'`);
		const hunkCalls = h.calls.filter((call) => call.args[0] === "session" || call.args[0] === "--version");
		assert.ok(hunkCalls.length >= 4);
		assert.ok(hunkCalls.every((call) => call.command === h.hunkExecutable));
		assert.deepEqual(h.notices, [{ message: "No annotations were left on the diff.", type: "info" }]);
	});

	it("stops on version skew before touching panes, notes, checkpoints, or rationale", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pStale");
		attachSession(WORKTREE, STALE_SESSION);
		const sidecar = writeSidecar();
		const stored = fs.readFileSync(sidecar, "utf8");
		const checkpoint = { base: "older-base", last: PREV_SHA };
		const h = harness({ sessionReads: [{ fail: SKEW_ERROR }], checkpoint });

		await h.run();

		assert.deepEqual(paneMutations(h.calls), []);
		assert.equal(
			h.calls.some((call) => call.args[1] === "comment"),
			false,
		);
		assert.deepEqual(ownedReview(WORKTREE), { paneId: "w9:pStale", sessionId: STALE_SESSION });
		assert.deepEqual(getCheckpoint(WORKTREE), checkpoint);
		assert.equal(fs.readFileSync(sidecar, "utf8"), stored);
		assert.deepEqual(h.sent, []);
		assert.equal(h.notices.length, 1);
		assert.equal(h.notices[0]?.type, "error");
		assert.ok(h.notices[0]?.message.includes(h.hunkExecutable));
		assert.match(h.notices[0]?.message ?? "", /0\.21\.1.*missing required support for list/);
		assert.match(h.notices[0]?.message ?? "", /restart Pi from a fresh shell/);
	});

	it("keeps a failed launch-discovery baseline and recovers its unread notes on retry", async (t) => {
		herdrEnv(t);
		const sidecar = writeSidecar();
		const checkpoint = { base: BASE, last: PREV_SHA };
		const first = harness({
			preexisting: ["foreign"],
			sessionReads: [["foreign"], { fail: SKEW_ERROR }, { fail: SKEW_ERROR }, { fail: SKEW_ERROR }],
			checkpoint,
		});

		await first.run();

		assert.deepEqual(ownedReview(WORKTREE), { paneId: "w9:p2", beforeSessionIds: ["foreign"] });
		assert.equal(
			first.calls.some((call) => call.args[1] === "close"),
			false,
		);
		assert.equal(first.calls.filter((call) => call.args.slice(0, 2).join(" ") === "session list").length, 4);
		assert.equal(first.notices.length, 1, "discovery failures must not report an empty review");
		assert.match(first.notices[0]?.message ?? "", /missing required support/);
		assert.deepEqual(getCheckpoint(WORKTREE), checkpoint);
		assert.equal(fs.existsSync(sidecar), true);

		const second = harness({
			preexisting: ["foreign", NEW_SESSION],
			launchedSessionId: "replacement",
			noteReads: [[{ filePath: "a.ts", newRange: [2, 2], body: "recover me" }], []],
		});
		await second.run();

		const reads = second.calls.filter((call) => call.args.slice(0, 3).join(" ") === "session comment list");
		assert.deepEqual(
			reads.map((call) => call.args[3]),
			[NEW_SESSION, "replacement"],
		);
		const readIndex = second.calls.indexOf(reads[0]!);
		const closeIndex = second.calls.findIndex((call) => call.args[1] === "close");
		const splitIndex = second.calls.findIndex((call) => call.args[1] === "split");
		assert.ok(readIndex < closeIndex && closeIndex < splitIndex, "recover notes before replacing the pane");
		assert.match(second.sent[0]?.content ?? "", /recover me/);
		assert.equal(fs.existsSync(sidecar), false);
	});

	it("delivers carried notes even when the replacement's discovery fails", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pStale");
		attachSession(WORKTREE, STALE_SESSION);
		const h = harness({
			sessionReads: [[STALE_SESSION], { fail: SKEW_ERROR }, { fail: SKEW_ERROR }, { fail: SKEW_ERROR }],
			noteReads: [[{ filePath: "a.ts", body: "already read" }]],
		});

		await h.run();

		assert.match(h.sent[0]?.content ?? "", /already read/);
		assert.equal(h.notices.length, 1);
		assert.match(h.notices[0]?.message ?? "", /could not discover/);
		assert.equal(h.calls.filter((call) => call.args[1] === "close").length, 1, "only the drained pane may close");
	});

	it("tolerates a transient daemon boot failure within the launch poll window", async (t) => {
		herdrEnv(t);
		const h = harness({ sessionReads: [[], { fail: "daemon port is reachable but not healthy" }, [NEW_SESSION]] });

		await h.run();

		assert.deepEqual(h.notices, [{ message: "No annotations were left on the diff.", type: "info" }]);
		assert.equal(ownedReview(WORKTREE), undefined);
		assert.equal(h.calls.filter((call) => call.args.slice(0, 2).join(" ") === "session list").length, 3);
	});

	it("does not report an earlier transient error when the final discovery succeeds empty", async (t) => {
		herdrEnv(t);
		const h = harness({ sessionReads: [[], { fail: "daemon starting" }, [], []] });

		await h.run();

		assert.equal(h.notices.length, 1);
		assert.match(h.notices[0]?.message ?? "", /never registered a session/);
	});

	it("reports the final discovery failure even after an earlier successful empty poll", async (t) => {
		herdrEnv(t);
		const h = harness({ sessionReads: [[], [], [], { fail: "daemon disconnected" }] });

		await h.run();

		assert.equal(h.notices.length, 1);
		assert.match(h.notices[0]?.message ?? "", /could not discover.*daemon disconnected/);
		assert.equal(ownedReview(WORKTREE)?.paneId, "w9:p2");
	});

	it("distinguishes a genuine registration timeout from a CLI failure", async (t) => {
		herdrEnv(t);
		const h = harness({ neverRegisters: true });

		await h.run();

		assert.equal(h.notices.length, 1);
		assert.match(h.notices[0]?.message ?? "", /never registered a session/);
		assert.deepEqual(ownedReview(WORKTREE)?.beforeSessionIds, []);
		assert.equal(
			h.calls.some((call) => call.args[1] === "close"),
			false,
		);
	});

	it("does not guess when multiple sessions appear after launch", async (t) => {
		herdrEnv(t);
		const h = harness({ sessionReads: [[], ["first", "second"]] });

		await h.run();

		assert.match(h.notices[0]?.message ?? "", /multiple new hunk sessions/);
		assert.equal(
			h.calls.some((call) => call.args[1] === "close" || call.args[1] === "comment"),
			false,
		);
		assert.equal(ownedReview(WORKTREE)?.sessionId, undefined);
	});
});

describe("/diff pending-review safety", () => {
	it("keeps a legacy untracked pane even if exactly one session is live", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pLegacy");
		const h = harness({ preexisting: ["possibly-foreign"] });

		await h.run();

		assert.deepEqual(paneMutations(h.calls), []);
		assert.match(h.notices[0]?.message ?? "", /could not identify the previous review/);
		assert.equal(ownedReview(WORKTREE)?.paneId, "w9:pLegacy");
	});

	for (const live of [[], ["new-one", "new-two"]]) {
		it(`keeps an unidentified pane with ${live.length} candidate sessions`, async (t) => {
			herdrEnv(t);
			rememberPane(WORKTREE, "w9:pPending", new Set(["foreign"]));
			const h = harness({ preexisting: ["foreign", ...live] });

			await h.run();

			assert.deepEqual(paneMutations(h.calls), []);
			assert.equal(
				h.calls.some((call) => call.args[1] === "comment"),
				false,
			);
			assert.equal(ownedReview(WORKTREE)?.sessionId, undefined);
			assert.match(h.notices[0]?.message ?? "", /close its pane to abandon it/);
		});
	}

	it("does not adopt a foreign session after the pending pane was closed", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pPending", new Set());
		const h = harness({ pendingPaneMissing: true, preexisting: ["later-foreign"] });

		await h.run();

		const reads = h.calls.filter((call) => call.args.slice(0, 3).join(" ") === "session comment list");
		assert.deepEqual(
			reads.map((call) => call.args[3]),
			[NEW_SESSION],
		);
		assert.match(h.notices[0]?.message ?? "", /previous review's notes were lost/);
	});

	it("does not confuse a Herdr probe failure with a missing pane", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pPending", new Set());
		const h = harness({ paneGetError: "connection_refused" });

		await h.run();

		assert.deepEqual(paneMutations(h.calls), []);
		assert.equal(ownedReview(WORKTREE)?.paneId, "w9:pPending");
	});

	it("keeps an identified TUI that temporarily disappears from the daemon", async (t) => {
		herdrEnv(t);
		rememberPane(WORKTREE, "w9:pDisconnected");
		attachSession(WORKTREE, STALE_SESSION);
		const h = harness();

		await h.run();

		assert.deepEqual(paneMutations(h.calls), []);
		assert.equal(ownedReview(WORKTREE)?.sessionId, STALE_SESSION);
		assert.equal(h.notices.length, 1);
		assert.equal(h.notices[0]?.type, "error");
	});

	it("copies the launch baseline and discards it once the session is attached", (t) => {
		herdrEnv(t);
		const before = new Set(["foreign"]);
		rememberPane(WORKTREE, "w9:pPending", before);
		before.add("later");
		assert.deepEqual(ownedReview(WORKTREE)?.beforeSessionIds, ["foreign"]);

		attachSession(WORKTREE, NEW_SESSION);

		assert.deepEqual(ownedReview(WORKTREE), { paneId: "w9:pPending", sessionId: NEW_SESSION });
	});
});
