/**
 * Git publish skill guard.
 *
 * Requires workflow-specific skills before publish tools can execute.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { hasInvokedSkill } from "../../platform/skill-tracker";

function requiredSkillForTool(toolName: string): "pull-request" | "issue-logging" | null {
	if (toolName === "publish_pr") return "pull-request";
	if (toolName === "publish_issue") return "issue-logging";
	return null;
}

export function registerPublishSkillGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event) => {
		const toolName = event.toolName;
		const skillName = requiredSkillForTool(toolName);
		if (!skillName || hasInvokedSkill(skillName)) return;

		return {
			block: true,
			reason: `The ${toolName} tool requires the ${skillName} skill. Call skill({ name: "${skillName}" }) first, then retry ${toolName}.`,
		};
	});
}
