/**
 * bq_query tool — run BigQuery SQL files through the bq CLI.
 *
 * SQL is read from a .sql file and sent to bq via stdin. Query stdout is
 * written to scratch space; tool output contains only a summary and metadata.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { AgentToolResult, ExtensionAPI, ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";
import { type BigQueryOutputFormat, isPathWithin, resolveBigQueryConfig } from "../../../platform/config";
import { requireSessionState } from "../../../platform/session";
import { getEffectiveCwd } from "../runtime/session";

const DEFAULT_OUTPUT_FORMAT: BigQueryOutputFormat = "csv";
const DEFAULT_MAX_ROWS = 100;
const BQ_TIMEOUT_MS = 10 * 60 * 1000;
const BQ_SCAN_APPROVAL_THRESHOLD_BYTES = 1_000_000_000_000n;
const MAX_ERROR_CHARS = 20_000;
const MAX_DESCRIPTION_CHARS = 500;
const DISPLAY_ELLIPSIS = "…";
const MAX_CALL_LINE_CHARS = 110;
const MAX_CALL_PATH_CHARS = 42;
const MAX_RESULT_LINE_CHARS = 220;
const MIN_DISPLAY_DESCRIPTION_CHARS = 24;
const ANSI_ESCAPE_PATTERN = new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, "g");
const CONTROL_CHARS_PATTERN = /[\p{Cc}]+/gu;

const BqQueryParams = Type.Object({
	path: Type.String({ description: "Path to a .sql file. Relative paths resolve from the current effective cwd." }),
	description: Type.String({
		description: "Required short TLDR of what this query does. Do not include raw SQL or result rows.",
	}),
	dryRun: Type.Optional(
		Type.Boolean({
			description: "Validate the SQL with a BigQuery dry run and do not execute it. Defaults to false.",
		}),
	),
	projectId: Type.Optional(Type.String({ description: "BigQuery project ID. Overrides configured defaults." })),
	location: Type.Optional(Type.String({ description: "BigQuery job location. Overrides configured defaults." })),
	maxRows: Type.Optional(
		Type.Number({ description: "Maximum rows for bq query output. Defaults to config, then 100." }),
	),
	outputFormat: Type.Optional(
		Type.Union([
			Type.Literal("csv", { description: "Write CSV query output." }),
			Type.Literal("json", { description: "Write JSON query output." }),
		]),
	),
});

type BqQueryInput = Static<typeof BqQueryParams>;

interface BqCaptureResult {
	code: number;
	stdout: string;
	stderr: string;
	timedOut: boolean;
	aborted: boolean;
}

interface BqFileResult {
	code: number;
	stderr: string;
	outputBytes: number;
	outputLineBreaks: number;
	outputEndsWithNewline: boolean;
	timedOut: boolean;
	aborted: boolean;
}

interface SchemaFieldSummary {
	name: string;
	type: string | null;
	mode: string | null;
}

interface DryRunSummary {
	ran: boolean;
	jobId: string | null;
	estimatedBytes: string | null;
	statementType: string | null;
	schemaFieldCount: number | null;
	schemaFields: SchemaFieldSummary[];
	message?: string;
}

interface JobSummary {
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

interface BqScanApprovalMetadata {
	thresholdBytes: string;
	estimatedBytes: string | null;
	required: boolean;
	reason: BqScanApprovalReason;
	approved: boolean | null;
	granted: boolean | null;
}

interface BqQueryDetails {
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

type BqToolResult = AgentToolResult<BqQueryDetails> & { isError?: boolean };

function trimOrNull(value: string | undefined): string | null {
	const trimmed = value?.trim();
	return trimmed ? trimmed : null;
}

function sanitizeQueryDescription(value: unknown): string {
	if (typeof value !== "string") {
		throw new Error("description is required and must be a non-empty TLDR of the query.");
	}

	const sanitized = value
		.replace(ANSI_ESCAPE_PATTERN, " ")
		.replace(CONTROL_CHARS_PATTERN, " ")
		.replace(/\s+/g, " ")
		.trim();

	if (!sanitized) {
		throw new Error("description is required and must be a non-empty TLDR of the query.");
	}

	return truncateForDisplay(sanitized, MAX_DESCRIPTION_CHARS);
}

function displayLength(value: string): number {
	return Array.from(value).length;
}

function truncateForDisplay(value: string, maxChars: number): string {
	const chars = Array.from(value);
	if (chars.length <= maxChars) return value;
	if (maxChars <= 0) return "";
	if (maxChars === 1) return DISPLAY_ELLIPSIS;
	return `${chars
		.slice(0, maxChars - 1)
		.join("")
		.trimEnd()}${DISPLAY_ELLIPSIS}`;
}

function truncatePathTail(value: string, maxChars: number): string {
	const chars = Array.from(value);
	if (chars.length <= maxChars) return value;
	if (maxChars <= 0) return "";
	if (maxChars === 1) return DISPLAY_ELLIPSIS;
	return `${DISPLAY_ELLIPSIS}${chars.slice(-(maxChars - 1)).join("")}`;
}

function descriptionPreview(value: unknown, maxChars: number): string | null {
	try {
		return truncateForDisplay(sanitizeQueryDescription(value), maxChars);
	} catch {
		return null;
	}
}

function sqlPathPreview(value: unknown, maxChars: number): string {
	if (typeof value !== "string") return "...";
	const sanitized = value
		.replace(ANSI_ESCAPE_PATTERN, " ")
		.replace(CONTROL_CHARS_PATTERN, " ")
		.replace(/\s+/g, " ")
		.trim();
	return sanitized ? truncatePathTail(sanitized, maxChars) : "...";
}

function expandHome(rawPath: string): string {
	if (rawPath === "~") return process.env.HOME ?? rawPath;
	if (rawPath.startsWith("~/")) return path.join(process.env.HOME ?? "~", rawPath.slice(2));
	return rawPath;
}

async function existingRealpath(filePath: string): Promise<string | null> {
	try {
		return await fs.realpath(filePath);
	} catch {
		return null;
	}
}

async function resolveSqlPath(rawPath: string, cwd: string, allowedRoots: string[]): Promise<string> {
	const expanded = expandHome(rawPath);
	const resolved = path.resolve(cwd, expanded);
	if (path.extname(resolved).toLowerCase() !== ".sql") {
		throw new Error(`bq_query path must point to a .sql file: ${resolved}`);
	}

	const stat = await fs.stat(resolved);
	if (!stat.isFile()) throw new Error(`bq_query path is not a file: ${resolved}`);

	const realSqlPath = await fs.realpath(resolved);
	const realRoots = (await Promise.all(allowedRoots.map((root) => existingRealpath(root)))).filter(
		(root): root is string => root !== null,
	);
	if (!realRoots.some((root) => isPathWithin(realSqlPath, root))) {
		throw new Error("bq_query SQL files must live under the effective cwd, scratch directory, or project directories.");
	}

	return realSqlPath;
}

function validateMaxRows(value: number): number {
	if (!Number.isInteger(value) || value < 1) {
		throw new Error(`maxRows must be a positive integer; received ${value}`);
	}
	return value;
}

function safeStem(sqlPath: string): string {
	const stem = path.basename(sqlPath, path.extname(sqlPath));
	const safe = stem.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
	return (safe || "query").slice(0, 80);
}

function timestampForFile(date: Date): string {
	return date.toISOString().replace(/[:.]/g, "-");
}

function timestampForJob(date: Date): string {
	return date.toISOString().replace(/[-:.TZ]/g, "");
}

function queryHash(sql: string): string {
	return createHash("sha256").update(sql).digest("hex").slice(0, 12);
}

function emptyDryRun(): DryRunSummary {
	return {
		ran: false,
		jobId: null,
		estimatedBytes: null,
		statementType: null,
		schemaFieldCount: null,
		schemaFields: [],
	};
}

function emptyJob(message?: string): JobSummary {
	return {
		fetched: false,
		state: null,
		error: null,
		totalBytesProcessed: null,
		totalBytesBilled: null,
		totalSlotMs: null,
		cacheHit: null,
		creationTime: null,
		startTime: null,
		endTime: null,
		...(message ? { message } : {}),
	};
}

function appendLimited(current: string, chunk: Buffer | string): string {
	const text = Buffer.isBuffer(chunk) ? chunk.toString("utf8") : chunk;
	const next = current + text;
	return next.length > MAX_ERROR_CHARS ? next.slice(next.length - MAX_ERROR_CHARS) : next;
}

async function ensurePrivateDir(dirPath: string): Promise<void> {
	await fs.mkdir(dirPath, { recursive: true, mode: 0o700 });
	const stat = await fs.lstat(dirPath);
	if (stat.isSymbolicLink() || !stat.isDirectory()) {
		throw new Error(`Unsafe BigQuery output directory: ${dirPath}`);
	}
	await fs.chmod(dirPath, 0o700);
}

async function writeDiagnostic(outputDir: string, jobId: string, text: string): Promise<string> {
	await ensurePrivateDir(outputDir);
	const diagnosticPath = path.join(outputDir, `${jobId}.diagnostic.txt`);
	await fs.writeFile(diagnosticPath, `${text.trim()}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
	return diagnosticPath;
}

function buildGlobalArgs(format: BigQueryOutputFormat, projectId: string | null, location: string | null): string[] {
	const args = [`--format=${format}`, "--quiet", "--headless=true"];
	if (projectId) args.push(`--project_id=${projectId}`);
	if (location) args.push(`--location=${location}`);
	return args;
}

function buildQueryArgs(opts: {
	format: BigQueryOutputFormat;
	projectId: string | null;
	location: string | null;
	jobId: string;
	maxRows?: number;
	dryRun?: boolean;
}): string[] {
	const args = [
		...buildGlobalArgs(opts.format, opts.projectId, opts.location),
		"query",
		"--use_legacy_sql=false",
		`--job_id=${opts.jobId}`,
	];
	if (opts.dryRun) args.push("--dry_run");
	if (opts.maxRows !== undefined) args.push(`--max_rows=${opts.maxRows}`);
	return args;
}

function buildShowArgs(projectId: string | null, location: string | null, jobId: string): string[] {
	return [...buildGlobalArgs("json", projectId, location), "show", "-j", jobId];
}

function cleanupTimer(timer: NodeJS.Timeout | null, signal: AbortSignal | undefined, onAbort: () => void): void {
	if (timer) clearTimeout(timer);
	signal?.removeEventListener("abort", onAbort);
}

function runBqCapture(
	args: string[],
	input: string,
	cwd: string,
	signal: AbortSignal | undefined,
): Promise<BqCaptureResult> {
	return new Promise((resolve, reject) => {
		const child = spawn("bq", args, { cwd, stdio: ["pipe", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		let timedOut = false;
		let aborted = false;
		let settled = false;

		const finish = (fn: () => void): void => {
			if (settled) return;
			settled = true;
			cleanupTimer(timer, signal, onAbort);
			fn();
		};

		const onAbort = (): void => {
			aborted = true;
			child.kill("SIGTERM");
		};

		const timer = setTimeout(() => {
			timedOut = true;
			child.kill("SIGTERM");
		}, BQ_TIMEOUT_MS);

		signal?.addEventListener("abort", onAbort, { once: true });

		child.stdout.on("data", (chunk: Buffer) => {
			stdout += chunk.toString("utf8");
		});
		child.stderr.on("data", (chunk: Buffer) => {
			stderr = appendLimited(stderr, chunk);
		});
		child.on("error", (error) => finish(() => reject(error)));
		child.on("close", (code) =>
			finish(() =>
				resolve({
					code: code ?? 1,
					stdout,
					stderr,
					timedOut,
					aborted,
				}),
			),
		);

		child.stdin.end(input);
	});
}

function runBqToFile(
	args: string[],
	input: string,
	cwd: string,
	outputPath: string,
	signal: AbortSignal | undefined,
): Promise<BqFileResult> {
	return new Promise((resolve, reject) => {
		const child = spawn("bq", args, { cwd, stdio: ["pipe", "pipe", "pipe"] });
		const output = fsSync.createWriteStream(outputPath, { flags: "wx", mode: 0o600 });
		let stderr = "";
		let outputBytes = 0;
		let outputLineBreaks = 0;
		let outputEndsWithNewline = false;
		let timedOut = false;
		let aborted = false;
		let outputFinished = false;
		let closeCode: number | null = null;
		let settled = false;

		const finish = (fn: () => void): void => {
			if (settled) return;
			settled = true;
			cleanupTimer(timer, signal, onAbort);
			fn();
		};

		const maybeResolve = (): void => {
			if (closeCode === null || !outputFinished) return;
			finish(() =>
				resolve({
					code: closeCode ?? 1,
					stderr,
					outputBytes,
					outputLineBreaks,
					outputEndsWithNewline,
					timedOut,
					aborted,
				}),
			);
		};

		const onAbort = (): void => {
			aborted = true;
			child.kill("SIGTERM");
		};

		const timer = setTimeout(() => {
			timedOut = true;
			child.kill("SIGTERM");
		}, BQ_TIMEOUT_MS);

		signal?.addEventListener("abort", onAbort, { once: true });

		child.stdout.on("data", (chunk: Buffer) => {
			const text = chunk.toString("utf8");
			outputBytes += chunk.length;
			outputLineBreaks += text.split("\n").length - 1;
			outputEndsWithNewline = text.endsWith("\n");
		});
		child.stderr.on("data", (chunk: Buffer) => {
			stderr = appendLimited(stderr, chunk);
		});
		child.stdout.pipe(output);

		output.on("finish", () => {
			outputFinished = true;
			maybeResolve();
		});
		output.on("error", (error) => {
			child.kill("SIGTERM");
			finish(() => reject(error));
		});
		child.on("error", (error) => {
			output.destroy();
			finish(() => reject(error));
		});
		child.on("close", (code) => {
			closeCode = code ?? 1;
			maybeResolve();
		});

		child.stdin.end(input);
	});
}

function parseJson(raw: string): unknown | null {
	const trimmed = raw.trim();
	if (!trimmed) return null;
	try {
		return JSON.parse(trimmed);
	} catch {
		return null;
	}
}

function asRecord(value: unknown): Record<string, unknown> | null {
	return typeof value === "object" && value !== null && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function valueAt(value: unknown, keys: string[]): unknown {
	let current: unknown = value;
	for (const key of keys) {
		const record = asRecord(current);
		if (!record) return undefined;
		current = record[key];
	}
	return current;
}

function firstString(value: unknown, paths: string[][]): string | null {
	for (const candidatePath of paths) {
		const valueAtPath = valueAt(value, candidatePath);
		if (typeof valueAtPath === "string" && valueAtPath) return valueAtPath;
		if (typeof valueAtPath === "number" && Number.isFinite(valueAtPath)) return String(valueAtPath);
	}
	return null;
}

function firstErrorMessage(value: unknown): string | null {
	const direct = firstString(value, [
		["status", "errorResult", "message"],
		["error", "message"],
	]);
	if (direct) return direct;

	const errors = valueAt(value, ["status", "errors"]);
	if (Array.isArray(errors)) {
		for (const error of errors) {
			const message = firstString(error, [["message"]]);
			if (message) return message;
		}
	}
	return null;
}

function summarizeSchemaFields(parsed: unknown): { count: number | null; fields: SchemaFieldSummary[] } {
	const fields = valueAt(parsed, ["statistics", "query", "schema", "fields"]);
	if (!Array.isArray(fields)) return { count: null, fields: [] };

	return {
		count: fields.length,
		fields: fields
			.map((field): SchemaFieldSummary | null => {
				const record = asRecord(field);
				const name = record?.name;
				if (typeof name !== "string" || !name) return null;
				return {
					name,
					type: typeof record.type === "string" ? record.type : null,
					mode: typeof record.mode === "string" ? record.mode : null,
				};
			})
			.filter((field): field is SchemaFieldSummary => field !== null)
			.slice(0, 25),
	};
}

function summarizeDryRun(jobId: string, stdout: string): DryRunSummary {
	const parsed = parseJson(stdout);
	const schema = summarizeSchemaFields(parsed);
	return {
		ran: true,
		jobId,
		estimatedBytes:
			firstString(parsed, [
				["statistics", "query", "totalBytesProcessed"],
				["statistics", "totalBytesProcessed"],
				["totalBytesProcessed"],
			]) ?? null,
		statementType: firstString(parsed, [["statistics", "query", "statementType"]]),
		schemaFieldCount: schema.count,
		schemaFields: schema.fields,
		...(parsed ? {} : { message: "Dry-run output was not valid JSON." }),
	};
}

function summarizeJob(stdout: string): JobSummary {
	const parsed = parseJson(stdout);
	if (!parsed) {
		return emptyJob("Job metadata output was not valid JSON.");
	}

	const cacheHit = valueAt(parsed, ["statistics", "query", "cacheHit"]);

	return {
		fetched: true,
		state: firstString(parsed, [["status", "state"]]),
		error: firstErrorMessage(parsed),
		totalBytesProcessed: firstString(parsed, [
			["statistics", "query", "totalBytesProcessed"],
			["statistics", "totalBytesProcessed"],
		]),
		totalBytesBilled: firstString(parsed, [["statistics", "query", "totalBytesBilled"]]),
		totalSlotMs: firstString(parsed, [["statistics", "query", "totalSlotMs"]]),
		cacheHit: typeof cacheHit === "boolean" ? cacheHit : null,
		creationTime: firstString(parsed, [["statistics", "creationTime"]]),
		startTime: firstString(parsed, [["statistics", "startTime"]]),
		endTime: firstString(parsed, [["statistics", "endTime"]]),
	};
}

function parseDryRunEstimatedBytes(value: string | null): bigint | null {
	if (value === null || !/^\d+$/.test(value)) return null;

	try {
		return BigInt(value);
	} catch {
		return null;
	}
}

function isNonAuthoritativeDryRunStatementType(statementType: string | null): boolean {
	const normalized = statementType?.trim().toUpperCase();
	return normalized === "SCRIPT";
}

function buildScanApprovalMetadata(
	rawEstimatedBytes: string | null,
	statementType: string | null = null,
): BqScanApprovalMetadata {
	const thresholdBytes = BQ_SCAN_APPROVAL_THRESHOLD_BYTES.toString();
	const estimatedBytes = parseDryRunEstimatedBytes(rawEstimatedBytes);
	const estimateNonAuthoritative = isNonAuthoritativeDryRunStatementType(statementType);

	if (estimatedBytes === null) {
		return {
			thresholdBytes,
			estimatedBytes: null,
			required: true,
			reason: "estimate_unknown",
			approved: null,
			granted: null,
		};
	}

	const overThreshold = estimatedBytes > BQ_SCAN_APPROVAL_THRESHOLD_BYTES;
	const required = overThreshold || estimateNonAuthoritative;
	return {
		thresholdBytes,
		estimatedBytes: estimatedBytes.toString(),
		required,
		reason: overThreshold ? "over_threshold" : estimateNonAuthoritative ? "estimate_non_authoritative" : null,
		approved: null,
		granted: null,
	};
}

function formatBytes(bytes: string | null): string {
	if (!bytes) return "unknown";
	const value = Number(bytes);
	if (!Number.isFinite(value)) return `${bytes} bytes`;
	const units = ["bytes", "KiB", "MiB", "GiB", "TiB", "PiB"];
	let scaled = value;
	let unit = units[0] ?? "bytes";
	for (const candidate of units) {
		unit = candidate;
		if (Math.abs(scaled) < 1024 || candidate === units[units.length - 1]) break;
		scaled /= 1024;
	}
	return unit === "bytes" ? `${value} bytes` : `${scaled.toFixed(2)} ${unit}`;
}

function formatDecimalBytes(bytes: string | null): string {
	if (!bytes) return "unknown";
	const value = Number(bytes);
	if (!Number.isFinite(value)) return `${bytes} bytes`;
	const units = ["bytes", "KB", "MB", "GB", "TB", "PB"];
	let scaled = value;
	let unit = units[0] ?? "bytes";
	for (const candidate of units) {
		unit = candidate;
		if (Math.abs(scaled) < 1000 || candidate === units[units.length - 1]) break;
		scaled /= 1000;
	}
	return unit === "bytes" ? `${value} bytes` : `${scaled.toFixed(2)} ${unit}`;
}

function formatScanBytesWithRaw(bytes: string | null): string {
	if (!bytes) return "unknown";
	return `${formatDecimalBytes(bytes)} / ${bytes} bytes`;
}

function safeApprovalPromptValue(value: string | null, fallback: string): string {
	if (!value) return fallback;
	const sanitized = value
		.replace(ANSI_ESCAPE_PATTERN, " ")
		.replace(CONTROL_CHARS_PATTERN, " ")
		.replace(/\s+/g, " ")
		.trim();
	return sanitized || fallback;
}

function withScanApprovalDecision(
	approval: BqScanApprovalMetadata,
	approved: boolean | null,
	granted: boolean | null,
): BqScanApprovalMetadata {
	return { ...approval, approved, granted };
}

function formatNonAuthoritativeEstimateNote(statementType: string | null): string {
	const statementTypeText = safeApprovalPromptValue(statementType, "");
	return statementTypeText
		? `dry-run estimate may be non-authoritative for statement type ${statementTypeText}`
		: "dry-run estimate may be non-authoritative";
}

function formatScanApprovalRequirement(details: BqQueryDetails): string | null {
	const approval = details.approval;
	if (!approval.required) return null;

	const threshold = formatScanBytesWithRaw(approval.thresholdBytes);
	const nonAuthoritativeNote = isNonAuthoritativeDryRunStatementType(details.dryRun.statementType)
		? `; ${formatNonAuthoritativeEstimateNote(details.dryRun.statementType)}`
		: "";

	if (approval.reason === "over_threshold") {
		const estimate = approval.estimatedBytes ? formatScanBytesWithRaw(approval.estimatedBytes) : "unknown";
		return `estimated scan ${estimate} exceeds approval threshold ${threshold}${nonAuthoritativeNote}`;
	}

	if (approval.reason === "estimate_unknown") {
		return `scan estimate is unknown or unparseable${nonAuthoritativeNote}; approval threshold is ${threshold}`;
	}

	if (approval.reason === "estimate_non_authoritative") {
		const estimate = approval.estimatedBytes ? formatScanBytesWithRaw(approval.estimatedBytes) : "unknown";
		return `${formatNonAuthoritativeEstimateNote(details.dryRun.statementType)}; estimated scan ${estimate} may be incomplete; approval threshold is ${threshold}`;
	}

	return `approval threshold is ${threshold}`;
}

function formatScanApprovalStatus(details: BqQueryDetails): string {
	const approval = details.approval;
	const threshold = formatScanBytesWithRaw(approval.thresholdBytes);

	if (!approval.required) {
		const estimate = approval.estimatedBytes ? formatScanBytesWithRaw(approval.estimatedBytes) : "unknown";
		return `Approval: not required; estimated scan ${estimate} is at or below threshold ${threshold}.`;
	}

	if (approval.reason === "estimate_unknown") {
		const requirement =
			formatScanApprovalRequirement(details) ??
			`scan estimate is unknown or unparseable; approval threshold is ${threshold}`;
		if (approval.granted === false) {
			return `Approval: required but not granted; ${requirement}.`;
		}
		return `Approval: required before execution; ${requirement}.`;
	}

	const requirement = formatScanApprovalRequirement(details) ?? `approval threshold is ${threshold}`;
	if (approval.reason === "over_threshold" || approval.reason === "estimate_non_authoritative") {
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
		`Estimated scan: ${formatScanBytesWithRaw(details.approval.estimatedBytes)}`,
		`Approval threshold: ${formatScanBytesWithRaw(details.approval.thresholdBytes)}`,
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
		`Estimated scan: ${formatScanBytesWithRaw(details.approval.estimatedBytes)}`,
	);
	if (details.dryRun.statementType) {
		lines.push(`Statement type: ${safeApprovalPromptValue(details.dryRun.statementType, "unknown")}`);
	}
	lines.push(formatScanApprovalStatus(details));
	if (details.dryRun.message) lines.push(`Dry-run note: ${details.dryRun.message}`);
	return lines.join("\n");
}

async function evaluateScanApproval(
	details: BqQueryDetails,
	ctx: ExtensionContext,
	signal: AbortSignal | undefined,
): Promise<BqToolResult | null> {
	const approval = details.approval;

	if (!approval.required) {
		details.approval = withScanApprovalDecision(approval, null, true);
		return null;
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
		if (!ctx.hasUI) {
			details.approval = withScanApprovalDecision(approval, null, false);
			return {
				isError: true,
				details,
				content: [
					{
						type: "text",
						text: buildApprovalGateFailureText(
							details,
							"BigQuery execution blocked; interactive approval is unavailable, so execution was not attempted.",
						),
					},
				],
			};
		}

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

function diagnosticText(result: BqCaptureResult | BqFileResult): string {
	return result.stderr.trim();
}

function formatProcessFailure(result: BqCaptureResult | BqFileResult, fallback: string): string {
	const pieces: string[] = [];
	if (result.aborted) pieces.push("bq process aborted.");
	if (result.timedOut) pieces.push(`bq process timed out after ${BQ_TIMEOUT_MS / 1000}s.`);
	pieces.push(diagnosticText(result) || fallback);
	return pieces.join("\n");
}

function csvRowCount(result: BqFileResult): number {
	if (result.outputBytes === 0) return 0;
	const lineCount = result.outputLineBreaks + (result.outputEndsWithNewline ? 0 : 1);
	return Math.max(0, lineCount - 1);
}

function buildDryRunText(details: BqQueryDetails): string {
	const lines = ["BigQuery dry run passed."];
	if (details.description) lines.push(`Description: ${details.description}`);
	lines.push(
		`SQL file: ${details.sqlPath}`,
		`Dry-run job ID: ${details.dryRun.jobId ?? "unknown"}`,
		`Estimated scan: ${formatScanBytesWithRaw(details.dryRun.estimatedBytes)}`,
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
	if (approvalRequirement) lines.push(`Approval would be required before execution: ${approvalRequirement}.`);
	if (details.dryRun.message) lines.push(`Dry-run note: ${details.dryRun.message}`);
	return lines.join("\n");
}

function buildSuccessText(details: BqQueryDetails, outputBytes: number): string {
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
		lines.push(`Dry run: passed; estimated scan ${formatScanBytesWithRaw(details.dryRun.estimatedBytes)}`);
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

function renderCall(args: BqQueryInput, theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
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

function renderResult(
	result: AgentToolResult<BqQueryDetails>,
	options: { isPartial?: boolean },
	theme: Theme,
	context?: { isError?: boolean },
) {
	const { Text } = require("@mariozechner/pi-tui");
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

			try {
				description = sanitizeQueryDescription(params.description);

				const state = requireSessionState();
				const config = resolveBigQueryConfig(state.project);
				if (config.enabled === false) {
					throw new Error("bq_query is disabled by Basecamp BigQuery config.");
				}

				const projectId = trimOrNull(params.projectId) ?? trimOrNull(config.default_project_id);
				const location = trimOrNull(params.location) ?? trimOrNull(config.default_location);
				const outputFormat = params.outputFormat ?? config.default_output_format ?? DEFAULT_OUTPUT_FORMAT;
				const maxRows = validateMaxRows(params.maxRows ?? config.default_max_rows ?? DEFAULT_MAX_ROWS);
				const dryRunOnly = params.dryRun === true;

				const effectiveCwd = getEffectiveCwd();
				const projectSqlRoot = state.worktreeDir ?? state.repoRoot;
				const allowedSqlRoots = [effectiveCwd, projectSqlRoot, state.scratchDir, ...state.additionalDirs];
				sqlPath = await resolveSqlPath(params.path, effectiveCwd, allowedSqlRoots);
				const sql = await fs.readFile(sqlPath, "utf8");
				const now = new Date();
				const hash = queryHash(sql);
				jobId = `basecamp_${timestampForJob(now)}_${hash}`;
				const dryRunJobId = `${jobId}_dryrun`;
				const outputDir = path.join(state.scratchDir, "bigquery");
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
					approval: buildScanApprovalMetadata(null),
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
					details.approval = buildScanApprovalMetadata(details.dryRun.estimatedBytes);
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
				details.approval = buildScanApprovalMetadata(details.dryRun.estimatedBytes, details.dryRun.statementType);

				if (dryRunOnly) {
					return {
						details,
						content: [{ type: "text", text: buildDryRunText(details) }],
					};
				}

				const approvalFailure = await evaluateScanApproval(details, ctx, signal);
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
						approval: buildScanApprovalMetadata(null),
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
