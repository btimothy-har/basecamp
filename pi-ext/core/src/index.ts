/**
 * Core extension — session lifecycle, prompt assembly, worktrees, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerContextInjection } from "./context-injection";
import { registerDiscoverTool } from "./discover";
import { registerEscalate } from "./escalate";
import { registerFooter } from "./footer";
import { registerHandoff } from "./handoff";
import { registerHeader } from "./header";
import { registerOpenCommand } from "./open";
import { registerPrompt } from "./prompt";
import { getState, registerSession } from "./session";
import { registerTitle } from "./title";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerSession(pi);
	registerPrompt(pi);
	registerContextInjection(pi);
	registerHeader(pi);
	registerFooter(pi);
	registerHandoff(pi);
	registerOpenCommand(pi, getState);
	registerTitle(pi);
	registerDiscoverTool(pi);

	// Escalate surfaces decisions to the user — subagents should report
	// back to their parent instead.
	if (!isSubagent) {
		registerEscalate(pi);
	}
}
