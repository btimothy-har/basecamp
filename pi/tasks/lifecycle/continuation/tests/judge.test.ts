import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { AssistantMessage, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import {
	buildJudgeContext,
	buildJudgeTool,
	parseJudgeResponse,
	resolveJudgeModel,
	runJudge,
} from "#tasks/lifecycle/continuation/judge.ts";
import { recentUserMessages } from "#tasks/lifecycle/continuation/messages.ts";
import { buildRubric, CONTINUATION_RUBRIC, offeredCategories } from "#tasks/lifecycle/continuation/rubric.ts";
import {
	type ContinuationVerdict,
	ContinuationVerdictSchema,
	type JudgeInput,
} from "#tasks/lifecycle/continuation/types.ts";

const fakeModel: Model<any> = {
	id: "claude-haiku",
	name: "Claude Haiku",
	api: "anthropic-messages",
	provider: "anthropic",
	baseUrl: "https://example.test",
	reasoning: false,
	input: ["text"],
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
	contextWindow: 200_000,
	maxTokens: 4096,
};

function assistantWithToolCall(name: string, args: object): AssistantMessage {
	return {
		role: "assistant",
		content: [{ type: "toolCall", id: "call-1", name, arguments: args as Record<string, unknown> }],
		api: "anthropic-messages",
		provider: "anthropic",
		model: "claude-haiku",
		usage: {
			input: 0,
			output: 0,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 0,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "toolUse",
		timestamp: 1,
	};
}

function judgeInput(overrides: Partial<JudgeInput> = {}): JudgeInput {
	return {
		goal: "Ship the feature.",
		taskSnapshot: "2 of 3 tasks open",
		mode: "work",
		readOnly: false,
		subagent: false,
		finalAssistantMessage: "I will now run the tests.",
		recentUserMessages: ["Please ship the feature."],
		...overrides,
	};
}

describe("ContinuationVerdictSchema", () => {
	it("accepts valid verdicts for both retrigger values", () => {
		assert.ok(Value.Check(ContinuationVerdictSchema, { retrigger: true, category: "I", reason: "It said next." }));
		assert.ok(Value.Check(ContinuationVerdictSchema, { retrigger: false, category: "Q", reason: "It asked." }));
	});

	it("rejects missing fields, wrong types, unknown categories, and extra properties", () => {
		assert.equal(Value.Check(ContinuationVerdictSchema, { retrigger: true, category: "I" }), false);
		assert.equal(
			Value.Check(ContinuationVerdictSchema, { retrigger: "yes", category: "I", reason: "Wrong type." }),
			false,
		);
		assert.equal(
			Value.Check(ContinuationVerdictSchema, { retrigger: true, category: "X", reason: "Unknown category." }),
			false,
		);
		assert.equal(
			Value.Check(ContinuationVerdictSchema, { retrigger: true, category: "I", reason: "Extra.", extra: 1 }),
			false,
		);
	});

	it("accepts exactly the six rubric categories", () => {
		for (const category of ["Q", "D", "H", "I", "R", "E"] as const) {
			assert.ok(Value.Check(ContinuationVerdictSchema, { retrigger: true, category, reason: "ok" }));
		}
	});
});

describe("parseJudgeResponse", () => {
	it("parses valid verdicts for both retrigger values", () => {
		const retrigger: ContinuationVerdict = { retrigger: true, category: "E", reason: "Stopped on an error." };
		const stop: ContinuationVerdict = { retrigger: false, category: "D", reason: "Work is done." };
		assert.deepEqual(parseJudgeResponse(assistantWithToolCall("continuation_verdict", retrigger), false), retrigger);
		assert.deepEqual(parseJudgeResponse(assistantWithToolCall("continuation_verdict", stop), false), stop);
	});

	it("returns null for zero, two, or wrongly named tool calls", () => {
		const verdict = { retrigger: false, category: "Q", reason: "It asked." };
		const base = assistantWithToolCall("continuation_verdict", verdict);
		assert.equal(parseJudgeResponse({ ...base, content: [{ type: "text", text: "no call" }] }, false), null);
		assert.equal(
			parseJudgeResponse(
				{
					...base,
					content: [
						{ type: "toolCall", id: "call-1", name: "continuation_verdict", arguments: verdict },
						{ type: "toolCall", id: "call-2", name: "continuation_verdict", arguments: verdict },
					],
				},
				false,
			),
			null,
		);
		assert.equal(parseJudgeResponse(assistantWithToolCall("other_tool", verdict), false), null);
	});

	it("returns null when arguments fail schema validation", () => {
		assert.equal(
			parseJudgeResponse(assistantWithToolCall("continuation_verdict", { retrigger: true, category: "X" }), false),
			null,
		);
	});

	// The tool enum is a provider hint, not a gate, so the parser has to enforce the
	// withholding too — otherwise a Q verdict strands a run with no user to answer it.
	it("rejects a category the subagent tool schema withheld, while accepting it for a primary session", () => {
		const asked = { retrigger: false, category: "Q" as const, reason: "It asked the user." };
		const response = assistantWithToolCall("continuation_verdict", asked);

		assert.deepEqual(parseJudgeResponse(response, false), asked);
		assert.equal(parseJudgeResponse(response, true), null);
	});

	// retrigger and category are deliberately redundant: disagreement means the model
	// was confused, and failing open is cheaper than acting on a contradiction.
	it("returns null when retrigger contradicts the category's polarity", () => {
		const vetoButNudge = { retrigger: true, category: "Q" as const, reason: "It asked." };
		const triggerButHold = { retrigger: false, category: "I" as const, reason: "Work remains." };

		assert.equal(parseJudgeResponse(assistantWithToolCall("continuation_verdict", vetoButNudge), false), null);
		assert.equal(parseJudgeResponse(assistantWithToolCall("continuation_verdict", triggerButHold), false), null);
	});

	it("returns null for a reason beyond the schema bound", () => {
		const verbose = { retrigger: true, category: "R" as const, reason: "x".repeat(401) };
		assert.equal(parseJudgeResponse(assistantWithToolCall("continuation_verdict", verbose), false), null);
	});
});

describe("runJudge", () => {
	it("returns parsed verdicts from an injected complete and forces the continuation_verdict tool", async () => {
		const verdict: ContinuationVerdict = { retrigger: true, category: "R", reason: "Tasks remain open." };
		const result = await runJudge({
			model: fakeModel,
			auth: { apiKey: "test-key" },
			context: buildJudgeContext(judgeInput()),
			subagent: false,
			complete: async (_model, _context, options) => {
				assert.equal(options?.apiKey, "test-key");
				assert.deepEqual(options?.toolChoice, { type: "tool", name: "continuation_verdict" });
				return assistantWithToolCall("continuation_verdict", verdict);
			},
		});
		assert.deepEqual(result, verdict);
	});

	it("returns null for missing, duplicated, or invalid tool-call responses", async () => {
		const verdict = { retrigger: false, category: "H", reason: "Waiting on CI." };
		const cases: AssistantMessage[] = [
			{ ...assistantWithToolCall("continuation_verdict", verdict), content: [{ type: "text", text: "held" }] },
			{
				...assistantWithToolCall("continuation_verdict", verdict),
				content: [
					{ type: "toolCall", id: "call-1", name: "continuation_verdict", arguments: verdict },
					{ type: "toolCall", id: "call-2", name: "other_tool", arguments: {} },
				],
			},
			assistantWithToolCall("continuation_verdict", { retrigger: true, category: "Z", reason: "bad" }),
		];
		for (const response of cases) {
			assert.equal(
				await runJudge({
					model: fakeModel,
					auth: { apiKey: "test-key" },
					context: buildJudgeContext(judgeInput()),
					subagent: false,
					complete: async () => response,
				}),
				null,
			);
		}
	});

	it("throws provider error messages from error stop reasons", async () => {
		await assert.rejects(
			runJudge({
				model: fakeModel,
				auth: { apiKey: "test-key" },
				context: buildJudgeContext(judgeInput()),
				subagent: false,
				complete: async () => ({
					...assistantWithToolCall("continuation_verdict", { retrigger: false, category: "Q", reason: "ok" }),
					stopReason: "error",
					errorMessage: "provider rejected tool choice",
				}),
			}),
			/provider rejected tool choice/,
		);
		await assert.rejects(
			runJudge({
				model: fakeModel,
				auth: { apiKey: "test-key" },
				context: buildJudgeContext(judgeInput()),
				subagent: false,
				complete: async () => ({
					...assistantWithToolCall("continuation_verdict", { retrigger: false, category: "Q", reason: "ok" }),
					stopReason: "error",
				}),
			}),
			/continuation judge provider returned an error/,
		);
	});
});

describe("resolveJudgeModel", () => {
	it("returns null when the fast alias is unset", async () => {
		const ctx = {} as ExtensionContext;
		assert.equal(await resolveJudgeModel(ctx), null);
	});
});

describe("buildJudgeContext", () => {
	it("serializes the judge input into the user message as JSON with the rubric and tool", () => {
		const input = judgeInput();
		const context = buildJudgeContext(input);
		assert.ok(!(context.systemPrompt ?? "").includes("{{"));
		assert.deepEqual(context.tools, [buildJudgeTool(false)]);
		assert.equal(context.messages.length, 1);
		const content = context.messages[0]?.content;
		assert.equal(typeof content, "string");
		if (typeof content !== "string") throw new Error("expected string content");
		const payload = JSON.parse(content.replace(/^Judge whether the agent's stop was premature\. Input:\n\n/, ""));
		assert.deepEqual(payload, {
			goal: input.goal,
			task_snapshot: input.taskSnapshot,
			mode: input.mode,
			read_only: input.readOnly,
			final_assistant_message: input.finalAssistantMessage,
			recent_user_messages: input.recentUserMessages,
		});
	});

	it("suppresses veto Q for subagents while the primary variant retains it", () => {
		const primary = buildJudgeContext(judgeInput({ subagent: false }));
		const subagent = buildJudgeContext(judgeInput({ subagent: true }));
		assert.notEqual(primary.systemPrompt, subagent.systemPrompt);

		assert.match(primary.systemPrompt ?? "", /Q \(Asked\)/);
		assert.match(primary.systemPrompt ?? "", /ANY question counts/);
		assert.ok(!(subagent.systemPrompt ?? "").includes("Q (Asked)"));
		assert.match(subagent.systemPrompt ?? "", /a question in the final message is NOT a reason to stop/);
		assert.match(subagent.systemPrompt ?? "", /decide and proceed/);
		assert.match(subagent.systemPrompt ?? "", /report the blocker as its deliverable/);
		// Vetoes D and H still apply to subagents.
		assert.match(subagent.systemPrompt ?? "", /D \(Delivered\)/);
		assert.match(subagent.systemPrompt ?? "", /H \(Held\)/);

		// The subagent tool schema withholds Q so the model cannot emit it at all.
		const categoriesOf = (tool: unknown): string[] => {
			const schema = (tool as { parameters: { properties: { category: { anyOf: { const: string }[] } } } }).parameters;
			return schema.properties.category.anyOf.map((variant) => variant.const);
		};
		assert.deepEqual(categoriesOf(primary.tools?.[0]), ["Q", "D", "H", "I", "R", "E"]);
		assert.deepEqual(categoriesOf(subagent.tools?.[0]), ["D", "H", "I", "R", "E"]);
	});
});

describe("CONTINUATION_RUBRIC", () => {
	it("names all six rubric categories and the uncertainty tie-break", () => {
		for (const marker of ["Q (Asked)", "D (Delivered)", "H (Held)", "I (Intent)", "R (Remaining)", "E (Error)"]) {
			assert.ok(CONTINUATION_RUBRIC.includes(marker), `missing ${marker}`);
		}
		assert.match(CONTINUATION_RUBRIC, /when uncertain, do NOT retrigger/);
		assert.match(CONTINUATION_RUBRIC, /one keystroke/);
	});

	it("is a usable prompt rather than a template", () => {
		assert.equal(CONTINUATION_RUBRIC, buildRubric(false));
		assert.ok(!CONTINUATION_RUBRIC.includes("{{"));
	});

	// The stated vetoes and the offered categories are one decision; drift between
	// them is what silently re-enables Q for runs that have no user to answer it.
	it("keeps the stated Q veto and the offered Q category in lockstep", () => {
		for (const subagent of [false, true]) {
			assert.equal(buildRubric(subagent).includes("Q (Asked)"), offeredCategories(subagent).includes("Q"));
		}
	});
});

describe("recentUserMessages", () => {
	function sessionManager(entries: unknown[]): ExtensionContext["sessionManager"] {
		return { getEntries: () => entries } as ExtensionContext["sessionManager"];
	}

	it("returns only user-role messages, most-recent-last, respecting the limit", () => {
		const entries = [
			{ type: "message", message: { role: "user", content: "first" } },
			{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "reply" }] } },
			{ type: "custom", data: {} },
			{ type: "message", message: { role: "user", content: [{ type: "text", text: "second" }] } },
			{
				type: "message",
				message: {
					role: "user",
					content: [
						{ type: "text", text: "third " },
						{ type: "text", text: "part" },
					],
				},
			},
		];
		assert.deepEqual(recentUserMessages(sessionManager(entries)), ["first", "second", "third part"]);
		assert.deepEqual(recentUserMessages(sessionManager(entries), 2), ["second", "third part"]);
		assert.deepEqual(recentUserMessages(sessionManager(entries), 1), ["third part"]);
	});

	it("defaults to the five most recent user messages", () => {
		const entries = Array.from({ length: 7 }, (_, i) => ({
			type: "message",
			message: { role: "user", content: `msg-${i}` },
		}));
		assert.deepEqual(recentUserMessages(sessionManager(entries)), ["msg-2", "msg-3", "msg-4", "msg-5", "msg-6"]);
	});
});
