import { DEFAULT_HEALTH_TIMEOUT_MS, optionalNumber, optionalString, requestJsonOverUds } from "../../../hub/index.ts";

export interface WorkstreamAgentView {
	agent_id: string | null;
	agent_handle: string | null;
	repo: string | null;
	worktree_label: string | null;
	status: string | null;
	error: string | null;
	joined_at: string | null;
	run_status: string | null;
}

export interface WorkstreamVersionView {
	version: number | null;
	label: string | null;
	brief: string | null;
	constraints: string | null;
	created_at: string | null;
}

export interface WorkstreamSummary {
	id: string | null;
	slug: string | null;
	label: string | null;
	brief: string | null;
	constraints: string | null;
	source_dossier_path: string | null;
	source_repo_page_path: string | null;
	status: string | null;
	version: number | null;
	created_at: string | null;
	updated_at: string | null;
	agent_count: number | null;
}

export type WorkstreamDetail = WorkstreamSummary & {
	agents: WorkstreamAgentView[];
	versions: WorkstreamVersionView[];
};

function parseWorkstreamAgent(value: unknown): WorkstreamAgentView | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	return {
		agent_id: optionalString(record.agent_id),
		agent_handle: optionalString(record.agent_handle),
		repo: optionalString(record.repo),
		worktree_label: optionalString(record.worktree_label),
		status: optionalString(record.status),
		error: optionalString(record.error),
		joined_at: optionalString(record.joined_at),
		run_status: optionalString(record.run_status),
	};
}

function parseWorkstreamSummary(value: unknown): WorkstreamSummary | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	return {
		id: optionalString(record.id),
		slug: optionalString(record.slug),
		label: optionalString(record.label),
		brief: optionalString(record.brief),
		constraints: optionalString(record.constraints),
		source_dossier_path: optionalString(record.source_dossier_path),
		source_repo_page_path: optionalString(record.source_repo_page_path),
		status: optionalString(record.status),
		version: optionalNumber(record.version),
		created_at: optionalString(record.created_at),
		updated_at: optionalString(record.updated_at),
		agent_count: optionalNumber(record.agent_count),
	};
}

function parseWorkstreamVersion(value: unknown): WorkstreamVersionView | null {
	if (!value || typeof value !== "object") return null;
	const record = value as Record<string, unknown>;
	return {
		version: optionalNumber(record.version),
		label: optionalString(record.label),
		brief: optionalString(record.brief),
		constraints: optionalString(record.constraints),
		created_at: optionalString(record.created_at),
	};
}

export function buildWorkstreamsPath(filter: {
	status?: string;
	repo?: string;
	dossierPath?: string;
	query?: string;
}): string {
	const params = new URLSearchParams();
	if (filter.status !== undefined) params.set("status", filter.status);
	if (filter.repo !== undefined) params.set("repo", filter.repo);
	if (filter.dossierPath !== undefined) params.set("dossier_path", filter.dossierPath);
	if (filter.query !== undefined) params.set("query", filter.query);
	const query = params.toString();
	return query ? `/workstreams?${query}` : "/workstreams";
}

export function parseWorkstreamsResponse(parsed: unknown): WorkstreamSummary[] | null {
	if (!parsed || typeof parsed !== "object") return null;
	const record = parsed as Record<string, unknown>;
	const rawWorkstreams = Array.isArray(record.workstreams) ? record.workstreams : [];
	return rawWorkstreams.map(parseWorkstreamSummary).filter((item): item is WorkstreamSummary => item !== null);
}

export function parseWorkstreamDetailResponse(parsed: unknown): WorkstreamDetail | null {
	const summary = parseWorkstreamSummary(parsed);
	if (!summary) return null;
	const record = (parsed as Record<string, unknown>) ?? {};
	const rawAgents = Array.isArray(record.agents) ? record.agents : [];
	const agents = rawAgents.map(parseWorkstreamAgent).filter((agent): agent is WorkstreamAgentView => agent !== null);
	const rawVersions = Array.isArray(record.versions) ? record.versions : [];
	const versions = rawVersions
		.map(parseWorkstreamVersion)
		.filter((version): version is WorkstreamVersionView => version !== null);
	return { ...summary, agents, versions };
}

export async function listWorkstreams(
	socketPath: string,
	filter: { status?: string; repo?: string; dossierPath?: string; query?: string },
	timeoutMs = DEFAULT_HEALTH_TIMEOUT_MS,
): Promise<WorkstreamSummary[] | null> {
	const parsed = await requestJsonOverUds(socketPath, buildWorkstreamsPath(filter), timeoutMs);
	return parseWorkstreamsResponse(parsed);
}

export async function getWorkstream(
	socketPath: string,
	identifier: string,
	timeoutMs = DEFAULT_HEALTH_TIMEOUT_MS,
): Promise<WorkstreamDetail | null> {
	const parsed = await requestJsonOverUds(socketPath, `/workstreams/${encodeURIComponent(identifier)}`, timeoutMs);
	return parseWorkstreamDetailResponse(parsed);
}
