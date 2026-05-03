import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { resetAgentMode } from "./mode";

export function registerSession(pi: ExtensionAPI): void {
	pi.on("session_start", async () => {
		resetAgentMode();
	});
}
