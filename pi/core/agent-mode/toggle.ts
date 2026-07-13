import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type AgentMode, cycleAgentMode, getAgentMode } from "./index.ts";

const MODE_LABELS: Record<AgentMode, string> = {
	analysis: "Analysis/research",
	planning: "Explore",
	work: "Work",
	copilot: "Repo copilot",
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
