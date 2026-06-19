import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { clearModelAliasProvidersForTesting, registerModelAliasProvider } from "../../platform/model-aliases.ts";
import {
	type CompactFunction,
	generateCompactionWithModel,
	resolveCompactionModel,
} from "../runtime/compaction-model.ts";

function model(provider: string, id: string): Model<Api> {
	return { provider, id } as unknown as Model<Api>;
}

function registerCompactionAlias(value: string): void {
	registerModelAliasProvider({
		id: "test",
		resolve(alias) {
			return alias === "compaction" ? value : undefined;
		},
		list() {
			return [{ alias: "compaction", model: value, providerId: "test" }];
		},
	});
}

function contextWithModels(
	models: Model<Api>[],
	currentModel = model("current", "current-model"),
	auth: { ok: true; apiKey: string; headers?: Record<string, string> } | { ok: false; error: string } = {
		ok: true,
		apiKey: "test-key",
		headers: { "x-test": "header" },
	},
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

function compactionEvent(signal = new AbortController().signal) {
	return {
		preparation: { branchEntries: [] } as never,
		customInstructions: "preserve handoff details",
		signal,
	};
}

describe("resolveCompactionModel", () => {
	it("returns undefined when the compaction alias is absent", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const ctx = contextWithModels([model("anthropic", "claude-haiku")]);

		assert.equal(resolveCompactionModel(ctx), undefined);
	});

	it("resolves canonical provider/model aliases", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const alternate = model("anthropic", "claude-haiku");
		registerCompactionAlias("anthropic/claude-haiku");
		const ctx = contextWithModels([alternate]);

		assert.equal(resolveCompactionModel(ctx), alternate);
	});

	it("resolves unique bare model aliases", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const alternate = model("anthropic", "claude-haiku");
		registerCompactionAlias("claude-haiku");
		const ctx = contextWithModels([model("openai", "gpt-4o-mini"), alternate]);

		assert.equal(resolveCompactionModel(ctx), alternate);
	});

	it("falls through when the alias points at a missing model", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		registerCompactionAlias("missing-model");
		const ctx = contextWithModels([model("anthropic", "claude-haiku")]);

		assert.equal(resolveCompactionModel(ctx), undefined);
	});

	it("falls through when the alias is ambiguous", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		registerCompactionAlias("shared-model");
		const ctx = contextWithModels([model("provider-a", "shared-model"), model("provider-b", "shared-model")]);

		assert.equal(resolveCompactionModel(ctx), undefined);
	});

	it("falls through when the alias resolves to the current model", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const current = model("anthropic", "claude-sonnet");
		registerCompactionAlias("anthropic/claude-sonnet");
		const ctx = contextWithModels([model("anthropic", "claude-sonnet")], current);

		assert.equal(resolveCompactionModel(ctx), undefined);
	});
});

describe("generateCompactionWithModel", () => {
	it("returns undefined without calling auth or compact when no alias is configured", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		let authCalled = false;
		const ctx = {
			...contextWithModels([model("anthropic", "claude-haiku")]),
			modelRegistry: {
				find: () => undefined,
				getAll: () => [],
				getApiKeyAndHeaders: async () => {
					authCalled = true;
					return { ok: true, apiKey: "test-key", headers: {} };
				},
			},
		} as unknown as ExtensionContext;
		let compactCalled = false;
		const compact: CompactFunction = async () => {
			compactCalled = true;
			return { summary: "unexpected" } as never;
		};

		assert.equal(await generateCompactionWithModel(compactionEvent(), ctx, compact), undefined);
		assert.equal(authCalled, false);
		assert.equal(compactCalled, false);
	});

	it("calls compact with the alternate model, auth, custom instructions, and signal", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const alternate = model("anthropic", "claude-haiku");
		registerCompactionAlias("anthropic/claude-haiku");
		const ctx = contextWithModels([alternate]);
		const signal = new AbortController().signal;
		const event = compactionEvent(signal);
		const compactionResult = { summary: "compacted" } as never;
		let compactArgs: Parameters<CompactFunction> | undefined;
		const compact: CompactFunction = async (...args) => {
			compactArgs = args;
			return compactionResult;
		};

		const result = await generateCompactionWithModel(event, ctx, compact);

		assert.deepEqual(result, { compaction: compactionResult });
		assert.equal(compactArgs?.[0], event.preparation);
		assert.equal(compactArgs?.[1], alternate);
		assert.equal(compactArgs?.[2], "test-key");
		assert.deepEqual(compactArgs?.[3], { "x-test": "header" });
		assert.equal(compactArgs?.[4], "preserve handoff details");
		assert.equal(compactArgs?.[5], signal);
	});

	it("falls through on auth failures without calling compact", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const alternate = model("anthropic", "claude-haiku");
		registerCompactionAlias("anthropic/claude-haiku");
		const ctx = contextWithModels([alternate], model("current", "current-model"), { ok: false, error: "missing auth" });
		let compactCalled = false;
		const compact: CompactFunction = async () => {
			compactCalled = true;
			return { summary: "unexpected" } as never;
		};

		assert.equal(await generateCompactionWithModel(compactionEvent(), ctx, compact), undefined);
		assert.equal(compactCalled, false);
	});

	it("falls through when alternate compaction throws", async (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const alternate = model("anthropic", "claude-haiku");
		registerCompactionAlias("anthropic/claude-haiku");
		const ctx = contextWithModels([alternate]);
		const compact: CompactFunction = async () => {
			throw new Error("alternate model failed");
		};

		assert.equal(await generateCompactionWithModel(compactionEvent(), ctx, compact), undefined);
	});
});
