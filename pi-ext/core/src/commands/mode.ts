import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { toggleAgentMode } from "../runtime/mode";

export function registerModeCommand(pi: ExtensionAPI): void {
	pi.registerCommand("mode", {
		description: "Toggle supervisor mode",
		handler: async (args, ctx) => {
			if (args?.trim()) {
				ctx.ui.notify("/mode takes no arguments", "error");
				return;
			}

			const mode = toggleAgentMode();
			ctx.ui.notify(mode === "supervisor" ? "Supervisor mode on" : "Supervisor mode off", "info");
		},
	});
}
