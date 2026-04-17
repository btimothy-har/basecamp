/**
 * Core extension — session lifecycle, prompt assembly, worktrees, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerContextInjection } from "./context-injection";
import { registerFooter } from "./footer";
import { registerHandoff } from "./handoff";
import { registerHeader } from "./header";
import { registerOpenCommand } from "./open";
import { registerPrompt } from "./prompt";
import { getState, registerSession } from "./session";
import { registerTracker } from "./tracker";

export default function (pi: ExtensionAPI) {
	registerSession(pi);
	registerPrompt(pi);
	registerContextInjection(pi);
	registerHeader(pi);
	registerFooter(pi);
	registerHandoff(pi);
	registerOpenCommand(pi, getState);
	registerTracker(pi);
}
