import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBqQueryTool } from "./src/tools/bq-query.ts";

export default function (pi: ExtensionAPI): void {
	registerBqQueryTool(pi);
}
