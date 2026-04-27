/**
 * Async agent watcher — detects completed async agents and polls status.
 *
 * Result watcher: fs.watch() on ASYNC_RESULTS_DIR for new .json files.
 * When detected, reads the result, emits AGENT_ASYNC_COMPLETE_EVENT, and
 * deletes the file. Includes restart-on-error and deduplication.
 *
 * Status poller: setInterval reads status.json from each tracked async
 * job's directory. Updates in-memory AsyncJobState for the UI and
 * agent_status tool.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { EventBus } from "@mariozechner/pi-coding-agent";
import {
	AGENT_ASYNC_COMPLETE_EVENT,
	AGENT_ASYNC_STARTED_EVENT,
	ASYNC_RESULTS_DIR,
	type AsyncJobState,
	type AsyncResult,
	type AsyncStatus,
} from "./types.ts";

const POLL_INTERVAL_MS = 500;
const WATCHER_RESTART_DELAY_MS = 3000;

// ============================================================================
// State
// ============================================================================

export interface AsyncWatcherState {
	jobs: Map<string, AsyncJobState>;
	watcher: fs.FSWatcher | null;
	poller: NodeJS.Timeout | null;
	restartTimer: NodeJS.Timeout | null;
	seen: Set<string>;
	onUpdate?: () => void;
}

export function createWatcherState(): AsyncWatcherState {
	return {
		jobs: new Map(),
		watcher: null,
		poller: null,
		restartTimer: null,
		seen: new Set(),
	};
}

// ============================================================================
// Result Watcher
// ============================================================================

function processResultFile(filePath: string, events: EventBus, seen: Set<string>): void {
	const fileName = path.basename(filePath);
	if (seen.has(fileName)) return;

	let data: AsyncResult;
	try {
		const raw = fs.readFileSync(filePath, "utf-8");
		data = JSON.parse(raw) as AsyncResult;
	} catch {
		// File might not be fully written yet — will retry on next watch event.
		return;
	}

	seen.add(fileName);

	try {
		fs.unlinkSync(filePath);
	} catch {
		// Best effort cleanup.
	}

	events.emit(AGENT_ASYNC_COMPLETE_EVENT, data);
}

function startWatcher(state: AsyncWatcherState, events: EventBus): void {
	fs.mkdirSync(ASYNC_RESULTS_DIR, { recursive: true });

	try {
		state.watcher = fs.watch(ASYNC_RESULTS_DIR, (eventType, fileName) => {
			if (eventType !== "rename" || !fileName) return;
			const name = fileName.toString();
			if (!name.endsWith(".json")) return;
			processResultFile(path.join(ASYNC_RESULTS_DIR, name), events, state.seen);
		});

		state.watcher.on("error", () => {
			stopWatcher(state);
			state.restartTimer = setTimeout(() => {
				state.restartTimer = null;
				startWatcher(state, events);
			}, WATCHER_RESTART_DELAY_MS);
		});

		state.watcher.unref?.();
	} catch {
		state.restartTimer = setTimeout(() => {
			state.restartTimer = null;
			startWatcher(state, events);
		}, WATCHER_RESTART_DELAY_MS);
	}
}

function stopWatcher(state: AsyncWatcherState): void {
	state.watcher?.close();
	state.watcher = null;
	if (state.restartTimer) {
		clearTimeout(state.restartTimer);
		state.restartTimer = null;
	}
}

/** Pick up any result files that appeared before the watcher started. */
function primeExistingResults(state: AsyncWatcherState, events: EventBus): void {
	try {
		for (const file of fs.readdirSync(ASYNC_RESULTS_DIR)) {
			if (!file.endsWith(".json")) continue;
			processResultFile(path.join(ASYNC_RESULTS_DIR, file), events, state.seen);
		}
	} catch {
		// Directory might not exist yet.
	}
}

// ============================================================================
// Status Poller
// ============================================================================

