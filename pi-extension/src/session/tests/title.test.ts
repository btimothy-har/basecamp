import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, AssistantMessage, Model } from "@mariozechner/pi-ai";
import type { ExtensionContext, SessionEntry } from "@mariozechner/pi-coding-agent";
import { clearModelAliasProvidersForTesting } from "../../platform/model-aliases.ts";
import {
	buildTitleContext,
	type GenerateTitleCompletionOptions,
	generateTitleCompletion,
	validateTitleResponse,
} from "../ui/title.ts";

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
	it("passes the parent model and auth headers to completion options and joins text blocks", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const parentModel = model("current", "current-model");
		let authModel: Model<Api> | undefined;
		let completionModel: Model<Api> | undefined;
		let completionOptions: Parameters<NonNullable<GenerateTitleCompletionOptions["complete"]>>[2] | undefined;
		let promptContent = "";
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
			return assistantMessage([
				{ type: "text", text: "Focused" },
				{ type: "thinking", thinking: "hidden" },
				{ type: "text", text: "Title" },
			]);
		};

		const result = await generateTitleCompletion(ctx, "session context", undefined, { complete });

		assert.equal(result, "Focused\nTitle");
		assert.equal(authModel, parentModel);
		assert.equal(completionModel, parentModel);
		assert.equal(completionOptions?.apiKey, "test-key");
		assert.deepEqual(completionOptions?.headers, { "x-test": "header" });
		assert.equal(completionOptions?.temperature, 0.2);
		assert.equal(completionOptions?.maxTokens, 32);
		assert.ok(completionOptions?.signal instanceof AbortSignal);
		assert.match(promptContent, /session context/);
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
							command: "npm --prefix pi-extension run test:session",
							nested: { path: "pi-extension/src/session/tests/title.test.ts", extra: "x".repeat(200) },
						},
					},
				],
			}),
		]);

		assert.match(context, /\[Tool:bash\] call args=/);
		assert.match(context, /"command":"npm --prefix pi-extension run test:session"/);
		assert.match(context, /"nested":\{"path":"pi-extension\/src\/session\/tests\/title\.test\.ts"/);
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
