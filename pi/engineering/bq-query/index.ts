/**
 * bq_query tool — run BigQuery SQL files through the bq CLI.
 *
 * SQL is read from a .sql file and sent to bq via stdin. Query stdout is
 * written to scratch space; tool output contains only a summary and metadata.
 */

import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getWorkspaceEffectiveCwd, requireWorkspaceState } from "#core/workspace/service.ts";
import { buildQueryArgs, buildShowArgs, runBqCapture, runBqToFile } from "../bigquery/cli.ts";
import { emptyDryRun, emptyJob, summarizeDryRun, summarizeJob } from "../bigquery/job-summary.ts";
import { buildScanApprovalMetadata, evaluateScanApproval, scanApprovalModeForContext } from "./approval.ts";
import { sanitizeQueryDescription, trimOrNull } from "./format.ts";
import {
	type BqQueryDetails,
	BqQueryParams,
	type BqToolResult,
	DEFAULT_MAX_ROWS,
	DEFAULT_OUTPUT_FORMAT,
} from "./params.ts";
import {
	buildDryRunText,
	buildSuccessText,
	csvRowCount,
	formatProcessFailure,
	renderCall,
	renderResult,
} from "./render.ts";
import {
	ensurePrivateDir,
	queryHash,
	resolveSqlPath,
	safeStem,
	timestampForFile,
	timestampForJob,
	validateMaxRows,
	writeDiagnostic,
} from "./sql-files.ts";

export function registerBqQueryTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "bq_query",
		label: "BigQuery Query",
		description:
			"Run a BigQuery query from a .sql file with the bq CLI. " +
			"Requires a short plain-language description/TLDR. " +
			"SQL is read from the file and sent via stdin; raw rows are written to a scratch output file, not returned.",
		promptSnippet: "Run BigQuery SQL from a .sql file with a short TLDR and save result rows to scratch space",
		parameters: BqQueryParams,

		async execute(_id, params, signal, _onUpdate, ctx): Promise<BqToolResult> {
			let description: string | null = null;
			let sqlPath = "";
			let jobId = "";
			let details: BqQueryDetails | null = null;
			const scanApprovalMode = scanApprovalModeForContext(ctx);
			const forceNoUiSoftLock = params.force === true;

			try {
				description = sanitizeQueryDescription(params.description);

				const workspace = requireWorkspaceState();
				const projectId = trimOrNull(params.projectId);
				const location = trimOrNull(params.location);
				const outputFormat = params.outputFormat ?? DEFAULT_OUTPUT_FORMAT;
				const maxRows = validateMaxRows(params.maxRows ?? DEFAULT_MAX_ROWS);
				const dryRunOnly = params.dryRun === true;

				const effectiveCwd = getWorkspaceEffectiveCwd();
				sqlPath = await resolveSqlPath(params.path, effectiveCwd, workspace.scratchDir);
				const sql = await fs.readFile(sqlPath, "utf8");
				const now = new Date();
				const hash = queryHash(sql);
				jobId = `basecamp_${timestampForJob(now)}_${hash}`;
				const dryRunJobId = `${jobId}_dryrun`;
				const outputDir = path.join(workspace.scratchDir, "bigquery");
				await ensurePrivateDir(outputDir);
				const outputPath = dryRunOnly
					? null
					: path.join(outputDir, `${safeStem(sqlPath)}-${timestampForFile(now)}-${hash}-${jobId}.${outputFormat}`);

				details = {
					description,
					sqlPath,
					outputPath,
					outputFormat,
					maxRows,
					projectId,
					location,
					jobId,
					outputBytes: null,
					rowCount: null,
					diagnosticPath: null,
					dryRun: emptyDryRun(),
					approval: buildScanApprovalMetadata(null, null, scanApprovalMode),
					job: null,
				};

				const dryRun = await runBqCapture(
					buildQueryArgs({
						format: "json",
						projectId,
						location,
						jobId: dryRunJobId,
						dryRun: true,
					}),
					sql,
					effectiveCwd,
					signal,
				);

				if (dryRun.code !== 0) {
					details.dryRun = { ...emptyDryRun(), ran: true, jobId: dryRunJobId };
					details.approval = buildScanApprovalMetadata(
						details.dryRun.estimatedBytes,
						details.dryRun.statementType,
						scanApprovalMode,
					);
					details.diagnosticPath = await writeDiagnostic(
						outputDir,
						dryRunJobId,
						formatProcessFailure(dryRun, "Unknown dry-run failure"),
					);
					return {
						isError: true,
						details,
						content: [
							{
								type: "text",
								text: `BigQuery dry-run failed; execution was not attempted. Diagnostics: ${details.diagnosticPath}`,
							},
						],
					};
				}

				details.dryRun = summarizeDryRun(dryRunJobId, dryRun.stdout);
				details.approval = buildScanApprovalMetadata(
					details.dryRun.estimatedBytes,
					details.dryRun.statementType,
					scanApprovalMode,
				);

				if (dryRunOnly) {
					return {
						details,
						content: [{ type: "text", text: buildDryRunText(details) }],
					};
				}

				const approvalFailure = await evaluateScanApproval(details, ctx, signal, forceNoUiSoftLock);
				if (approvalFailure) return approvalFailure;

				if (!outputPath) throw new Error("Internal error: missing BigQuery output path.");

				const execution = await runBqToFile(
					buildQueryArgs({ format: outputFormat, projectId, location, jobId, maxRows }),
					sql,
					effectiveCwd,
					outputPath,
					signal,
				);
				details.outputBytes = execution.outputBytes;
				details.rowCount = outputFormat === "csv" ? csvRowCount(execution) : null;

				if (execution.code !== 0) {
					details.diagnosticPath = await writeDiagnostic(
						outputDir,
						`${jobId}_execution`,
						formatProcessFailure(execution, "Unknown bq execution failure"),
					);
					return {
						isError: true,
						details,
						content: [
							{
								type: "text",
								text: `BigQuery execution failed. Output, if any, was written to ${outputPath}. Diagnostics: ${details.diagnosticPath}`,
							},
						],
					};
				}

				const metadata = await runBqCapture(buildShowArgs(projectId, location, jobId), "", effectiveCwd, signal);
				if (metadata.code === 0) {
					details.job = summarizeJob(metadata.stdout);
				} else {
					details.diagnosticPath = await writeDiagnostic(
						outputDir,
						`${jobId}_metadata`,
						formatProcessFailure(metadata, "Unable to fetch job metadata."),
					);
					details.job = emptyJob(`Job metadata fetch failed. Diagnostics: ${details.diagnosticPath}`);
				}

				return {
					details,
					content: [{ type: "text", text: buildSuccessText(details, execution.outputBytes) }],
				};
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				return {
					isError: true,
					details: details ?? {
						description,
						sqlPath: sqlPath || params.path,
						outputPath: null,
						outputFormat: DEFAULT_OUTPUT_FORMAT,
						maxRows: DEFAULT_MAX_ROWS,
						projectId: null,
						location: null,
						jobId,
						outputBytes: null,
						rowCount: null,
						diagnosticPath: null,
						dryRun: emptyDryRun(),
						approval: buildScanApprovalMetadata(null, null, scanApprovalMode),
						job: null,
					},
					content: [{ type: "text", text: `bq_query failed: ${message}` }],
				};
			}
		},
		renderCall,
		renderResult,
	});
}
