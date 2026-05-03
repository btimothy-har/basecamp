/**
 * Core extension — shared tools, catalog providers, and context injection.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerContextInjection } from "./prompt/context-injection";
import { registerBqQueryTool } from "./tools/bq-query";
import { registerCoreCatalogProviders } from "./tools/catalog-providers";
import { registerEscalate } from "./tools/escalate/index.js";
import { registerSkillTool } from "./tools/skill";
import { registerSkillLifecycle } from "./tools/skill-tracker";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerSkillLifecycle(pi);
	registerCoreCatalogProviders(pi);
	registerContextInjection(pi);
	registerSkillTool(pi);
	registerBqQueryTool(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerEscalate(pi);
	}
}
