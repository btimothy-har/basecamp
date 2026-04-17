/**
 * Escalate — surface blockers or decisions to the user.
 *
 * Presents questions sequentially with optional context hints and
 * predefined options. Supports back-navigation between questions.
 */

import type { ExtensionAPI, ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

// ============================================================================
// Render helpers
// ============================================================================

function renderSuccess(message: string, theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${message}`), 0, 0);
}

function renderPartial(theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

// ============================================================================
// Dialog helpers
// ============================================================================

const SOMETHING_ELSE = "Something else...";

/** Build dialog title with optional counter and context. */
function buildTitle(question: string, hint?: string, index?: number, total?: number): string {
	const counter = total && total > 1 ? `(${(index ?? 0) + 1}/${total}) ` : "";
	const ctx = hint ? `\n${hint}` : "";
	return `${counter}${question}${ctx}`;
}

/** Show a single question via select (with options) or input (without). */
async function askOne(
	ui: ExtensionContext["ui"],
	title: string,
	options: string[] | undefined,
	prefill?: string,
): Promise<string | undefined> {
	if (options?.length) {
		const choices = [...options, SOMETHING_ELSE];
		const picked = await ui.select(title, choices);
		if (!picked) return undefined;
		if (picked === SOMETHING_ELSE) {
			return await ui.input(title, prefill);
		}
		return picked;
	}
	return await ui.input(title, prefill);
}

// ============================================================================
// Registration
// ============================================================================

export function registerEscalate(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "escalate",
		label: "Escalate",
		description:
			"Surface a blocker or decision to the user. Use when you need user input, hit ambiguity, or are stuck. Pauses execution until the user responds.",
		promptSnippet: "Pause and ask the user for a decision or help with a blocker",
		parameters: Type.Object({
			questions: Type.Array(Type.String(), {
				description: "Questions to ask the user, presented in sequence",
			}),
			context: Type.Optional(
				Type.Array(Type.String(), {
					description: "Recommendations or context per question (same order as questions)",
				}),
			),
			options: Type.Optional(
				Type.Array(Type.Array(Type.String()), {
					description:
						"Options per question (same order as questions). Use empty array [] for questions without options.",
				}),
			),
		}),
		async execute(_id, params, _signal, _onUpdate, execCtx) {
			if (!execCtx.hasUI) {
				const summary = params.questions.map((q) => `[escalation] ${q}`).join("\n");
				return {
					content: [{ type: "text", text: summary }],
					details: { questions: params.questions, answers: null },
				};
			}

			const total = params.questions.length;
			const answers = new Map<number, string>();
			let index = 0;

			while (index < total) {
				const question = params.questions[index]!;
				const hint = params.context?.[index];
				const opts = params.options?.[index];
				const title = buildTitle(question, hint, index, total);
				const existing = answers.get(index);

				const answer = await askOne(execCtx.ui, title, opts?.length ? opts : undefined, existing);

				if (!answer) {
					if (index > 0) {
						index--;
						continue;
					}
					return {
						content: [{ type: "text", text: "User dismissed without answering." }],
						details: { questions: params.questions, answers: null },
					};
				}

				answers.set(index, answer);
				index++;
			}

			// Format results
			if (total === 1) {
				const answer = answers.get(0) ?? "";
				return {
					content: [{ type: "text", text: answer }],
					details: { questions: params.questions, answers: [answer] },
				};
			}

			const answerList = params.questions.map((_, i) => answers.get(i) ?? null);
			const answerLines = params.questions.map((q, i) => `${q}\n→ ${answerList[i] ?? "(no answer)"}`);
			return {
				content: [{ type: "text", text: answerLines.join("\n\n") }],
				details: { questions: params.questions, answers: answerList },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const qs = args.questions as string[] | undefined;
			const preview = qs?.[0] ?? "...";
			const trimmed = preview.length > 60 ? `${preview.slice(0, 60)}...` : preview;
			const suffix = qs && qs.length > 1 ? ` (+${qs.length - 1} more)` : "";
			return new Text(theme.fg("toolTitle", theme.bold("escalate ")) + theme.fg("dim", trimmed + suffix), 0, 0);
		},
		renderResult(result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			const details = result.details as { answers: (string | null)[] | null };
			if (!details?.answers) {
				const { Text } = require("@mariozechner/pi-tui");
				return new Text(theme.fg("warning", "⚠") + theme.fg("dim", " dismissed"), 0, 0);
			}
			const count = details.answers.filter(Boolean).length;
			return renderSuccess(`${count} answer${count !== 1 ? "s" : ""} received`, theme);
		},
	});
}
