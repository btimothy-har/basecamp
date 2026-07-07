import type { AssistantMessage, Context, Model, ModelThinkingLevel } from "@earendil-works/pi-ai";
import { complete as defaultComplete, getSupportedThinkingLevels } from "@earendil-works/pi-ai";
import { Value } from "@sinclair/typebox/value";
import { type Dimension, type Finding, ReportFindingsArgs, report_findings } from "./findings.ts";

export interface TransposeDeps {
	model: Model<any>;
	auth: { apiKey?: string; headers?: Record<string, string> };
	complete?: typeof import("@earendil-works/pi-ai").complete;
	signal?: AbortSignal;
}

export const TRANSPOSE_RULESET = `You convert ONE code-review report into structured findings. Extract EVERY distinct finding the report raises — do not merge, drop, invent, split arbitrarily, or re-prioritize. Preserve the reviewer's file paths, line numbers, and remediation guidance. Map the reviewer's severity/impact/risk language onto this canonical scale by REAL-WORLD IMPACT: critical = data loss, crash, security breach, or broken core behavior; high = incorrect results or a serious flaw in a common path; medium = an edge-case bug or moderate issue; low = a minor/nitpick issue. Behavior-preserving clarity, style, naming, and documentation issues are AT MOST medium and usually low, regardless of any 'impact score' the reviewer assigned. If the report states it is clean / has no findings, return an empty findings array. Call report_findings exactly once.`;

const PORTABLE_THINKING_LEVELS: ModelThinkingLevel[] = ["low", "medium", "high", "xhigh"];

function buildTransposeContext(prose: string): Context {
	return {
		systemPrompt: TRANSPOSE_RULESET,
		messages: [
			{
				role: "user",
				content: prose,
				timestamp: Date.now(),
			},
		],
		tools: [report_findings],
	};
}

function resolveTransposeReasoningEffort(model: Model<any>): ModelThinkingLevel | undefined {
	if (!model.reasoning) return undefined;

	const supported = new Set(getSupportedThinkingLevels(model));
	if (supported.has("minimal") && typeof model.thinkingLevelMap?.minimal === "string") return "minimal";
	return PORTABLE_THINKING_LEVELS.find((level) => supported.has(level));
}

function resolveTransposeToolChoice(model: Model<any>): unknown {
	if (model.api === "anthropic-messages") return { type: "tool", name: "report_findings" };
	return { type: "function", function: { name: "report_findings" } };
}

function parseTransposeResponse(msg: AssistantMessage): ReportFindingsArgs | null {
	const toolCalls = msg.content.filter((content) => content.type === "toolCall");
	if (toolCalls.length !== 1) return null;

	const call = toolCalls[0];
	if (call === undefined || call.type !== "toolCall" || call.name !== "report_findings") return null;

	const args: unknown = call.arguments;
	if (!Value.Check(ReportFindingsArgs, args)) return null;

	return args;
}

export async function transposeReport(prose: string, dimension: Dimension, deps: TransposeDeps): Promise<Finding[]> {
	const complete = deps.complete ?? defaultComplete;
	const reasoningEffort = resolveTransposeReasoningEffort(deps.model);
	const msg = await complete(deps.model, buildTransposeContext(prose), {
		...deps.auth,
		signal: deps.signal,
		toolChoice: resolveTransposeToolChoice(deps.model),
		...(reasoningEffort === undefined ? {} : { reasoningEffort }),
	});
	if (msg.stopReason === "error") throw new Error(msg.errorMessage ?? "review transposer provider returned an error");

	const args = parseTransposeResponse(msg);
	if (args === null) throw new Error("review transposer did not return a valid report_findings tool call");

	return args.findings.map((finding) => ({ ...finding, dimension }));
}
