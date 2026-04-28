import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type AgentMode, cycleAgentMode, setAgentMode } from "../runtime/mode";

const MODE_LABELS: Record<AgentMode, string> = {
	planning: "Planning/discovery",
	supervisor: "Supervisor",
	executor: "IC/executor",
};

const MODE_CHOICES = [MODE_LABELS.planning, MODE_LABELS.supervisor, MODE_LABELS.executor] as const;

function parseMode(value: string): AgentMode | null {
	switch (value.trim().toLowerCase()) {
		case "plan":
		case "planning":
		case "discovery":
			return "planning";
		case "supervisor":
		case "sup":
			return "supervisor";
		case "executor":
		case "execute":
		case "ic":
			return "executor";
		default:
			return null;
	}
}

function modeFromChoice(choice: (typeof MODE_CHOICES)[number]): AgentMode {
	if (choice === MODE_LABELS.supervisor) return "supervisor";
	if (choice === MODE_LABELS.executor) return "executor";
	return "planning";
}

export function registerModeCommand(pi: ExtensionAPI): void {
	pi.registerCommand("mode", {
		description: "Switch execution posture",
		handler: async (args, ctx) => {
			const requested = args?.trim();
			let mode: AgentMode | null = null;

			if (requested) {
				mode = parseMode(requested);
				if (!mode) {
					ctx.ui.notify("Usage: /mode planning|supervisor|executor", "error");
					return;
				}
			} else if (ctx.hasUI) {
				const choice = await ctx.ui.select("Execution posture", [...MODE_CHOICES]);
				if (!choice) return;
				mode = modeFromChoice(choice as (typeof MODE_CHOICES)[number]);
			} else {
				mode = cycleAgentMode();
			}

			setAgentMode(mode);
			ctx.ui.notify(`${MODE_LABELS[mode]} mode`, "info");
		},
	});
}
