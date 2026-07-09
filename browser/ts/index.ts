import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { disconnectBrowser } from "./browser/connection.ts";
import { registerBrowserEvalTool } from "./tools/browser-eval.ts";
import { registerBrowserScreenshotTool } from "./tools/browser-screenshot.ts";

export default function (pi: ExtensionAPI): void {
	registerBrowserEvalTool(pi);
	registerBrowserScreenshotTool(pi);
	pi.on("session_shutdown", async () => {
		await disconnectBrowser();
	});
}
