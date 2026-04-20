import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { EscalateDialog } from "./dialog.js";
import { renderCall, renderResult } from "./render.js";
import type { QuestionAnswer } from "./types.js";

export function registerEscalate(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "escalate",
		label: "Escalate",
		description:
			"Surface a blocker or decision to the user. Use when you need user input, hit ambiguity, or are stuck. Pauses execution until the user responds. Keep questions short and direct; put background reasoning in context.",
		promptSnippet: "Pause and ask the user for a decision or help with a blocker",
		parameters: Type.Object({
			questions: Type.Array(
				Type.Object({
					question: Type.String({ description: "Short, direct question. One-liner.", maxLength: 60 }),
					context: Type.Optional(Type.String({ description: "Background, reasoning, constraints. Can be longer." })),
					options: Type.Optional(Type.Array(Type.String(), { description: "Predefined options to choose from" })),
					multiSelect: Type.Optional(
						Type.Boolean({ description: "Allow selecting multiple options. Defaults to false." }),
					),
				}),
				{ description: "Questions to ask the user, presented in sequence" },
			),
		}),
		async execute(_id, params, _signal, _onUpdate, execCtx) {
			if (!execCtx.hasUI) {
				const summary = params.questions.map((q) => `[escalation] ${q.question}`).join("\n");
				return {
					content: [{ type: "text", text: summary }],
					details: null,
				};
			}

			const result = await execCtx.ui.custom<QuestionAnswer[] | null>((tui, theme, keybindings, done) => {
				return new EscalateDialog(params.questions, tui, theme, keybindings, done);
			});

			if (!result) {
				return {
					content: [{ type: "text", text: "User dismissed without answering." }],
					details: null,
				};
			}

			return {
				content: [{ type: "text", text: JSON.stringify(result) }],
				details: result,
			};
		},
		renderCall,
		renderResult,
	});
}
