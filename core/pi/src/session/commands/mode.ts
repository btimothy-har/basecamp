import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type AgentMode, cycleAgentMode, getAgentMode } from "../agent-mode.ts";

const MODE_LABELS: Record<AgentMode, string> = {
	analysis: "Analysis/research",
	planning: "Explore",
	copilot: "Repo copilot",
	supervisor: "Supervisor",
	executor: "IC/executor",
};

export function registerModeShortcut(pi: ExtensionAPI): void {
	pi.registerShortcut("shift+tab", {
		description: "Cycle session mode",
		handler: async (ctx) => {
			const before = getAgentMode();
			const mode = cycleAgentMode();
			if (mode === before && mode === "copilot") {
				ctx.ui.notify("Copilot mode is locked for this session", "info");
				return;
			}

			ctx.ui.notify(`${MODE_LABELS[mode]} mode`, "info");
		},
	});
}
