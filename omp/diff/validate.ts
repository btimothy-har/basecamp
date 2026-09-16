/**
 * Validation of annotation targets against one frozen diff snapshot. Paths
 * must stay inside the repository, ranges must be 1-based inclusive and
 * contained in one of the file's new-side hunk ranges, and the anchor hash
 * comes from the exact new-side lines in the patch Hunk will display.
 */

import { isAbsolute, normalize, relative, sep } from "node:path";
import type { DiffAnnotation } from "./annotations.ts";
import { anchorHashForLines, span } from "./annotations.ts";
import type { DiffFile, DiffRange, DiffSnapshot } from "./loader.ts";

/** One annotate_diff target before validation. */
export interface AnnotationTarget {
	path: string;
	range: DiffRange;
	summary: string;
	rationale?: string;
}

/** Why a single target was rejected. */
export interface AnnotationIssue {
	path: string;
	range?: DiffRange;
	reason: string;
}

/** A target that passed every check and carries its fresh anchor hash. */
export interface ValidatedTarget {
	path: string;
	newRange: DiffRange;
	anchorHash: string;
	summary: string;
	rationale?: string;
}

export interface ValidationResult {
	valid: ValidatedTarget[];
	issues: AnnotationIssue[];
}

export interface RevalidationResult {
	current: DiffAnnotation[];
	stale: DiffAnnotation[];
}

/**
 * Normalize an input path to a repository-relative "/" path, or null when it
 * is empty, the repository root itself, or escapes the repository. Absolute
 * paths inside the repository are accepted and rebased.
 */
export function repositoryRelativePath(filePath: string, repositoryRoot: string): string | null {
	const relativePath = isAbsolute(filePath) ? relative(repositoryRoot, filePath) : normalize(filePath);
	if (
		relativePath === "" ||
		relativePath === "." ||
		relativePath === ".." ||
		relativePath.startsWith(`..${sep}`) ||
		isAbsolute(relativePath)
	) {
		return null;
	}
	return relativePath.split(sep).join("/");
}

/** The diff hunk whose new-side range fully contains `range`, if one exists. */
function containingRange(file: DiffFile, range: DiffRange): DiffRange | undefined {
	return file.newRanges.find((candidate) => candidate.start <= range.start && range.end <= candidate.end);
}

function rangeProblem(range: DiffRange): string | null {
	if (!Number.isInteger(range.start) || !Number.isInteger(range.end) || range.start < 1) {
		return "line ranges are 1-based positive integers";
	}
	if (range.end < range.start) return `range ${span(range)} is reversed`;
	return null;
}

function snapshotAnchorHash(file: DiffFile, path: string, range: DiffRange): string | null {
	const lines: string[] = [];
	for (let line = range.start; line <= range.end; line++) {
		if (!file.newLines.has(line)) return null;
		lines.push(file.newLines.get(line) as string);
	}
	return anchorHashForLines(path, range, lines);
}

/**
 * Validate targets against the exact patch bytes already loaded for the
 * review. Targets are independent: valid ones come back regardless of how
 * many siblings were rejected.
 */
export async function validateTargets(
	snapshot: DiffSnapshot,
	targets: readonly AnnotationTarget[],
): Promise<ValidationResult> {
	const issues: AnnotationIssue[] = [];
	const candidates: { target: AnnotationTarget; path: string; file: DiffFile }[] = [];

	for (const target of targets) {
		const path = repositoryRelativePath(target.path, snapshot.repositoryRoot);
		if (path === null) {
			issues.push({ path: target.path, range: target.range, reason: "path is outside the repository" });
			continue;
		}
		const problem = rangeProblem(target.range);
		if (problem) {
			issues.push({ path, range: target.range, reason: problem });
			continue;
		}
		const file = snapshot.files.find((candidate) => candidate.path === path);
		if (!file) {
			issues.push({ path, range: target.range, reason: "file is not part of the current diff" });
			continue;
		}
		if (!containingRange(file, target.range)) {
			const ranges = file.newRanges.map(span).join(", ");
			issues.push({
				path,
				range: target.range,
				reason: `range ${span(target.range)} lies outside the displayed new-side hunk lines (${ranges})`,
			});
			continue;
		}
		candidates.push({ target, path, file });
	}

	const valid: ValidatedTarget[] = [];
	for (const { target, path, file } of candidates) {
		const hash = snapshotAnchorHash(file, path, target.range);
		if (hash === null) {
			issues.push({
				path,
				range: target.range,
				reason: `range ${span(target.range)} does not address the frozen diff content`,
			});
			continue;
		}
		valid.push({
			path,
			newRange: { start: target.range.start, end: target.range.end },
			anchorHash: hash,
			summary: target.summary,
			...(target.rationale === undefined ? {} : { rationale: target.rationale }),
		});
	}
	return { valid, issues };
}

/**
 * Re-check active annotations against the frozen diff loaded for /diff. An
 * annotation is stale when its repository changed, its file left the diff,
 * its range no longer covers new-side hunk lines, or its exact patch text no
 * longer matches. Both partitions preserve input order.
 */
export async function revalidateAnnotations(
	snapshot: DiffSnapshot,
	annotations: readonly DiffAnnotation[],
): Promise<RevalidationResult> {
	const stale: DiffAnnotation[] = [];
	const current: DiffAnnotation[] = [];
	for (const annotation of annotations) {
		if (annotation.repository !== snapshot.repository) {
			stale.push(annotation);
			continue;
		}
		const file = snapshot.files.find((candidate) => candidate.path === annotation.path);
		if (
			!file ||
			!containingRange(file, annotation.newRange) ||
			snapshotAnchorHash(file, annotation.path, annotation.newRange) !== annotation.anchorHash
		) {
			stale.push(annotation);
			continue;
		}
		current.push(annotation);
	}
	return { current, stale };
}
