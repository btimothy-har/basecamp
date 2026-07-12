import { buildAgentHandle } from "#core/hub/index.ts";
import type { DaemonClient, DaemonDispatchFrameOptions, DaemonDispatchResult } from "./client.ts";

export async function dispatchWithHandleRetry(
	daemonClient: Pick<DaemonClient, "dispatchAgent">,
	buildParams: (agentHandle: string) => DaemonDispatchFrameOptions,
	opts: { initialHandle: string; attempts: number },
): Promise<{ agentHandle: string; result: DaemonDispatchResult | null }> {
	let agentHandle = opts.initialHandle;
	let result: DaemonDispatchResult | null = null;
	for (let attempt = 0; attempt < opts.attempts; attempt++) {
		result = await daemonClient.dispatchAgent(buildParams(agentHandle));
		if (result.status !== "rejected" || result.reason !== "duplicate_agent_handle" || attempt === opts.attempts - 1)
			break;
		agentHandle = buildAgentHandle();
	}
	return { agentHandle, result };
}
