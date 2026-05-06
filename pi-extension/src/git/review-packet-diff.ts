import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { exec } from "../platform/exec.ts";
import type { ReviewCard, ReviewDiffReference, ReviewPacket, ReviewReference } from "./review-packet.ts";

export const REVIEW_DIFF_DEFAULT_CONTEXT_LINES = 3;
export const REVIEW_DIFF_MAX_CHARS = 16_000;
export const REVIEW_DIFF_TIMEOUT_MS = 10_000;
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

interface UnifiedDiffHunk {
	newStart: number;
	newLines: number;
	lines: string[];
}

interface UnifiedDiffBlock {
	headerLines: string[];
	hunks: UnifiedDiffHunk[];
}

interface LineRange {
	start: number;
	end: number;
}

interface ResolveReviewPacketDiffsOptions {
	cwd?: string;
	maxChars?: number;
	timeout?: number;
}

function assertGitRevision(value: string, label: string): void {
	if (!value || value.startsWith("-") || value.includes("..") || /\s/.test(value)) {
		throw new Error(`${label} must be a simple revision, not an option or range.`);
	}
}

function assertRepoRelativePath(path: string): void {
	if (path.startsWith("/") || path.split(/[\\/]+/).includes("..")) {
		throw new Error("Review diff path must be repo-relative.");
	}
}

function contextLines(diff: ReviewDiffReference): number {
	return diff.contextLines ?? REVIEW_DIFF_DEFAULT_CONTEXT_LINES;
}

function pathForDiff(reference: ReviewReference): string | undefined {
	return reference.diff?.path ?? reference.path;
}

function stripAnsi(value: string): string {
	let result = "";
	let index = 0;

	while (index < value.length) {
		if (value.charCodeAt(index) === 0x1b && value[index + 1] === "[") {
			index += 2;
			while (index < value.length) {
				const code = value.charCodeAt(index);
				index += 1;
				if (code >= 0x40 && code <= 0x7e) break;
			}
			continue;
		}

		result += value[index];
		index += 1;
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

function sanitizeDiffText(value: string): string {
	return stripUnsafeControl(value).replace(/\r\n?/g, "\n");
}

function sanitizeMessage(value: string): string {
	const sanitized = stripUnsafeControl(value).trim();
	if (sanitized.length <= REVIEW_DIFF_MESSAGE_MAX_CHARS) return sanitized;
	return `${sanitized.slice(0, REVIEW_DIFF_MESSAGE_MAX_CHARS)}\n[message truncated]`;
}

export function buildReviewDiffArgs(reference: ReviewReference): string[] {
	if (!reference.diff) return [];

	const diff = reference.diff;
	assertGitRevision(diff.base, "Review diff base");
	if (diff.head) assertGitRevision(diff.head, "Review diff head");

	const path = pathForDiff(reference);
	if (path) assertRepoRelativePath(path);

	const args = ["diff", "--no-ext-diff", "--no-color", `--unified=${contextLines(diff)}`];
	args.push(diff.head ? `${diff.base}...${diff.head}` : diff.base);
	if (path) args.push("--", path);
	return args;
}

function requestedLineRange(diff: ReviewDiffReference): LineRange | null {
	if (diff.lineStart === undefined && diff.lineEnd === undefined) return null;
	const start = diff.lineStart ?? diff.lineEnd;
	const end = diff.lineEnd ?? diff.lineStart;
	if (start === undefined || end === undefined) return null;
	return { start, end };
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
	const normalized = sanitizeDiffText(text);
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

function hunkIntersectsRange(hunk: UnifiedDiffHunk, range: LineRange): boolean {
	const hunkEnd = hunk.newLines === 0 ? hunk.newStart : hunk.newStart + hunk.newLines - 1;
	return hunk.newStart <= range.end && hunkEnd >= range.start;
}

export function filterUnifiedDiffToNewLineRange(text: string, range: LineRange): string | null {
	const lines: string[] = [];

	for (const block of parseUnifiedDiff(text)) {
		const matchingHunks = block.hunks.filter((hunk) => hunkIntersectsRange(hunk, range));
		if (matchingHunks.length === 0) continue;
		lines.push(...block.headerLines);
		for (const hunk of matchingHunks) lines.push(...hunk.lines);
	}

	return lines.length > 0 ? `${lines.join("\n")}\n` : null;
}

export function truncateResolvedDiffText(
	text: string,
	maxChars = REVIEW_DIFF_MAX_CHARS,
): { text: string; truncated: boolean } {
	const sanitized = sanitizeDiffText(text);
	if (sanitized.length <= maxChars) return { text: sanitized, truncated: false };
	const marker = "\n[diff truncated]\n";
	if (maxChars <= marker.length) return { text: marker.slice(0, Math.max(0, maxChars)), truncated: true };
	const keep = maxChars - marker.length;
	return { text: `${sanitized.slice(0, keep)}${marker}`, truncated: true };
}

function noMatch(args: string[], message: string): ResolvedReviewDiffEvidence {
	return { status: "no_match", message, truncated: false, args };
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
				resolvedDiff: {
					status: "git_error",
					message:
						sanitizeMessage(result.stderr) ||
						sanitizeMessage(result.stdout) ||
						`git diff failed with exit code ${result.code}`,
					truncated: false,
					args,
				},
			};
		}

		const range = requestedLineRange(reference.diff);
		const filtered = range ? filterUnifiedDiffToNewLineRange(result.stdout, range) : result.stdout;
		if (!filtered?.trim()) {
			const message = range
				? `No diff hunk intersects requested new-file line range ${range.start}-${range.end}.`
				: "git diff produced no output for this reference.";
			return { ...reference, resolvedDiff: noMatch(args, message) };
		}

		const truncated = truncateResolvedDiffText(filtered, options.maxChars ?? REVIEW_DIFF_MAX_CHARS);
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
			resolvedDiff: {
				status: "git_error",
				message: sanitizeMessage(error instanceof Error ? error.message : String(error)),
				truncated: false,
				args,
			},
		};
	}
}

export async function resolveReviewPacketDiffs(
	pi: ExtensionAPI,
	packet: ReviewPacket,
	options: ResolveReviewPacketDiffsOptions = {},
): Promise<DisplayReviewPacket> {
	const cards = await Promise.all(
		packet.cards.map(async (card) => ({
			...card,
			references: card.references
				? await Promise.all(card.references.map((reference) => resolveReferenceDiff(pi, reference, options)))
				: undefined,
		})),
	);
	return { ...packet, cards };
}
