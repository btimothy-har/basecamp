import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { disconnectBrowser } from "./src/browser/connection.ts";
import { registerBrowserEvalTool } from "./src/tools/browser-eval.ts";
import { registerBrowserScreenshotTool } from "./src/tools/browser-screenshot.ts";

export default function (pi: ExtensionAPI): void {
	registerBrowserEvalTool(pi);
	registerBrowserScreenshotTool(pi);
	pi.on("session_shutdown", async () => {
		await disconnectBrowser();
	});
}
