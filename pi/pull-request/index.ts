import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";

const pullRequestDir = path.dirname(fileURLToPath(import.meta.url));
export const pullRequestSkillPath = path.join(pullRequestDir, "skills", "pull-request", "SKILL.md");

/** Expose the pull-request lifecycle skill only to user-facing primary sessions. */
export default function registerPullRequest(pi: ExtensionAPI): void {
	if (!isSubagent()) {
		pi.on("resources_discover", () => ({ skillPaths: [pullRequestSkillPath] }));
	}
}
