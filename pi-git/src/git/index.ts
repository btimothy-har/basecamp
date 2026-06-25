/**
 * Git — code walkthrough, PR prompt command, and review packet workflows.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./commands";
import { registerReviewPacketTool } from "./review-packet-tool";

export default function (pi: ExtensionAPI) {
	registerCommands(pi);
	registerReviewPacketTool(pi);
}
