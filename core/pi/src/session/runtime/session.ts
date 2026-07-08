import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { restoreAgentModeFromSessionState, setAgentMode } from "../agent-mode.ts";
import { setCopilotLaunchReader } from "../copilot-launch.ts";

export function registerSession(pi: ExtensionAPI): void {
	pi.registerFlag("copilot", {
		description: "Start a locked repo-copilot session (immutable mode; cannot be changed via shift+tab).",
		type: "boolean",
	});
	// Sole owner of --copilot; other packages read the launch value via isCopilotLaunch().
	setCopilotLaunchReader(() => pi.getFlag("copilot") !== undefined);

	pi.on("session_start", async () => {
		if (pi.getFlag("copilot") !== undefined) {
			setAgentMode("copilot");
			return;
		}

		restoreAgentModeFromSessionState();
	});
}
