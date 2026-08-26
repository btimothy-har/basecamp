import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import { compileSystemPrompt } from "./prompt.ts";
import { type SystemPromptPreview, showSystemPromptPreview } from "./viewer.ts";

type CompilePrompt = (pi: ExtensionAPI, modelId?: string) => string;
type ShowPreview = (preview: SystemPromptPreview, ctx: ExtensionCommandContext) => Promise<void>;

interface SystemPromptCommandDependencies {
	compile?: CompilePrompt;
	show?: ShowPreview;
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

export function registerSystemPromptCommand(
	pi: ExtensionAPI,
	dependencies: SystemPromptCommandDependencies = {},
): void {
	if (isSubagent()) return;

	const compile = dependencies.compile ?? compileSystemPrompt;
	const show = dependencies.show ?? showSystemPromptPreview;

	pi.registerCommand("system-prompt", {
		description: "Preview Basecamp's freshly compiled system prompt",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("/system-prompt does not accept arguments.", "error");
				return;
			}
			if (ctx.mode !== "tui") {
				ctx.ui.notify("/system-prompt requires the interactive terminal UI.", "info");
				return;
			}

			let preview: SystemPromptPreview;
			try {
				preview = {
					prompt: compile(pi, ctx.model?.id),
					inactive: Boolean(ctx.getSystemPromptOptions().customPrompt),
				};
			} catch (error) {
				ctx.ui.notify(`Could not compile system prompt: ${errorMessage(error)}`, "error");
				return;
			}

			try {
				await show(preview, ctx);
			} catch (error) {
				ctx.ui.notify(`Could not show system prompt: ${errorMessage(error)}`, "error");
			}
		},
	});
}
