import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { resetAgentMode } from "../../../platform/session";

export function registerSession(pi: ExtensionAPI): void {
	pi.on("session_start", async () => {
		resetAgentMode();
	});
}
