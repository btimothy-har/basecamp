import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { basecampRoot } from "pi-core/platform/paths.ts";

export const WORKSTREAM_LAUNCH_STATE_VERSION = 1;

export type WorkstreamLaunchOperationStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";

export interface WorkstreamLaunchOperationState {
	status: WorkstreamLaunchOperationStatus;
	message?: string;
	error?: string;
}

export interface WorkstreamLaunchSource {
	dossierPath: string;
	repoPagePath?: string;
}

export interface WorkstreamLaunchWorkstream {
	label: string;
	brief: string;
	constraints?: string;
}

export interface WorkstreamLaunchWorktree {
	label: string;
	path?: string;
	branch?: string;
	created?: boolean;
}

export interface WorkstreamLaunchAgent {
	handle?: string;
	type?: string;
}

export interface WorkstreamLaunchRecord {
	id: string;
	fingerprint: string;
	repo: string;
	source: WorkstreamLaunchSource;
	workstream: WorkstreamLaunchWorkstream;
	worktree: WorkstreamLaunchWorktree;
	agent: WorkstreamLaunchAgent;
	setup: WorkstreamLaunchOperationState;
	herdr: WorkstreamLaunchOperationState;
	launch: WorkstreamLaunchOperationState;
	createdAt: string;
	updatedAt: string;
}

export interface WorkstreamLaunchState {
	version: typeof WORKSTREAM_LAUNCH_STATE_VERSION;
	records: WorkstreamLaunchRecord[];
}

export type WorkstreamLaunchRecordInput = WorkstreamLaunchRecord;
export type WorkstreamLaunchRecordDraft = Omit<WorkstreamLaunchRecord, "id">;

export type WorkstreamLaunchOperationUpdate = Partial<WorkstreamLaunchOperationState> & {
	status: WorkstreamLaunchOperationStatus;
};

export interface WorkstreamLaunchRecordUpdate {
	fingerprint?: string;
	repo?: string;
	source?: Partial<WorkstreamLaunchSource>;
	workstream?: Partial<WorkstreamLaunchWorkstream>;
	worktree?: Partial<WorkstreamLaunchWorktree>;
	agent?: Partial<WorkstreamLaunchAgent>;
	setup?: WorkstreamLaunchOperationUpdate;
	herdr?: WorkstreamLaunchOperationUpdate;
	launch?: WorkstreamLaunchOperationUpdate;
	updatedAt?: string;
}

export interface WorkstreamLaunchFingerprintInput {
	repo: string;
	dossierPath: string;
	label: string;
}

export interface WorkstreamLaunchListFilter {
	repo?: string;
	dossierPath?: string;
}

export interface WorkstreamLaunchDuplicateLookup {
	repo?: string;
	fingerprint?: string;
	worktreeLabel?: string;
}

export interface WorkstreamLaunchAppendResult {
	appended: boolean;
	record: WorkstreamLaunchRecord;
	state: WorkstreamLaunchState;
}

export function defaultWorkstreamLaunchesDir(homeDir = os.homedir()): string {
	return path.join(basecampRoot(homeDir), "workstream-launches");
}

export function workstreamLaunchStatePath(dir = defaultWorkstreamLaunchesDir()): string {
	return path.join(dir, "launch-index.json");
}

export function emptyWorkstreamLaunchState(): WorkstreamLaunchState {
	return { version: WORKSTREAM_LAUNCH_STATE_VERSION, records: [] };
}

function normalizeFingerprintLabel(value: string): string {
	return value.trim().toLowerCase().replace(/\s+/g, " ");
}

const WORKSTREAM_LAUNCH_ID_MAX_LENGTH = 40;

export function slugifyWorkstreamLaunchId(label: string): string {
	const slug = label
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, WORKSTREAM_LAUNCH_ID_MAX_LENGTH)
		.replace(/-+$/g, "");
	return slug || "workstream";
}

function nextAvailableWorkstreamLaunchIdFromRecords(
	records: WorkstreamLaunchRecord[],
	repo: string,
	baseLabel: string,
): string {
	const base = slugifyWorkstreamLaunchId(baseLabel);
	const taken = new Set(records.filter((record) => record.repo === repo).map((record) => record.id));
	if (!taken.has(base)) return base;
	for (let suffix = 2; ; suffix += 1) {
		const candidate = `${base}-${suffix}`;
		if (!taken.has(candidate)) return candidate;
	}
}

