import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./pr.ts";

export default function (pi: ExtensionAPI) {
	registerCommands(pi);
}
