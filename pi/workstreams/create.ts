import { randomUUID } from "node:crypto";
import type { DaemonClient } from "#core/swarm/agents/client.ts";
import { defaultWorkstreamToolsDeps, errorMessage, type WorkstreamToolsDeps } from "./deps.ts";
import { parseCreateWorkstreamParams } from "./params.ts";
import { type CreateWorkstreamToolResult, failedDetails, toolResult } from "./results.ts";

const MAX_SLUG_ATTEMPTS = 25;

/**
 * create_workstream — stage a durable workstream record in the daemon (id + slug +
 * brief/label/constraints + dossier pointer). Record-only: it does not provision a
 * worktree or open a Herdr pane (that is launch_workstream) and does not start an agent.
 */
export async function executeCreateWorkstream(
	params: unknown,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<CreateWorkstreamToolResult> {
	const parsed = parseCreateWorkstreamParams(params);
	if (!parsed.ok) {
		return toolResult(
			failedDetails(parsed.message, "Call create_workstream again with non-empty required fields."),
			true,
		);
	}

	const client = await deps.getClient();
	if (!client) {
		return toolResult(
			failedDetails(
				"basecamp hub is not connected; cannot create a workstream.",
				"Ensure the daemon is running (it starts automatically for top-level sessions), then call create_workstream again.",
			),
			true,
		);
	}

	const workstreamId = `ws_${randomUUID()}`;
	let slug: string | null = null;
	let createResult: Awaited<ReturnType<DaemonClient["createWorkstream"]>> | null = null;

	for (let attempt = 0; attempt < MAX_SLUG_ATTEMPTS; attempt += 1) {
		const candidate = deps.generateWorkstreamName(() => false);
		try {
			createResult = await client.createWorkstream({
				workstreamId,
				slug: candidate,
				label: parsed.value.workstream.label,
				brief: parsed.value.workstream.brief,
				sourceDossierPath: parsed.value.source.dossierPath,
				...(parsed.value.workstream.constraints ? { constraints: parsed.value.workstream.constraints } : {}),
				...(parsed.value.source.repoPagePath ? { sourceRepoPagePath: parsed.value.source.repoPagePath } : {}),
			});
		} catch (err) {
			return toolResult(
				failedDetails(
					`Failed to create workstream in daemon: ${errorMessage(err)}`,
					"Retry create_workstream; if the error persists, check the daemon.",
				),
				true,
			);
		}
		if (createResult.status === "created") {
			slug = candidate;
			break;
		}
		if (createResult.status === "slug_conflict") continue;
		break;
	}

	if (!slug || createResult?.status !== "created") {
		return toolResult(
			failedDetails(
				`Daemon rejected workstream creation: ${createResult?.error ?? createResult?.status ?? "no unique slug"}`,
				"Inspect the daemon error (or existing workstreams) and retry create_workstream.",
			),
			true,
		);
	}

	return toolResult({
		status: "created",
		message: `Workstream "${parsed.value.workstream.label}" created as ${slug}.`,
		id: createResult.workstream_id ?? workstreamId,
		slug,
		next_step: `Stage execution with launch_workstream (workstream: "${slug}") to provision a worktree + Herdr pane, or edit_workstream to refine the brief.`,
	});
}
