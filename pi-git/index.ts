import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./src/git/commands.ts";

export default function (pi: ExtensionAPI) {
	registerCommands(pi);
}
