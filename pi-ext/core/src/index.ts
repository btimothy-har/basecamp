/**
 * Core extension — session lifecycle, prompt assembly, worktrees, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerModeShortcut } from "./commands/mode";
import { registerContextInjection } from "./prompt/context-injection";
import { registerSession } from "./runtime/session";
import { registerBqQueryTool } from "./tools/bq-query";
import { registerCoreCatalogProviders } from "./tools/catalog-providers";
import { registerEscalate } from "./tools/escalate/index.js";
import { registerSkillTool } from "./tools/skill";
import { registerSkillLifecycle } from "./tools/skill-tracker";
import { registerFooter } from "./ui/footer";
import { registerModeEditor } from "./ui/mode-editor";
import { registerTitle } from "./ui/title";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerSession(pi);
	registerSkillLifecycle(pi);
	registerCoreCatalogProviders(pi);
	registerContextInjection(pi);
	registerFooter(pi);
	registerModeEditor(pi);
	registerTitle(pi);
	registerSkillTool(pi);
	registerBqQueryTool(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerModeShortcut(pi);
		registerEscalate(pi);
	}
}
