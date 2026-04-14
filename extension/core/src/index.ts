/**
 * Core extension — session lifecycle, prompt assembly, worktrees, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerSession } from "./session";
import { registerPrompt } from "./prompt";
import { registerHandoff } from "./handoff";
import { registerOpenCommand } from "./open";
import { getState } from "./session";

export default function (pi: ExtensionAPI) {
	registerSession(pi);
	registerPrompt(pi);
	registerHandoff(pi);
	registerOpenCommand(pi, getState);
}
