import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type AgentMode, cycleAgentMode } from "../agent-mode.ts";

const MODE_LABELS: Record<AgentMode, string> = {
	analysis: "Analysis/research",
	planning: "Explore",
	supervisor: "Supervisor",
	executor: "IC/executor",
};

export function registerModeShortcut(pi: ExtensionAPI): void {
	pi.registerShortcut("shift+tab", {
		description: "Cycle session mode",
		handler: async (ctx) => {
			const mode = cycleAgentMode();
			ctx.ui.notify(`${MODE_LABELS[mode]} mode`, "info");
		},
	});
}
