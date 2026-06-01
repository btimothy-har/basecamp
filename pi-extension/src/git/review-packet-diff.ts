import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exec } from "../platform/exec.ts";
import {
	REVIEW_PACKET_LIMITS,
	type ReviewCard,
	type ReviewDiffReference,
	type ReviewPacket,
	type ReviewReference,
} from "./review-packet.ts";

export const REVIEW_DIFF_DEFAULT_CONTEXT_LINES = 3;
export const REVIEW_DIFF_MAX_CHARS = 16_000;
export const REVIEW_DIFF_TIMEOUT_MS = 10_000;
export const REVIEW_DIFF_CONCURRENCY_LIMIT = 10;
export const REVIEW_DIFF_MESSAGE_MAX_CHARS = 1_000;

export type ResolvedReviewDiffStatus = "resolved" | "no_match" | "git_error";

export interface ResolvedReviewDiffEvidence {
	status: ResolvedReviewDiffStatus;
	text?: string;
	message?: string;
	truncated: boolean;
	args: string[];
}

export type DisplayReviewReference = ReviewReference & {
	resolvedDiff?: ResolvedReviewDiffEvidence;
};

export type DisplayReviewCard = Omit<ReviewCard, "references"> & {
	references?: DisplayReviewReference[];
};

export type DisplayReviewPacket = Omit<ReviewPacket, "cards"> & {
	cards: DisplayReviewCard[];
};

export interface UnifiedDiffHunk {
	newStart: number;
	newLines: number;
	lines: string[];
}

export interface UnifiedDiffBlock {
	headerLines: string[];
	hunks: UnifiedDiffHunk[];
}

export interface ReviewDiffLineRange {
	start: number;
	end: number;
}

interface ResolveReviewPacketDiffsOptions {
	cwd?: string;
	maxChars?: number;
	timeout?: number;
	concurrency?: number;
}

function validateRevision(value: string | undefined, label: string): string {
	if (
		!value ||
		value !== value.trim() ||
		value.startsWith("-") ||
		value.includes("..") ||
		/\s/.test(value) ||
		hasUnsafeControl(value)
	) {
		throw new Error(`${label} must be a simple revision, not an option, range, or whitespace-containing value.`);
	}
	return value;
}

function validateContextLines(value: number | undefined): number {
	if (value === undefined) return REVIEW_DIFF_DEFAULT_CONTEXT_LINES;
	if (!Number.isInteger(value) || value < 0 || value > REVIEW_PACKET_LIMITS.diffContextLines) {
		throw new Error(`Review diff contextLines must be an integer from 0 to ${REVIEW_PACKET_LIMITS.diffContextLines}.`);
	}
	return value;
}

function hasUnsafeControl(value: string): boolean {
	for (const char of value) {
		const code = char.charCodeAt(0);
		if (code < 0x20 || code === 0x7f) return true;
	}
	return false;
}

function validateRepoRelativePath(path: string | undefined): string {
	if (!path || path !== path.trim() || path.startsWith("/") || /^[A-Za-z]:[\\/]/.test(path)) {
		throw new Error("Review diff path must be a repo-relative path.");
	}
	if (path.split(/[\\/]+/).includes("..") || hasUnsafeControl(path)) {
		throw new Error("Review diff path must be a repo-relative path without parent traversal or control characters.");
	}
	return path;
}

function pathForDiff(reference: ReviewReference): string {
	return validateRepoRelativePath(reference.diff?.path ?? reference.path);
}

export function buildReviewDiffArgs(reference: ReviewReference): string[] {
	if (!reference.diff) return [];

	const diff = reference.diff;
	const base = validateRevision(diff.base, "Review diff base");
	const head = diff.head === undefined ? undefined : validateRevision(diff.head, "Review diff head");
	const contextLines = validateContextLines(diff.contextLines);
	const path = pathForDiff(reference);
	const revision = head ? `${base}...${head}` : base;

	return ["diff", "--no-ext-diff", "--no-color", `--unified=${contextLines}`, revision, "--", path];
}

