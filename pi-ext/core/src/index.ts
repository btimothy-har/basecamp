/**
 * Core extension — context injection and BigQuery tool.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerContextInjection } from "./prompt/context-injection";
import { registerBqQueryTool } from "./tools/bq-query";

export default function (pi: ExtensionAPI) {
	registerContextInjection(pi);
	registerBqQueryTool(pi);
}
