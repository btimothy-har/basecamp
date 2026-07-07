import type { Api, AssistantMessage, Context, Model, ToolCall } from "@earendil-works/pi-ai";
import { complete as defaultComplete } from "@earendil-works/pi-ai";
import { Value } from "@sinclair/typebox/value";
import { resolveForcedToolChoice, resolvePortableReasoningEffort } from "pi-core/platform/model-resolution.ts";
import { type Dimension, type Finding, ReportFindingsArgs, report_findings } from "./findings.ts";

export interface TransposeDeps {
	model: Model<Api>;
	auth: { apiKey?: string; headers?: Record<string, string> };
	complete?: typeof import("@earendil-works/pi-ai").complete;
	signal?: AbortSignal;
}

export const TRANSPOSE_RULESET = `You convert ONE code-review report into structured findings. Extract EVERY distinct finding the report raises — do not merge, drop, invent, split arbitrarily, or re-prioritize. Preserve the reviewer's file paths, line numbers, and remediation guidance. Map the reviewer's severity/impact/risk language onto this canonical scale by REAL-WORLD IMPACT: critical = data loss, crash, security breach, or broken core behavior; high = incorrect results or a serious flaw in a common path; medium = an edge-case bug or moderate issue; low = a minor/nitpick issue. Behavior-preserving clarity, style, naming, and documentation issues are AT MOST medium and usually low, regardless of any 'impact score' the reviewer assigned. If the report states it is clean / has no findings, return an empty findings array. Call report_findings exactly once.`;

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

function parseTransposeResponse(msg: AssistantMessage): ReportFindingsArgs | null {
	const toolCalls = msg.content.filter((content): content is ToolCall => content.type === "toolCall");
	if (toolCalls.length !== 1) return null;

	const call = toolCalls[0];
	if (call === undefined || call.name !== "report_findings") return null;

	const args: unknown = call.arguments;
	if (!Value.Check(ReportFindingsArgs, args)) return null;

	return args;
}

export async function transposeReport(prose: string, dimension: Dimension, deps: TransposeDeps): Promise<Finding[]> {
	const complete = deps.complete ?? defaultComplete;
	const reasoningEffort = resolvePortableReasoningEffort(deps.model);
	const msg = await complete(deps.model, buildTransposeContext(prose), {
		...deps.auth,
		signal: deps.signal,
		toolChoice: resolveForcedToolChoice(deps.model, "report_findings"),
		...(reasoningEffort === undefined ? {} : { reasoningEffort }),
	});
	if (msg.stopReason === "error") throw new Error(msg.errorMessage ?? "review transposer provider returned an error");

	const args = parseTransposeResponse(msg);
	if (args === null) throw new Error("review transposer did not return a valid report_findings tool call");

	return args.findings.map((finding) => ({ ...finding, dimension }));
}
