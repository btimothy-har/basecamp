/**
 * Copilot plan guard.
 *
 * Hard-blocks the plan() tool in copilot sessions. Copilot stages work via
 * launch_workstream and never implements in-session. Registered before the
 * plan-skill guard so the copilot-specific reason is the message the agent
 * sees, rather than the generic "invoke the planning skill" one.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getAgentMode } from "pi-core/session/agent-mode.ts";

export function registerPlanCopilotGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event) => {
		if (event.toolName !== "plan") return;
		if (getAgentMode() !== "copilot") return;
		return {
			block: true,
			reason: "plan() is disabled in copilot sessions — stage work with launch_workstream instead.",
		};
	});
}
