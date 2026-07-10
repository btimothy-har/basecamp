/**
 * Scan-approval policy for the bq_query tool: thresholds, metadata, status text, and the execution gate.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { formatScanBytes, safeApprovalPromptValue } from "./format.ts";
import { isNonAuthoritativeDryRunStatementType, parseDryRunEstimatedBytes } from "./job-summary.ts";
import {
	BQ_INTERACTIVE_APPROVAL_THRESHOLD_BYTES,
	BQ_NO_UI_SOFT_LOCK_THRESHOLD_BYTES,
	type BqQueryDetails,
	type BqScanApprovalMetadata,
	type BqScanApprovalMode,
	type BqToolResult,
} from "./params.ts";

function scanApprovalThresholdBytes(mode: BqScanApprovalMode): bigint {
	return mode === "no_ui_soft_lock" ? BQ_NO_UI_SOFT_LOCK_THRESHOLD_BYTES : BQ_INTERACTIVE_APPROVAL_THRESHOLD_BYTES;
}

export function scanApprovalModeForContext(ctx: ExtensionContext): BqScanApprovalMode {
	return ctx.hasUI === false ? "no_ui_soft_lock" : "interactive_approval";
}

export function buildScanApprovalMetadata(
	rawEstimatedBytes: string | null,
	statementType: string | null = null,
	mode: BqScanApprovalMode = "interactive_approval",
): BqScanApprovalMetadata {
	const threshold = scanApprovalThresholdBytes(mode);
	const thresholdBytes = threshold.toString();
	const estimatedBytes = parseDryRunEstimatedBytes(rawEstimatedBytes);
	const estimateNonAuthoritative = isNonAuthoritativeDryRunStatementType(statementType);

	if (estimatedBytes === null) {
		return {
			thresholdBytes,
			estimatedBytes: null,
			required: true,
			reason: "estimate_unknown",
			mode,
			approved: null,
			granted: null,
			forced: false,
		};
	}

	const overThreshold = estimatedBytes > threshold;
	const required = overThreshold || estimateNonAuthoritative;
	return {
		thresholdBytes,
		estimatedBytes: estimatedBytes.toString(),
		required,
		reason: overThreshold ? "over_threshold" : estimateNonAuthoritative ? "estimate_non_authoritative" : null,
		mode,
		approved: null,
		granted: null,
		forced: false,
	};
}

function withScanApprovalDecision(
	approval: BqScanApprovalMetadata,
	approved: boolean | null,
	granted: boolean | null,
	forced = approval.forced,
): BqScanApprovalMetadata {
	return { ...approval, approved, granted, forced };
}

function formatScanThresholdLabel(approval: BqScanApprovalMetadata): string {
	return approval.mode === "no_ui_soft_lock" ? "no-UI soft-lock threshold" : "approval threshold";
}

function formatNonAuthoritativeEstimateNote(statementType: string | null): string {
	const statementTypeText = safeApprovalPromptValue(statementType, "");
	return statementTypeText
		? `dry-run estimate may be non-authoritative for statement type ${statementTypeText}`
		: "dry-run estimate may be non-authoritative";
}

export function formatScanApprovalRequirement(details: BqQueryDetails): string | null {
	const approval = details.approval;
	if (!approval.required) return null;

	const threshold = formatScanBytes(approval.thresholdBytes);
	const thresholdLabel = formatScanThresholdLabel(approval);
	const nonAuthoritativeNote = isNonAuthoritativeDryRunStatementType(details.dryRun.statementType)
		? `; ${formatNonAuthoritativeEstimateNote(details.dryRun.statementType)}`
		: "";

	if (approval.reason === "over_threshold") {
		const estimate = approval.estimatedBytes ? formatScanBytes(approval.estimatedBytes) : "unknown";
		return `estimated scan ${estimate} exceeds ${thresholdLabel} ${threshold}${nonAuthoritativeNote}`;
	}

	if (approval.reason === "estimate_unknown") {
		return `scan estimate is unknown or unparseable${nonAuthoritativeNote}; ${thresholdLabel} is ${threshold}`;
	}

	if (approval.reason === "estimate_non_authoritative") {
		const estimate = approval.estimatedBytes ? formatScanBytes(approval.estimatedBytes) : "unknown";
		return `${formatNonAuthoritativeEstimateNote(details.dryRun.statementType)}; estimated scan ${estimate} may be incomplete; ${thresholdLabel} is ${threshold}`;
	}

	return `${thresholdLabel} is ${threshold}`;
}

export function formatScanApprovalStatus(details: BqQueryDetails): string {
	const approval = details.approval;
	const threshold = formatScanBytes(approval.thresholdBytes);
	const thresholdLabel = formatScanThresholdLabel(approval);

	if (!approval.required) {
		const estimate = approval.estimatedBytes ? formatScanBytes(approval.estimatedBytes) : "unknown";
		if (approval.mode === "no_ui_soft_lock") {
			return `Soft lock: not triggered; estimated scan ${estimate} is at or below ${thresholdLabel} ${threshold}.`;
		}
		return `Approval: not required; estimated scan ${estimate} is at or below threshold ${threshold}.`;
	}

	const requirement =
		formatScanApprovalRequirement(details) ??
		(approval.reason === "estimate_unknown"
			? `scan estimate is unknown or unparseable; ${thresholdLabel} is ${threshold}`
			: `${thresholdLabel} is ${threshold}`);

	if (approval.mode === "no_ui_soft_lock") {
		if (approval.forced && approval.granted === true) {
			return `Soft lock: overridden with force: true in no-UI context; ${requirement}.`;
		}
		if (approval.granted === false) {
			return `Soft lock: required but not overridden; ${requirement}. Rerun with force: true to intentionally proceed.`;
		}
		return `Soft lock: required before execution in no-UI context; ${requirement}. Rerun with force: true to intentionally proceed.`;
	}

	if (approval.reason === "estimate_unknown") {
		if (approval.forced && approval.granted === true) {
			return `Approval: overridden with force: true; ${requirement}.`;
		}
		if (approval.granted === false) {
			return `Approval: required but not granted; ${requirement}.`;
		}
		return `Approval: required before execution; ${requirement}.`;
	}

	if (approval.reason === "over_threshold" || approval.reason === "estimate_non_authoritative") {
		if (approval.forced && approval.granted === true) {
			return `Approval: overridden with force: true; ${requirement}.`;
		}
		if (approval.approved === true && approval.granted === true) {
			return `Approval: required and granted; ${requirement}.`;
		}
		if (approval.approved === false) return `Approval: required and declined; ${requirement}.`;
		if (approval.granted === false) return `Approval: required but not granted; ${requirement}.`;
		return `Approval: required before execution; ${requirement}.`;
	}

	if (approval.granted === false) {
		return "Approval: required but not granted; approval requirement could not be determined.";
	}
	return "Approval: required before execution; approval requirement could not be determined.";
}

function buildScanApprovalPrompt(details: BqQueryDetails): string {
	const lines = [
		`TLDR: ${safeApprovalPromptValue(details.description, "unavailable")}`,
		`SQL file: ${safeApprovalPromptValue(details.sqlPath, "unknown")}`,
		`Project: ${safeApprovalPromptValue(details.projectId, "default")}`,
		`Location: ${safeApprovalPromptValue(details.location, "default")}`,
		`Estimated scan: ${formatScanBytes(details.approval.estimatedBytes)}`,
		`Approval threshold: ${formatScanBytes(details.approval.thresholdBytes)}`,
		`Output format: ${details.outputFormat}`,
		`Max rows: ${details.maxRows}`,
	];
	if (details.dryRun.statementType) {
		lines.push(`Statement type: ${safeApprovalPromptValue(details.dryRun.statementType, "unknown")}`);
	}
	const requirement = formatScanApprovalRequirement(details);
	if (requirement) lines.push(`Approval requirement: ${requirement}.`);
	lines.push("Note: maxRows limits returned rows, not scanned bytes.");
	return lines.join("\n");
}

function buildApprovalGateFailureText(details: BqQueryDetails, headline: string): string {
	const lines = [headline];
	if (details.description) lines.push(`Description: ${details.description}`);
	lines.push(
		`SQL file: ${details.sqlPath}`,
		`Dry-run job ID: ${details.dryRun.jobId ?? "unknown"}`,
		`Estimated scan: ${formatScanBytes(details.approval.estimatedBytes)}`,
	);
	if (details.dryRun.statementType) {
		lines.push(`Statement type: ${safeApprovalPromptValue(details.dryRun.statementType, "unknown")}`);
	}
	lines.push(formatScanApprovalStatus(details));
	if (details.dryRun.message) lines.push(`Dry-run note: ${details.dryRun.message}`);
	return lines.join("\n");
}

export async function evaluateScanApproval(
	details: BqQueryDetails,
	ctx: ExtensionContext,
	signal: AbortSignal | undefined,
	force: boolean,
): Promise<BqToolResult | null> {
	const approval = details.approval;

	if (!approval.required) {
		details.approval = withScanApprovalDecision(approval, null, true);
		return null;
	}

	if (force) {
		details.approval = withScanApprovalDecision(approval, null, true, true);
		return null;
	}

	if (approval.mode === "no_ui_soft_lock") {
		details.approval = withScanApprovalDecision(approval, null, false);
		return {
			isError: true,
			details,
			content: [
				{
					type: "text",
					text: buildApprovalGateFailureText(
						details,
						"BigQuery execution soft-locked in no-UI context; execution was not attempted. Rerun bq_query with force: true to intentionally override this no-UI soft lock.",
					),
				},
			],
		};
	}

	if (approval.reason === "estimate_unknown") {
		details.approval = withScanApprovalDecision(approval, null, false);
		return {
			isError: true,
			details,
			content: [
				{
					type: "text",
					text: buildApprovalGateFailureText(
						details,
						"BigQuery execution blocked; dry-run scan estimate was missing or unparseable, so execution was not attempted.",
					),
				},
			],
		};
	}

	if (approval.reason === "over_threshold" || approval.reason === "estimate_non_authoritative") {
		const approved = await ctx.ui.confirm("Approve BigQuery execution?", buildScanApprovalPrompt(details), { signal });
		if (!approved) {
			details.approval = withScanApprovalDecision(details.approval, false, false);
			return {
				isError: true,
				details,
				content: [
					{
						type: "text",
						text: buildApprovalGateFailureText(
							details,
							"BigQuery execution declined by user; execution was not attempted.",
						),
					},
				],
			};
		}

		details.approval = withScanApprovalDecision(details.approval, true, true);
		return null;
	}

	details.approval = withScanApprovalDecision(approval, null, false);
	return {
		isError: true,
		details,
		content: [
			{
				type: "text",
				text: buildApprovalGateFailureText(
					details,
					"BigQuery execution blocked; approval requirement could not be determined, so execution was not attempted.",
				),
			},
		],
	};
}
