import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isCopilotLaunch } from "#core/agent-mode/copilot.ts";
import { restoreAgentModeFromSessionState, setAgentMode } from "#core/agent-mode/index.ts";

export function registerSession(pi: ExtensionAPI): void {
	// Declared here so Pi's parser accepts --copilot; the value is read from argv by
	// isCopilotLaunch(), because Pi applies flag values only after extensions load.
	pi.registerFlag("copilot", {
		description: "Start a locked repo-copilot session (immutable mode; cannot be changed via shift+tab).",
		type: "boolean",
	});

	pi.on("session_start", async () => {
		if (isCopilotLaunch()) {
			setAgentMode("copilot");
			return;
		}

		restoreAgentModeFromSessionState();
	});
}
