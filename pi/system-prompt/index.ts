import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerPrompt } from "./prompt.ts";

export default function (pi: ExtensionAPI): void {
	registerPrompt(pi);
}
