import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import { registerReviewTool } from "./tools.ts";

const codeReviewDir = path.dirname(fileURLToPath(import.meta.url));
export const codeReviewPromptPath = path.join(codeReviewDir, "prompts", "code-review.md");
export const codeReviewSkillPath = path.join(codeReviewDir, "skills", "code-review", "SKILL.md");

/**
 * The code-review feature domain — an explicit `/code-review` prompt starts an independent review,
 * while the model-invocable skill owns the method and `report_findings` owns result delivery.
 *
 * All three surfaces are primary-only. Only the review chair calls `report_findings`; dispatched
 * reviewer lenses return reports and never need the prompt, skill, or result tool.
 */
export default function registerCodeReview(pi: ExtensionAPI): void {
	if (!isSubagent()) {
		registerReviewTool(pi);
		pi.on("resources_discover", () => ({
			promptPaths: [codeReviewPromptPath],
			skillPaths: [codeReviewSkillPath],
		}));
	}
}
