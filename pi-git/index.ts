import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./src/git/commands.ts";
import { registerReviewPacketTool } from "./src/git/review-packet-tool.ts";

export default function (pi: ExtensionAPI) {
	registerCommands(pi);
	registerReviewPacketTool(pi);
}
