export const DEFAULT_RECENT_ROOT_LIMIT = 5;
export const MAX_RECENT_ROOT_LIMIT = 50;
export const RECENT_ROOT_STEP = 5;

export const EMPTY_FILTERS = Object.freeze({
	repo: "all",
	worktree: "all",
	kind: "all",
	liveOnly: false,
	status: "all",
	type: "all",
});

const HANDLE_PATTERN = /^[A-Za-z0-9_.-]{1,128}$/;
const RUN_STATUSES = new Set(["pending", "running", "completed", "failed", "idle"]);
const CONTEXT_CACHE = new WeakMap();

function record(value) {
	return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function string(value) {
	return typeof value === "string" && value ? value : null;
}

function number(value, fallback = 0) {
	return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function integer(value, fallback, minimum, maximum) {
	const parsed = Math.trunc(number(value, fallback));
	return Math.max(minimum, Math.min(parsed, maximum));
}

function normalizeAgent(value) {
	const agent = record(value);
	const agentHandle = string(agent.agent_handle);
	if (!agentHandle || !HANDLE_PATTERN.test(agentHandle)) return null;
	return {
		...agent,
		agent_handle: agentHandle,
		parent_handle: string(agent.parent_handle),
		depth: number(agent.depth),
		agent_type: string(agent.agent_type) ?? "agent",
		session_name: string(agent.session_name) ?? agentHandle,
		model: string(agent.model) ?? "default",
		status: RUN_STATUSES.has(agent.status) ? agent.status : "idle",
		recent_activity: Array.isArray(agent.recent_activity) ? agent.recent_activity.map(record) : [],
		skills: Array.isArray(agent.skills) ? agent.skills.map(record) : [],
		task: agent.task && typeof agent.task === "object" ? agent.task : null,
	};
}

function normalizeRoot(value) {
	const root = record(value);
	const rootHandle = string(root.root_handle);
	if (!rootHandle || !HANDLE_PATTERN.test(rootHandle)) return null;
	return {
		...root,
		root_handle: rootHandle,
		session_name: string(root.session_name) ?? rootHandle,
		repo: string(root.repo) ?? "Unscoped sessions",
		worktree_label: string(root.worktree_label) ?? "protected checkout",
		branch: string(root.branch) ?? "—",
		model: string(root.model) ?? "default",
		agent_mode: string(root.agent_mode) ?? "work",
		kind: ["root", "workstream", "copilot"].includes(root.kind) ? root.kind : "root",
		live: root.live === true,
		agents: (Array.isArray(root.agents) ? root.agents : []).map(normalizeAgent).filter(Boolean),
		stages: Array.isArray(root.stages) ? root.stages.map(record) : [],
		task: root.task && typeof root.task === "object" ? root.task : null,
		agent_count: number(root.agent_count),
		stage_count: number(root.stage_count),
		agents_truncated: root.agents_truncated === true,
		stages_truncated: root.stages_truncated === true,
	};
}

export function normalizeSnapshot(value) {
	const snapshot = record(value);
	if (!Array.isArray(snapshot.roots)) throw new Error("Invalid dashboard snapshot");
	const recentRootLimitMax = integer(
		snapshot.recent_root_limit_max,
		MAX_RECENT_ROOT_LIMIT,
		DEFAULT_RECENT_ROOT_LIMIT,
		MAX_RECENT_ROOT_LIMIT,
	);
	return {
		generated_at: string(snapshot.generated_at),
		window_hours: number(snapshot.window_hours, 24),
		recent_root_limit: integer(
			snapshot.recent_root_limit,
			DEFAULT_RECENT_ROOT_LIMIT,
			DEFAULT_RECENT_ROOT_LIMIT,
			recentRootLimitMax,
		),
		recent_root_limit_max: recentRootLimitMax,
		roots_truncated: snapshot.roots_truncated === true,
		roots: snapshot.roots.map(normalizeRoot).filter(Boolean),
	};
}

export function nextRecentRootLimit(current, maximum = MAX_RECENT_ROOT_LIMIT) {
	const safeMaximum = integer(maximum, MAX_RECENT_ROOT_LIMIT, DEFAULT_RECENT_ROOT_LIMIT, MAX_RECENT_ROOT_LIMIT);
	const safeCurrent = integer(current, DEFAULT_RECENT_ROOT_LIMIT, DEFAULT_RECENT_ROOT_LIMIT, safeMaximum);
	return Math.min(safeMaximum, safeCurrent + RECENT_ROOT_STEP);
}

export function canLoadMoreRoots(snapshot, current) {
	return snapshot?.roots_truncated === true && current < snapshot.recent_root_limit_max;
}

export function rootLoaderMode(snapshot, current, loading, connection) {
	if (!snapshot?.roots_truncated) return current > DEFAULT_RECENT_ROOT_LIMIT ? "complete" : "hidden";
	if (loading || current > snapshot.recent_root_limit) {
		if (connection === "busy") return "busy";
		if (connection === "offline") return "offline";
		return "loading";
	}
	return canLoadMoreRoots(snapshot, current) ? "more" : "limit";
}

export function snapshotFailureState(status, hasSnapshot) {
	if (status === 429) return hasSnapshot ? "busy" : "loading";
	return "offline";
}

export function uniqueValues(values) {
	return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

export function contextsForRoot(root) {
	const cached = CONTEXT_CACHE.get(root);
	if (cached) return cached;
	const byHandle = new Map(root.agents.map((agent) => [agent.agent_handle, agent]));
	const children = new Map();
	const treeRoots = [];
	for (const agent of root.agents) {
		const parent = byHandle.get(agent.parent_handle);
		if (parent && parent !== agent) {
			const siblings = children.get(parent.agent_handle) ?? [];
			siblings.push(agent);
			children.set(parent.agent_handle, siblings);
		} else {
			treeRoots.push(agent);
		}
	}

	const contexts = [];
	const visited = new Set();
	function walk(agent, ancestors, visiting) {
		if (visited.has(agent.agent_handle) || visiting.has(agent.agent_handle)) return;
		const nextVisiting = new Set(visiting).add(agent.agent_handle);
		contexts.push({
			agent,
			parent: ancestors.at(-1)?.agent ?? null,
			depth: ancestors.length,
			ancestors: ancestors.map((context) => context.agent),
		});
		visited.add(agent.agent_handle);
		const context = contexts.at(-1);
		for (const child of children.get(agent.agent_handle) ?? []) {
			walk(child, [...ancestors, context], nextVisiting);
		}
	}

	for (const agent of treeRoots) walk(agent, [], new Set());
	for (const agent of root.agents) walk(agent, [], new Set());
	CONTEXT_CACHE.set(root, contexts);
	return contexts;
}

export function findAgentContext(root, agentHandle) {
	return contextsForRoot(root).find(({ agent }) => agent.agent_handle === agentHandle) ?? null;
}

export function descendantContexts(root, agentHandle) {
	return contextsForRoot(root).filter(({ ancestors }) => ancestors.some((agent) => agent.agent_handle === agentHandle));
}

export function agentMatches(agent, filters) {
	return (
		(filters.status === "all" || agent.status === filters.status) &&
		(filters.type === "all" || agent.agent_type === filters.type)
	);
}

export function agentFiltersActive(filters) {
	return filters.status !== "all" || filters.type !== "all";
}

export function matchingContexts(root, filters) {
	return contextsForRoot(root).filter(({ agent }) => agentMatches(agent, filters));
}

export function visibleContexts(root, filters) {
	const contexts = contextsForRoot(root);
	if (!agentFiltersActive(filters)) return contexts.map((context) => ({ ...context, contextOnly: false }));
	const matches = contexts.filter(({ agent }) => agentMatches(agent, filters));
	const visible = new Set();
	for (const context of matches) {
		visible.add(context.agent.agent_handle);
		for (const ancestor of context.ancestors) visible.add(ancestor.agent_handle);
	}
	return contexts
		.filter(({ agent }) => visible.has(agent.agent_handle))
		.map((context) => ({ ...context, contextOnly: !agentMatches(context.agent, filters) }));
}

export function rootMatches(root, filters) {
	if (filters.repo !== "all" && root.repo !== filters.repo) return false;
	if (filters.worktree !== "all" && root.worktree_label !== filters.worktree) return false;
	if (filters.kind !== "all" && root.kind !== filters.kind) return false;
	if (filters.liveOnly && !root.live) return false;
	if (agentFiltersActive(filters) && matchingContexts(root, filters).length === 0) return false;
	return true;
}

export function visibleRoots(snapshot, filters) {
	return snapshot?.roots.filter((root) => rootMatches(root, filters)) ?? [];
}

export function stagesForRoot(root) {
	if (root.stages.length) return root.stages;
	if (!root.task) return [];
	return [
		{
			index: 0,
			goal: root.task.goal,
			active: true,
			archived_at: null,
			agent_mode: root.agent_mode,
			progress: root.task.progress ?? { completed: 0, deleted: 0, total: 0 },
			tasks: root.task.task_plan ?? [],
			tasks_truncated: false,
		},
	];
}

export function defaultStageIndex(root) {
	const stages = stagesForRoot(root);
	return stages.find((stage) => stage.active)?.index ?? stages.at(-1)?.index ?? null;
}

export function selectedStage(root, index) {
	const stages = stagesForRoot(root);
	return stages.find((stage) => stage.index === index) ?? stages.find((stage) => stage.active) ?? stages.at(-1) ?? null;
}

export function assignment(agent) {
	return (
		string(agent.task?.current_task?.label) ??
		string(agent.task?.task_plan?.find((task) => task.status === "active")?.label) ??
		string(agent.session_name) ??
		"No active assignment"
	);
}

export function agentSummary(agent) {
	return (
		string(agent.task?.current_task?.description) ??
		(agent.status === "failed" ? string(agent.error_preview) : string(agent.result_preview)) ??
		string(agent.recent_activity.at(-1)?.snippet) ??
		"No additional run context is available."
	);
}

export function activityText(activity) {
	return (
		string(activity.snippet) ??
		string(activity.label) ??
		string(activity.toolName) ??
		string(activity.category) ??
		"Activity recorded"
	);
}

export function currentGoal(root) {
	return (
		string(root.task?.goal) ?? string(selectedStage(root, defaultStageIndex(root))?.goal) ?? "No active goal recorded."
	);
}

export function progressPercent(progress) {
	const total = number(progress?.total);
	return total > 0 ? Math.round((number(progress?.completed) / total) * 100) : 0;
}

export function relativeTime(timestamp, now = Date.now()) {
	const value = Date.parse(timestamp ?? "");
	if (!Number.isFinite(value)) return "—";
	const seconds = Math.max(0, Math.round((now - value) / 1000));
	if (seconds < 60) return "now";
	if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
	if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
	return `${Math.floor(seconds / 86400)}d`;
}

export function clockTime(timestamp) {
	const value = new Date(timestamp ?? "");
	if (!Number.isFinite(value.getTime())) return "—";
	return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(value);
}

export function elapsedTime(startedAt, endedAt = null, now = Date.now()) {
	const start = Date.parse(startedAt ?? "");
	const end = endedAt ? Date.parse(endedAt) : now;
	if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "—";
	const seconds = Math.floor((end - start) / 1000);
	if (seconds < 3600)
		return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
	return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function titleCase(value) {
	return String(value ?? "")
		.split(/[-_]/)
		.filter(Boolean)
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function routeFor(rootHandle, agentHandle = null) {
	const root = encodeURIComponent(rootHandle);
	return agentHandle ? `#/sessions/${root}/agents/${encodeURIComponent(agentHandle)}` : `#/sessions/${root}`;
}

export function parseRoute(hash) {
	const parts = String(hash ?? "")
		.replace(/^#\/?/, "")
		.split("/")
		.filter(Boolean);
	if (parts[0] !== "sessions" || !parts[1]) return null;
	try {
		const rootHandle = decodeURIComponent(parts[1]);
		if (!HANDLE_PATTERN.test(rootHandle)) return null;
		if (parts.length === 2) return { rootHandle, agentHandle: null };
		if (parts.length !== 4 || parts[2] !== "agents") return null;
		const agentHandle = decodeURIComponent(parts[3]);
		return HANDLE_PATTERN.test(agentHandle) ? { rootHandle, agentHandle } : null;
	} catch {
		return null;
	}
}
