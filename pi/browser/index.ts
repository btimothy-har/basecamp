import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { disconnectBrowser } from "./chrome.ts";
import { registerBrowserEvalTool } from "./tools/eval.ts";
import { registerBrowserScreenshotTool } from "./tools/screenshot.ts";

export default function (pi: ExtensionAPI): void {
	registerBrowserEvalTool(pi);
	registerBrowserScreenshotTool(pi);
	pi.on("session_shutdown", async () => {
		await disconnectBrowser();
	});
}
