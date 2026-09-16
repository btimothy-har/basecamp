import { describe, expect, test } from "bun:test";
import type { SessionEntry } from "@oh-my-pi/pi-coding-agent";
import type { DiffAnnotation } from "../annotations.ts";
import {
	activeAnnotations,
	DIFF_ANNOTATION_CUSTOM_TYPE,
	type DiffJournalCompleted,
	type DiffJournalRecorded,
	type DiffJournalWithdrawn,
	diffJournalBoundaryIndex,
	parseDiffJournalEvent,
	recordAnnotations,
	recordDiffCompleted,
	withdrawAnnotations,
} from "../journal.ts";

let sequence = 0;

function fields() {
	sequence += 1;
	return {
		id: `entry-${sequence}`,
		parentId: sequence === 1 ? null : `entry-${sequence - 1}`,
		timestamp: "2026-09-16T00:00:00.000Z",
	};
}

function journalEntry(data: unknown): SessionEntry {
	return { ...fields(), type: "custom", customType: DIFF_ANNOTATION_CUSTOM_TYPE, data } as SessionEntry;
}

function foreignEntry(data: unknown): SessionEntry {
	return { ...fields(), type: "custom", customType: "other.extension", data } as SessionEntry;
}

function resetBoundary(): SessionEntry {
	return { ...fields(), type: "reset_boundary" } as SessionEntry;
}

function annotation(overrides: Partial<DiffAnnotation> = {}): DiffAnnotation {
	return {
		id: "aaaaaaaaaaaa",
		repository: "basecamp",
		path: "src/a.ts",
		newRange: { start: 2, end: 4 },
		anchorHash: "0123456789abcdef",
		summary: "watch this",
		...overrides,
	};
}

function recorded(...annotations: DiffAnnotation[]): DiffJournalRecorded {
	return { v: 1, kind: "recorded", annotations };
}

function withdrawn(...ids: string[]): DiffJournalWithdrawn {
	return { v: 1, kind: "withdrawn", ids };
}

function completed(reviewRef = "artifact://review-1", throughEntryId?: string): DiffJournalCompleted {
	return { v: 1, kind: "diff-completed", reviewRef, ...(throughEntryId === undefined ? {} : { throughEntryId }) };
}

describe("parseDiffJournalEvent", () => {
	test("round-trips every well-formed event kind", () => {
		expect(parseDiffJournalEvent(recorded(annotation()))).toEqual(recorded(annotation()));
		expect(parseDiffJournalEvent(recorded(annotation(), annotation({ id: "bbbbbbbbbbbb" })))).toEqual(
			recorded(annotation(), annotation({ id: "bbbbbbbbbbbb" })),
		);
		expect(parseDiffJournalEvent(withdrawn("aaaaaaaaaaaa"))).toEqual(withdrawn("aaaaaaaaaaaa"));
		expect(parseDiffJournalEvent(completed())).toEqual(completed());
		expect(parseDiffJournalEvent(recorded(annotation({ rationale: "why" })))).toEqual(
			recorded(annotation({ rationale: "why" })),
		);
	});

	test("rejects non-objects and missing markers", () => {
		expect(parseDiffJournalEvent(null)).toBeNull();
		expect(parseDiffJournalEvent(undefined)).toBeNull();
		expect(parseDiffJournalEvent("recorded")).toBeNull();
		expect(parseDiffJournalEvent([])).toBeNull();
		expect(parseDiffJournalEvent({})).toBeNull();
		expect(parseDiffJournalEvent({ kind: "recorded", annotations: [annotation()] })).toBeNull();
	});

	test("rejects wrong versions and unknown kinds", () => {
		expect(parseDiffJournalEvent({ v: 2, kind: "withdrawn", ids: ["a"] })).toBeNull();
		expect(parseDiffJournalEvent({ v: "1", kind: "withdrawn", ids: ["a"] })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "edited", ids: ["a"] })).toBeNull();
	});

	test("rejects extra keys at the event and annotation level", () => {
		expect(parseDiffJournalEvent({ ...completed(), extra: true })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "recorded", annotations: [{ ...annotation(), extra: 1 }] })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "withdrawn", ids: ["a"], note: "x" })).toBeNull();
	});

	test("rejects malformed recorded payloads", () => {
		expect(parseDiffJournalEvent({ v: 1, kind: "recorded", annotations: [] })).toBeNull();
		expect(parseDiffJournalEvent(recorded(annotation({ summary: "" })))).toBeNull();
		expect(
			parseDiffJournalEvent({ v: 1, kind: "recorded", annotations: [{ ...annotation(), anchorHash: 3 }] }),
		).toBeNull();
		expect(
			parseDiffJournalEvent({
				v: 1,
				kind: "recorded",
				annotations: [{ ...annotation(), newRange: { start: 4, end: 2 } }],
			}),
		).toBeNull();
		expect(
			parseDiffJournalEvent({
				v: 1,
				kind: "recorded",
				annotations: [{ ...annotation(), newRange: { start: 0, end: 2 } }],
			}),
		).toBeNull();
		expect(
			parseDiffJournalEvent({
				v: 1,
				kind: "recorded",
				annotations: [{ ...annotation(), newRange: { start: 1.5, end: 2 } }],
			}),
		).toBeNull();
		expect(
			parseDiffJournalEvent({ v: 1, kind: "recorded", annotations: [{ ...annotation(), rationale: 7 }] }),
		).toBeNull();
	});

	test("rejects malformed withdrawn and diff-completed payloads", () => {
		expect(parseDiffJournalEvent({ v: 1, kind: "withdrawn", ids: [] })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "withdrawn", ids: ["a", 2] })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "withdrawn", ids: [""] })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "diff-completed", reviewRef: "" })).toBeNull();
		expect(parseDiffJournalEvent({ v: 1, kind: "diff-completed" })).toBeNull();
		expect(parseDiffJournalEvent({ ...completed(), throughEntryId: "" })).toBeNull();
		expect(parseDiffJournalEvent({ ...completed(), throughEntryId: 7 })).toBeNull();
	});
});

