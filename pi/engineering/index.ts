import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBqQueryTool } from "./bigquery/index.ts";

export default function (pi: ExtensionAPI): void {
	registerBqQueryTool(pi);
}
