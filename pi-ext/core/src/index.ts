/**
 * Core extension — BigQuery tool.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerBqQueryTool } from "./tools/bq-query";

export default function (pi: ExtensionAPI) {
	registerBqQueryTool(pi);
}
