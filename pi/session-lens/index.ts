import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerSessionLensCommands } from "./commands.ts";

export default function registerSessionLens(pi: ExtensionAPI): void {
	registerSessionLensCommands(pi);
}
