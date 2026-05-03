/**
 * Core extension — context injection, BigQuery tool, and primary-only escalation.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerContextInjection } from "./prompt/context-injection";
import { registerBqQueryTool } from "./tools/bq-query";
import { registerEscalate } from "./tools/escalate/index.js";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerContextInjection(pi);
	registerBqQueryTool(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerEscalate(pi);
	}
}
