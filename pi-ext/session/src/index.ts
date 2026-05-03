/**
 * Session extension — mode lifecycle, shell UI, and session title behavior.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerModeShortcut } from "./commands/mode";
import { registerSession } from "./runtime/session";
import { registerFooter } from "./ui/footer";
import { registerModeEditor } from "./ui/mode-editor";
import { registerTitle } from "./ui/title";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerSession(pi);
	registerFooter(pi);
	registerModeEditor(pi);
	registerTitle(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerModeShortcut(pi);
	}
}
