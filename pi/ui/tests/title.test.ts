import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, AssistantMessage, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { clearModelAliasProvidersForTesting } from "#core/platform/model-aliases.ts";
import { type GenerateTitleCompletionOptions, generateTitleCompletion, validateTitleResponse } from "../title.ts";

function model(provider: string, id: string): Model<Api> {
	return { provider, id, name: id, api: "test-api" } as unknown as Model<Api>;
}

function assistantMessage(content: AssistantMessage["content"]): AssistantMessage {
	return {
		role: "assistant",
		content,
		api: "test-api",
		provider: "test-provider",
		model: "test-model",
		usage: {
			input: 0,
			output: 0,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 0,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "stop",
		timestamp: Date.now(),
	};
}

describe("validateTitleResponse", () => {
	it("accepts valid short titles with whitespace normalized", () => {
		assert.equal(validateTitleResponse("  Hardened   Title\tGeneration  "), "Hardened Title Generation");
		assert.equal(validateTitleResponse("one two three four five"), "one two three four five");
	});

	it("returns null for empty or whitespace output", () => {
		assert.equal(validateTitleResponse(""), null);
		assert.equal(validateTitleResponse("  \n\t  "), null);
	});

	it("returns null for exact null output", () => {
		assert.equal(validateTitleResponse("null"), null);
		assert.equal(validateTitleResponse(" NULL "), null);
	});

	it("returns null for titles below the word-count floor", () => {
		assert.equal(validateTitleResponse("Fix"), null);
		assert.equal(validateTitleResponse("Update"), null);
	});

	it("sanitizes multiline or explanatory output", () => {
		assert.equal(validateTitleResponse("Title One\nTitle Two"), "Title One");
		assert.equal(validateTitleResponse("Title: Hardened Title Generation"), "Title Hardened Title Generation");
		assert.equal(validateTitleResponse("Hardened Title Generation."), "Hardened Title Generation");
	});

	it("sanitizes quoted, markdown, or wrapped output", () => {
		assert.equal(validateTitleResponse('"Hardened Title Generation"'), "Hardened Title Generation");
		assert.equal(validateTitleResponse("**Hardened Title Generation**"), "Hardened Title Generation");
		assert.equal(validateTitleResponse("(Hardened Title Generation)"), "Hardened Title Generation");
	});

	it("truncates overlength output to six words", () => {
		assert.equal(validateTitleResponse("one two three four five six seven"), "one two three four five six");
		assert.equal(validateTitleResponse("one two three four five six"), "one two three four five six");
	});
});

describe("generateTitleCompletion", () => {
	it("passes the parent model and auth headers to completion options and parses a set_title tool call", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const parentModel = model("current", "current-model");
		let authModel: Model<Api> | undefined;
		let completionModel: Model<Api> | undefined;
		let completionOptions: Parameters<NonNullable<GenerateTitleCompletionOptions["complete"]>>[2] | undefined;
		let promptContent = "";
		let toolNames: string[] = [];
		const ctx = {
			model: parentModel,
			modelRegistry: {
				getApiKeyAndHeaders: async (requestedModel: Model<Api>) => {
					authModel = requestedModel;
					return { ok: true, apiKey: "test-key", headers: { "x-test": "header" } };
				},
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async (
			requestedModel,
			context,
			options,
		) => {
			completionModel = requestedModel;
			completionOptions = options;
			promptContent = String(context.messages.at(0)?.content ?? "");
			toolNames = context.tools?.map((tool) => tool.name) ?? [];
			return assistantMessage([
				{
					type: "toolCall",
					id: "1",
					name: "set_title",
					arguments: { title: "Hardened Title Generation" },
				},
			]);
		};

		const result = await generateTitleCompletion(ctx, "session context", undefined, { complete });

		assert.equal(result, "Hardened Title Generation");
		assert.equal(validateTitleResponse(result), "Hardened Title Generation");
		assert.equal(authModel, parentModel);
		assert.equal(completionModel, parentModel);
		assert.equal(completionOptions?.apiKey, "test-key");
		assert.deepEqual(completionOptions?.headers, { "x-test": "header" });
		assert.equal(completionOptions?.temperature, 0);
		assert.equal(completionOptions?.maxTokens, undefined);
		assert.ok(completionOptions?.signal instanceof AbortSignal);
		assert.match(promptContent, /session context/);
		assert.deepEqual(toolNames, ["set_title"]);
	});

	it("returns a null-equivalent string when the set_title tool reports null", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "test-key", headers: {} }),
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async () =>
			assistantMessage([{ type: "toolCall", id: "1", name: "set_title", arguments: { title: null } }]);

		const result = await generateTitleCompletion(ctx, "context", undefined, { complete });

		assert.equal(validateTitleResponse(result), null);
	});

	it("returns a null-equivalent string when the response has no tool call", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "test-key", headers: {} }),
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async () =>
			assistantMessage([{ type: "text", text: "Unexpected Title" }]);

		const result = await generateTitleCompletion(ctx, "context", undefined, { complete });

		assert.equal(validateTitleResponse(result), null);
	});

	it("returns a null-equivalent string when the tool call has the wrong name", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "test-key", headers: {} }),
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async () =>
			assistantMessage([{ type: "toolCall", id: "1", name: "other_tool", arguments: { title: "Unexpected Title" } }]);

		const result = await generateTitleCompletion(ctx, "context", undefined, { complete });

		assert.equal(validateTitleResponse(result), null);
	});

	it("rejects auth failures without invoking completion", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				getApiKeyAndHeaders: async () => ({ ok: false, error: "missing auth" }),
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		let completeCalled = false;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async () => {
			completeCalled = true;
			return assistantMessage([{ type: "text", text: "Unexpected Title" }]);
		};

		await assert.rejects(generateTitleCompletion(ctx, "context", undefined, { complete }), /missing auth/);
		assert.equal(completeCalled, false);
	});

	it("rejects when no model is available", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = {
			model: undefined,
			modelRegistry: {
				getApiKeyAndHeaders: async () => {
					throw new Error("auth should not be requested");
				},
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async () =>
			assistantMessage([{ type: "text", text: "Unexpected Title" }]);

		await assert.rejects(generateTitleCompletion(ctx, "context", undefined, { complete }), /no model available/);
	});

	it("passes a completion signal that aborts on the configured timeout", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "test-key", headers: {} }),
				find: () => undefined,
				getAll: () => [],
			},
		} as unknown as ExtensionContext;
		let completionSignal: AbortSignal | undefined;
		const complete: NonNullable<GenerateTitleCompletionOptions["complete"]> = async (_model, _context, options) => {
			completionSignal = options?.signal;
			return new Promise<AssistantMessage>((_resolve, reject) => {
				options?.signal?.addEventListener("abort", () => reject(options.signal?.reason), { once: true });
			});
		};

		await assert.rejects(generateTitleCompletion(ctx, "context", undefined, { complete, timeoutMs: 1 }), /timeout/);
		assert.equal(completionSignal?.aborted, true);
	});
});
