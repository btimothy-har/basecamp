import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { restoreAgentModeFromSessionState } from "../agent-mode.ts";

export function registerSession(pi: ExtensionAPI): void {
	pi.on("session_start", async () => {
		restoreAgentModeFromSessionState();
	});
}
