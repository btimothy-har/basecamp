import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { basecampRoot } from "pi-core/platform/paths.ts";
import type { PlanWorkstreamInput } from "./plan-input.ts";

export const WORKSTREAM_STATE_VERSION = 1;

export type PersistedWorkstreamStatus = "blocked" | "ready" | "dispatched" | "failed";

export type PersistedWorkstreamFailureStage = "worktree" | "setup" | "launch" | "cap";

export interface PersistedWorkstreamEntry {
	id: string;
	label: string;
	dependsOn: string[];
	status: PersistedWorkstreamStatus;
	agent?: {
		handle: string;
		type: string;
	};
	worktree?: {
		label: string;
		path: string;
		branch: string;
		created: boolean;
	};
	failure_stage?: PersistedWorkstreamFailureStage;
	message?: string;
	updatedAt?: string;
}

export interface PersistedWorkstreamRun {
	planId: string;
	plan: {
		goal: string;
		context: string;
		design: string;
		success: string;
		boundaries: string;
	};
	status?: string;
	handoff_status?: string;
	message?: string;
	updatedAt?: string;
	workstreams: Record<string, PersistedWorkstreamEntry>;
}

export interface WorkstreamLaunchState {
	version: 1;
	runs: Record<string, PersistedWorkstreamRun>;
}

export interface WorkstreamPlanFingerprintInput {
	goal: string;
	context: string;
	design: string;
	success: string;
	boundaries: string;
	workstreams: PlanWorkstreamInput[];
}

export function defaultWorkstreamStateDir(homeDir = os.homedir()): string {
	return path.join(basecampRoot(homeDir), "workstreams");
}

export function workstreamStateFilePath(sessionId: string, dir = defaultWorkstreamStateDir()): string {
	return path.join(dir, `${sessionId}.json`);
}

export function emptyWorkstreamLaunchState(): WorkstreamLaunchState {
	return { version: WORKSTREAM_STATE_VERSION, runs: {} };
}

function canonicalize(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(canonicalize);
	if (value && typeof value === "object") {
		const record = value as Record<string, unknown>;
		const result: Record<string, unknown> = {};
		for (const key of Object.keys(record).sort()) {
			const child = record[key];
			if (child !== undefined) result[key] = canonicalize(child);
		}
		return result;
	}
	return value;
}

function canonicalJson(value: unknown): string {
	return JSON.stringify(canonicalize(value));
}

export function computeWorkstreamPlanId(input: WorkstreamPlanFingerprintInput): string {
	const fingerprint = {
		goal: input.goal,
		context: input.context,
		design: input.design,
		success: input.success,
		boundaries: input.boundaries,
		workstreams: input.workstreams.map((workstream) => ({
			id: workstream.id,
			label: workstream.label,
			scope: workstream.scope,
			outcome: workstream.outcome,
			boundaries: workstream.boundaries,
			...(workstream.worktreeSlug !== undefined ? { worktreeSlug: workstream.worktreeSlug } : {}),
			...(workstream.dependsOn !== undefined ? { dependsOn: [...workstream.dependsOn].sort() } : {}),
		})),
	};
	return crypto.createHash("sha256").update(canonicalJson(fingerprint)).digest("hex").slice(0, 16);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPersistedState(value: unknown): value is WorkstreamLaunchState {
	if (!isRecord(value)) return false;
	if (value.version !== WORKSTREAM_STATE_VERSION) return false;
	if (!isRecord(value.runs)) return false;
	return true;
}

export function loadWorkstreamLaunchState(filePath: string): WorkstreamLaunchState {
	try {
		const raw = fs.readFileSync(filePath, "utf8");
		const parsed = JSON.parse(raw);
		return isPersistedState(parsed) ? parsed : emptyWorkstreamLaunchState();
	} catch {
		return emptyWorkstreamLaunchState();
	}
}

export function findPersistedWorkstreamEntryByWorktreeLabel(
	state: WorkstreamLaunchState,
	worktreeLabel: string,
): PersistedWorkstreamEntry | null {
	let match: { entry: PersistedWorkstreamEntry; timestamp: string } | null = null;
	for (const run of Object.values(state.runs)) {
		for (const entry of Object.values(run.workstreams)) {
			if (entry.worktree?.label !== worktreeLabel) continue;
			const timestamp = entry.updatedAt ?? run.updatedAt ?? "";
			if (!match || timestamp >= match.timestamp) match = { entry, timestamp };
		}
	}
	return match?.entry ?? null;
}

export function saveWorkstreamLaunchState(filePath: string, state: WorkstreamLaunchState): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.${process.pid}.${Date.now()}.tmp`;
	fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
	fs.renameSync(tmp, filePath);
}
