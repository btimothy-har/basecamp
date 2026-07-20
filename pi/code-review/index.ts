import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import { registerReviewTool } from "./tools.ts";

const codeReviewDir = path.dirname(fileURLToPath(import.meta.url));
export const codeReviewSkillPath = path.join(codeReviewDir, "skills", "code-review", "SKILL.md");

/**
 * The code-review feature domain — a user-invoked, independent multi-agent review of the current
 * branch. The top-level session runs the `code-review` skill (hidden from the model; invoked with
 * `/skill:code-review`), which dispatches the reviewer specialists via the swarm dispatch tools and
 * calls the `report_findings` tool to compute the verdict, open the annotation pane, and persist the
 * review packet. The domain owns no orchestration: the skill drives it, and `report_findings` is the
 * only tool. The skill is exposed primary-only (never in subagents) via `resources_discover`.
 */
export default function registerCodeReview(pi: ExtensionAPI): void {
	registerReviewTool(pi);
	if (!isSubagent()) {
		pi.on("resources_discover", () => ({ skillPaths: [codeReviewSkillPath] }));
	}
}
