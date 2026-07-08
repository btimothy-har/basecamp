/**
 * Git — PR prompt command.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./commands.ts";

export default function (pi: ExtensionAPI) {
	registerCommands(pi);
}
