import { afterEach, describe, expect, test } from "bun:test";
import * as path from "node:path";
import type { AgentToolResult } from "@oh-my-pi/pi-coding-agent";
import type { AnnotateDiffDetails, RemoveAnnotationDetails } from "../annotation-tools.ts";
import { anchorHash, annotationId } from "../annotations.ts";
import { activeAnnotations, DIFF_ANNOTATION_CUSTOM_TYPE, parseDiffJournalEvent } from "../journal.ts";
import {
	CONTENT,
	cleanupAnnotationToolHarnesses,
	annotationToolHarness as harness,
	annotationInput as input,
	journalEntries,
	NEW_LINES,
	repository,
} from "./support/annotation-tool-harness.ts";

afterEach(cleanupAnnotationToolHarnesses);

describe("annotate_diff", () => {
	test("records one journal event with full payloads and returns stable ids", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		const result = await h.annotate(input());

		expect(h.appended).toHaveLength(1);
		expect(h.appended[0]?.customType).toBe(DIFF_ANNOTATION_CUSTOM_TYPE);
		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		const recorded = event.annotations[0];
		if (!recorded) throw new Error("expected one recorded annotation");
		const expectedAnchorHash = anchorHash("src/a.ts", { start: 2, end: 4 }, CONTENT);
		if (expectedAnchorHash === null) throw new Error("expected a valid anchor hash");
		expect(recorded).toEqual({
			id: annotationId({
				repository: "basecamp",
				path: "src/a.ts",
				newRange: { start: 2, end: 4 },
				summary: "watch this",
			}),
			repository: "basecamp",
			path: "src/a.ts",
			newRange: { start: 2, end: 4 },
			anchorHash: expectedAnchorHash,
			summary: "watch this",
		});
		// details comes from our own tool definition above, not external input.
		const details = result.details as AnnotateDiffDetails;
		expect(details.recorded).toHaveLength(1);
		expect(details.active).toBe(1);
		const text = result.content[0]?.type === "text" ? result.content[0].text : "";
		expect(text).toContain(recorded.id);
	});

	test("threads rationale through to the recorded annotation", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await h.annotate(input([{ rationale: "boundary math lives here" }]));

		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		expect(event.annotations[0]?.rationale).toBe("boundary math lives here");
	});

	test("rebases an in-repository absolute path", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await h.annotate(input([{ path: path.join(root, "src/a.ts") }]));

		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		expect(event.annotations[0]?.path).toBe("src/a.ts");
	});

	test("rejects invalid targets and appends nothing", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await expect(h.annotate(input([{ path: "../outside.ts" }, {}]))).rejects.toThrow(/rejected/);
		expect(h.appended).toHaveLength(0);
	});

	test("rejects ranges outside the displayed new-side hunk lines", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({
			repositoryRoot: root,
			files: [{ path: "src/a.ts", newRanges: [{ start: 1, end: 3 }], newLines: NEW_LINES }],
		});

		await expect(h.annotate(input([{ line_start: 4, line_end: 5 }]))).rejects.toThrow(
			/outside the displayed new-side hunk lines/,
		);
		expect(h.appended).toHaveLength(0);
	});

	test("collapses exact duplicates within one batch", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		const result = await h.annotate(input([{}, {}]));

		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		expect(event.annotations).toHaveLength(1);
		const details = result.details as AnnotateDiffDetails;
		expect(details.skippedDuplicates).toBe(1);
	});

	test("exact duplicates of active annotations no-op without an event", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		await first.annotate(input());

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		const result = await second.annotate(input());

		expect(second.appended).toHaveLength(0);
		const text = result.content[0]?.type === "text" ? result.content[0].text : "";
		expect(text).toMatch(/No new annotations/);
		const details = result.details as AnnotateDiffDetails;
		expect(details.active).toBe(1);
	});

	test("a reworded rationale records a new annotation under a new id", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		await first.annotate(input());

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		await second.annotate(input([{ rationale: "corrected" }]));

		expect(second.appended).toHaveLength(1);
		expect(activeAnnotations([...second.entries, ...journalEntries(second.appended)])).toHaveLength(2);
	});

	test("is only available to the interactive session that owns /diff", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		for (const options of [
			{ mode: "print" as const },
			{ mode: "rpc" as const },
			{ mode: "tui" as const, hasUI: false },
		]) {
			const h = harness({ repositoryRoot: root, ...options });
			await expect(h.annotate(input())).rejects.toThrow(/only available in the interactive session/);
			expect(h.appended).toHaveLength(0);
		}
	});

	test("does not append journal state after cancellation", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const controller = new AbortController();
		const h = harness({ repositoryRoot: root, afterLoad: () => controller.abort() });

		await expect(h.annotate(input(), controller.signal)).rejects.toThrow();
		expect(h.appended).toHaveLength(0);
	});
});

/** details is this module's own tool payload, not external input. */
function recordedId(result: AgentToolResult): string {
	const details = result.details as AnnotateDiffDetails;
	const id = details.recorded[0]?.id;
	if (!id) throw new Error("expected a recorded id");
	return id;
}

describe("remove_annotation", () => {
	test("appends a withdrawal for currently active ids", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		const id = recordedId(await first.annotate(input()));

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		const removal = await second.remove({ ids: [id] });

		expect(second.appended).toHaveLength(1);
		expect(parseDiffJournalEvent(second.appended[0]?.data)).toEqual({ v: 1, kind: "withdrawn", ids: [id] });
		const details = removal.details as RemoveAnnotationDetails;
		expect(details.withdrawn).toEqual([id]);
		expect(activeAnnotations([...second.entries, ...journalEntries(second.appended)])).toEqual([]);
	});

	test("dedupes repeated ids in one call", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		const id = recordedId(await first.annotate(input()));

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		await second.remove({ ids: [id, id] });

		expect(parseDiffJournalEvent(second.appended[0]?.data)).toEqual({ v: 1, kind: "withdrawn", ids: [id] });
	});

	test("rejects ids without an active annotation and appends nothing", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await expect(h.remove({ ids: ["000000000000"] })).rejects.toThrow(/No active annotation with id/);
		expect(h.appended).toHaveLength(0);
	});

	test("a completed /diff clears the ids a withdrawal can target", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		const id = recordedId(await first.annotate(input()));
		const completedBoundary = journalEntries([
			...first.appended,
			{
				customType: DIFF_ANNOTATION_CUSTOM_TYPE,
				data: { v: 1, kind: "diff-completed", reviewRef: "artifact://r1", throughEntryId: "entry-0" },
			},
		]);

		const second = harness({ repositoryRoot: root, entries: completedBoundary });
		await expect(second.remove({ ids: [id] })).rejects.toThrow(/No active annotation with id/);
		expect(second.appended).toHaveLength(0);
	});

	test("is only available to the interactive session that owns /diff", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		for (const options of [{ mode: "json" as const }, { mode: "tui" as const, hasUI: false }]) {
			const h = harness({ repositoryRoot: root, ...options });
			await expect(h.remove({ ids: ["000000000000"] })).rejects.toThrow(/only available in the interactive session/);
			expect(h.appended).toHaveLength(0);
		}
	});
});
