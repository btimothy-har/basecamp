import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBqQueryTool } from "./bq-query/index.ts";

export default function (pi: ExtensionAPI): void {
	registerBqQueryTool(pi);
}
