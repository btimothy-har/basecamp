import { DEFAULT_HEALTH_TIMEOUT_MS, optionalString, requestJsonOverUds } from "../../../hub/index.ts";

export interface RunSummaryTaskInfo {
	goal?: string | null;
	current_task?: {
		label?: string | null;
	} | null;
}

export interface RunSummaryAgent {
	agent_handle?: string | null;
	agent_type?: string | null;
	session_name?: string | null;
	status?: string | null;
	created_at?: string | null;
	started_at?: string | null;
	task?: RunSummaryTaskInfo | null;
}

export interface RunSummaryResult {
	agents: RunSummaryAgent[];
}

function parseRunSummaryTask(value: unknown): RunSummaryTaskInfo | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	const currentTask = record.current_task;
	return {
		goal: optionalString(record.goal),
		current_task:
			currentTask && typeof currentTask === "object"
				? { label: optionalString((currentTask as Record<string, unknown>).label) }
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
	return {
		agent_handle: agentHandle,
		agent_type: optionalString(record.agent_type),
		session_name: sessionName,
		status,
		created_at: optionalString(record.created_at),
		started_at: optionalString(record.started_at),
		task: parseRunSummaryTask(record.task),
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
