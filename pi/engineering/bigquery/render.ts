/**
 * Result text builders and TUI call/result renderers for the bq_query tool.
 */

import type { AgentToolResult, Theme } from "@earendil-works/pi-coding-agent";
import { formatScanApprovalRequirement, formatScanApprovalStatus } from "./approval.ts";
import {
	descriptionPreview,
	displayLength,
	formatBytes,
	formatScanBytes,
	safeApprovalPromptValue,
	sqlPathPreview,
} from "./format.ts";
import {
	BQ_TIMEOUT_MS,
	type BqCaptureResult,
	type BqFileResult,
	type BqQueryDetails,
	type BqQueryInput,
	type BqToolResult,
	MAX_CALL_LINE_CHARS,
	MAX_CALL_PATH_CHARS,
	MAX_RESULT_LINE_CHARS,
	MIN_DISPLAY_DESCRIPTION_CHARS,
} from "./params.ts";

function diagnosticText(result: BqCaptureResult | BqFileResult): string {
	return result.stderr.trim();
}

export function formatProcessFailure(result: BqCaptureResult | BqFileResult, fallback: string): string {
	const pieces: string[] = [];
	if (result.aborted) pieces.push("bq process aborted.");
	if (result.timedOut) pieces.push(`bq process timed out after ${BQ_TIMEOUT_MS / 1000}s.`);
	pieces.push(diagnosticText(result) || fallback);
	return pieces.join("\n");
}

export function csvRowCount(result: BqFileResult): number {
	if (result.outputBytes === 0) return 0;
	const lineCount = result.outputLineBreaks + (result.outputEndsWithNewline ? 0 : 1);
	return Math.max(0, lineCount - 1);
}

export function buildDryRunText(details: BqQueryDetails): string {
	const lines = ["BigQuery dry run passed."];
	if (details.description) lines.push(`Description: ${details.description}`);
	lines.push(
		`SQL file: ${details.sqlPath}`,
		`Dry-run job ID: ${details.dryRun.jobId ?? "unknown"}`,
		`Estimated scan: ${formatScanBytes(details.dryRun.estimatedBytes)}`,
	);
	if (details.projectId) lines.push(`Project: ${details.projectId}`);
	if (details.location) lines.push(`Location: ${details.location}`);
	if (details.dryRun.statementType) {
		lines.push(`Statement type: ${safeApprovalPromptValue(details.dryRun.statementType, "unknown")}`);
	}
	if (details.dryRun.schemaFieldCount !== null) {
		lines.push(`Schema fields: ${details.dryRun.schemaFieldCount}`);
	}
	const approvalRequirement = formatScanApprovalRequirement(details);
	if (approvalRequirement) {
		const gateText =
			details.approval.mode === "no_ui_soft_lock"
				? "No-UI soft lock would apply before execution"
				: "Approval would be required before execution";
		lines.push(`${gateText}: ${approvalRequirement}.`);
	}
	if (details.dryRun.message) lines.push(`Dry-run note: ${details.dryRun.message}`);
	return lines.join("\n");
}

export function buildSuccessText(details: BqQueryDetails, outputBytes: number): string {
	const lines = ["BigQuery query complete."];
	if (details.description) lines.push(`Description: ${details.description}`);
	lines.push(
		`SQL file: ${details.sqlPath}`,
		`Job ID: ${details.jobId}`,
		`Output: ${details.outputPath}`,
		`Output bytes: ${outputBytes}`,
		`Rows: ${details.rowCount ?? "unknown"}`,
		`Format: ${details.outputFormat}`,
		`Max rows: ${details.maxRows}`,
	);
	if (details.projectId) lines.push(`Project: ${details.projectId}`);
	if (details.location) lines.push(`Location: ${details.location}`);

	if (details.dryRun.ran) {
		lines.push(`Dry run: passed; estimated scan ${formatScanBytes(details.dryRun.estimatedBytes)}`);
		if (details.dryRun.statementType) {
			lines.push(`Statement type: ${safeApprovalPromptValue(details.dryRun.statementType, "unknown")}`);
		}
		if (details.dryRun.message) lines.push(`Dry-run note: ${details.dryRun.message}`);
	} else {
		lines.push("Dry run: skipped");
	}

	lines.push(formatScanApprovalStatus(details));

	if (details.job?.fetched) {
		if (details.job.state) lines.push(`Job state: ${details.job.state}`);
		lines.push(`Bytes processed: ${formatBytes(details.job.totalBytesProcessed)}`);
		lines.push(`Bytes billed: ${formatBytes(details.job.totalBytesBilled)}`);
		if (details.job.cacheHit !== null) lines.push(`Cache hit: ${details.job.cacheHit ? "yes" : "no"}`);
	} else if (details.job?.message) {
		lines.push(`Job metadata: ${details.job.message}`);
	}

	return lines.join("\n");
}

export function renderCall(args: BqQueryInput, theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	const sqlPath = sqlPathPreview(args.path, MAX_CALL_PATH_CHARS);
	const descriptionBudget = Math.max(
		MIN_DISPLAY_DESCRIPTION_CHARS,
		MAX_CALL_LINE_CHARS - "bq_query ".length - " · ".length - displayLength(sqlPath),
	);
	const description = descriptionPreview(args.description, descriptionBudget) ?? "...";
	return new Text(
		theme.fg("toolTitle", theme.bold("bq_query ")) + theme.fg("dim", `${description} · ${sqlPath}`),
		0,
		0,
	);
}

export function renderResult(
	result: AgentToolResult<BqQueryDetails>,
	options: { isPartial?: boolean },
	theme: Theme,
	context?: { isError?: boolean },
) {
	const { Text } = require("@earendil-works/pi-tui");
	if (options.isPartial) return new Text(theme.fg("dim", "..."), 0, 0);

	const details = result.details;
	if (!details) {
		const text = result.content[0];
		return new Text(text?.type === "text" ? text.text : "bq_query complete", 0, 0);
	}

	if ((result as BqToolResult).isError || context?.isError) {
		return new Text(theme.fg("error", "bq_query failed") + theme.fg("dim", ` ${details.sqlPath}`), 0, 0);
	}

	const bytes = details.job?.totalBytesProcessed ?? details.dryRun.estimatedBytes;
	const suffix = bytes ? ` — ${formatBytes(bytes)}` : "";
	const outputSummary = ` → ${details.outputPath ?? "no output"}${suffix}`;
	const descriptionBudget = MAX_RESULT_LINE_CHARS - "✓ bq_query".length - displayLength(outputSummary) - 1;
	const description =
		descriptionBudget >= MIN_DISPLAY_DESCRIPTION_CHARS
			? descriptionPreview(details.description, descriptionBudget)
			: null;
	return new Text(
		theme.fg("success", "✓") +
			theme.fg("toolTitle", theme.bold(" bq_query")) +
			(description ? theme.fg("dim", ` ${description}`) : "") +
			theme.fg("dim", outputSummary),
		0,
		0,
	);
}
