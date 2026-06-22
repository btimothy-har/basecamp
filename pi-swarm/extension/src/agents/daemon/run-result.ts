import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { resolveDaemonPaths } from "./paths.ts";

export const BASECAMP_RUNNER_MANAGED_RESULT = "BASECAMP_RUNNER_MANAGED_RESULT";
export const BASECAMP_RUN_RESULT_PATH = "BASECAMP_RUN_RESULT_PATH";
export const BASECAMP_RUN_ATTEMPT = "BASECAMP_RUN_ATTEMPT";

export type RunResultStatus = "ok" | "error";

export interface RunResultAttempt {
	attempt: number;
	status: RunResultStatus;
	result: string | null;
	error: string | null;
}

export interface FinalRunResult {
	status: RunResultStatus;
	result: string | null;
	error: string | null;
	retry_count: number;
}

export interface RunResultSidecar {
	run_id: string;
	agent_id: string;
	attempts: RunResultAttempt[];
	final: FinalRunResult | null;
}

export function resolveRunResultPath(agentId: string, runId: string, homeDir = os.homedir()): string {
	return path.join(resolveDaemonPaths(homeDir).agentsDir, agentId, "runs", runId, "result.json");
}

export async function readRunResultSidecar(filePath: string): Promise<RunResultSidecar | null> {
	let raw: string;
	try {
		raw = await fs.promises.readFile(filePath, "utf8");
	} catch (error) {
		if (isNodeError(error) && error.code === "ENOENT") return null;
		throw error;
	}
	return parseRunResultSidecar(JSON.parse(raw));
}

export async function writeRunResultSidecar(filePath: string, sidecar: RunResultSidecar): Promise<void> {
	const directory = path.dirname(filePath);
	await fs.promises.mkdir(directory, { recursive: true, mode: 0o700 });
	const tempName = `.result.${process.pid}.${Date.now()}.${Math.random().toString(16).slice(2)}.tmp`;
	const tempPath = path.join(directory, tempName);
	await fs.promises.writeFile(tempPath, `${JSON.stringify(sidecar, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
	await fs.promises.rename(tempPath, filePath);
}

export async function upsertRunResultAttempt(
	filePath: string,
	metadata: Pick<RunResultSidecar, "run_id" | "agent_id">,
	attempt: RunResultAttempt,
): Promise<RunResultSidecar> {
	const existing = await readRunResultSidecar(filePath);
	const sidecar: RunResultSidecar = existing ?? {
		run_id: metadata.run_id,
		agent_id: metadata.agent_id,
		attempts: [],
		final: null,
	};
	if (sidecar.run_id !== metadata.run_id || sidecar.agent_id !== metadata.agent_id) {
		throw new Error("run result sidecar metadata mismatch");
	}

	const index = sidecar.attempts.findIndex((item) => item.attempt === attempt.attempt);
	if (index >= 0) {
		sidecar.attempts[index] = attempt;
	} else {
		sidecar.attempts.push(attempt);
		sidecar.attempts.sort((left, right) => left.attempt - right.attempt);
	}
	await writeRunResultSidecar(filePath, sidecar);
	return sidecar;
}

function parseRunResultSidecar(value: unknown): RunResultSidecar {
	if (!isRecord(value)) throw new Error("invalid run result sidecar");
	const runId = value.run_id;
	const agentId = value.agent_id;
	const attempts = value.attempts;
	const final = value.final;
	if (typeof runId !== "string" || typeof agentId !== "string" || !Array.isArray(attempts)) {
		throw new Error("invalid run result sidecar");
	}
	return {
		run_id: runId,
		agent_id: agentId,
		attempts: attempts.map(parseRunResultAttempt),
		final: final === null ? null : parseFinalRunResult(final),
	};
}

function parseRunResultAttempt(value: unknown): RunResultAttempt {
	if (!isRecord(value)) throw new Error("invalid run result attempt");
	const { attempt, status, result, error } = value;
	if (typeof attempt !== "number" || !Number.isInteger(attempt) || !isRunResultStatus(status)) {
		throw new Error("invalid run result attempt");
	}
	if (!isNullableString(result) || !isNullableString(error)) {
		throw new Error("invalid run result attempt");
	}
	return { attempt, status, result, error };
}

function parseFinalRunResult(value: unknown): FinalRunResult {
	if (!isRecord(value)) throw new Error("invalid final run result");
	const { status, result, error, retry_count } = value;
	if (!isRunResultStatus(status) || typeof retry_count !== "number" || !Number.isInteger(retry_count)) {
		throw new Error("invalid final run result");
	}
	if (!isNullableString(result) || !isNullableString(error)) {
		throw new Error("invalid final run result");
	}
	return { status, result, error, retry_count };
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRunResultStatus(value: unknown): value is RunResultStatus {
	return value === "ok" || value === "error";
}

function isNullableString(value: unknown): value is string | null {
	return typeof value === "string" || value === null;
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
	return error instanceof Error && "code" in error;
}
