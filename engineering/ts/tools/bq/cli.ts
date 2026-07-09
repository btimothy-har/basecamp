/**
 * bq CLI argument builders and child-process runners for the bq_query tool.
 */

import { spawn } from "node:child_process";
import * as fsSync from "node:fs";
import {
	type BigQueryOutputFormat,
	BQ_TIMEOUT_MS,
	type BqCaptureResult,
	type BqFileResult,
	MAX_ERROR_CHARS,
} from "./params.ts";

function buildGlobalArgs(format: BigQueryOutputFormat, projectId: string | null, location: string | null): string[] {
	const args = [`--format=${format}`, "--quiet", "--headless=true"];
	if (projectId) args.push(`--project_id=${projectId}`);
	if (location) args.push(`--location=${location}`);
	return args;
}

export function buildQueryArgs(opts: {
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

export function buildShowArgs(projectId: string | null, location: string | null, jobId: string): string[] {
	return [...buildGlobalArgs("json", projectId, location), "show", "-j", jobId];
}

function cleanupTimer(timer: NodeJS.Timeout | null, signal: AbortSignal | undefined, onAbort: () => void): void {
	if (timer) clearTimeout(timer);
	signal?.removeEventListener("abort", onAbort);
}

function appendLimited(current: string, chunk: Buffer | string): string {
	const text = Buffer.isBuffer(chunk) ? chunk.toString("utf8") : chunk;
	const next = current + text;
	return next.length > MAX_ERROR_CHARS ? next.slice(next.length - MAX_ERROR_CHARS) : next;
}

export function runBqCapture(
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

export function runBqToFile(
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
