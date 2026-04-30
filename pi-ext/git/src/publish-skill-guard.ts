/**
 * Git publish skill guard.
 *
 * Requires workflow-specific skills before publish tools can execute.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { hasInvokedSkill } from "../../platform/skill-tracker";

function requiredSkillForTool(toolName: string): "create-pr" | "create-issue" | null {
	if (toolName === "pr_publish") return "create-pr";
	if (toolName === "issue_publish") return "create-issue";
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
