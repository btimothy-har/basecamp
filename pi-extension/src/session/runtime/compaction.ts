import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { compact } from "@mariozechner/pi-coding-agent";
import { generateCompactionWithModel } from "./compaction-model.ts";

export function registerCompactionModel(pi: ExtensionAPI): void {
	pi.on("session_before_compact", async (event, ctx) => {
		const result = await generateCompactionWithModel(event, ctx, compact);
		return result;
	});
}
