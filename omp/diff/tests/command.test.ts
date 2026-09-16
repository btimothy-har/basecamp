import { afterEach, describe, expect, test } from "bun:test";
import { formatUserAnnotations } from "../command.ts";
import { parseDiffJournalEvent } from "../journal.ts";
import { cleanupCommandHarnesses, createCommandHarness, savedReview } from "./support/command-harness.ts";

afterEach(cleanupCommandHarnesses);

describe("/diff", () => {
	test("runs one frozen review, discards stale agent context, and returns user notes", async () => {
		const h = createCommandHarness();
		await h.invoke();

		expect(h.calls.map((call) => [call.command, call.args[0], call.args[1]])).toEqual([
			[h.calls[0]?.command, "--version", undefined],
			[h.calls[0]?.command, "patch", "--help"],
			[h.calls[0]?.command, "session", "list"],
			["herdr", "pane", "split"],
			["herdr", "pane", "run"],
			["herdr", "pane", "process-info"],
			[h.calls[0]?.command, "session", "list"],
			[h.calls[0]?.command, "session", "comment"],
			["herdr", "pane", "close"],
		]);
		expect(h.calls.every((call) => call.options?.cwd === h.root)).toBe(true);
		const launch = h.calls[4];
		expect(launch?.args).toContain("'patch'");
		expect(launch?.args).toContain("'/tmp/review.patch'");
		expect(launch?.args).toContain("'/tmp/agent context.json'");
		expect(launch?.args).toContain("'--agent-notes'");
		expect(h.writtenPatches).toEqual(["diff --git a/src/a.ts b/src/a.ts\n@@ -2 +2 @@\n-old\n+two\n"]);
		expect(h.projected.map((batch) => batch.map((annotation) => annotation.id))).toEqual([["current-id"]]);
		expect(savedReview(h.saved)).toMatchObject({
			status: "submitted",
			displayed_agent_annotation_ids: ["current-id"],
			discarded_agent_annotation_ids: ["stale-id"],
			user_annotations: [
				{ filePath: "src/a.ts", newRange: [2, 2], body: "new-side note" },
				{ filePath: "src/old.ts", oldRange: [7, 8], body: "removed note" },
			],
		});
		expect(h.saved[0]?.toolType).toBe("diff-review");
		expect(parseDiffJournalEvent(h.appended[0]?.data)).toEqual({
			v: 1,
			kind: "diff-completed",
			reviewRef: "artifact://review-42",
			throughEntryId: "journal-1",
		});
		expect(h.sent[0]?.options).toBeUndefined();
		expect(h.sent[0]?.content).toContain("src/old.ts:7-8 (removed lines)");
		expect(h.sent[0]?.content).toContain("artifact://review-42");
		expect(h.notifications.some((notice) => notice.message.includes("stale-id"))).toBe(true);
		expect(h.events.map((event) => event.data)).toEqual([
			{ active: true, label: "Reviewing in Hunk" },
			{ active: false },
		]);
		expect(h.idleCount()).toBe(1);
	});

	test("binds a patch-mode session to a child behind an executable launcher", async () => {
		const h = createCommandHarness({ wrappedProcess: true });
		await h.invoke();

		expect(h.saved).toHaveLength(1);
		expect(h.calls.some((call) => call.args[1] === "close")).toBe(true);
	});

	test("leaves the pane open when pane-run delivery is indeterminate", async () => {
		const h = createCommandHarness({ paneRunFails: true });
		await h.invoke();

		expect(h.cleanupCount()).toBe(0);
		expect(h.calls.some((call) => call.args[1] === "close")).toBe(false);
		expect(h.saved).toHaveLength(0);
		expect(h.notifications.at(-1)?.message).toContain("private launch inputs remain available");
	});

	test("reads and archives an empty review even when the confirmation is cancelled", async () => {
		const h = createCommandHarness({ confirmed: false, comments: '{"comments":[]}', withAnnotations: false });
		await h.invoke();

		expect(savedReview(h.saved).status).toBe("cancelled");
		expect(h.calls.some((call) => call.args[1] === "comment")).toBe(true);
		expect(h.calls.some((call) => call.args[1] === "close")).toBe(true);
		expect(h.appended).toHaveLength(1);
		expect(h.sent).toHaveLength(0);
		expect(h.notifications.at(-1)?.message).toContain("No annotations were left");
	});

	test("captures and returns notes already written when confirmation is cancelled", async () => {
		const h = createCommandHarness({ confirmed: false, withAnnotations: false });
		await h.invoke();

		expect(savedReview(h.saved).status).toBe("cancelled");
		expect(h.calls.some((call) => call.args[1] === "close")).toBe(true);
		expect(h.appended).toHaveLength(1);
		expect(h.sent[0]?.content).toContain("new-side note");
	});

	test("cleans the frozen patch when agent-context projection fails", async () => {
		const h = createCommandHarness({ contextError: "context failed" });
		await h.invoke();

		expect(h.cleanupCount()).toBe(1);
		expect(h.calls.some((call) => call.command === "herdr")).toBe(false);
		expect(h.notifications.at(-1)?.message).toContain("context failed");
	});

	test("leaves Hunk open and state unconsumed when reading notes fails", async () => {
		const h = createCommandHarness({ comments: "not-json" });
		await h.invoke();

		expect(h.calls.some((call) => call.args[1] === "close")).toBe(false);
		expect(h.saved).toHaveLength(0);
		expect(h.appended).toHaveLength(0);
		expect(h.sent).toHaveLength(0);
		expect(h.notifications.at(-1)?.message).toContain("still open so they are not lost");
	});

	test("leaves Hunk open and state unconsumed when artifact persistence fails", async () => {
		const h = createCommandHarness({ artifactPath: null });
		await h.invoke();

		expect(h.calls.some((call) => call.args[1] === "close")).toBe(false);
		expect(h.appended).toHaveLength(0);
		expect(h.sent).toHaveLength(0);
		expect(h.notifications.at(-1)?.message).toContain("pane remains open");
	});

	test("does not consume or close a review after the originating session changes", async () => {
		const h = createCommandHarness({ sessionChangesAfterSave: true });
		await h.invoke();

		expect(h.saved).toHaveLength(1);
		expect(h.calls.some((call) => call.args[1] === "close")).toBe(false);
		expect(h.appended).toHaveLength(0);
		expect(h.sent).toHaveLength(0);
		expect(h.notifications.at(-1)?.message).toContain("originating OMP session");
	});

	test("keeps the launched pane open when no session matches its process", async () => {
		const h = createCommandHarness({ sessionPid: 999 });
		await h.invoke();

		expect(h.cleanupCount()).toBe(0);
		expect(h.calls.some((call) => call.args[1] === "close")).toBe(false);
		expect(h.saved).toHaveLength(0);
		expect(h.appended).toHaveLength(0);
		expect(h.notifications.at(-1)?.message).toContain("private launch inputs remain available");
	});

	test("reports omitted diff entries without aborting the review", async () => {
		const warning = 'Untracked directory "vendor/" was omitted; embedded repositories are not expanded.';
		const h = createCommandHarness({ warnings: [warning] });
		await h.invoke();

		expect(h.notifications).toContainEqual({ message: warning, level: "warning" });
		expect(h.saved).toHaveLength(1);
	});

	test("formats both sides of a mixed user selection", () => {
		const message = formatUserAnnotations(
			[{ filePath: "src/a.ts", newRange: [8, 10], oldRange: [8, 9], body: "mixed" }],
			"artifact://review-1",
		);
		expect(message).toContain("src/a.ts:8-10 (new lines) and src/a.ts:8-9 (removed lines)");
	});

	test("rejects arguments before waiting, loading the diff, or invoking a shell", async () => {
		const h = createCommandHarness();
		await h.invoke("last");

		expect(h.idleCount()).toBe(0);
		expect(h.loadCount()).toBe(0);
		expect(h.calls).toHaveLength(0);
		expect(h.notifications).toEqual([{ message: "/diff takes no arguments.", level: "error" }]);
	});
});
