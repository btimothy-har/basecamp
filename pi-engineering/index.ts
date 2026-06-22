import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { disconnectBrowser } from "./src/browser/connection.ts";
import { registerBqQueryTool } from "./src/tools/bq-query.ts";
import { registerBrowserEvalTool } from "./src/tools/browser-eval.ts";
import { registerBrowserScreenshotTool } from "./src/tools/browser-screenshot.ts";

export default function (pi: ExtensionAPI): void {
	registerBqQueryTool(pi);
	registerBrowserEvalTool(pi);
	registerBrowserScreenshotTool(pi);

	pi.on("session_shutdown", async () => {
		await disconnectBrowser();
	});
}
