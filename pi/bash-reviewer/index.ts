import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { recentHumanMessages, resolveGateModel, runGate } from "./llm.ts";
import { type ReviewDeps, reviewBashCommand } from "./review.ts";

export function registerBashReviewer(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		if (!isToolCallEventType("bash", event)) return undefined;

		const command = event.input.command ?? "";
		if (command === "") return undefined;

		const agentDepth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");

		const deps: ReviewDeps = {
			resolveModel: () => resolveGateModel(ctx),
			recentMessages: () => recentHumanMessages(ctx.sessionManager),
			runGate: (args) => runGate(args),
			confirm: (title, body) => ctx.ui.confirm(title, body, { signal: ctx.signal }),
			hasUI: ctx.hasUI,
			isSubagent: Number.isFinite(agentDepth) && agentDepth > 0,
			signal: ctx.signal,
			audit: (entry) => pi.appendEntry("bash-reviewer", entry),
			notify: (message, type) => {
				if (ctx.hasUI) ctx.ui.notify(message, type);
			},
		};

		return await reviewBashCommand(command, deps);
	});
}

export default registerBashReviewer;
