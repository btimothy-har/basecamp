import type { DaemonClient } from "../agents/daemon/client.ts";
import { defaultWorkstreamToolsDeps, errorMessage, type WorkstreamToolsDeps } from "./deps.ts";
import { parseSetWorkstreamStatusParams } from "./params.ts";
import { type SetWorkstreamStatusToolResult, statusTextResult } from "./results.ts";

export async function executeSetWorkstreamStatus(
	params: unknown,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<SetWorkstreamStatusToolResult> {
	const parsed = parseSetWorkstreamStatusParams(params);
	if (!parsed.ok) {
		return statusTextResult(
			{
				status: "failed",
				message: parsed.message,
				workstream: "",
				next_step: "Call set_workstream_status again with a workstream id/slug and status 'open' or 'closed'.",
			},
			true,
		);
	}

	const client = await deps.getClient();
	if (!client) {
		return statusTextResult(
			{
				status: "failed",
				message: "basecamp hub is not connected; cannot update workstream status.",
				workstream: parsed.value.workstream,
				next_step: "Ensure the daemon is running, then call set_workstream_status again.",
			},
			true,
		);
	}

	let result: Awaited<ReturnType<DaemonClient["updateWorkstream"]>>;
	try {
		result = await client.updateWorkstream({
			workstream: parsed.value.workstream,
			status: parsed.value.status,
		});
	} catch (err) {
		return statusTextResult(
			{
				status: "failed",
				message: `Could not update workstream status: ${errorMessage(err)}`,
				workstream: parsed.value.workstream,
				next_step: "Retry set_workstream_status; if the error persists, check the daemon.",
			},
			true,
		);
	}

	if (result.status === "updated") {
		return statusTextResult({
			status: "updated",
			message: `Workstream "${parsed.value.workstream}" is now ${parsed.value.status}.`,
			workstream: parsed.value.workstream,
			next_step: "Use list_workstreams to verify the updated status.",
		});
	}
	if (result.status === "not_found") {
		return statusTextResult(
			{
				status: "not_found",
				message: `No workstream found for "${parsed.value.workstream}".`,
				workstream: parsed.value.workstream,
				next_step: "Use list_workstreams to find the correct id or slug, then call set_workstream_status again.",
			},
			true,
		);
	}
	if (result.status === "invalid_status") {
		return statusTextResult(
			{
				status: "invalid_status",
				message: `Status "${parsed.value.status}" is not valid for this workstream.`,
				workstream: parsed.value.workstream,
				next_step: "Use 'open' or 'closed' as the status.",
			},
			true,
		);
	}
	return statusTextResult(
		{
			status: "failed",
			message: `Daemon rejected status update: ${result.error ?? result.status}`,
			workstream: parsed.value.workstream,
			next_step: "Check the daemon error and retry set_workstream_status.",
		},
		true,
	);
}
