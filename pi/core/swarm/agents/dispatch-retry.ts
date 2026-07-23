import { buildAgentHandle } from "../../hub/index.ts";
import type { DaemonClient, DaemonDispatchFrameOptions, DaemonDispatchResult } from "./client.ts";

/**
 * Owns the duplicate-handle retry policy for daemon dispatch. `buildParams` runs per
 * attempt (it may provision per-handle resources — deliverable branches are handle-keyed),
 * and `onRetry` runs after a duplicate rejection so the caller can discard those resources
 * before the next attempt mints a new handle.
 */
export async function dispatchWithHandleRetry(
	daemonClient: Pick<DaemonClient, "dispatchAgent">,
	buildParams: (agentHandle: string) => DaemonDispatchFrameOptions | Promise<DaemonDispatchFrameOptions>,
	opts: { initialHandle: string; attempts: number; onRetry?: (rejectedHandle: string) => void | Promise<void> },
): Promise<{ agentHandle: string; result: DaemonDispatchResult | null }> {
	let agentHandle = opts.initialHandle;
	let result: DaemonDispatchResult | null = null;
	for (let attempt = 0; attempt < opts.attempts; attempt++) {
		result = await daemonClient.dispatchAgent(await buildParams(agentHandle));
		if (result.status !== "rejected" || result.reason !== "duplicate_agent_handle" || attempt === opts.attempts - 1)
			break;
		await opts.onRetry?.(agentHandle);
		agentHandle = buildAgentHandle();
	}
	return { agentHandle, result };
}
