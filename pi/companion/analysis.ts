import { type ChildProcess, spawn } from "node:child_process";
import type { ExtensionAPI, SessionEntry } from "@earendil-works/pi-coding-agent";
import { processScoped } from "#core/global-registry.ts";
import { isCompanionActive } from "#core/host/env.ts";
import { getWorkspaceEffectiveCwd } from "#core/project/workspace/state.ts";
import { buildUserContext } from "#core/session/user-context.ts";
import { getTasksReader } from "#tasks/index.ts";

export const MIN_USER_TURNS = 2;
export const ANALYSIS_TIMEOUT_MS = 60_000;

export interface AnalysisTaskSummary {
	label: string;
	status: string;
}

export interface AnalysisTasksState {
	goal: string | null;
	tasks: AnalysisTaskSummary[];
}

export interface AnalysisState {
	inFlight: boolean;
	child: ChildProcess | null;
}

export interface AnalysisDeps {
	isActive: () => boolean;
	branch: SessionEntry[];
	sessionId: string;
	tasksState: AnalysisTasksState | null;
	cwd: string;
	spawnFn: typeof spawn;
}

// Surviving state: an in-flight analyze child outlives /reload.
const getAnalysisState = processScoped<AnalysisState>("basecamp.companionAnalysis", () => ({
	inFlight: false,
	child: null,
}));

export function countUserTurns(branch: SessionEntry[]): number {
	return branch.filter((entry) => entry.type === "message" && entry.message.role === "user").length;
}

export function buildAlreadyTracked(state: AnalysisTasksState | null | undefined): string {
	if (!state) return "";
	const lines: string[] = [];

	if (state.goal) lines.push(`Goal: ${state.goal}`);

	const tasks = state.tasks.filter((task) => task.status !== "deleted");
	if (tasks.length > 0) {
		lines.push("Tasks:");
		for (const task of tasks) lines.push(`[${task.status}] ${task.label}`);
	}

	return lines.join("\n");
}

export function buildEnvelope(context: string, alreadyTracked: string): string {
	return JSON.stringify({ context, alreadyTracked });
}

interface StartAnalysisOptions {
	spawnFn: typeof spawn;
	cwd: string;
	sessionId: string;
	context: string;
	alreadyTracked: string;
}

export function startAnalysis(state: AnalysisState, options: StartAnalysisOptions): void {
	state.inFlight = true;

	const done = () => {
		state.inFlight = false;
		state.child = null;
	};

	let watchdog: ReturnType<typeof setTimeout> | null = null;

	try {
		const args = ["companion", "analyze", "--session-id", options.sessionId];

		const child = options.spawnFn("basecamp", args, {
			cwd: options.cwd,
			stdio: ["pipe", "ignore", "ignore"],
		});
		state.child = child;

		const finalize = () => {
			if (watchdog) {
				clearTimeout(watchdog);
				watchdog = null;
			}
			done();
		};

		watchdog = setTimeout(() => {
			try {
				child.kill();
			} catch {
				// best effort
			}
		}, ANALYSIS_TIMEOUT_MS);
		// Best-effort watchdog must never keep the event loop (or process exit) waiting.
		watchdog.unref?.();

		child.on("error", () => {
			finalize();
		});
		child.on("close", () => {
			finalize();
		});

		try {
			child.stdin?.end(buildEnvelope(options.context, options.alreadyTracked));
		} catch {
			// best effort
		}
	} catch {
		if (watchdog) clearTimeout(watchdog);
		done();
	}
}

export function maybeRunAnalysis(state: AnalysisState, deps: AnalysisDeps): void {
	if (state.inFlight) return;
	if (!deps.isActive()) return;
	if (countUserTurns(deps.branch) < MIN_USER_TURNS) return;

	const context = buildUserContext(deps.branch);
	if (!context.trim()) return;

	startAnalysis(state, {
		spawnFn: deps.spawnFn,
		cwd: deps.cwd,
		sessionId: deps.sessionId,
		context,
		alreadyTracked: buildAlreadyTracked(deps.tasksState),
	});
}

export default function registerCompanionAnalysis(pi: ExtensionAPI): void {
	if (Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0) return;

	const state = getAnalysisState();

	pi.on("agent_end", (_event, ctx) => {
		try {
			maybeRunAnalysis(state, {
				isActive: isCompanionActive,
				branch: ctx.sessionManager.getBranch(),
				sessionId: ctx.sessionManager.getSessionId(),
				tasksState: getTasksReader()?.getState() ?? null,
				cwd: getWorkspaceEffectiveCwd(),
				spawnFn: spawn,
			});
		} catch {
			// never block agent_end
		}
	});

	pi.on("session_shutdown", () => {
		try {
			state.child?.kill();
		} catch {
			// best effort
		}
		state.inFlight = false;
		state.child = null;
	});
}
