import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isCopilotLaunch } from "#core/agent-mode/copilot.ts";
import { awaitDaemonConnection } from "#core/hub/index.ts";
import { resolveAgentDepthState } from "#core/swarm/agents/types.ts";
import { registerWorkstreamStartup } from "./start.ts";
import { registerWorkstreamTools } from "./tools.ts";

/**
 * The workstreams feature domain — durable, repo-neutral coordination state for
 * copilot-staged work, built on the swarm primitive (`#core/swarm`). Shaping and
 * staging workstreams is the copilot's job, so the tools register only for copilot
 * sessions; the `pi --workstream` startup attaches any top-level session as an
 * additive workstream agent.
 *
 * Registration-time gating is sound because copilot is launch-only and immutable:
 * the mode cannot change mid-session, so an unregistered tool can never become
 * callable later. That is why these tools need no call-time block, unlike plan().
 */
export default function registerWorkstreams(pi: ExtensionAPI): void {
	const { isTopLevel, atMaxDepth } = resolveAgentDepthState();

	if (isTopLevel && !atMaxDepth && isCopilotLaunch()) {
		registerWorkstreamTools(pi, awaitDaemonConnection);
	}
	if (isTopLevel) {
		registerWorkstreamStartup(pi, awaitDaemonConnection);
	}
}
