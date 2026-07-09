/**
 * SQL path resolution, input validation, and scratch-file helpers for the bq_query tool.
 */

import { createHash } from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { SCRATCH_SQL_PATH_ERROR, TMP_PI_ROOT } from "./params.ts";

function expandHome(rawPath: string): string {
	if (rawPath === "~") return process.env.HOME ?? rawPath;
	if (rawPath.startsWith("~/")) return path.join(process.env.HOME ?? "~", rawPath.slice(2));
	return rawPath;
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

async function existingRealpath(filePath: string): Promise<string | null> {
	try {
		return await fs.realpath(filePath);
	} catch {
		return null;
	}
}

export async function resolveSqlPath(rawPath: string, cwd: string, scratchDir: string): Promise<string> {
	const expanded = expandHome(rawPath);
	const resolved = path.resolve(cwd, expanded);
	if (path.extname(resolved).toLowerCase() !== ".sql") {
		throw new Error(`bq_query path must point to a .sql file: ${resolved}`);
	}

	const stat = await fs.stat(resolved);
	if (!stat.isFile()) throw new Error(`bq_query path is not a file: ${resolved}`);

	const realSqlPath = await fs.realpath(resolved);
	const [realScratchDir, realTmpPiRoot] = await Promise.all([
		existingRealpath(scratchDir),
		existingRealpath(TMP_PI_ROOT),
	]);
	if (!realScratchDir || !realTmpPiRoot || !isPathWithin(realScratchDir, realTmpPiRoot)) {
		throw new Error(SCRATCH_SQL_PATH_ERROR);
	}
	if (!isPathWithin(realSqlPath, realScratchDir)) {
		throw new Error(SCRATCH_SQL_PATH_ERROR);
	}

	return realSqlPath;
}

export function validateMaxRows(value: number): number {
	if (!Number.isInteger(value) || value < 1) {
		throw new Error(`maxRows must be a positive integer; received ${value}`);
	}
	return value;
}

export function safeStem(sqlPath: string): string {
	const stem = path.basename(sqlPath, path.extname(sqlPath));
	const safe = stem.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
	return (safe || "query").slice(0, 80);
}

export function timestampForFile(date: Date): string {
	return date.toISOString().replace(/[:.]/g, "-");
}

export function timestampForJob(date: Date): string {
	return date.toISOString().replace(/[-:.TZ]/g, "");
}

export function queryHash(sql: string): string {
	return createHash("sha256").update(sql).digest("hex").slice(0, 12);
}

export async function ensurePrivateDir(dirPath: string): Promise<void> {
	await fs.mkdir(dirPath, { recursive: true, mode: 0o700 });
	const stat = await fs.lstat(dirPath);
	if (stat.isSymbolicLink() || !stat.isDirectory()) {
		throw new Error(`Unsafe BigQuery output directory: ${dirPath}`);
	}
	await fs.chmod(dirPath, 0o700);
}

export async function writeDiagnostic(outputDir: string, jobId: string, text: string): Promise<string> {
	await ensurePrivateDir(outputDir);
	const diagnosticPath = path.join(outputDir, `${jobId}.diagnostic.txt`);
	await fs.writeFile(diagnosticPath, `${text.trim()}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
	return diagnosticPath;
}