function stripAnsi(value: string): string {
	let result = "";
	let index = 0;

	while (index < value.length) {
		const code = value.charCodeAt(index);
		if (code !== 0x1b) {
			result += value[index];
			index += 1;
			continue;
		}

		const next = value[index + 1];
		if (next === "[") {
			index += 2;
			while (index < value.length) {
				const sequenceCode = value.charCodeAt(index);
				index += 1;
				if (sequenceCode >= 0x40 && sequenceCode <= 0x7e) break;
			}
			continue;
		}

		if (next === "]") {
			index += 2;
			while (index < value.length) {
				const sequenceCode = value.charCodeAt(index);
				if (sequenceCode === 0x07) {
					index += 1;
					break;
				}
				if (sequenceCode === 0x1b && value[index + 1] === "\\") {
					index += 2;
					break;
				}
				index += 1;
			}
			continue;
		}

		if (next === "P" || next === "X" || next === "^" || next === "_") {
			index += 2;
			while (index < value.length) {
				if (value.charCodeAt(index) === 0x1b && value[index + 1] === "\\") {
					index += 2;
					break;
				}
				index += 1;
			}
			continue;
		}

		index += next ? 2 : 1;
	}

	return result;
}

function stripUnsafeControl(value: string): string {
	let result = "";
	for (const char of stripAnsi(value)) {
		const code = char.charCodeAt(0);
		if (code === 0x09 || code === 0x0a || code === 0x0d || (code >= 0x20 && code !== 0x7f)) result += char;
	}
	return result;
}

function sanitizeText(value: string): string {
	return stripUnsafeControl(value).replace(/\r\n?/g, "\n");
}

function sanitizeMessage(value: string): string {
	const sanitized = sanitizeText(value).trim();
	if (sanitized.length <= REVIEW_DIFF_MESSAGE_MAX_CHARS) return sanitized;
	return `${sanitized.slice(0, REVIEW_DIFF_MESSAGE_MAX_CHARS)}\n[message truncated]`;
}

function parseHunkHeader(line: string): { newStart: number; newLines: number } | null {
	const match = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/.exec(line);
	if (!match?.[1]) return null;
	return {
		newStart: Number.parseInt(match[1], 10),
		newLines: match[2] === undefined ? 1 : Number.parseInt(match[2], 10),
	};
}

export function parseUnifiedDiff(text: string): UnifiedDiffBlock[] {
	const normalized = sanitizeText(text);
	if (!normalized) return [];

	const lines = normalized.endsWith("\n") ? normalized.slice(0, -1).split("\n") : normalized.split("\n");
	const blocks: UnifiedDiffBlock[] = [];
	let block: UnifiedDiffBlock = { headerLines: [], hunks: [] };
	let hunk: UnifiedDiffHunk | null = null;

	function finishHunk(): void {
		if (!hunk) return;
		block.hunks.push(hunk);
		hunk = null;
	}

	function finishBlock(): void {
		finishHunk();
		if (block.headerLines.length > 0 || block.hunks.length > 0) blocks.push(block);
		block = { headerLines: [], hunks: [] };
	}

	for (const line of lines) {
		if (line.startsWith("diff --git ")) {
			finishBlock();
			block.headerLines.push(line);
			continue;
		}

		const hunkHeader = parseHunkHeader(line);
		if (hunkHeader) {
			finishHunk();
			hunk = { ...hunkHeader, lines: [line] };
			continue;
		}

		if (hunk) hunk.lines.push(line);
		else block.headerLines.push(line);
	}

	finishBlock();
	return blocks;
}

function hunkIntersectsRange(hunk: UnifiedDiffHunk, range: ReviewDiffLineRange): boolean {
	const hunkEnd = hunk.newLines === 0 ? hunk.newStart : hunk.newStart + hunk.newLines - 1;
	return hunk.newStart <= range.end && hunkEnd >= range.start;
}

export function filterUnifiedDiffToNewLineRange(text: string, range: ReviewDiffLineRange): string | null {
	const output: string[] = [];

	for (const block of parseUnifiedDiff(text)) {
		const matchingHunks = block.hunks.filter((hunk) => hunkIntersectsRange(hunk, range));
		if (matchingHunks.length === 0) continue;
		output.push(...block.headerLines);
		for (const hunk of matchingHunks) output.push(...hunk.lines);
	}

	return output.length > 0 ? `${output.join("\n")}\n` : null;
}

