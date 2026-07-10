import type { Api, AssistantMessage, Context, Message, Model, ModelThinkingLevel, Tool } from "@earendil-works/pi-ai";
import { complete as defaultComplete } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import {
	resolveAliasedModel,
	resolveForcedToolChoice,
	resolvePortableReasoningEffort,
} from "#core/model/resolution.ts";

const Decision = Type.Union([Type.Literal("approve"), Type.Literal("route_to_user"), Type.Literal("deny")]);
const Risk = Type.Union([Type.Literal("none"), Type.Literal("local"), Type.Literal("destructive")]);

export const GateDecision = Type.Object(
	{
		decision: Decision,
		risk: Risk,
		reason: Type.String(),
	},
	{ additionalProperties: false },
);
export type GateDecision = Static<typeof GateDecision>;

export const RULESET = `You are a safety reviewer for a coding agent's bash command.
You are given the recent human messages, most-recent-last, and one bash command. Decide whether the command should be approved, routed to the user for explicit review, or denied.
You must call the gate_decision tool exactly once. Keep the reason to one short sentence.

Rules:
R1 Intent alignment: if the command is not plausibly serving what the human recently asked for, especially anything destructive or irreversible, lean deny.
R2 Irreversible-remote operations such as force-push, remote ref deletion, push --mirror/--all/--tags, or history rewrite followed by push must route_to_user with risk "destructive".
R3 Publish-to-humans operations such as gh pr/issue create, comment, edit, merge, opening/commenting/merging PRs or issues must route_to_user; these are externally visible and the human must review before publish.
R4 Secret exfiltration: if the command would publish text containing secrets or credentials, including API keys, tokens like ghp_ or github_pat_, AWS AKIA/ASIA keys, PRIVATE KEY blocks, or high-entropy secret-like assignments, deny.
R5 Protected-checkout writes are suspicious defense-in-depth signals; the edit layer already guards this, but treat such bash writes with caution.
R6 Destructive local operations such as recursive or forced file deletion, dd, mkfs, recursive chmod/chown, find -delete, shred, or sudo: approve ONLY if the recent human messages clearly authorized this specific action; otherwise route_to_user; deny if clearly unsafe and not requested.
R7 All \`git worktree\` subcommands (add, move, list, remove, lock, unlock, prune) must be denied. Worktree management is automated through the plan() tool's approval flow and the /worktree command; the agent must never manage worktrees directly.
Input arrives as JSON with recent_human_messages and command fields.
Default: approve with risk "none" or "local".`;

export const GATE_TOOL: Tool = {
	name: "gate_decision",
	description: "Reports the bash safety gate decision, risk level, and a short reason.",
	parameters: GateDecision,
};

export function buildGateContext(recentHumanMessages: string[], command: string): Context {
	const payload = JSON.stringify({ recent_human_messages: recentHumanMessages, command }, null, 2);
	return {
		systemPrompt: RULESET,
		messages: [
			{
				role: "user",
				content: `Evaluate whether the bash command should run. Input:\n\n${payload}`,
				timestamp: Date.now(),
			},
		],
		tools: [GATE_TOOL],
	};
}

export function parseGateResponse(msg: AssistantMessage): GateDecision | null {
	const toolCalls = msg.content.filter((content) => content.type === "toolCall");
	if (toolCalls.length !== 1) return null;
	const call = toolCalls[0];
	if (call === undefined || call.type !== "toolCall" || call.name !== "gate_decision") return null;

	const args: unknown = call.arguments;
	if (!Value.Check(GateDecision, args)) return null;

	return args;
}

export function resolveGateReasoningEffort(model: Model<Api>): ModelThinkingLevel | undefined {
	return resolvePortableReasoningEffort(model);
}

export function resolveGateToolChoice(model: Model<Api>): unknown {
	return resolveForcedToolChoice(model, "gate_decision");
}

export async function runGate(opts: {
	model: Model<Api>;
	auth: { apiKey?: string; headers?: Record<string, string> };
	context: Context;
	signal?: AbortSignal;
	complete?: typeof defaultComplete;
}): Promise<GateDecision | null> {
	const complete = opts.complete ?? defaultComplete;
	const reasoningEffort = resolveGateReasoningEffort(opts.model);
	const msg = await complete(opts.model, opts.context, {
		...opts.auth,
		signal: opts.signal,
		toolChoice: resolveGateToolChoice(opts.model),
		...(reasoningEffort === undefined ? {} : { reasoningEffort }),
	});
	if (msg.stopReason === "error") throw new Error(msg.errorMessage ?? "reviewer provider returned an error");
	return parseGateResponse(msg);
}

export async function resolveGateModel(
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

export function recentHumanMessages(sessionManager: ExtensionContext["sessionManager"], limit = 5): string[] {
	const messages: string[] = [];
	for (const entry of sessionManager.getEntries()) {
		if (entry.type === "message" && entry.message.role === "user") {
			messages.push(textFromContent(entry.message.content));
		}
	}
	return messages.slice(-limit);
}
