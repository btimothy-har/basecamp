import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { clearModelAliasProvidersForTesting, registerModelAliasProvider } from "../index.ts";
import {
	resolveAliasedModel,
	resolveForcedToolChoice,
	resolveModelFromString,
	resolveModelReference,
	resolvePortableReasoningEffort,
} from "../resolution.ts";

function model(provider: string, id: string): Model<Api> {
	return { provider, id } as unknown as Model<Api>;
}

function contextWithModels(
	models: Model<Api>[],
	currentModel = model("current", "current-model"),
	auth: { ok: boolean; apiKey?: string; headers?: Record<string, string> } = { ok: true, apiKey: "test-key" },
): ExtensionContext {
	return {
		model: currentModel,
		modelRegistry: {
			find: (provider: string, id: string) =>
				models.find((candidate) => candidate.provider === provider && candidate.id === id),
			getAll: () => models,
			getApiKeyAndHeaders: async () => auth,
		},
	} as unknown as ExtensionContext;
}

const fakeCompletionModel: Model<Api> = {
	id: "fake-model",
	name: "Fake Model",
	api: "openai-responses",
	provider: "fake-provider",
	baseUrl: "https://example.test",
	reasoning: false,
	input: ["text"],
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
	contextWindow: 128_000,
	maxTokens: 4096,
};

function completionModel(overrides: Partial<Model<Api>>): Model<Api> {
	return { ...fakeCompletionModel, ...overrides };
}

describe("resolveModelFromString", () => {
	it("resolves canonical provider/modelId via modelRegistry.find", () => {
		const fast = model("anthropic", "claude-3-5-haiku-latest");
		let findArgs: [string, string] | null = null;
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				find: (provider: string, id: string) => {
					findArgs = [provider, id];
					return fast;
				},
				getAll: () => [fast],
			},
		} as unknown as ExtensionContext;

		assert.equal(resolveModelFromString(ctx, "anthropic/claude-3-5-haiku-latest"), fast);
		assert.deepEqual(findArgs, ["anthropic", "claude-3-5-haiku-latest"]);
	});

	it("returns the unique exact bare model id from getAll", () => {
		const fast = model("anthropic", "claude-3-5-haiku-latest");
		const ctx = contextWithModels([model("openai", "gpt-4o-mini"), fast]);

		assert.equal(resolveModelFromString(ctx, "claude-3-5-haiku-latest"), fast);
	});

	it("falls back to ctx.model for ambiguous bare model ids", () => {
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("provider-a", "shared-id"), model("provider-b", "shared-id")], current);

		assert.equal(resolveModelFromString(ctx, "shared-id"), current);
	});

	it("falls back to ctx.model for missing bare model ids", () => {
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("anthropic", "claude-3-5-haiku-latest")], current);

		assert.equal(resolveModelFromString(ctx, "missing-model"), current);
	});

	it("falls back to ctx.model when modelName is undefined", () => {
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("anthropic", "claude-3-5-haiku-latest")], current);

		assert.equal(resolveModelFromString(ctx, undefined), current);
	});
});

describe("resolveModelReference", () => {
	it("strictly resolves canonical provider/modelId references", () => {
		const fast = model("anthropic", "claude-3-5-haiku-latest");
		const ctx = contextWithModels([fast]);

		assert.equal(resolveModelReference(ctx, "anthropic/claude-3-5-haiku-latest"), fast);
	});

	it("strictly resolves only unique bare model ids", () => {
		const fast = model("anthropic", "claude-3-5-haiku-latest");
		const ctx = contextWithModels([model("openai", "gpt-4o-mini"), fast]);

		assert.equal(resolveModelReference(ctx, "claude-3-5-haiku-latest"), fast);
	});

	it("returns undefined for missing or ambiguous bare model ids", () => {
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("provider-a", "shared-id"), model("provider-b", "shared-id")], current);

		assert.equal(resolveModelReference(ctx, "shared-id"), undefined);
		assert.equal(resolveModelReference(ctx, "missing-model"), undefined);
	});
});

describe("resolveAliasedModel", () => {
	it("resolves configured aliases to an authenticated concrete model", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const fast = model("anthropic", "claude-3-5-haiku-latest");
		const ctx = contextWithModels([fast], model("current", "current-model"), {
			ok: true,
			headers: { authorization: "Bearer test" },
		});
		registerModelAliasProvider({
			id: "test",
			resolve(alias) {
				return alias === "fast" ? "anthropic/claude-3-5-haiku-latest" : undefined;
			},
			list() {
				return [];
			},
		});

		assert.deepEqual(await resolveAliasedModel(ctx, "fast"), {
			model: fast,
			auth: { apiKey: undefined, headers: { authorization: "Bearer test" } },
		});
	});

	it("returns null when the alias, model, or auth is unavailable", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = contextWithModels([model("anthropic", "claude-3-5-haiku-latest")]);

		assert.equal(await resolveAliasedModel(ctx, "fast"), null);

		registerModelAliasProvider({
			id: "test",
			resolve(alias) {
				return alias === "fast" ? "anthropic/missing" : "anthropic/claude-3-5-haiku-latest";
			},
			list() {
				return [];
			},
		});

		assert.equal(await resolveAliasedModel(ctx, "fast"), null);
		assert.equal(
			await resolveAliasedModel(
				contextWithModels([model("anthropic", "claude-3-5-haiku-latest")], model("current", "current-model"), {
					ok: true,
				}),
				"other",
			),
			null,
		);
	});
});

describe("completion option helpers", () => {
	it("selects forced tool choice shapes by model api", () => {
		assert.deepEqual(resolveForcedToolChoice(completionModel({ api: "anthropic-messages" }), "report_findings"), {
			type: "tool",
			name: "report_findings",
		});
		assert.deepEqual(resolveForcedToolChoice(completionModel({ api: "openai-responses" }), "report_findings"), {
			type: "function",
			name: "report_findings",
		});
		assert.equal(
			resolveForcedToolChoice(completionModel({ api: "openai-codex-responses" }), "report_findings"),
			"required",
		);
		assert.deepEqual(resolveForcedToolChoice(completionModel({ api: "openai-completions" }), "report_findings"), {
			type: "function",
			function: { name: "report_findings" },
		});
	});

	it("uses portable reasoning effort for reasoning models", () => {
		assert.equal(resolvePortableReasoningEffort(completionModel({ reasoning: false })), undefined);
		assert.equal(resolvePortableReasoningEffort(completionModel({ reasoning: true })), "low");
		assert.equal(
			resolvePortableReasoningEffort(completionModel({ reasoning: true, thinkingLevelMap: { minimal: "low" } })),
			"minimal",
		);
		assert.equal(
			resolvePortableReasoningEffort(completionModel({ reasoning: true, thinkingLevelMap: { minimal: null } })),
			"low",
		);
	});
});
