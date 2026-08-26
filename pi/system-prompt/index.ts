import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerSystemPromptCommand } from "./command.ts";
import { registerPrompt } from "./prompt.ts";

export default function (pi: ExtensionAPI): void {
	registerPrompt(pi);
	registerSystemPromptCommand(pi);
}
