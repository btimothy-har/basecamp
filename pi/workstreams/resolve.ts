import type { WorkstreamDetail } from "#core/swarm/agents/client.ts";
import { errorMessage, type WorkstreamToolsDeps } from "./deps.ts";

export type ResolveWorkstreamResult =
	| { ok: true; detail: WorkstreamDetail & { slug: string } }
	| { ok: false; reason: "error" | "not_found"; message: string };

/**
 * Resolve a workstream by id/slug over the daemon socket, normalizing the two
 * failure modes (lookup threw vs. no such workstream). Shared by edit_workstream
 * and launch_workstream, which map the failure to their own tool-specific next steps.
 */
export async function resolveWorkstreamDetail(
	deps: WorkstreamToolsDeps,
	identifier: string,
): Promise<ResolveWorkstreamResult> {
	const socketPath = deps.resolveSocketPath();
	let detail: WorkstreamDetail | null;
	try {
		detail = await deps.getWorkstreamDetail(socketPath, identifier);
	} catch (err) {
		return { ok: false, reason: "error", message: errorMessage(err) };
	}
	if (!detail?.slug) {
		return { ok: false, reason: "not_found", message: `No workstream found for "${identifier}".` };
	}
	return { ok: true, detail: detail as WorkstreamDetail & { slug: string } };
}
