/**
 * Dry-run and job-metadata parsing and summarization for the bq_query tool.
 */

import type { DryRunSummary, JobSummary, SchemaFieldSummary } from "./params.ts";

export function emptyDryRun(): DryRunSummary {
	return {
		ran: false,
		jobId: null,
		estimatedBytes: null,
		statementType: null,
		schemaFieldCount: null,
		schemaFields: [],
	};
}

export function emptyJob(message?: string): JobSummary {
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

export function summarizeDryRun(jobId: string, stdout: string): DryRunSummary {
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

export function summarizeJob(stdout: string): JobSummary {
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

export function parseDryRunEstimatedBytes(value: string | null): bigint | null {
	if (value === null || !/^\d+$/.test(value)) return null;

	try {
		return BigInt(value);
	} catch {
		return null;
	}
}

export function isNonAuthoritativeDryRunStatementType(statementType: string | null): boolean {
	const normalized = statementType?.trim().toUpperCase();
	return normalized === "SCRIPT";
}
