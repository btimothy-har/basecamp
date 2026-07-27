/** Text rendering for the annotation list and finding card. */

import type { Theme } from "@earendil-works/pi-coding-agent";
import type { Finding, Severity } from "#code-review/findings.ts";
import type { FindingListItem } from "./model.ts";

const SEVERITY_COLOR: Record<Severity, "error" | "warning" | "muted" | "dim"> = {
	critical: "error",
	high: "warning",
	medium: "muted",
	low: "dim",
};

export function findingLocation(finding: Finding): string {
	return `${finding.file ?? "(no file)"}:${finding.lineStart ?? "?"}`;
}

export function renderHeader(total: number, commented: number, theme: Theme): string {
	const counts = `${total} finding${total === 1 ? "" : "s"}  ·  ${commented} commented`;
	return `${theme.fg("accent", theme.bold("Code Review"))}  ${theme.fg("dim", counts)}`;
}

export function renderFindingList(items: FindingListItem[], selected: number, theme: Theme): string[] {
	return items.map((item) => {
		const cursor = item.index === selected ? theme.fg("accent", "▸") : " ";
		const severity = theme.fg(SEVERITY_COLOR[item.finding.severity], `[${item.finding.severity}]`);
		const location = theme.fg("dim", findingLocation(item.finding));
		// The comment marker trails the line so its double-width glyph cannot skew column alignment.
		const marker = item.commented ? "  📝" : "";
		return `${cursor} ${severity} ${theme.bold(item.finding.title)}  ${location}${marker}`;
	});
}

export function renderFindingCard(finding: Finding, index: number, total: number, theme: Theme): string[] {
	const severity = theme.fg(SEVERITY_COLOR[finding.severity], `[${finding.severity}]`);
	return [
		theme.fg("dim", `Finding ${index + 1} of ${total}`),
		`${severity} ${theme.fg("dim", `[${finding.dimension}]`)}  ${theme.fg("dim", findingLocation(finding))}`,
		theme.fg("accent", theme.bold(finding.title)),
		"",
		finding.detail,
		"",
		theme.fg("warning", `Fix: ${finding.remediation ?? "—"}`),
		"",
		`${theme.fg("muted", "Author response")}  ${theme.fg("dim", finding.response?.trim() || "—")}`,
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
		: "[←→: Prev/Next]  [↓: Comment]  [Esc: Back to list]";
	return theme.fg("dim", keys);
}