describe("activeAnnotations", () => {
	test("folds recorded events in order", () => {
		const first = annotation({ id: "111111111111" });
		const second = annotation({ id: "222222222222", path: "src/b.ts" });
		const entries = [journalEntry(recorded(first)), journalEntry(recorded(second))];
		expect(activeAnnotations(entries)).toEqual([first, second]);
	});

	test("withdrawn removes by id, and a later record re-adds", () => {
		const target = annotation({ id: "111111111111" });
		const kept = annotation({ id: "222222222222" });
		expect(activeAnnotations([journalEntry(recorded(target, kept)), journalEntry(withdrawn(target.id))])).toEqual([
			kept,
		]);
		expect(
			activeAnnotations([
				journalEntry(recorded(target)),
				journalEntry(withdrawn(target.id)),
				journalEntry(recorded(target)),
			]),
		).toEqual([target]);
	});

	test("exact duplicate recordings collapse", () => {
		const target = annotation();
		expect(activeAnnotations([journalEntry(recorded(target)), journalEntry(recorded(target))])).toEqual([target]);
		expect(activeAnnotations([journalEntry(recorded(target, target))])).toEqual([target]);
	});

	test("ignores other customTypes, non-custom entries, and malformed events", () => {
		const target = annotation();
		const entries = [
			foreignEntry(recorded(annotation({ id: "999999999999" }))),
			resetBoundary(),
			journalEntry({ v: 1, kind: "recorded", annotations: [{ bogus: true }] }),
			journalEntry(null),
			journalEntry(recorded(target)),
		];
		expect(activeAnnotations(entries)).toEqual([target]);
	});

	test("a reset boundary drops everything recorded before it", () => {
		const before = annotation({ id: "111111111111" });
		const after = annotation({ id: "222222222222" });
		const entries = [journalEntry(recorded(before)), resetBoundary(), journalEntry(recorded(after))];
		expect(activeAnnotations(entries)).toEqual([after]);
	});

	test("a completed diff drops annotations through its captured branch leaf", () => {
		const before = annotation({ id: "111111111111" });
		const after = annotation({ id: "222222222222" });
		const beforeEntry = journalEntry(recorded(before));
		const entries = [
			beforeEntry,
			journalEntry(completed("artifact://review-1", beforeEntry.id)),
			journalEntry(recorded(after)),
		];
		expect(activeAnnotations(entries)).toEqual([after]);
	});

	test("the later of reset and a completion cutoff bounds the state", () => {
		const stale = annotation({ id: "111111111111" });
		const live = annotation({ id: "222222222222" });
		const beforeReset = journalEntry(recorded(stale));
		const resetAfterCutoff = resetBoundary();
		expect(
			activeAnnotations([
				beforeReset,
				resetAfterCutoff,
				journalEntry(completed("artifact://review-1", beforeReset.id)),
				journalEntry(recorded(live)),
			]),
		).toEqual([live]);

		const resetBeforeCutoff = resetBoundary();
		const beforeCompletion = journalEntry(recorded(stale));
		expect(
			activeAnnotations([
				resetBeforeCutoff,
				beforeCompletion,
				journalEntry(completed("artifact://review-1", beforeCompletion.id)),
				journalEntry(recorded(live)),
			]),
		).toEqual([live]);
	});

	test("a completion preserves annotations recorded after its captured cutoff", () => {
		const displayed = annotation({ id: "111111111111" });
		const concurrent = annotation({ id: "222222222222" });
		const displayedEntry = journalEntry(recorded(displayed));
		const concurrentEntry = journalEntry(recorded(concurrent));
		const completion = journalEntry(completed("artifact://review-1", displayedEntry.id));

		expect(activeAnnotations([displayedEntry, concurrentEntry, completion])).toEqual([concurrent]);
	});

	test("a malformed diff-completed payload does not bound the state", () => {
		const target = annotation();
		const entries = [journalEntry(recorded(target)), journalEntry({ v: 1, kind: "diff-completed", reviewRef: "" })];
		expect(activeAnnotations(entries)).toEqual([target]);
	});

	test("only entries on the active branch are folded", () => {
		// getBranch() yields the active path; annotations recorded on an
		// abandoned branch simply never appear in the array the fold sees.
		const abandoned = annotation({ id: "111111111111" });
		const live = annotation({ id: "222222222222" });
		const activeBranch = [journalEntry(recorded(live))];
		expect(activeAnnotations(activeBranch)).toEqual([live]);
		expect(activeAnnotations(activeBranch)).not.toContainEqual(abandoned);
	});
});

