import type { WorkstreamAgentView, WorkstreamSummary } from "../agents/client.ts";
import { defaultWorkstreamToolsDeps, errorMessage, type WorkstreamToolsDeps } from "./deps.ts";
import { parseListWorkstreamsParams } from "./params.ts";
import { type ListWorkstreamsToolResult, listTextResult } from "./results.ts";

export async function executeListWorkstreams(
	params: unknown,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<ListWorkstreamsToolResult> {
	const parsed = parseListWorkstreamsParams(params);
	const socketPath = deps.resolveSocketPath();

	// Single-identifier lookup: if query is an exact slug or id, fetch the detail with agents view
	if (parsed.query && !parsed.status && !parsed.repo && !parsed.dossierPath) {
		try {
			const detail = await deps.getWorkstreamDetail(socketPath, parsed.query);
			if (detail) {
				return listTextResult({
					status: "ok",
					message: `Found workstream ${detail.slug ?? detail.id}.`,
					count: 1,
					workstreams: [detail],
					workstream: detail,
					next_step: formatAgentsNextStep(detail.agents),
				});
			}
		} catch {
			// fall through to list
		}
	}

	let summaries: WorkstreamSummary[] | null;
	try {
		summaries = await deps.listWorkstreamSummaries(socketPath, {
			...(parsed.status ? { status: parsed.status } : {}),
			...(parsed.repo ? { repo: parsed.repo } : {}),
			...(parsed.dossierPath ? { dossierPath: parsed.dossierPath } : {}),
			...(parsed.query ? { query: parsed.query } : {}),
		});
	} catch (err) {
		return listTextResult(
			{
				status: "failed",
				message: `Could not list workstreams: ${errorMessage(err)}`,
				count: 0,
				workstreams: [],
				next_step: "Ensure the daemon is running, then call list_workstreams again.",
			},
			true,
		);
	}

	if (summaries === null) {
		return listTextResult(
			{
				status: "failed",
				message: "basecamp hub is not connected; cannot list workstreams.",
				count: 0,
				workstreams: [],
				next_step:
					"Ensure the daemon is running (it starts automatically for top-level sessions), then call list_workstreams again.",
			},
			true,
		);
	}

	return listTextResult({
		status: "ok",
		message: `Found ${summaries.length} workstream${summaries.length === 1 ? "" : "s"}.`,
		count: summaries.length,
		workstreams: summaries,
		next_step:
			"For a single workstream's agents view, pass its slug or id as the query parameter. Use set_workstream_status to open or close a workstream.",
	});
}

function formatAgentsNextStep(agents: WorkstreamAgentView[]): string {
	if (agents.length === 0) {
		return "No agents are attached to this workstream yet. Run pi --workstream=<slug> in the workstream worktree to attach.";
	}
	const handles = agents
		.filter((a) => a.agent_handle)
		.map((a) => a.agent_handle)
		.join(", ");
	return `Attached agents: ${handles}. Use message_agent or ask_agent to reach them by handle.`;
}
