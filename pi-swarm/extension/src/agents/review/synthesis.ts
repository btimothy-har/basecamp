import type { Finding, Severity } from "./findings.ts";
import { SEVERITY_RANK } from "./findings.ts";

export type VerdictDecision = "request-changes" | "comment" | "approve-with-notes" | "approve";

export interface Verdict {
	decision: VerdictDecision;
	blocking: boolean;
	counts: Record<Severity, number>;
}

function compareNullableStrings(left: string | null, right: string | null): number {
	if (left === null && right === null) return 0;
	if (left === null) return 1;
	if (right === null) return -1;
	return left.localeCompare(right);
}

function compareNullableNumbers(left: number | null, right: number | null): number {
	if (left === null && right === null) return 0;
	if (left === null) return 1;
	if (right === null) return -1;
	return left - right;
}

export function mergeFindings(reports: Finding[][]): Finding[] {
	return reports
		.flat()
		.map((finding, index) => ({ finding, index }))
		.sort((left, right) => {
			const severity = SEVERITY_RANK[left.finding.severity] - SEVERITY_RANK[right.finding.severity];
			if (severity !== 0) return severity;

			const file = compareNullableStrings(left.finding.file, right.finding.file);
			if (file !== 0) return file;

			const lineStart = compareNullableNumbers(left.finding.lineStart, right.finding.lineStart);
			if (lineStart !== 0) return lineStart;

			return left.index - right.index;
		})
		.map(({ finding }) => finding);
}

function emptyCounts(): Record<Severity, number> {
	return {
		critical: 0,
		high: 0,
		medium: 0,
		low: 0,
	};
}

export function computeVerdict(findings: Finding[]): Verdict {
	const counts = emptyCounts();
	for (const finding of findings) {
		counts[finding.severity] += 1;
	}

	if (counts.critical >= 1) return { decision: "request-changes", blocking: true, counts };
	if (counts.high >= 3) return { decision: "request-changes", blocking: true, counts };
	if (counts.high >= 1) return { decision: "comment", blocking: false, counts };
	if (counts.medium >= 1 || counts.low >= 1) return { decision: "approve-with-notes", blocking: false, counts };
	return { decision: "approve", blocking: false, counts };
}
