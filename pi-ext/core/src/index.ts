/**
 * Core extension — session lifecycle, prompt assembly, worktrees, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerHandoff } from "./commands/handoff";
import { registerOpenCommand } from "./commands/open";
import { registerContextInjection } from "./prompt/context-injection";
import { registerPrompt } from "./prompt/prompt";
import { getState, registerSession } from "./runtime/session";
import { registerCoreCatalogProviders } from "./tools/catalog-providers";
import { registerDiscoverTool } from "./tools/discover";
import { registerEscalate } from "./tools/escalate/index.js";
import { registerSkillTool } from "./tools/skill";
import { registerSkillLifecycle } from "./tools/skill-tracker";
import { registerFooter } from "./ui/footer";
import { registerHeader } from "./ui/header";
import { registerTitle } from "./ui/title";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerSession(pi);
	registerSkillLifecycle(pi);
	registerCoreCatalogProviders(pi);
	registerPrompt(pi);
	registerContextInjection(pi);
	registerHeader(pi);
	registerFooter(pi);
	registerHandoff(pi);
	registerOpenCommand(pi, getState);
	registerTitle(pi);
	registerDiscoverTool(pi);
	registerSkillTool(pi);

	// Escalate surfaces decisions to the user — subagents should report
	// back to their parent instead.
	if (!isSubagent) {
		registerEscalate(pi);
	}
}
