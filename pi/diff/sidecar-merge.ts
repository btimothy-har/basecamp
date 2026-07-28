/**
 * Annotation identity and span merging — what an annotation *is*, and how a new
 * batch folds into one already recorded. Split from storage so the rules that
 * decide "the same annotation" live in one place: `annotationId` fixes identity,
 * `sameAnchor` is the coarser "describes the same thing" comparison, and both
 * the fresh-write and merge paths share them.
 */

import { createHash } from "node:crypto";
import type { AnnotatedFile, Annotation, Sidecar } from "./sidecar.ts";

/**
 * Deterministic annotation key: sha256 of path, range, summary, and
 * rationale, first 12 hex chars. Same content → same key, so exact-duplicate
 * dedupe on merge is free; a corrected rationale yields a NEW key, so
 * rewording an annotation never silently collides with — or is silently
 * dropped in favour of — the wording it replaces. 12 chars (not 8) buys a
 * cheap collision margin.
 */
export function annotationId(
	filePath: string,
	newRange: [number, number],
	summary: string,
	rationale?: string,
): string {
	return createHash("sha256")
		.update(`${filePath}\n${newRange[0]}\n${newRange[1]}\n${summary}\n${rationale ?? ""}`)
		.digest("hex")
		.slice(0, 12);
}

export interface RecordedAnnotation {
	id: string;
	path: string;
	newRange: [number, number];
	summary: string;
}

/**
 * An annotation after stamping, where the id is established rather than
 * optional — the schema keeps `id` optional for sidecars written before it
 * existed, so the guarantee is expressed here instead of re-checked downstream.
 */
export type StampedAnnotation = Annotation & { id: string };
export type StampedFile = Omit<AnnotatedFile, "annotations"> & { annotations: StampedAnnotation[] };

/**
 * Two annotations describe the same thing when they share a range and a
 * headline; only the rationale may have been corrected. Identity (the key)
 * includes the rationale, so this is deliberately the coarser comparison.
 */
function sameAnchor(a: Annotation, b: Annotation): boolean {
	return a.newRange[0] === b.newRange[0] && a.newRange[1] === b.newRange[1] && a.summary === b.summary;
}

/**
 * Every incoming annotation is stamped with its computed id — always computed,
 * never trusted from input — and, within one batch, exact duplicates collapse
 * to their first occurrence. Entries are folded by path: one entry per path,
 * annotations concatenated in encounter order, a later non-undefined per-file
 * summary winning — so one call can never write two entries for the same path
 * (which would leave later merges updating only the first, and the shared
 * path's annotations unremovable as ambiguous).
 */
export function stampFiles(files: AnnotatedFile[]): StampedFile[] {
	const byPath = new Map<string, StampedFile>();
	for (const f of files) {
		let entry = byPath.get(f.path);
		if (!entry) {
			entry = { path: f.path, annotations: [] };
			byPath.set(f.path, entry);
		}
		for (const a of f.annotations) {
			const stamped = { ...a, id: annotationId(f.path, a.newRange, a.summary, a.rationale) };
			const at = entry.annotations.findIndex((held) => sameAnchor(held, stamped));
			// Supersede within the batch exactly as a correction supersedes an already
			// stored annotation — the guarantee cannot depend on whether a sidecar for
			// this span happens to exist yet. Identical resubmissions collapse here too.
			if (at >= 0) entry.annotations[at] = stamped;
			else entry.annotations.push(stamped);
		}
		if (f.summary !== undefined) entry.summary = f.summary;
	}
	return [...byPath.values()];
}

/**
 * Merge incoming (already stamped) files into an existing sidecar of the same
 * review span: existing entries keep their annotations; a same-path incoming
 * entry appends annotations whose ids are not already present (exact
 * duplicates collapse) and, when it carries a summary, replaces the entry's
 * summary; new paths are added. The incoming top-level summary always wins.
 *
 * Supersession: the annotation id includes the rationale, so a corrected
 * rationale for the same path + range + summary arrives under a NEW id.
 * Rather than appending a near-duplicate, the incoming annotation REPLACES
 * the matching stored one in place — same position, new rationale and id —
 * which is what the "annotate again to reword" workflow promises.
 *
 * Returns the merged sidecar and the annotations this call actually
 * contributed (appended or superseding, in call order).
 */
export function mergeSidecar(
	existing: Sidecar,
	incoming: StampedFile[],
	summary: string,
): { sidecar: Sidecar; recorded: RecordedAnnotation[] } {
	const recorded: RecordedAnnotation[] = [];
	const files = existing.files.map((f) => ({ ...f, annotations: [...f.annotations] }));
	for (const incomingFile of incoming) {
		const entry = files.find((f) => f.path === incomingFile.path);
		if (!entry) {
			files.push({ ...incomingFile, annotations: [...incomingFile.annotations] });
			for (const a of incomingFile.annotations) {
				recorded.push({ id: a.id, path: incomingFile.path, newRange: a.newRange, summary: a.summary });
			}
			continue;
		}
		const present = new Set(
			entry.annotations.map((a) => a.id ?? annotationId(entry.path, a.newRange, a.summary, a.rationale)),
		);
		for (const a of incomingFile.annotations) {
			const id = a.id;
			if (present.has(id)) continue; // Exact duplicate — collapse.
			const superseded = entry.annotations.findIndex((stored) => sameAnchor(stored, a));
			if (superseded >= 0) {
				present.delete(entry.annotations[superseded]?.id ?? "");
				entry.annotations[superseded] = a;
			} else {
				entry.annotations.push(a);
			}
			present.add(id);
			recorded.push({ id, path: incomingFile.path, newRange: a.newRange, summary: a.summary });
		}
		if (incomingFile.summary !== undefined) entry.summary = incomingFile.summary;
	}
	return { sidecar: { ...existing, summary, files }, recorded };
}
