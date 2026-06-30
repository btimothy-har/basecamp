import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, AssistantMessage, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { clearModelAliasProvidersForTesting } from "pi-core/platform/model-aliases.ts";
import {
	buildTitleContext,
	type GenerateTitleCompletionOptions,
	generateTitleCompletion,
	validateTitleResponse,
} from "../title.ts";

function entry(message: unknown): SessionEntry {
	return { type: "message", message } as unknown as SessionEntry;
}

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

	it("returns null for multiline or explanatory output", () => {
		assert.equal(validateTitleResponse("Title One\nTitle Two"), null);
		assert.equal(validateTitleResponse("Title: Hardened Title Generation"), null);
		assert.equal(validateTitleResponse("Title; Hardened Title Generation"), null);
		assert.equal(validateTitleResponse("Hardened Title Generation."), null);
	});

	it("returns null for quoted, markdown, or wrapped output", () => {
		assert.equal(validateTitleResponse('"Hardened Title Generation"'), null);
		assert.equal(validateTitleResponse("**Hardened Title Generation**"), null);
		assert.equal(validateTitleResponse("(Hardened Title Generation)"), null);
	});

	it("returns null for overlength output without truncating", () => {
		const overlength = "one two three four five six";

		assert.equal(validateTitleResponse(overlength), null);
		assert.notEqual(validateTitleResponse(overlength), "one two three four five");
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
		assert.equal(completionOptions?.temperature, 0.2);
		assert.equal(completionOptions?.maxTokens, 32);
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

describe("buildTitleContext", () => {
	it("includes parsed user and assistant text plus the pending prompt", () => {
		const context = buildTitleContext(
			[
				entry({ role: "user", content: "Please harden title generation." }),
				entry({ role: "assistant", content: [{ type: "text", text: "I will inspect the title module." }] }),
			],
			"Add focused tests next.",
		);

		assert.match(context, /\[User\]\nPlease harden title generation\./);
		assert.match(context, /\[Assistant\]\nI will inspect the title module\./);
		assert.match(context, /\[Pending User Prompt\]\nAdd focused tests next\./);
	});

	it("uses the 30 most recent message entries and keeps the pending prompt", () => {
		const entries: SessionEntry[] = [
			...Array.from({ length: 35 }, (_, index) => entry({ role: "user", content: `message ${index + 1}` })),
			{ type: "summary", text: "non-message entry after recent messages" } as unknown as SessionEntry,
			{ type: "checkpoint", text: "another non-message entry" } as unknown as SessionEntry,
		];

		const context = buildTitleContext(entries, "pending prompt after recent messages");

		assert.doesNotMatch(context, /\bmessage 5\b/);
		assert.match(context, /\bmessage 6\b/);
		assert.match(context, /\bmessage 35\b/);
		assert.match(context, /\[Pending User Prompt\]\npending prompt after recent messages/);
	});

	it("keeps newest recent messages when the context budget is exceeded", () => {
		const largeMessage = (index: number) =>
			[
				`oversized message ${index}`,
				...Array.from({ length: 80 }, (_, line) => `detail ${line} ${"x".repeat(40)}`),
			].join("\n");
		const entries = Array.from({ length: 12 }, (_, index) => entry({ role: "user", content: largeMessage(index + 1) }));

		const context = buildTitleContext(entries);

		assert.ok(context.length <= 8_000, `context length ${context.length} exceeded bound`);
		assert.doesNotMatch(context, /\boversized message 1\b/);
		assert.doesNotMatch(context, /\boversized message 2\b/);
		assert.doesNotMatch(context, /\boversized message 3\b/);
		assert.match(context, /\boversized message 4\b/);
		assert.match(context, /\boversized message 12\b/);
		assert.match(context, /…\n\n\[User\]\noversized message 5/);
		assert.ok(context.indexOf("oversized message 4") < context.indexOf("oversized message 5"));
		assert.ok(context.indexOf("oversized message 5") < context.indexOf("oversized message 12"));
	});

	it("represents tool calls as compact metadata and summarized args", () => {
		const context = buildTitleContext([
			entry({
				role: "assistant",
				content: [
					{ type: "text", text: "Running tests." },
					{
						type: "toolCall",
						name: "bash",
						arguments: {
							command: "npm --prefix core/pi run test:session",
							nested: { path: "core/pi/src/session/tests/title.test.ts", extra: "x".repeat(200) },
						},
					},
				],
			}),
		]);

		assert.match(context, /\[Tool:bash\] call args=/);
		assert.match(context, /"command":"npm --prefix core\/pi run test:session"/);
		assert.match(context, /"nested":\{"path":"core\/pi\/src\/session\/tests\/title\.test\.ts"/);
	});

	it("omits raw tool result body text and includes result metadata with error status", () => {
		const context = buildTitleContext([
			entry({
				role: "toolResult",
				toolName: "bash",
				isError: true,
				content: [{ type: "text", text: "SECRET raw tool output that must not be included" }],
			}),
		]);

		assert.equal(context, "[Tool:bash] result omitted (error)");
		assert.doesNotMatch(context, /SECRET raw tool output/);
	});

	it("reduces fenced code and log-like text while keeping overall output bounded", () => {
		const fencedCode = `Before code\n\`\`\`ts\n${"const secret = 1;\n".repeat(500)}\`\`\`\nAfter code`;
		const logs = Array.from({ length: 500 }, (_, index) => `2026-05-04T12:00:00 INFO noisy line ${index}`).join("\n");
		const repeatedEntries = Array.from({ length: 20 }, () =>
			entry({ role: "user", content: `${fencedCode}\n${logs}` }),
		);
		const context = buildTitleContext(repeatedEntries, "Final pending prompt");

		assert.ok(context.length <= 8_000, `context length ${context.length} exceeded bound`);
		assert.match(context, /\[fenced code block omitted\]/);
		assert.match(context, /\[\d+ log-like lines omitted\]/);
		assert.doesNotMatch(context, /const secret = 1/);
	});
});
