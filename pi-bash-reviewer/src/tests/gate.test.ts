import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { AssistantMessage, Model } from "@earendil-works/pi-ai";
import {
	buildGateContext,
	GATE_TOOL,
	type GateDecision,
	parseGateResponse,
	RULESET,
	runGate,
} from "../reviewer/gate.ts";

function assistantWithToolCall(name: string, args: Record<string, unknown>): AssistantMessage {
	return {
		role: "assistant",
		content: [{ type: "toolCall", id: "call-1", name, arguments: args }],
		api: "anthropic-messages",
		provider: "anthropic",
		model: "claude-haiku",
		usage: {
			input: 0,
			output: 0,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 0,
			cost: {
				input: 0,
				output: 0,
				cacheRead: 0,
				cacheWrite: 0,
				total: 0,
			},
		},
		stopReason: "toolUse",
		timestamp: 1,
	};
}

function assertParsesDecision(decision: GateDecision): void {
	assert.deepEqual(parseGateResponse(assistantWithToolCall("gate_decision", decision)), decision);
}

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

describe("parseGateResponse", () => {
	it("parses valid approve, route_to_user, and deny gate_decision tool calls", () => {
		assertParsesDecision({ decision: "approve", risk: "none", reason: "This matches the requested local inspection." });
		assertParsesDecision({
			decision: "route_to_user",
			risk: "destructive",
			reason: "Force-push requires human confirmation.",
		});
		assertParsesDecision({ decision: "deny", risk: "destructive", reason: "The command would publish a token." });
	});

	it("returns null when the gate_decision tool call is missing", () => {
		assert.equal(parseGateResponse(assistantWithToolCall("other_tool", { decision: "approve" })), null);
		assert.equal(
			parseGateResponse({
				...assistantWithToolCall("gate_decision", { decision: "approve", risk: "none", reason: "ok" }),
				content: [{ type: "text", text: "approve" }],
			}),
			null,
		);
	});

	it("returns null when gate_decision arguments are schema-invalid", () => {
		assert.equal(
			parseGateResponse(
				assistantWithToolCall("gate_decision", { decision: "allow", risk: "none", reason: "Invalid enum." }),
			),
			null,
		);
		assert.equal(
			parseGateResponse(assistantWithToolCall("gate_decision", { decision: "approve", risk: "none" })),
			null,
		);
	});

	it("returns null when there is not exactly one gate_decision tool call", () => {
		const decision = { decision: "approve", risk: "none", reason: "ok" };
		assert.equal(
			parseGateResponse({
				...assistantWithToolCall("gate_decision", decision),
				content: [
					{ type: "toolCall", id: "call-1", name: "gate_decision", arguments: decision },
					{ type: "toolCall", id: "call-2", name: "gate_decision", arguments: decision },
				],
			}),
			null,
		);
		assert.equal(
			parseGateResponse({
				...assistantWithToolCall("gate_decision", decision),
				content: [
					{ type: "toolCall", id: "call-1", name: "gate_decision", arguments: decision },
					{ type: "toolCall", id: "call-2", name: "other_tool", arguments: {} },
				],
			}),
			null,
		);
	});
});

describe("runGate", () => {
	it("returns parsed decisions from an injected complete function", async () => {
		for (const decision of [
			{ decision: "approve", risk: "none", reason: "The command is safe." },
			{ decision: "route_to_user", risk: "destructive", reason: "The command publishes externally." },
			{ decision: "deny", risk: "destructive", reason: "The command leaks a secret." },
		] satisfies GateDecision[]) {
			const result = await runGate({
				model: fakeModel,
				auth: { apiKey: "test-key" },
				context: buildGateContext(["Please inspect status."], "git status"),
				complete: async () => assistantWithToolCall("gate_decision", decision),
			});

			assert.deepEqual(result, decision);
		}
	});

	it("returns null when complete throws", async () => {
		const result = await runGate({
			model: fakeModel,
			auth: { apiKey: "test-key" },
			context: buildGateContext([], "git push --force"),
			complete: async () => {
				throw new Error("provider unavailable");
			},
		});

		assert.equal(result, null);
	});
});

describe("buildGateContext", () => {
	it("sets the ruleset, includes the gate tool, and embeds recent messages plus command as JSON", () => {
		const recentHumanMessages = ["Check the repo status.", "Now make a commit."];
		const command = "git commit -m 'test'";
		const context = buildGateContext(recentHumanMessages, command);

		assert.equal(context.systemPrompt, RULESET);
		assert.deepEqual(context.tools, [GATE_TOOL]);
		assert.equal(context.messages.length, 1);
		const message = context.messages[0];
		assert.equal(message?.role, "user");
		const content = message?.content;
		assert.equal(typeof content, "string");
		if (typeof content !== "string") throw new Error("expected string content");
		assert.match(content, /"recent_human_messages"/);
		assert.match(content, /"command"/);
		assert.ok(content.includes(JSON.stringify(command)));
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.deepEqual(payload, { recent_human_messages: recentHumanMessages, command });
	});
});
