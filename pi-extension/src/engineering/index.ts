/**
 * Engineering extension — tools and capabilities for data/engineering workflows.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBqQueryTool } from "./tools/bq-query";

export default function (pi: ExtensionAPI): void {
	registerBqQueryTool(pi);
}
