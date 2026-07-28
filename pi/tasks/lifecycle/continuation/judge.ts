import type { Api, AssistantMessage, Context, Message, Model, ModelThinkingLevel, Tool } from "@earendil-works/pi-ai";
import { complete as defaultComplete } from "@earendil-works/pi-ai/compat";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import {
	resolveAliasedModel,
	resolveForcedToolChoice,
	resolvePortableReasoningEffort,
} from "#core/model/resolution.ts";
import { type ContinuationVerdict, type JudgeInput, RUBRIC_CATEGORIES, type RubricCategory } from "./types.ts";

// Q is vetoed for subagents by withholding it from the tool schema entirely —
// the model cannot emit a verdict the parser would then have to distrust.
const PRIMARY_CATEGORIES = RUBRIC_CATEGORIES;
const SUBAGENT_CATEGORIES = RUBRIC_CATEGORIES.filter((category) => category !== "Q");

const SUBAGENT_VARIANT = `Subagent divergence: this agent was dispatched by another agent and has no user, so a question is unanswerable and stopping on one wastes the run. Veto Q does not apply here: a question in the final message is NOT a reason to stop. If the agent found itself facing a question or choice, it should decide and proceed, or report the blocker as its deliverable (veto D). Vetoes D and H still apply.`;

// The rubric is the sole authority on stop legitimacy; the wording is an
// agreed design artifact — categories and the tie-break must keep their meaning verbatim.
export const CONTINUATION_RUBRIC = `You are judging whether a coding agent's stop was premature. The agent has stopped producing tool calls and returned control. Decide whether it should be nudged to continue. Call the continuation_verdict tool exactly once. Keep the reason to one short sentence.

Do NOT retrigger (retrigger: false) if any of these hold:
- Q (Asked): the final message asks the user anything — a question, a choice, a confirmation, or permission. ANY question counts, including one whose answer looks obvious.
- D (Delivered): the requested work appears done — the goal is satisfied, or in analysis/planning mode findings, a synthesis, or a plan has been presented for review.
- H (Held): it is waiting on a human action or an external event it cannot progress itself.

Otherwise retrigger (retrigger: true), specifically when:
- I (Intent): the final message states or implies a next action that was not performed.
- R (Remaining): the goal or task state shows work left, and the message neither asks nor claims completion.
- E (Error): it stopped at an unresolved error without either recovering or delivering a conclusion.

Tie-break: when uncertain, do NOT retrigger. A wrong stop costs the user one keystroke; a wrong continue burns a whole agent run.

{{SUBAGENT_CLAUSE}}Input arrives as JSON with goal, task_snapshot, mode, read_only, final_assistant_message, and recent_user_messages (most-recent-last) fields.`;

// Line prefix identifying the Q veto bullet so it can be stripped for subagents.
const Q_VETO_LINE = "- Q (Asked):";

function categorySchema(categories: readonly RubricCategory[]) {
	return Type.Union(categories.map((category) => Type.Literal(category)));
}

export const ContinuationVerdictSchema = Type.Object(
	{
		retrigger: Type.Boolean(),
		category: categorySchema(RUBRIC_CATEGORIES),
		reason: Type.String(),
	},
	{ additionalProperties: false },
);

function judgeTool(subagent: boolean): Tool {
	return {
		name: "continuation_verdict",
		description: "Reports whether the agent's stop was premature, the rubric category, and a short reason.",
		parameters: Type.Object(
			{
				retrigger: Type.Boolean(),
				category: categorySchema(subagent ? SUBAGENT_CATEGORIES : PRIMARY_CATEGORIES),
				reason: Type.String(),
			},
			{ additionalProperties: false },
		),
	};
}

export const JUDGE_TOOL: Tool = judgeTool(false);

export function buildJudgeContext(input: JudgeInput): Context {
	// Subagents have no user, so veto Q must be removed from the rubric rather
	// than merely de-prioritized — a question would otherwise look like a clean stop.
	const subagentClause = input.subagent ? `${SUBAGENT_VARIANT}\n\n` : "";
	const payload = JSON.stringify(
		{
			goal: input.goal,
			task_snapshot: input.taskSnapshot,
			mode: input.mode,
			read_only: input.readOnly,
			final_assistant_message: input.finalAssistantMessage,
			recent_user_messages: input.recentUserMessages,
		},
		null,
		2,
	);
	const systemPrompt = input.subagent
		? CONTINUATION_RUBRIC.split("\n")
				.filter((line) => !line.startsWith(Q_VETO_LINE))
				.join("\n")
				.replace("{{SUBAGENT_CLAUSE}}", subagentClause)
		: CONTINUATION_RUBRIC.replace("{{SUBAGENT_CLAUSE}}", "");
	return {
		systemPrompt,
		messages: [
			{
				role: "user",
				content: `Judge whether the agent's stop was premature. Input:\n\n${payload}`,
				timestamp: Date.now(),
			},
		],
		tools: [judgeTool(input.subagent)],
	};
}

export function parseJudgeResponse(msg: AssistantMessage): ContinuationVerdict | null {
	const toolCalls = msg.content.filter((content) => content.type === "toolCall");
	if (toolCalls.length !== 1) return null;
	const call = toolCalls[0];
	if (call === undefined || call.type !== "toolCall" || call.name !== "continuation_verdict") return null;

	const args: unknown = call.arguments;
	if (!Value.Check(ContinuationVerdictSchema, args)) return null;

	return args;
}

export function resolveJudgeReasoningEffort(model: Model<Api>): ModelThinkingLevel | undefined {
	return resolvePortableReasoningEffort(model);
}

export function resolveJudgeToolChoice(model: Model<Api>): unknown {
	return resolveForcedToolChoice(model, "continuation_verdict");
}

// Fail-open by design (the inverse of bash-reviewer's fail-closed posture):
// every failure path returns null and the caller treats null as "do not nudge".
export async function runJudge(opts: {
	model: Model<Api>;
	auth: { apiKey?: string; headers?: Record<string, string> };
	context: Context;
	signal?: AbortSignal;
	complete?: typeof defaultComplete;
}): Promise<ContinuationVerdict | null> {
	const complete = opts.complete ?? defaultComplete;
	const reasoningEffort = resolveJudgeReasoningEffort(opts.model);
	const msg = await complete(opts.model, opts.context, {
		...opts.auth,
		signal: opts.signal,
		toolChoice: resolveJudgeToolChoice(opts.model),
		...(reasoningEffort === undefined ? {} : { reasoningEffort }),
	});
	if (msg.stopReason === "error") throw new Error(msg.errorMessage ?? "continuation judge provider returned an error");
	return parseJudgeResponse(msg);
}

// The feature is deliberately inert without a configured fast alias.
export async function resolveJudgeModel(
	ctx: ExtensionContext,
): Promise<{ model: Model<Api>; auth: { apiKey?: string; headers?: Record<string, string> } } | null> {
	return resolveAliasedModel(ctx, "fast");
}

function textFromContent(content: Message["content"]): string {
	if (typeof content === "string") return content;
	return content
		.filter((item) => item.type === "text")
		.map((item) => item.text)
		.join("");
}

// Local reimplementation of bash-reviewer's recentHumanMessages: cross-domain
// imports resolve only through a domain's public index, which does not export it.
export function recentUserMessages(sessionManager: ExtensionContext["sessionManager"], limit = 5): string[] {
	const messages: string[] = [];
	for (const entry of sessionManager.getEntries()) {
		if (entry.type === "message" && entry.message.role === "user") {
			messages.push(textFromContent(entry.message.content));
		}
	}
	return messages.slice(-limit);
}