describe("diffJournalBoundaryIndex", () => {
	test("is -1 without markers", () => {
		expect(diffJournalBoundaryIndex([journalEntry(recorded(annotation()))])).toBe(-1);
	});

	test("uses the later of the last reset and the last completion cutoff", () => {
		const recordedEntry = journalEntry(recorded(annotation()));
		const reset = resetBoundary();
		const completion = journalEntry(completed("artifact://review-1", recordedEntry.id));
		expect(diffJournalBoundaryIndex([recordedEntry, reset, completion])).toBe(1);
		expect(diffJournalBoundaryIndex([recordedEntry, completion, reset])).toBe(2);
		expect(diffJournalBoundaryIndex([recordedEntry, reset])).toBe(1);
	});
});

describe("journal appenders", () => {
	function sink() {
		const appended: { customType: string; data: unknown }[] = [];
		return {
			appended,
			append: (customType: string, data?: unknown) => {
				appended.push({ customType, data });
			},
		};
	}

	test("recordAnnotations appends a parseable recorded event under the stable customType", () => {
		const { appended, append } = sink();
		recordAnnotations(append, [annotation()]);
		expect(appended).toHaveLength(1);
		expect(appended[0]?.customType).toBe(DIFF_ANNOTATION_CUSTOM_TYPE);
		expect(parseDiffJournalEvent(appended[0]?.data)).toEqual(recorded(annotation()));
	});

	test("withdrawAnnotations and recordDiffCompleted append parseable events", () => {
		const { appended, append } = sink();
		withdrawAnnotations(append, ["aaaaaaaaaaaa"]);
		recordDiffCompleted(append, "artifact://review-9", "entry-7");
		expect(appended.map((entry) => entry.customType)).toEqual([
			DIFF_ANNOTATION_CUSTOM_TYPE,
			DIFF_ANNOTATION_CUSTOM_TYPE,
		]);
		expect(parseDiffJournalEvent(appended[0]?.data)).toEqual(withdrawn("aaaaaaaaaaaa"));
		expect(parseDiffJournalEvent(appended[1]?.data)).toEqual(completed("artifact://review-9", "entry-7"));
	});

	test("empty batches append nothing", () => {
		const { appended, append } = sink();
		recordAnnotations(append, []);
		withdrawAnnotations(append, []);
		expect(appended).toHaveLength(0);
	});

	test("appended events fold back into state, and a completion bounds only its cutoff", () => {
		const { appended, append } = sink();
		const target = annotation();
		recordAnnotations(append, [target]);
		const firstEntry = journalEntry(appended[0]?.data);
		recordDiffCompleted(append, "artifact://review-1", firstEntry.id);
		recordAnnotations(append, [annotation({ id: "222222222222" })]);
		const entries = [firstEntry, ...appended.slice(1).map((entry) => journalEntry(entry.data))];
		expect(activeAnnotations(entries)).toEqual([annotation({ id: "222222222222" })]);
	});
});
