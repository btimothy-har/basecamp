/**
 * Annotation journal. Diff annotations are events appended to the OMP session
 * as CustomEntries under the stable customType "basecamp.diff.annotation" —
 * the payload lives directly in the entry; there is no artifact, source
 * snapshot, or remapping path. State is folded from the active branch suffix
 * after the later of the last reset_boundary and the last diff-completed
 * entry: a successful /diff establishes the next boundary, and annotations
 * recorded on abandoned branches never enter the fold because only the
 * active branch is read.
 */

import { type } from "@oh-my-pi/omptype";
import type { ExtensionAPI, SessionEntry } from "@oh-my-pi/pi-coding-agent";
import type { DiffAnnotation } from "./annotations.ts";

export const DIFF_ANNOTATION_CUSTOM_TYPE = "basecamp.diff.annotation";

const JOURNAL_VERSION = 1;

/** A batch of full annotation payloads recorded in one annotate_diff call. */
export interface DiffJournalRecorded {
	v: 1;
	kind: "recorded";
	annotations: DiffAnnotation[];
}

/** Withdrawal of one or more annotation ids via remove_annotation. */
export interface DiffJournalWithdrawn {
	v: 1;
	kind: "withdrawn";
	ids: string[];
}

/** A completed /diff: everything before this entry is consumed state. */
export interface DiffJournalCompleted {
	v: 1;
	kind: "diff-completed";
	reviewRef: string;
	/** Last branch entry included when /diff loaded its annotation journal. */
	throughEntryId?: string;
}

export type DiffJournalEvent = DiffJournalRecorded | DiffJournalWithdrawn | DiffJournalCompleted;

/** pi.appendEntry, closure-captured at registration and threaded in. */
export type AppendEntry = ExtensionAPI["appendEntry"];

const rangeSchema = type({
	start: type("number.integer >= 1"),
	end: type("number.integer >= 1"),
	"+": "reject",
}).narrow((range, ctx) => range.end >= range.start || ctx.mustBe("an end greater than or equal to start"));

const annotationSchema = type({
	id: type("string > 0"),
	repository: type("string > 0"),
	path: type("string > 0"),
	newRange: rangeSchema,
	anchorHash: type("string > 0"),
	summary: type("string > 0"),
	"rationale?": type("string > 0"),
	"+": "reject",
});

const journalEventSchema = type({
	v: "1",
	kind: "'recorded'",
	annotations: annotationSchema.array().atLeastLength(1),
	"+": "reject",
})
	.or({
		v: "1",
		kind: "'withdrawn'",
		ids: type("string > 0").array().atLeastLength(1),
		"+": "reject",
	})
	.or({
		v: "1",
		kind: "'diff-completed'",
		reviewRef: "string > 0",
		"throughEntryId?": "string > 0",
		"+": "reject",
	});

/**
 * Parse a CustomEntry data payload into a journal event, or null when it is
 * not a well-formed v1 event. Fail-closed: unknown kinds, wrong versions,
 * extra keys, and malformed payloads are all ignored by the fold rather than
 * guessed at.
 */
export function parseDiffJournalEvent(data: unknown): DiffJournalEvent | null {
	const parsed = journalEventSchema(data);
	return parsed instanceof type.errors ? null : (parsed as DiffJournalEvent);
}

/** The validated journal event an entry carries, or null when it carries none. */
function journalEvent(entry: SessionEntry): DiffJournalEvent | null {
	if (entry.type !== "custom") return null;
	if (entry.customType !== DIFF_ANNOTATION_CUSTOM_TYPE) return null;
	return parseDiffJournalEvent(entry.data);
}

/**
 * Index through which annotations are consumed: the later of the last reset
 * boundary and every valid diff-completed cutoff. A completion points back to
 * the branch leaf captured before Hunk opened, so annotations appended while
 * the user reviews remain after the boundary.
 */
export function diffJournalBoundaryIndex(entries: readonly SessionEntry[]): number {
	let boundary = -1;
	const indexById = new Map(entries.map((entry, index) => [entry.id, index]));
	for (let index = 0; index < entries.length; index++) {
		const entry = entries[index];
		if (!entry) continue;
		if (entry.type === "reset_boundary") {
			boundary = index;
			continue;
		}
		const event = journalEvent(entry);
		if (event?.kind !== "diff-completed" || event.throughEntryId === undefined) continue;
		const throughIndex = indexById.get(event.throughEntryId);
		if (throughIndex !== undefined && throughIndex < index) boundary = Math.max(boundary, throughIndex);
	}
	return boundary;
}

/**
 * Fold the journal into the currently active annotations. Expects the active
 * branch (ctx.sessionManager.getBranch()); anything before the boundary — a
 * completed /diff or a context reset — is consumed state and drops out.
 * Recorded annotations key by id, so exact duplicates collapse; withdrawals
 * delete; a later record of the same id re-adds after a withdrawal.
 */
export function activeAnnotations(entries: readonly SessionEntry[]): DiffAnnotation[] {
	const boundary = diffJournalBoundaryIndex(entries);
	const active = new Map<string, DiffAnnotation>();
	for (const entry of entries.slice(boundary + 1)) {
		const event = journalEvent(entry);
		if (!event) continue;
		if (event.kind === "recorded") {
			for (const annotation of event.annotations) active.set(annotation.id, annotation);
		} else if (event.kind === "withdrawn") {
			for (const id of event.ids) active.delete(id);
		}
	}
	return [...active.values()];
}

/** Append a recorded event; an empty batch appends nothing. */
export function recordAnnotations(appendEntry: AppendEntry, annotations: DiffAnnotation[]): void {
	if (annotations.length === 0) return;
	const event: DiffJournalRecorded = { v: JOURNAL_VERSION, kind: "recorded", annotations };
	appendEntry(DIFF_ANNOTATION_CUSTOM_TYPE, event);
}

/** Append a withdrawn event; an empty id list appends nothing. */
export function withdrawAnnotations(appendEntry: AppendEntry, ids: string[]): void {
	if (ids.length === 0) return;
	const event: DiffJournalWithdrawn = { v: JOURNAL_VERSION, kind: "withdrawn", ids };
	appendEntry(DIFF_ANNOTATION_CUSTOM_TYPE, event);
}

/** Append a review record that consumes annotations only through its captured branch leaf. */
export function recordDiffCompleted(appendEntry: AppendEntry, reviewRef: string, throughEntryId?: string): void {
	const event: DiffJournalCompleted = {
		v: JOURNAL_VERSION,
		kind: "diff-completed",
		reviewRef,
		...(throughEntryId === undefined ? {} : { throughEntryId }),
	};
	appendEntry(DIFF_ANNOTATION_CUSTOM_TYPE, event);
}
