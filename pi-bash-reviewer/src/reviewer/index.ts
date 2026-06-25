import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";

export function registerBashReviewer(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, _ctx) => {
		if (!isToolCallEventType("bash", event)) return;
	});
}
