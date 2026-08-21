import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, AssistantMessage, Context, Model, ModelsApiStreamOptions } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { completeLens, type LensCompletionDeps } from "#session-lens/completion.ts";
import { buildLensRequest, calculateLensBudget } from "#session-lens/prompt.ts";
import { LensError } from "#session-lens/types.ts";

function explainer(overrides: Partial<Model<Api>> = {}): Model<Api> {
	return {
		id: "explain-1",
		name: "Explainer",
		api: "openai-responses",
		provider: "openai",
		baseUrl: "https://example.test",
		reasoning: false,
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 20_000,
		maxTokens: 4_000,
		...overrides,
	};
}

function response(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
	return {
		role: "assistant",
		content: [{ type: "text", text: "A clear explanation." }],
		api: "openai-responses",
		provider: "openai",
		model: "explain-1",
		usage: {
			input: 10,
			output: 5,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 15,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "stop",
		timestamp: 1,
		...overrides,
	};
}

interface Harness {
	ctx: ExtensionContext;
	deps: LensCompletionDeps;
	model: Model<Api>;
	authModels: Model<Api>[];
	calls: Array<{ model: Model<Api>; context: Context; options: ModelsApiStreamOptions<Api> | undefined }>;
}

function harness(
	options: { alias?: string; model?: Model<Api>; authError?: string; result?: AssistantMessage; throws?: Error } = {},
): Harness {
	const selectedModel = options.model ?? explainer();
	const authModels: Model<Api>[] = [];
	const calls: Harness["calls"] = [];
	const modelRegistry = {
		getApiKeyAndHeaders: async (requested: Model<Api>) => {
			authModels.push(requested);
			return options.authError
				? { ok: false as const, error: options.authError }
				: { ok: true as const, apiKey: "key" };
		},
		complete: async (requested: Model<Api>, context: Context, completeOptions?: ModelsApiStreamOptions<Api>) => {
			calls.push({ model: requested, context, options: completeOptions });
			if (options.throws) throw options.throws;
			return options.result ?? response();
		},
	};
	return {
		ctx: { model: explainer({ id: "primary-model" }), modelRegistry } as unknown as ExtensionContext,
		deps: {
			resolveAlias: () => options.alias ?? "openai/explain-1",
			resolveModel: () => selectedModel,
			createSessionId: () => "request-session-id",
		},
		model: selectedModel,
		authModels,
		calls,
	};
}

function request() {
	const budget = calculateLensBudget("explain", { columns: 100, rows: 40 });
	return buildLensRequest("explain", "", "[User]: explain this", budget);
}

async function rejectsWithCode(promise: Promise<unknown>, code: LensError["code"]): Promise<void> {
	await assert.rejects(promise, (error: unknown) => error instanceof LensError && error.code === code);
}

describe("completeLens", () => {
	it("uses only the explainer alias with an isolated uncached request", async () => {
		const h = harness();
		const result = await completeLens(h.ctx, request(), new AbortController().signal, h.deps);

		assert.equal(result.text, "A clear explanation.");
		assert.equal(result.model, "openai/explain-1");
		assert.equal(result.truncated, false);
		assert.deepEqual(h.authModels, [h.model]);
		assert.equal(h.calls.length, 1);
		assert.equal(h.calls[0]?.model, h.model);
		assert.equal(h.calls[0]?.context.tools, undefined);
		assert.equal(h.calls[0]?.options?.cacheRetention, "none");
		assert.equal(h.calls[0]?.options?.sessionId, "request-session-id");
		assert.equal(typeof h.calls[0]?.options?.maxTokens, "number");
	});

	it("marks provider length stops as truncated output", async () => {
		const h = harness({ result: response({ stopReason: "length" }) });
		const result = await completeLens(h.ctx, request(), new AbortController().signal, h.deps);
		assert.equal(result.truncated, true);
	});

	it("never falls back when the explainer alias or its model is missing", async () => {
		const missingAlias = harness({ alias: "" });
		missingAlias.deps.resolveAlias = () => undefined;
		await rejectsWithCode(
			completeLens(missingAlias.ctx, request(), new AbortController().signal, missingAlias.deps),
			"configuration",
		);
		assert.equal(missingAlias.calls.length, 0);

		const missingModel = harness();
		missingModel.deps.resolveModel = () => undefined;
		await rejectsWithCode(
			completeLens(missingModel.ctx, request(), new AbortController().signal, missingModel.deps),
			"configuration",
		);
		assert.equal(missingModel.calls.length, 0);
	});

	it("fails context preflight before resolving authentication", async () => {
		const h = harness({ model: explainer({ contextWindow: 10 }) });
		await rejectsWithCode(completeLens(h.ctx, request(), new AbortController().signal, h.deps), "context-window");
		assert.equal(h.authModels.length, 0);
		assert.equal(h.calls.length, 0);
	});

	it("reports authentication, provider, empty, and cancellation failures", async () => {
		const auth = harness({ authError: "login required" });
		await rejectsWithCode(completeLens(auth.ctx, request(), new AbortController().signal, auth.deps), "configuration");

		const provider = harness({ result: response({ stopReason: "error", errorMessage: "rate limited" }) });
		await rejectsWithCode(
			completeLens(provider.ctx, request(), new AbortController().signal, provider.deps),
			"provider",
		);

		const thrown = harness({ throws: new Error("network unavailable") });
		await rejectsWithCode(completeLens(thrown.ctx, request(), new AbortController().signal, thrown.deps), "provider");

		const providerAbort = harness({ result: response({ stopReason: "aborted" }) });
		await rejectsWithCode(
			completeLens(providerAbort.ctx, request(), new AbortController().signal, providerAbort.deps),
			"aborted",
		);

		const empty = harness({ result: response({ content: [] }) });
		await rejectsWithCode(completeLens(empty.ctx, request(), new AbortController().signal, empty.deps), "empty");

		const controller = new AbortController();
		controller.abort();
		const aborted = harness();
		await rejectsWithCode(completeLens(aborted.ctx, request(), controller.signal, aborted.deps), "aborted");
	});
});
