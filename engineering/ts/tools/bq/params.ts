/**
 * Constants, parameter schema, and result/summary/approval types for the bq_query tool.
 */

import type { AgentToolResult } from "@earendil-works/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";

export type BigQueryOutputFormat = "csv" | "json";

export const DEFAULT_OUTPUT_FORMAT: BigQueryOutputFormat = "csv";
export const DEFAULT_MAX_ROWS = 100;
export const BQ_TIMEOUT_MS = 10 * 60 * 1000;
export const BQ_INTERACTIVE_APPROVAL_THRESHOLD_BYTES = 1_000_000_000_000n;
export const BQ_NO_UI_SOFT_LOCK_THRESHOLD_BYTES = 5_000_000_000_000n;
export const MAX_ERROR_CHARS = 20_000;
export const MAX_DESCRIPTION_CHARS = 500;
export const DISPLAY_ELLIPSIS = "…";
export const MAX_CALL_LINE_CHARS = 110;
export const MAX_CALL_PATH_CHARS = 42;
export const MAX_RESULT_LINE_CHARS = 220;
export const MIN_DISPLAY_DESCRIPTION_CHARS = 24;
export const ANSI_ESCAPE_PATTERN = new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, "g");
export const CONTROL_CHARS_PATTERN = /[\p{Cc}]+/gu;
export const TMP_PI_ROOT = "/tmp/pi";
export const SCRATCH_SQL_PATH_ERROR =
	"bq_query SQL files must live under /tmp/pi/** (the workspace scratch directory).";

export const BqQueryParams = Type.Object({
	path: Type.String({
		description:
			"Path to a .sql file under the workspace scratch directory (`/tmp/pi/**`). Relative paths resolve from the current effective cwd.",
	}),
	description: Type.String({
		description: "Required short TLDR of what this query does. Do not include raw SQL or result rows.",
	}),
	dryRun: Type.Optional(
		Type.Boolean({
			description: "Validate the SQL with a BigQuery dry run and do not execute it. Defaults to false.",
		}),
	),
	force: Type.Optional(
		Type.Boolean({
			description:
				"Bypass scan-approval gates (no-UI soft lock, estimate_unknown, interactive confirmation) and proceed with query execution. Does not bypass dry-run failures or execution errors. Defaults to false.",
		}),
	),
	projectId: Type.Optional(Type.String({ description: "BigQuery project ID. Uses the bq CLI default when omitted." })),
	location: Type.Optional(Type.String({ description: "BigQuery job location. Uses the bq CLI default when omitted." })),
	maxRows: Type.Optional(Type.Number({ description: "Maximum rows for bq query output. Defaults to 100." })),
	outputFormat: Type.Optional(
		Type.Union([
			Type.Literal("csv", { description: "Write CSV query output." }),
			Type.Literal("json", { description: "Write JSON query output." }),
		]),
	),
});

export type BqQueryInput = Static<typeof BqQueryParams>;

export interface BqCaptureResult {
	code: number;
	stdout: string;
	stderr: string;
	timedOut: boolean;
	aborted: boolean;
}

export interface BqFileResult {
	code: number;
	stderr: string;
	outputBytes: number;
	outputLineBreaks: number;
	outputEndsWithNewline: boolean;
	timedOut: boolean;
	aborted: boolean;
}

export interface SchemaFieldSummary {
	name: string;
	type: string | null;
	mode: string | null;
}

export interface DryRunSummary {
	ran: boolean;
	jobId: string | null;
	estimatedBytes: string | null;
	statementType: string | null;
	schemaFieldCount: number | null;
	schemaFields: SchemaFieldSummary[];
	message?: string;
}

export interface JobSummary {
	fetched: boolean;
	state: string | null;
	error: string | null;
	totalBytesProcessed: string | null;
	totalBytesBilled: string | null;
	totalSlotMs: string | null;
	cacheHit: boolean | null;
	creationTime: string | null;
	startTime: string | null;
	endTime: string | null;
	message?: string;
}

type BqScanApprovalReason = "over_threshold" | "estimate_unknown" | "estimate_non_authoritative" | null;
export type BqScanApprovalMode = "interactive_approval" | "no_ui_soft_lock";

export interface BqScanApprovalMetadata {
	thresholdBytes: string;
	estimatedBytes: string | null;
	required: boolean;
	reason: BqScanApprovalReason;
	mode: BqScanApprovalMode;
	approved: boolean | null;
	granted: boolean | null;
	forced: boolean;
}

export interface BqQueryDetails {
	description: string | null;
	sqlPath: string;
	outputPath: string | null;
	outputFormat: BigQueryOutputFormat;
	maxRows: number;
	projectId: string | null;
	location: string | null;
	jobId: string;
	outputBytes: number | null;
	rowCount: number | null;
	diagnosticPath: string | null;
	dryRun: DryRunSummary;
	approval: BqScanApprovalMetadata;
	job: JobSummary | null;
}

export type BqToolResult = AgentToolResult<BqQueryDetails> & { isError?: boolean };
