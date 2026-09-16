import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerAnnotationTools from "./annotation-tools.ts";
import registerDiffCommand from "./command.ts";
import registerReadDiffTool from "./read-tool.ts";

/** Register OMP's local diff tools and transactional Hunk review command. */
export default function registerDiff(pi: ExtensionAPI): void {
	registerReadDiffTool(pi);
	registerAnnotationTools(pi);
	registerDiffCommand(pi);
}
