import type { DaemonClient } from "#core/swarm/agents/client.ts";
import { defaultWorkstreamToolsDeps, errorMessage, type WorkstreamToolsDeps } from "./deps.ts";
import { parseEditWorkstreamParams } from "./params.ts";
import { resolveWorkstreamDetail } from "./resolve.ts";
import { type EditWorkstreamToolResult, toolResult } from "./results.ts";

function failed(
	message: string,
	nextStep: string,
	status: "not_found" | "failed" = "failed",
): EditWorkstreamToolResult {
	return toolResult({ status, message, next_step: nextStep }, true);
}

/**
 * edit_workstream — revise an existing workstream's content in place, bumping its
 * version and retaining the prior version. Identity (id/slug), dossier pointer,
 * worktree, and attached agents are unchanged. Record-only: no worktree or pane.
 */
export async function executeEditWorkstream(
	params: unknown,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<EditWorkstreamToolResult> {
	const parsed = parseEditWorkstreamParams(params);
	if (!parsed.ok) {
		return failed(
			parsed.message,
			"Call edit_workstream again with a workstream id/slug and at least one field to change.",
		);
	}

	const client = await deps.getClient();
	if (!client) {
		return failed(
			"basecamp hub is not connected; cannot edit a workstream.",
			"Ensure the daemon is running, then call edit_workstream again.",
		);
	}

	const identifier = parsed.value.workstream;
	const resolved = await resolveWorkstreamDetail(deps, identifier);
	if (!resolved.ok) {
		return resolved.reason === "error"
			? failed(
					`Could not resolve workstream "${identifier}": ${resolved.message}`,
					"Check the id or slug with list_workstreams, then call edit_workstream again.",
				)
			: failed(
					resolved.message,
					"Use list_workstreams to find the correct id or slug, then call edit_workstream again.",
					"not_found",
				);
	}
	const detail = resolved.detail;

	// reviseWorkstream writes a full new version; carry forward any field not being changed.
	const label = parsed.value.label ?? detail.label ?? detail.slug;
	const brief = parsed.value.brief ?? detail.brief ?? "";
	const constraints = parsed.value.constraints ?? detail.constraints ?? null;

	let result: Awaited<ReturnType<DaemonClient["reviseWorkstream"]>>;
	try {
		result = await client.reviseWorkstream({
			workstream: detail.id ?? identifier,
			label,
			brief,
			constraints,
		});
	} catch (err) {
		return failed(
			`Could not edit workstream: ${errorMessage(err)}`,
			"Retry edit_workstream; if the error persists, check the daemon.",
		);
	}

	if (result.status === "revised") {
		return toolResult({
			status: "edited",
			message: `Workstream "${detail.label ?? detail.slug}" revised to version ${result.version}. The prior version is retained.`,
			id: detail.id ?? undefined,
			slug: detail.slug,
			version: result.version,
			next_step:
				"The change takes effect the next time an agent runs `pi --workstream`; a running agent keeps its brief until you reach out (ask_agent) or it restarts.",
		});
	}
	if (result.status === "not_found") {
		return failed(
			`No workstream found for "${identifier}".`,
			"Use list_workstreams to find the correct id or slug, then call edit_workstream again.",
			"not_found",
		);
	}
	return failed(
		`Daemon rejected the edit: ${result.error ?? result.status}`,
		"Check the daemon error and retry edit_workstream.",
	);
}
