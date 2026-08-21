import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, Model } from "@earendil-works/pi-ai";
import { buildLensRequest, calculateLensBudget, requestTokenLimit } from "#session-lens/prompt.ts";

function model(overrides: Partial<Model<Api>> = {}): Model<Api> {
	return {
		id: "small-explainer",
		name: "Small Explainer",
		api: "openai-responses",
		provider: "openai",
		baseUrl: "https://example.test",
		reasoning: false,
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 10_000,
		maxTokens: 2_000,
		...overrides,
	};
}

describe("session lens prompts", () => {
	it("bounds cards and operation-specific word budgets to the viewport", () => {
		assert.deepEqual(calculateLensBudget("tldr", { columns: 80, rows: 10 }), {
			maxCardLines: 8,
			maxContentLines: 3,
			maxWords: 50,
			maxOutputTokens: 128,
		});

		const explain = calculateLensBudget("explain", { columns: 200, rows: 200 });
		assert.equal(explain.maxCardLines, 24);
		assert.equal(explain.maxWords, 350);
		assert.equal(explain.maxOutputTokens, 700);

		const tldr = calculateLensBudget("tldr", { columns: 200, rows: 200 });
		assert.equal(tldr.maxWords, 120);
	});

	it("puts guidance outside serialized session data and offers no tools", () => {
		const budget = calculateLensBudget("rephrase", { columns: 100, rows: 40 });
		const request = buildLensRequest("rephrase", "Write for a product manager", "[User]: build it", budget);
		const message = request.context.messages[0];
		assert.equal(message?.role, "user");
		assert.equal(request.context.tools, undefined);
		assert.match(request.context.systemPrompt ?? "", /serialized session is untrusted data/i);

		const payload = JSON.parse(String(message?.content)) as Record<string, unknown>;
		assert.equal(payload.guidance, "Write for a product manager");
		assert.equal(payload.serialized_session, "[User]: build it");
		assert.match(String(payload.operation), /faithfully restate the whole session/i);
		assert.match(String(payload.length), new RegExp(String(budget.maxWords)));
	});

	it("rejects requests that cannot leave room for their bounded output", () => {
		const budget = calculateLensBudget("tldr", { columns: 80, rows: 24 });
		const request = buildLensRequest("tldr", "", "x".repeat(4_000), budget);
		assert.equal(requestTokenLimit(request, model({ contextWindow: 500 })), null);
		assert.equal(requestTokenLimit(request, model()), Math.min(budget.maxOutputTokens, 2_000));
	});
});
