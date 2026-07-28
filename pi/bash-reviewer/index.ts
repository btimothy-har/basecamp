import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import { recentUserMessages } from "#core/session/user-context.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { resolveGateModel, runGate } from "./llm.ts";
import { type ReviewDeps, reviewBashCommand } from "./review.ts";

export function registerBashReviewer(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		if (!isToolCallEventType("bash", event)) return undefined;

		const command = event.input.command ?? "";
		if (command === "") return undefined;

		const deps: ReviewDeps = {
			resolveModel: () => resolveGateModel(ctx),
			recentMessages: () => recentUserMessages(ctx.sessionManager.getEntries()),
			runGate: (args) => runGate(args),
			confirm: (title, body) =>
				withHerdrBlocked(pi, "Waiting for command approval", () => ctx.ui.confirm(title, body, { signal: ctx.signal })),
			hasUI: ctx.hasUI,
			isSubagent: isSubagent(),
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
