/**
 * Continuation guard — the fast-model call that judges a stop.
 *
 * The rubric itself lives in `rubric.ts`; this module is the plumbing around it
 * and mirrors `#bash-reviewer/llm.ts`. Every failure path returns null, because
 * the caller treats null as "do not nudge".
 */

import type { Api, AssistantMessage, Context, Model, ModelThinkingLevel, Tool } from "@earendil-works/pi-ai";
import { complete as defaultComplete } from "@earendil-works/pi-ai/compat";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { resolveForcedToolChoice, resolvePortableReasoningEffort } from "#core/model/resolution.ts";
import { buildRubric, categoryRetriggers, offeredCategories } from "./rubric.ts";
import { type ContinuationVerdict, type JudgeInput, verdictSchema } from "./types.ts";

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
		parameters: verdictSchema(offeredCategories(subagent)),
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

/**
 * Validates against the same narrowed schema the tool offered, because a provider
 * treats the parameter enum as a hint rather than a gate.
 */
export function parseJudgeResponse(msg: AssistantMessage, subagent: boolean): ContinuationVerdict | null {
	const toolCalls = msg.content.filter((content) => content.type === "toolCall");
	if (toolCalls.length !== 1) return null;
	const call = toolCalls[0];
	if (call === undefined || call.type !== "toolCall" || call.name !== "continuation_verdict") return null;

	const args: unknown = call.arguments;
	if (!Value.Check(verdictSchema(offeredCategories(subagent)), args)) return null;
	// A verdict that contradicts its own category is model confusion, not a decision.
	if (args.retrigger !== categoryRetriggers(args.category)) return null;

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
	subagent: boolean;
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
	return parseJudgeResponse(msg, opts.subagent);
}

// The judge rides the active session model — no dedicated alias, no config
// dependency. Fail-open stands: a missing model or unusable auth resolves to
// null and the caller does not nudge.
export async function resolveJudgeModel(
	ctx: ExtensionContext,
): Promise<{ model: Model<Api>; auth: { apiKey?: string; headers?: Record<string, string> } } | null> {
	const model = ctx.model;
	if (!model) return null;
	try {
		const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
		if (!auth.ok || (!auth.apiKey && !(auth.headers && Object.keys(auth.headers).length > 0))) return null;
		return { model, auth: { apiKey: auth.apiKey, headers: auth.headers } };
	} catch {
		return null;
	}
}
