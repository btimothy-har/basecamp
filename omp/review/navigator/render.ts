/** Text rendering for the navigator finding list and finding card. */

import type { Theme } from "@oh-my-pi/pi-coding-agent";
import { reviewPriorityCounts } from "../artifact.ts";
import type { IdentifiedReviewFinding, PreparedReview, ReviewPriority } from "../schema.ts";
import type { FindingListItem } from "./model.ts";

const PRIORITY_COLOR: Record<ReviewPriority, "error" | "warning" | "muted" | "dim"> = {
	0: "error",
	1: "warning",
	2: "muted",
	3: "dim",
};

export interface RowWindow {
	lines: readonly string[];
	maxStart: number;
	start: number;
}

export function windowRows(rows: readonly string[], requestedStart: number, maxRows: number, theme: Theme): RowWindow {
	const height = Math.max(1, Math.floor(maxRows));
	if (rows.length <= height) return { lines: rows, maxStart: 0, start: 0 };

	const contentHeight = Math.max(1, height - 2);
	const maxStart = Math.max(0, rows.length - contentHeight);
	const start = Math.min(Math.max(0, requestedStart), maxStart);
	const lines = rows.slice(start, start + contentHeight);
	if (start > 0) lines.unshift(theme.fg("dim", `↑ ${start} earlier line${start === 1 ? "" : "s"}`));
	const remaining = rows.length - (start + contentHeight);
	if (remaining > 0) lines.push(theme.fg("dim", `↓ ${remaining} more line${remaining === 1 ? "" : "s"}`));
	return { lines, maxStart, start };
}

function singleLine(text: string): string {
	return text.replace(/\s+/g, " ").trim();
}

export function priorityLabel(priority: ReviewPriority): string {
	return `P${priority}`;
}

export function findingLocation(finding: IdentifiedReviewFinding): string {
	const filePath = singleLine(finding.file_path);
	if (finding.line_end > finding.line_start) return `${filePath}:${finding.line_start}-${finding.line_end}`;
	return `${filePath}:${finding.line_start}`;
}

export function renderHeader(review: PreparedReview, commented: number, theme: Theme): string {
	const total = review.findings.length;
	const findingCount = `${total} finding${total === 1 ? "" : "s"}`;
	const verdict = review.overall_correctness === "correct" ? "Correct" : "Incorrect";
	const confidence = `${Math.round(review.confidence * 100)}% confidence`;
	const counts = reviewPriorityCounts(review.findings);
	return [
		`${theme.fg("accent", theme.bold("Code Review"))}  ${theme.fg("dim", singleLine(review.scope))}`,
		`${theme.fg(review.overall_correctness === "correct" ? "success" : "error", verdict)}  ·  ${confidence}  ·  ${findingCount}  ·  ${commented} commented`,
		`${theme.fg("accent", theme.bold("Overall recommendation"))}  ${review.recommendation.trim()}`,
		theme.fg("dim", `P0 ${counts[0]}   P1 ${counts[1]}   P2 ${counts[2]}   P3 ${counts[3]}`),
		"",
		`${theme.fg("muted", "Why")}  ${review.explanation.trim()}`,
	].join("\n");
}

export function renderFindingList(
	items: FindingListItem[],
	selected: number,
	theme: Theme,
	maxRows = Number.POSITIVE_INFINITY,
): string[] {
	const rowCapacity = Math.max(1, Math.floor(maxRows) - 2);
	const start =
		items.length > maxRows
			? Math.min(Math.max(0, selected - Math.floor(rowCapacity / 2)), Math.max(0, items.length - rowCapacity))
			: 0;
	const end = items.length > maxRows ? Math.min(items.length, start + rowCapacity) : items.length;
	const lines = items.slice(start, end).map((item) => {
		const cursor = item.index === selected ? theme.fg("accent", "▸") : " ";
		const priority = theme.fg(PRIORITY_COLOR[item.finding.priority], `[${priorityLabel(item.finding.priority)}]`);
		const location = theme.fg("dim", findingLocation(item.finding));
		const marker = item.commented ? theme.fg("dim", "  [commented]") : "";
		return `${cursor} ${priority} ${theme.bold(singleLine(item.finding.title))}  ${location}${marker}`;
	});
	if (start > 0) lines.unshift(theme.fg("dim", `↑ ${start} earlier`));
	if (end < items.length) lines.push(theme.fg("dim", `↓ ${items.length - end} more`));
	return lines;
}

export function renderFindingCard(
	finding: IdentifiedReviewFinding,
	index: number,
	total: number,
	theme: Theme,
): string[] {
	const priority = theme.fg(PRIORITY_COLOR[finding.priority], `[${priorityLabel(finding.priority)}]`);
	const confidence = theme.fg("dim", `${Math.round(finding.confidence * 100)}% confidence`);
	const location = theme.fg("dim", findingLocation(finding));
	return [
		theme.fg("dim", `Finding ${index + 1} of ${total}`),
		`${priority}  ${confidence}  ${location}`,
		theme.fg("accent", theme.bold(finding.title)),
		"",
		finding.body,
		"",
		theme.fg("accent", theme.bold("Recommendation")),
		finding.recommendation,
	];
}

export function renderCommentLabel(comment: string, editing: boolean, theme: Theme): string {
	if (editing) return theme.fg("accent", "Your comment");
	if (comment) return `${theme.fg("dim", "Your comment")}\n${comment}`;
	return `${theme.fg("dim", "Your comment")}  ${theme.fg("dim", "[↓]")}`;
}

export function listHint(theme: Theme): string {
	return theme.fg("dim", "[↑↓: Navigate]  [Space: Open]  [s: Submit]  [Esc: Discard all]");
}

export function cardHint(editing: boolean, theme: Theme): string {
	const keys = editing
		? "[Enter: Save]  [Esc: Save and close]  [shift+Enter: New line]"
		: "[←→: Prev/Next]  [PgUp/PgDn: Scroll]  [↓: Comment]  [Esc: Back]";
	return theme.fg("dim", keys);
}
