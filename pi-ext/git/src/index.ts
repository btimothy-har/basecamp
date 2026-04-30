/**
 * Git — guards against destructive operations + PR workflow commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerCommands } from "./commands";
import { registerGuards } from "./guards";
import { registerIssueTool } from "./issue-tool";
import { registerStatusTool } from "./status";
import { registerTool } from "./tool";

export default function (pi: ExtensionAPI) {
	registerGuards(pi);
	registerCommands(pi);
	registerStatusTool(pi);
	registerTool(pi);
	registerIssueTool(pi);
}