export function truncateResolvedDiffText(
	text: string,
	maxChars = REVIEW_DIFF_MAX_CHARS,
): { text: string; truncated: boolean } {
	const sanitized = sanitizeText(text);
	if (sanitized.length <= maxChars) return { text: sanitized, truncated: false };

	const marker = "\n[diff truncated]\n";
	if (maxChars <= marker.length) return { text: marker.slice(0, Math.max(0, maxChars)), truncated: true };

	return { text: `${sanitized.slice(0, maxChars - marker.length)}${marker}`, truncated: true };
}

function requestedLineRange(diff: ReviewDiffReference): ReviewDiffLineRange | null {
	if (diff.lineStart === undefined && diff.lineEnd === undefined) return null;
	const start = diff.lineStart ?? diff.lineEnd;
	const end = diff.lineEnd ?? diff.lineStart;
	if (start === undefined || end === undefined) return null;
	return { start, end };
}

function noMatch(args: string[], message: string): ResolvedReviewDiffEvidence {
	return { status: "no_match", message: sanitizeMessage(message), truncated: false, args };
}

function gitError(args: string[], message: string): ResolvedReviewDiffEvidence {
	return { status: "git_error", message: sanitizeMessage(message), truncated: false, args };
}

async function resolveReferenceDiff(
	pi: ExtensionAPI,
	reference: ReviewReference,
	options: ResolveReviewPacketDiffsOptions,
): Promise<DisplayReviewReference> {
	if (!reference.diff) return reference;

	let args: string[] = [];
	try {
		args = buildReviewDiffArgs(reference);
		const result = await exec(pi, "git", args, {
			cwd: options.cwd,
			timeout: options.timeout ?? REVIEW_DIFF_TIMEOUT_MS,
		});

		if (result.code !== 0) {
			return {
				...reference,
				resolvedDiff: gitError(
					args,
					sanitizeMessage(result.stderr) ||
						sanitizeMessage(result.stdout) ||
						`git diff failed with exit code ${result.code}`,
				),
			};
		}

		const range = requestedLineRange(reference.diff);
		const diffText = range ? filterUnifiedDiffToNewLineRange(result.stdout, range) : sanitizeText(result.stdout);
		if (!diffText?.trim()) {
			const message = range
				? `No diff hunk intersects requested new-file line range ${range.start}-${range.end}.`
				: "git diff produced no output for this reference.";
			return { ...reference, resolvedDiff: noMatch(args, message) };
		}

		const truncated = truncateResolvedDiffText(diffText, options.maxChars ?? REVIEW_DIFF_MAX_CHARS);
		return {
			...reference,
			resolvedDiff: {
				status: "resolved",
				text: truncated.text,
				truncated: truncated.truncated,
				args,
			},
		};
	} catch (error) {
		return {
			...reference,
			resolvedDiff: gitError(args, error instanceof Error ? error.message : String(error)),
		};
	}
}

async function runWithConcurrencyLimit<T>(limit: number, tasks: readonly (() => Promise<T>)[]): Promise<T[]> {
	if (tasks.length === 0) return [];
	const results: T[] = new Array(tasks.length);
	let nextIndex = 0;

	async function worker(): Promise<void> {
		while (nextIndex < tasks.length) {
			const index = nextIndex;
			nextIndex += 1;
			const task = tasks[index];
			if (!task) throw new Error(`Missing review diff task at index ${index}`);
			results[index] = await task();
		}
	}

	const workerCount = Math.min(Math.max(1, Math.floor(limit)), tasks.length);
	await Promise.all(Array.from({ length: workerCount }, () => worker()));
	return results;
}

export async function resolveReviewPacketDiffs(
	pi: ExtensionAPI,
	packet: ReviewPacket,
	options: ResolveReviewPacketDiffsOptions = {},
): Promise<DisplayReviewPacket> {
	const cards: DisplayReviewCard[] = packet.cards.map((card) => ({
		...card,
		references: card.references?.map((reference) => ({ ...reference })),
	}));
	const tasks: (() => Promise<void>)[] = [];

	for (const card of cards) {
		if (card.kind !== "diff-evidence") continue;
		card.references?.forEach((reference, index, references) => {
			if (!reference.diff) return;
			tasks.push(async () => {
				references[index] = await resolveReferenceDiff(pi, reference, options);
			});
		});
	}

	await runWithConcurrencyLimit(options.concurrency ?? REVIEW_DIFF_CONCURRENCY_LIMIT, tasks);
	return { ...packet, cards };
}
