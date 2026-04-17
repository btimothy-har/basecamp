/**
 * Core extension — session lifecycle, prompt assembly, worktrees, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerFooter } from "./footer";
import { registerHandoff } from "./handoff";
import { registerOpenCommand } from "./open";
import { registerPrompt } from "./prompt";
import { getState, registerSession } from "./session";

export default function (pi: ExtensionAPI) {
	registerSession(pi);
	registerPrompt(pi);
	registerFooter(pi);
	registerHandoff(pi);
	registerOpenCommand(pi, getState);
}
