/**
 * Copilot plan guard.
 *
 * Hard-blocks the plan() tool in copilot sessions. Copilot stages work via
 * launch_workstream and never implements in-session. Registered before the
 * plan-skill guard so the copilot-specific reason is the message the agent
 * sees, rather than the generic "invoke the planning skill" one.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type AgentMode, getAgentMode } from "#core/agent-mode/index.ts";

export const PLAN_TOOL_NAME = "plan";

/**
 * The single definition of "plan() is unavailable in this mode" — consumed by
 * this guard (the hard block) and by workspace's capabilities index (which
 * filters the catalog entry so copilot prompts never mention plan()).
 */
export function isPlanDisabledFor(mode: AgentMode): boolean {
	return mode === "copilot";
}

export function registerPlanCopilotGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event) => {
		if (event.toolName !== PLAN_TOOL_NAME) return;
		if (!isPlanDisabledFor(getAgentMode())) return;
		return {
			block: true,
			reason: "plan() is disabled in copilot sessions — stage work with launch_workstream instead.",
		};
	});
}
