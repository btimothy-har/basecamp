import { type ChildProcess, spawn } from "node:child_process";
import type { ExtensionAPI, SessionEntry } from "@earendil-works/pi-coding-agent";
import { isCompanionActive } from "../panes/state.ts";
import { resolveModelAlias } from "../platform/model-aliases.ts";
import { getTasksAccess } from "../platform/tasks-access.ts";
import { getWorkspaceService } from "../platform/workspace.ts";
import { buildTitleContext } from "../session/ui/title.ts";

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
	resolveModel: () => string | undefined;
	cwd: string;
	spawnFn: typeof spawn;
}

const analysisKey = Symbol.for("basecamp.companionAnalysis");

type GlobalWithAnalysis = typeof globalThis & {
	[analysisKey]?: AnalysisState;
};

function getAnalysisState(): AnalysisState {
	const globalObject = globalThis as GlobalWithAnalysis;
	globalObject[analysisKey] ??= { inFlight: false, child: null };
	return globalObject[analysisKey];
}

export function mapModelId(resolved: string): string {
	return resolved.replace("/", ":");
}

export function resolveAnalysisModel(): string | undefined {
	const resolved = resolveModelAlias("companion") ?? resolveModelAlias("compaction") ?? resolveModelAlias("fast");
	return resolved ? mapModelId(resolved) : undefined;
}

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

export function maybeRunAnalysis(state: AnalysisState, deps: AnalysisDeps): void {
	if (state.inFlight) return;
	if (!deps.isActive()) return;
	if (countUserTurns(deps.branch) < MIN_USER_TURNS) return;

	const model = deps.resolveModel();
	if (!model) return;

	const context = buildTitleContext(deps.branch);
	if (!context.trim()) return;

	const alreadyTracked = buildAlreadyTracked(deps.tasksState);
	state.inFlight = true;

	const done = () => {
		state.inFlight = false;
		state.child = null;
	};

	let watchdog: ReturnType<typeof setTimeout> | null = null;

	try {
		const child = deps.spawnFn("basecamp", ["companion-analyze", "--session-id", deps.sessionId, "--model", model], {
			cwd: deps.cwd,
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
			child.stdin?.end(buildEnvelope(context, alreadyTracked));
		} catch {
			// best effort
		}
	} catch {
		if (watchdog) clearTimeout(watchdog);
		done();
	}
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
				tasksState: getTasksAccess()?.getState() ?? null,
				resolveModel: resolveAnalysisModel,
				cwd: getWorkspaceService()?.getEffectiveCwd?.() ?? process.cwd(),
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
