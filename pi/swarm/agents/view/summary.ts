import {
	DEFAULT_HEALTH_TIMEOUT_MS,
	optionalBoolean,
	optionalNumber,
	optionalString,
	requestJsonOverUds,
} from "#core/hub/index.ts";

export interface RunSummaryTaskPlanItem {
	index?: number | null;
	label?: string | null;
	status?: string | null;
}

export interface RunSummaryTaskInfo {
	goal?: string | null;
	task_plan?: RunSummaryTaskPlanItem[];
	current_task?: {
		index?: number | null;
		label?: string | null;
		status?: string | null;
	} | null;
}

export interface RunSummaryActivity {
	kind?: string | null;
	seq?: number | null;
	timestamp?: string | null;
	category?: string | null;
	label?: string | null;
	snippet?: string | null;
	toolName?: string | null;
	isError?: boolean | null;
	turnIndex?: number | null;
	toolCount?: number | null;
}

export interface RunSummaryAgent {
	agent_handle?: string | null;
	agent_id_short?: string | null;
	agent_type?: string | null;
	model?: string | null;
	session_name?: string | null;
	status?: string | null;
	created_at?: string | null;
	started_at?: string | null;
	ended_at?: string | null;
	task?: RunSummaryTaskInfo | null;
	recent_activity?: RunSummaryActivity[];
}

export interface RunSummaryResult {
	root_id?: string | null;
	session_active?: boolean;
	agents: RunSummaryAgent[];
}

function parseRunSummaryActivity(value: unknown): RunSummaryActivity | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	const kind = optionalString(record.kind);
	const seq = optionalNumber(record.seq);
	const timestamp = optionalString(record.timestamp);
	if (kind === null || seq === null || timestamp === null) return null;
	return {
		kind,
		seq,
		timestamp,
		category: optionalString(record.category),
		label: optionalString(record.label),
		snippet: optionalString(record.snippet),
		toolName: optionalString(record.toolName),
		isError: optionalBoolean(record.isError),
		turnIndex: optionalNumber(record.turnIndex),
		toolCount: optionalNumber(record.toolCount),
	};
}

function parseRunSummaryTaskPlanItem(value: unknown): RunSummaryTaskPlanItem | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	return {
		index: optionalNumber(record.index),
		label: optionalString(record.label),
		status: optionalString(record.status),
	};
}

function parseRunSummaryTask(value: unknown): RunSummaryTaskInfo | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	const currentTask = record.current_task;
	const taskPlan = Array.isArray(record.task_plan)
		? record.task_plan.map(parseRunSummaryTaskPlanItem).filter((item): item is RunSummaryTaskPlanItem => item !== null)
		: [];
	return {
		goal: optionalString(record.goal),
		task_plan: taskPlan,
		current_task:
			currentTask && typeof currentTask === "object"
				? {
						index: optionalNumber((currentTask as Record<string, unknown>).index),
						label: optionalString((currentTask as Record<string, unknown>).label),
						status: optionalString((currentTask as Record<string, unknown>).status),
					}
				: null,
	};
}

function parseRunSummaryAgent(value: unknown): RunSummaryAgent | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	const agentHandle = optionalString(record.agent_handle);
	const sessionName = optionalString(record.session_name);
	const status = optionalString(record.status);
	if (agentHandle === null || sessionName === null || status === null) return null;
	const recentActivity = Array.isArray(record.recent_activity)
		? record.recent_activity.map(parseRunSummaryActivity).filter((item): item is RunSummaryActivity => item !== null)
		: [];
	return {
		agent_handle: agentHandle,
		agent_id_short: optionalString(record.agent_id_short),
		agent_type: optionalString(record.agent_type),
		model: optionalString(record.model),
		session_name: sessionName,
		status,
		created_at: optionalString(record.created_at),
		started_at: optionalString(record.started_at),
		ended_at: optionalString(record.ended_at),
		task: parseRunSummaryTask(record.task),
		recent_activity: recentActivity,
	};
}

export function buildRunSummaryPath(rootId: string, limit: number): string {
	const safeLimit = Math.max(0, Math.min(50, Math.trunc(limit)));
	return `/runs/summary?root_id=${encodeURIComponent(rootId)}&limit=${safeLimit}`;
}

export function parseRunSummaryResponse(parsed: unknown): RunSummaryResult | null {
	if (!parsed || typeof parsed !== "object") return null;
	const record = parsed as Record<string, unknown>;
	const rawAgents = Array.isArray(record.agents) ? record.agents : [];
	return {
		root_id: optionalString(record.root_id),
		session_active: typeof record.session_active === "boolean" ? record.session_active : undefined,
		agents: rawAgents.map(parseRunSummaryAgent).filter((agent): agent is RunSummaryAgent => agent !== null),
	};
}

export async function fetchRunSummary(
	socketPath: string,
	rootId: string,
	limit: number,
	timeoutMs = DEFAULT_HEALTH_TIMEOUT_MS,
): Promise<RunSummaryResult | null> {
	const parsed = await requestJsonOverUds(socketPath, buildRunSummaryPath(rootId, limit), timeoutMs);
	return parseRunSummaryResponse(parsed);
}
