/**
 * Plan skill guard.
 *
 * Requires the planning skill before interactive main-session plan() calls.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { hasInvokedSkill } from "../../../platform/skill-tracker";

const PLANNING_SKILL = "planning";

function isSubagent(): boolean {
	return Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;
}

export function registerPlanSkillGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "plan") return;
		if (!ctx.hasUI) return;
		if (isSubagent()) return;
		if (hasInvokedSkill(PLANNING_SKILL)) return;

		return {
			block: true,
			reason: `The plan tool requires the ${PLANNING_SKILL} skill in interactive main sessions. Call skill({ name: "${PLANNING_SKILL}" }) first, then retry plan.`,
		};
	});
}
