import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { RunSummaryAgent, RunSummaryResult } from "./client.ts";

export const ACTIVE_AGENTS_WIDGET_ID = "basecamp-swarm-agents";

const DEFAULT_DISPLAY_LIMIT = 5;
const DEFAULT_FETCH_LIMIT = 50;
const DEFAULT_REFRESH_MS = 2_000;
const FIELD_LIMIT = 80;

export interface ActiveAgentsWidgetOptions {
	rootId: string;
	socketPath: string;
	displayLimit?: number;
	fetchLimit?: number;
	refreshMs?: number;
	nowFn?: () => number;
	fetchSummary: (socketPath: string, rootId: string, limit: number) => Promise<RunSummaryResult | null>;
	setIntervalFn?: (handler: () => void, ms: number) => ReturnType<typeof setInterval>;
	clearIntervalFn?: (timer: ReturnType<typeof setInterval>) => void;
}

export interface ActiveAgentsWidgetController {
	refresh: () => Promise<void>;
	stop: () => void;
	clear: () => void;
}

function stripOsc(value: string): string {
	const escapeChar = String.fromCharCode(27);
	const bel = String.fromCharCode(7);
	const oscStart = `${escapeChar}]`;
	const stEnd = `${escapeChar}\\`;
	let result = value;
	let start = result.indexOf(oscStart);
	while (start >= 0) {
		const searchFrom = start + oscStart.length;
		const belEnd = result.indexOf(bel, searchFrom);
		const stEndIndex = result.indexOf(stEnd, searchFrom);
		const hasBelEnd = belEnd >= 0;
		const hasStEnd = stEndIndex >= 0;
		if (!hasBelEnd && !hasStEnd) return result.slice(0, start);
		const end = hasBelEnd && (!hasStEnd || belEnd < stEndIndex) ? belEnd : stEndIndex;
		const endLength = end === belEnd ? bel.length : stEnd.length;
		result = `${result.slice(0, start)}${result.slice(end + endLength)}`;
		start = result.indexOf(oscStart, start);
	}
	return result;
}

function stripAnsi(value: string): string {
	const escapeChar = String.fromCharCode(27);
	const csiPattern = new RegExp(`${escapeChar}(?:[@-Z\\\\-_]|\\[[0-?]*[ -/]*[@-~])`, "g");
	return stripOsc(value).replace(csiPattern, "");
}

function replaceControlCharacters(value: string): string {
	let result = "";
	for (const character of value) {
		const code = character.charCodeAt(0);
		result += code < 32 || code === 127 ? " " : character;
	}
	return result;
}

export function sanitizeWidgetText(value: unknown, maxLength = FIELD_LIMIT): string | null {
	if (typeof value !== "string") return null;
	const sanitized = replaceControlCharacters(stripAnsi(value)).replace(/\s+/g, " ").trim();
	if (!sanitized) return null;
	if (sanitized.length <= maxLength) return sanitized;
	return `${sanitized.slice(0, Math.max(0, maxLength - 1))}…`;
}

function truncateLine(line: string, width: number): string {
	if (width <= 0 || line.length <= width) return line;
	if (width === 1) return "…";
	return `${line.slice(0, width - 1)}…`;
}

function parseTime(value: string | null | undefined): number | null {
	const sanitized = sanitizeWidgetText(value, 64);
	if (!sanitized) return null;
	const time = Date.parse(sanitized);
	return Number.isFinite(time) ? time : null;
}

export function formatElapsed(
	startedAt: string | null | undefined,
	createdAt: string | null | undefined,
	nowMs: number,
): string {
	const startMs = parseTime(startedAt) ?? parseTime(createdAt) ?? nowMs;
	const elapsedSeconds = Math.max(0, Math.floor((nowMs - startMs) / 1000));
	if (elapsedSeconds < 60) return `${elapsedSeconds}s`;
	const elapsedMinutes = Math.floor(elapsedSeconds / 60);
	if (elapsedMinutes < 60) return `${elapsedMinutes}m`;
	const elapsedHours = Math.floor(elapsedMinutes / 60);
	const remainingMinutes = elapsedMinutes % 60;
	return remainingMinutes > 0 ? `${elapsedHours}h ${remainingMinutes}m` : `${elapsedHours}h`;
}

function taskLabel(agent: RunSummaryAgent): string {
	return (
		sanitizeWidgetText(agent.task?.current_task?.label, 48) ?? sanitizeWidgetText(agent.task?.goal, 48) ?? "working"
	);
}

function agentDisplayName(agent: RunSummaryAgent): string {
	return sanitizeWidgetText(agent.agent_handle, 32) ?? sanitizeWidgetText(agent.session_name, 32) ?? "agent";
}

