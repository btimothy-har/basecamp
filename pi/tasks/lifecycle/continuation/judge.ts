import type { Api, AssistantMessage, Context, Model, ModelThinkingLevel, Tool } from "@earendil-works/pi-ai";
import { complete as defaultComplete } from "@earendil-works/pi-ai/compat";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import {
	resolveAliasedModel,
	resolveForcedToolChoice,
	resolvePortableReasoningEffort,
} from "#core/model/resolution.ts";
import { buildRubric, offeredCategories } from "./rubric.ts";

import { type ContinuationVerdict, type JudgeInput, RUBRIC_CATEGORIES, type RubricCategory } from "./types.ts";

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

/**
 * Q is withheld from the subagent schema, not merely de-emphasized in the prompt:
 * left selectable, it is the obvious label for a question-shaped stop, and the
 * resulting `{retrigger: false, category: "Q"}` would strand a run that has no
 * user to answer it.
 */
export function buildJudgeTool(subagent: boolean): Tool {
	return {
		name: "continuation_verdict",
		description: "Reports whether the agent's stop was premature, the rubric category, and a short reason.",
		parameters: Type.Object(
			{
				retrigger: Type.Boolean(),
				category: categorySchema(offeredCategories(subagent)),
				reason: Type.String(),
			},
			{ additionalProperties: false },
		),
	};
}

export function buildJudgeContext(input: JudgeInput): Context {
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
	return {
		systemPrompt: buildRubric(input.subagent),
		messages: [
			{
				role: "user",
				content: `Judge whether the agent's stop was premature. Input:\n\n${payload}`,
				timestamp: Date.now(),
			},
		],
		tools: [buildJudgeTool(input.subagent)],
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
