/**
 * Shared vocabulary for diff annotations: the payload shape persisted in the
 * session journal, the deterministic annotation id, and the canonical
 * exact-range anchor hash that lets /diff discard annotations whose code
 * moved or changed. Folding lives in journal.ts; validation against the live
 * diff lives in validate.ts.
 */

import { createHash } from "node:crypto";
import type { DiffRange } from "./loader.ts";

/** A single annotation on the new side of the current diff. */
export interface DiffAnnotation {
	/** Deterministic content key — see {@link annotationId}. */
	id: string;
	/** DiffSnapshot.repository the annotation belongs to. */
	repository: string;
	/** Repository-relative path, "/" separators. */
	path: string;
	/** 1-based inclusive line range on the new side of the diff. */
	newRange: DiffRange;
	/** Canonical hash of the exact annotated lines — see {@link anchorHash}. */
	anchorHash: string;
	/** One-sentence headline shown beside the code in /diff. */
	summary: string;
	/** Optional longer rationale. */
	rationale?: string;
}

const ID_HEX_LENGTH = 12;
const ANCHOR_HEX_LENGTH = 16;

/**
 * Deterministic annotation key: sha256 of repository, path, range, summary,
 * and rationale, first 12 hex chars. Same content → same key, so exact
 * duplicates collapse on record; a corrected rationale yields a NEW key, so
 * rewording never collides with — or is silently dropped in favour of — the
 * wording it replaces. 12 chars (not 8) buys a cheap collision margin.
 */
export function annotationId(input: {
	repository: string;
	path: string;
	newRange: DiffRange;
	summary: string;
	rationale?: string;
}): string {
	return createHash("sha256")
		.update(
			`${input.repository}\n${input.path}\n${input.newRange.start}\n${input.newRange.end}\n${input.summary}\n${input.rationale ?? ""}`,
		)
		.digest("hex")
		.slice(0, ID_HEX_LENGTH);
}

/**
 * Split file content into lines, LF/CRLF-normalized. The trailing empty
 * element produced by a file's final newline is dropped; interior empty
 * lines are real lines and stay.
 */
export function contentLines(content: string): string[] {
	if (content === "") return [];
	const lines = content.split("\n").map((line) => (line.endsWith("\r") ? line.slice(0, -1) : line));
	if (lines[lines.length - 1] === "") lines.pop();
	return lines;
}

function hashRange(path: string, range: DiffRange, lines: readonly string[]): string {
	return createHash("sha256")
		.update(`${path}\n${range.start}\n${range.end}\n${lines.join("\n")}`)
		.digest("hex")
		.slice(0, ANCHOR_HEX_LENGTH);
}

/** Hash an already-addressed range, such as the exact lines parsed from a frozen patch. */
export function anchorHashForLines(path: string, range: DiffRange, lines: readonly string[]): string | null {
	if (!Number.isInteger(range.start) || !Number.isInteger(range.end)) return null;
	if (range.start < 1 || range.end < range.start) return null;
	if (lines.length !== range.end - range.start + 1) return null;
	return hashRange(path, range, lines);
}

/**
 * Canonical exact-range anchor: sha256 of path, range, and the file's exact
 * current lines within that range, first 16 hex chars. Returns null when the
 * range cannot address the content.
 */
export function anchorHash(path: string, range: DiffRange, content: string): string | null {
	const lines = contentLines(content);
	if (range.end > lines.length) return null;
	return anchorHashForLines(path, range, lines.slice(range.start - 1, range.end));
}

/** A range as `12` or `12-20`, for confirmations and issue messages. */
export function span(range: DiffRange): string {
	return range.start === range.end ? `${range.start}` : `${range.start}-${range.end}`;
}
