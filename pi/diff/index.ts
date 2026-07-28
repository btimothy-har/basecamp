import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerAnnotateTool } from "./annotate-tool.ts";
import { registerDiffCommand } from "./command.ts";
import { registerRemoveTool } from "./remove-tool.ts";

export default function (pi: ExtensionAPI): void {
	registerDiffCommand(pi);
	registerAnnotateTool(pi);
	registerRemoveTool(pi);
}
