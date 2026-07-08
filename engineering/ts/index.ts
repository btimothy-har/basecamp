import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBqQueryTool } from "./tools/bq-query.ts";

export default function (pi: ExtensionAPI): void {
	registerBqQueryTool(pi);
}