export function nextAvailableWorkstreamLaunchId(filePath: string, repo: string, baseLabel: string): string {
	return nextAvailableWorkstreamLaunchIdFromRecords(loadWorkstreamLaunchState(filePath).records, repo, baseLabel);
}

export function buildWorkstreamLaunchFingerprint(input: WorkstreamLaunchFingerprintInput): string {
	const payload = JSON.stringify({
		repo: input.repo.trim().toLowerCase(),
		dossierPath: path.normalize(input.dossierPath.trim()),
		label: normalizeFingerprintLabel(input.label),
	});
	return `wlfp_${crypto.createHash("sha256").update(payload).digest("hex").slice(0, 16)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
	return typeof value === "string" ? value : undefined;
}

function optionalBoolean(value: unknown): boolean | undefined {
	return typeof value === "boolean" ? value : undefined;
}

function normalizeOperationState(value: unknown): WorkstreamLaunchOperationState | null {
	if (!isRecord(value)) return null;
	const status = value.status;
	if (
		status !== "pending" &&
		status !== "running" &&
		status !== "succeeded" &&
		status !== "failed" &&
		status !== "skipped"
	) {
		return null;
	}
	return {
		status,
		...(optionalString(value.message) ? { message: optionalString(value.message) } : {}),
		...(optionalString(value.error) ? { error: optionalString(value.error) } : {}),
	};
}

function normalizeSource(value: unknown): WorkstreamLaunchSource | null {
	if (!isRecord(value) || typeof value.dossierPath !== "string") return null;
	return {
		dossierPath: value.dossierPath,
		...(optionalString(value.repoPagePath) ? { repoPagePath: optionalString(value.repoPagePath) } : {}),
	};
}

function normalizeWorkstream(value: unknown): WorkstreamLaunchWorkstream | null {
	if (!isRecord(value) || typeof value.label !== "string" || typeof value.brief !== "string") return null;
	return {
		label: value.label,
		brief: value.brief,
		...(optionalString(value.constraints) ? { constraints: optionalString(value.constraints) } : {}),
	};
}

function normalizeWorktree(value: unknown): WorkstreamLaunchWorktree | null {
	if (!isRecord(value) || typeof value.label !== "string") return null;
	return {
		label: value.label,
		...(optionalString(value.path) ? { path: optionalString(value.path) } : {}),
		...(optionalString(value.branch) ? { branch: optionalString(value.branch) } : {}),
		...(optionalBoolean(value.created) !== undefined ? { created: optionalBoolean(value.created) } : {}),
	};
}

function normalizeAgent(value: unknown): WorkstreamLaunchAgent | null {
	if (!isRecord(value)) return null;
	// Launch records are persisted before dispatch assigns a handle.
	return {
		...(optionalString(value.handle) ? { handle: optionalString(value.handle) } : {}),
		...(optionalString(value.type) ? { type: optionalString(value.type) } : {}),
	};
}

function normalizeRecord(value: unknown): WorkstreamLaunchRecord | null {
	if (!isRecord(value)) return null;
	if (
		typeof value.id !== "string" ||
		typeof value.fingerprint !== "string" ||
		typeof value.repo !== "string" ||
		typeof value.createdAt !== "string" ||
		typeof value.updatedAt !== "string"
	) {
		return null;
	}

	const source = normalizeSource(value.source);
	const workstream = normalizeWorkstream(value.workstream);
	const worktree = normalizeWorktree(value.worktree);
	const agent = normalizeAgent(value.agent);
	const setup = normalizeOperationState(value.setup);
	const herdr = normalizeOperationState(value.herdr);
	const launch = normalizeOperationState(value.launch);
	if (!source || !workstream || !worktree || !agent || !setup || !herdr || !launch) return null;

	return {
		id: value.id,
		fingerprint: value.fingerprint,
		repo: value.repo,
		source,
		workstream,
		worktree,
		agent,
		setup,
		herdr,
		launch,
		createdAt: value.createdAt,
		updatedAt: value.updatedAt,
	};
}

function normalizeRecordDraft(value: unknown, id: string): WorkstreamLaunchRecord | null {
	if (!isRecord(value)) return null;
	return normalizeRecord({ ...value, id });
}

function normalizeState(value: unknown): WorkstreamLaunchState {
	if (!isRecord(value)) return emptyWorkstreamLaunchState();
	if (value.version !== WORKSTREAM_LAUNCH_STATE_VERSION || !Array.isArray(value.records)) {
		return emptyWorkstreamLaunchState();
	}

	return {
		version: WORKSTREAM_LAUNCH_STATE_VERSION,
		records: value.records.flatMap((record) => {
			const normalized = normalizeRecord(record);
			return normalized ? [normalized] : [];
		}),
	};
}

export function loadWorkstreamLaunchState(filePath = workstreamLaunchStatePath()): WorkstreamLaunchState {
	try {
		const raw = fs.readFileSync(filePath, "utf8");
		return normalizeState(JSON.parse(raw));
	} catch {
		return emptyWorkstreamLaunchState();
	}
}

export function saveWorkstreamLaunchState(filePath: string, state: WorkstreamLaunchState): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	// Normalize at the write boundary so accidental durable-state fields never survive direct saves.
	fs.writeFileSync(tmp, JSON.stringify(normalizeState(state), null, 2));
	fs.renameSync(tmp, filePath);
}

const LAUNCH_STATE_LOCK_STALE_MS = 30_000;

function launchStateLockPath(filePath: string): string {
	return `${filePath}.lock`;
}

function errorCode(error: unknown): string | null {
	return typeof error === "object" && error !== null && "code" in error
		? String((error as { code?: unknown }).code)
		: null;
}

function acquireLaunchStateLock(filePath: string): number {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const lockPath = launchStateLockPath(filePath);
	try {
		return fs.openSync(lockPath, "wx");
	} catch (error) {
		if (errorCode(error) !== "EEXIST") throw error;
		try {
			const stat = fs.statSync(lockPath);
			if (Date.now() - stat.mtimeMs > LAUNCH_STATE_LOCK_STALE_MS) {
				fs.rmSync(lockPath, { force: true });
				return fs.openSync(lockPath, "wx");
			}
		} catch (staleError) {
			if (errorCode(staleError) !== "ENOENT") throw staleError;
			return fs.openSync(lockPath, "wx");
		}
		throw new Error("Workstream launch state is locked; retry shortly.");
	}
}

function withLaunchStateLock<T>(filePath: string, fn: () => T): T {
	const fd = acquireLaunchStateLock(filePath);
	const lockPath = launchStateLockPath(filePath);
	try {
		return fn();
	} finally {
		try {
			fs.closeSync(fd);
		} finally {
			fs.rmSync(lockPath, { force: true });
		}
	}
}

function findDuplicateRecord(
	records: WorkstreamLaunchRecord[],
	lookup: WorkstreamLaunchDuplicateLookup,
	scopeRepo?: string,
): WorkstreamLaunchRecord | null {
	if (!lookup.fingerprint && !lookup.worktreeLabel) return null;
	// Worktree labels are only unique within a repo, so scope matches to the
	// record's repo; a same-named worktree in another repo is not a duplicate.
	const repo = scopeRepo ?? lookup.repo;
	return (
		records.find((record) => {
			if (repo && record.repo !== repo) return false;
			if (lookup.fingerprint && record.fingerprint === lookup.fingerprint) return true;
			if (lookup.worktreeLabel && record.worktree.label === lookup.worktreeLabel) return true;
			return false;
		}) ?? null
	);
}

export function appendWorkstreamLaunchRecord(
	filePath: string,
	record: WorkstreamLaunchRecordInput,
): WorkstreamLaunchState {
	const normalized = normalizeRecord(record);
	if (!normalized) throw new Error("Invalid workstream launch record.");
	return withLaunchStateLock(filePath, () => {
		const state = loadWorkstreamLaunchState(filePath);
		state.records.push(normalized);
		saveWorkstreamLaunchState(filePath, state);
		return state;
	});
}

export function appendWorkstreamLaunchRecordIfAbsent(
	filePath: string,
	record: WorkstreamLaunchRecordInput,
	lookup: WorkstreamLaunchDuplicateLookup,
): WorkstreamLaunchAppendResult {
	const normalized = normalizeRecord(record);
	if (!normalized) throw new Error("Invalid workstream launch record.");
	return withLaunchStateLock(filePath, () => {
		const state = loadWorkstreamLaunchState(filePath);
		const idDuplicate = state.records.find(
			(existing) => existing.repo === normalized.repo && existing.id === normalized.id,
		);
		if (idDuplicate) return { appended: false, record: idDuplicate, state };
		const duplicate = findDuplicateRecord(state.records, lookup, normalized.repo);
		if (duplicate) return { appended: false, record: duplicate, state };
		state.records.push(normalized);
		saveWorkstreamLaunchState(filePath, state);
		return { appended: true, record: normalized, state };
	});
}

export function appendWorkstreamLaunchRecordWithAvailableId(
	filePath: string,
	record: WorkstreamLaunchRecordDraft,
	lookup: WorkstreamLaunchDuplicateLookup,
	baseLabel: string,
): WorkstreamLaunchAppendResult {
	return withLaunchStateLock(filePath, () => {
		const state = loadWorkstreamLaunchState(filePath);
		const draft = normalizeRecordDraft(record, slugifyWorkstreamLaunchId(baseLabel));
		if (!draft) throw new Error("Invalid workstream launch record.");

		const duplicate = findDuplicateRecord(state.records, lookup, draft.repo);
		if (duplicate) return { appended: false, record: duplicate, state };

		const id = nextAvailableWorkstreamLaunchIdFromRecords(state.records, draft.repo, baseLabel);
		const normalized = normalizeRecord({ ...draft, id });
		if (!normalized) throw new Error("Invalid workstream launch record.");
		state.records.push(normalized);
		saveWorkstreamLaunchState(filePath, state);
		return { appended: true, record: normalized, state };
	});
}

function mergeRecordUpdate(
	current: WorkstreamLaunchRecord,
	updates: WorkstreamLaunchRecordUpdate,
	now: string,
): WorkstreamLaunchRecord {
	const normalized = normalizeRecord({
		...current,
		...updates,
		source: updates.source ? { ...current.source, ...updates.source } : current.source,
		workstream: updates.workstream ? { ...current.workstream, ...updates.workstream } : current.workstream,
		worktree: updates.worktree ? { ...current.worktree, ...updates.worktree } : current.worktree,
		agent: updates.agent ? { ...current.agent, ...updates.agent } : current.agent,
		setup: updates.setup ?? current.setup,
		herdr: updates.herdr ?? current.herdr,
		launch: updates.launch ?? current.launch,
		id: current.id,
		createdAt: current.createdAt,
		updatedAt: updates.updatedAt ?? now,
	});
	if (!normalized) throw new Error("Invalid workstream launch record update.");
	return normalized;
}

export function updateWorkstreamLaunchRecord(
	filePath: string,
	id: string,
	updates: WorkstreamLaunchRecordUpdate,
	now = new Date().toISOString(),
): WorkstreamLaunchRecord | null {
	return withLaunchStateLock(filePath, () => {
		const state = loadWorkstreamLaunchState(filePath);
		const index = state.records.findIndex((record) => record.id === id);
		if (index === -1) return null;

		const current = state.records[index]!;
		const normalized = mergeRecordUpdate(current, updates, now);

		state.records[index] = normalized;
		saveWorkstreamLaunchState(filePath, state);
		return normalized;
	});
}

export function updateFailedWorkstreamLaunchRecord(
	filePath: string,
	id: string,
	updates: WorkstreamLaunchRecordUpdate,
	now = new Date().toISOString(),
): WorkstreamLaunchRecord | null {
	return withLaunchStateLock(filePath, () => {
		const state = loadWorkstreamLaunchState(filePath);
		const index = state.records.findIndex((record) => record.id === id);
		if (index === -1) return null;

		const current = state.records[index]!;
		if (current.launch.status !== "failed") return null;
		const normalized = mergeRecordUpdate(current, updates, now);

		state.records[index] = normalized;
		saveWorkstreamLaunchState(filePath, state);
		return normalized;
	});
}

export function listWorkstreamLaunchRecords(
	filePath = workstreamLaunchStatePath(),
	filter: WorkstreamLaunchListFilter = {},
): WorkstreamLaunchRecord[] {
	return loadWorkstreamLaunchState(filePath).records.filter((record) => {
		if (filter.repo && record.repo !== filter.repo) return false;
		if (filter.dossierPath && record.source.dossierPath !== filter.dossierPath) return false;
		return true;
	});
}

export function findDuplicateWorkstreamLaunch(
	filePath: string,
	lookup: WorkstreamLaunchDuplicateLookup,
): WorkstreamLaunchRecord | null {
	return findDuplicateRecord(loadWorkstreamLaunchState(filePath).records, lookup);
}

export function findWorkstreamLaunchById(filePath: string, id: string, repo?: string): WorkstreamLaunchRecord | null {
	return (
		loadWorkstreamLaunchState(filePath).records.find(
			(record) => record.id === id && (repo === undefined || record.repo === repo),
		) ?? null
	);
}

export function stampWorkstreamLaunchAgentHandle(
	filePath: string,
	id: string,
	handle: string,
	now = new Date().toISOString(),
): WorkstreamLaunchRecord | null {
	return updateWorkstreamLaunchRecord(filePath, id, { agent: { handle } }, now);
}
