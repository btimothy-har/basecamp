import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type AgentMode, cycleAgentMode } from "../runtime/mode";

const MODE_LABELS: Record<AgentMode, string> = {
	analysis: "Analysis/research",
	planning: "Planning/discovery",
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