function agentType(agent: RunSummaryAgent): string {
	return sanitizeWidgetText(agent.agent_type, 24) ?? "agent";
}

export function activeRunningAgents(
	agents: readonly RunSummaryAgent[],
	limit = DEFAULT_DISPLAY_LIMIT,
): RunSummaryAgent[] {
	const safeLimit = Math.max(0, Math.trunc(limit));
	return agents.filter((agent) => agent.status === "running").slice(0, safeLimit);
}

export function renderActiveAgentsWidgetLines(
	agents: readonly RunSummaryAgent[],
	options: { width?: number; limit?: number; nowMs?: number } = {},
): string[] {
	const width = options.width ?? 100;
	const nowMs = options.nowMs ?? Date.now();
	const runningAgents = agents.filter((agent) => agent.status === "running");
	const activeAgents = runningAgents.slice(0, Math.max(0, Math.trunc(options.limit ?? DEFAULT_DISPLAY_LIMIT)));
	if (runningAgents.length === 0) return [];

	const lines = [`Swarm agents (${runningAgents.length} running)`];
	for (const agent of activeAgents) {
		const elapsed = formatElapsed(agent.started_at, agent.created_at, nowMs);
		lines.push(`● ${agentDisplayName(agent)} [${agentType(agent)}] — ${taskLabel(agent)} — running ${elapsed}`);
	}
	return lines.map((line) => truncateLine(line, width));
}

export function publishActiveAgentsWidget(
	ctx: ExtensionContext,
	agents: readonly RunSummaryAgent[],
	options: { limit?: number; nowMs?: number } = {},
): void {
	if (!ctx.hasUI) return;
	const runningAgents = agents.filter((agent) => agent.status === "running");
	if (runningAgents.length === 0) {
		ctx.ui.setWidget(ACTIVE_AGENTS_WIDGET_ID, undefined, { placement: "belowEditor" });
		return;
	}

	ctx.ui.setWidget(
		ACTIVE_AGENTS_WIDGET_ID,
		(_tui, theme) => {
			const fg = theme.fg.bind(theme);
			let cachedLines: string[] | null = null;
			let cachedWidth = 0;
			return {
				invalidate() {
					cachedLines = null;
				},
				render(width: number): string[] {
					if (cachedLines && cachedWidth === width) return cachedLines;
					cachedWidth = width;
					cachedLines = renderActiveAgentsWidgetLines(runningAgents, {
						width,
						limit: options.limit ?? DEFAULT_DISPLAY_LIMIT,
						nowMs: options.nowMs,
					});
					return cachedLines.map((line, index) => (index === 0 ? fg("dim", line) : line));
				},
			};
		},
		{ placement: "belowEditor" },
	);
}

export function clearActiveAgentsWidget(ctx: ExtensionContext): void {
	if (!ctx.hasUI) return;
	ctx.ui.setWidget(ACTIVE_AGENTS_WIDGET_ID, undefined, { placement: "belowEditor" });
}

export function startActiveAgentsWidget(
	ctx: ExtensionContext,
	options: ActiveAgentsWidgetOptions,
): ActiveAgentsWidgetController {
	const displayLimit = options.displayLimit ?? DEFAULT_DISPLAY_LIMIT;
	const fetchLimit = options.fetchLimit ?? DEFAULT_FETCH_LIMIT;
	const refreshMs = options.refreshMs ?? DEFAULT_REFRESH_MS;
	const nowFn = options.nowFn ?? Date.now;
	const setIntervalFn = options.setIntervalFn ?? setInterval;
	const clearIntervalFn = options.clearIntervalFn ?? clearInterval;
	let stopped = false;
	let refreshing = false;

	async function refresh(): Promise<void> {
		if (stopped || refreshing) return;
		refreshing = true;
		try {
			const summary = await options.fetchSummary(options.socketPath, options.rootId, fetchLimit);
			if (stopped) return;
			if (!summary) {
				clearActiveAgentsWidget(ctx);
				return;
			}
			publishActiveAgentsWidget(ctx, summary.agents, { limit: displayLimit, nowMs: nowFn() });
		} catch {
			if (!stopped) clearActiveAgentsWidget(ctx);
		} finally {
			refreshing = false;
		}
	}

	const timer = setIntervalFn(() => {
		void refresh();
	}, refreshMs);
	void refresh();

	return {
		refresh,
		stop() {
			stopped = true;
			clearIntervalFn(timer);
			clearActiveAgentsWidget(ctx);
		},
		clear() {
			clearActiveAgentsWidget(ctx);
		},
	};
}
