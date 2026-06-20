import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./src/git/commands.ts";
import { registerGuards } from "./src/git/guards.ts";
import { registerIssueTool } from "./src/git/issue-tool.ts";
import { registerPublishSkillGuard } from "./src/git/publish-skill-guard.ts";
import { registerReviewPacketTool } from "./src/git/review-packet-tool.ts";
import { registerSafeGitTool } from "./src/git/safe-git-tool.ts";
import { registerStatusTool } from "./src/git/status.ts";
import { registerTool } from "./src/git/tool.ts";

export default function (pi: ExtensionAPI) {
	registerGuards(pi);
	registerPublishSkillGuard(pi);
	registerCommands(pi);
	registerStatusTool(pi);
	registerSafeGitTool(pi);
	registerTool(pi);
	registerIssueTool(pi);
	registerReviewPacketTool(pi);
}