function readStatus(asyncDir: string): AsyncStatus | null {
	const statusPath = path.join(asyncDir, "status.json");
	try {
		return JSON.parse(fs.readFileSync(statusPath, "utf-8")) as AsyncStatus;
	} catch {
		return null;
	}
}

function pollJobs(state: AsyncWatcherState): void {
	let changed = false;

	for (const job of state.jobs.values()) {
		if (job.status === "complete" || job.status === "failed") continue;

		const status = readStatus(job.asyncDir);
		if (!status) continue;

		const prev = job.status;
		job.status = status.state === "complete" ? "complete" : status.state === "failed" ? "failed" : "running";
		job.updatedAt = status.lastUpdate;
		job.model = status.model;
		job.toolCount = status.toolCount;
		job.turnCount = status.turnCount;
		job.taskProgress = status.taskProgress;

		if (job.status !== prev) changed = true;
	}

	if (changed) state.onUpdate?.();

	// Stop poller if no active jobs
	if (!hasActiveJobs(state)) {
		stopPoller(state);
		state.onUpdate?.();
	}
}

function startPoller(state: AsyncWatcherState): void {
	if (state.poller) return;
	state.poller = setInterval(() => pollJobs(state), POLL_INTERVAL_MS);
	state.poller.unref?.();
}

function stopPoller(state: AsyncWatcherState): void {
	if (state.poller) {
		clearInterval(state.poller);
		state.poller = null;
	}
}

// ============================================================================
// Job Tracking
// ============================================================================

function handleStarted(state: AsyncWatcherState, data: unknown): void {
	const info = data as {
		id?: string;
		agent?: string;
		agentSource?: "builtin" | "user";
		task?: string;
		asyncDir?: string;
	};
	if (!info.id) return;

	const now = Date.now();
	state.jobs.set(info.id, {
		asyncId: info.id,
		asyncDir: info.asyncDir ?? "",
		agent: info.agent ?? "unknown",
		agentSource: info.agentSource ?? "builtin",
		task: info.task ?? "",
		status: "queued",
		startedAt: now,
		updatedAt: now,
	});

	startPoller(state);
	state.onUpdate?.();
}

function handleComplete(state: AsyncWatcherState, data: unknown): void {
	const result = data as AsyncResult;
	if (!result.runId) return;

	const job = state.jobs.get(result.runId);
	if (job) {
		job.status = result.success ? "complete" : "failed";
		job.updatedAt = Date.now();
		state.onUpdate?.();
	}
}

// ============================================================================
// Public API
// ============================================================================

export function hasActiveJobs(state: AsyncWatcherState): boolean {
	for (const job of state.jobs.values()) {
		if (job.status === "queued" || job.status === "running") return true;
	}
	return false;
}

export function getActiveJobs(state: AsyncWatcherState): AsyncJobState[] {
	return Array.from(state.jobs.values()).filter((j) => j.status === "queued" || j.status === "running");
}

export function getAllJobs(state: AsyncWatcherState): AsyncJobState[] {
	return Array.from(state.jobs.values());
}

export function startAsyncWatcher(state: AsyncWatcherState, events: EventBus): void {
	events.on(AGENT_ASYNC_STARTED_EVENT, (data: unknown) => handleStarted(state, data));
	events.on(AGENT_ASYNC_COMPLETE_EVENT, (data: unknown) => handleComplete(state, data));

	startWatcher(state, events);
	primeExistingResults(state, events);
	startPoller(state);
}

export function stopAsyncWatcher(state: AsyncWatcherState): void {
	stopWatcher(state);
	stopPoller(state);
}

export function resetAsyncWatcher(state: AsyncWatcherState): void {
	state.jobs.clear();
	state.seen.clear();
	state.onUpdate?.();
}

export function killAllAsyncAgents(state: AsyncWatcherState): void {
	for (const job of state.jobs.values()) {
		if (job.status !== "queued" && job.status !== "running") continue;
		const status = readStatus(job.asyncDir);
		if (status?.pid) {
			try {
				process.kill(status.pid, "SIGTERM");
			} catch {
				// Process may have already exited.
			}
		}
	}
}
