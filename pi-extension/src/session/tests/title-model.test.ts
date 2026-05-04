import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, Model } from "@mariozechner/pi-ai";
import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import { clearModelAliasProvidersForTesting, registerModelAliasProvider } from "../../platform/model-aliases.ts";
import { resolveTitleModel, resolveTitleModelForContext } from "../ui/title-model.ts";

function model(provider: string, id: string): Model<Api> {
	return { provider, id } as unknown as Model<Api>;
}

function contextWithModels(models: Model<Api>[], currentModel = model("current", "current-model")): ExtensionContext {
	return {
		model: currentModel,
		modelRegistry: {
			find: (provider: string, id: string) =>
				models.find((candidate) => candidate.provider === provider && candidate.id === id),
			getAll: () => models,
		},
	} as unknown as ExtensionContext;
}

describe("resolveTitleModel", () => {
	it("uses the configured fast alias", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		registerModelAliasProvider({
			id: "test",
			resolve(alias) {
				return alias === "fast" ? "anthropic/claude-3-5-haiku-latest" : undefined;
			},
			list() {
				return [{ alias: "fast", model: "anthropic/claude-3-5-haiku-latest", providerId: "test" }];
			},
		});

		assert.equal(resolveTitleModel(), "anthropic/claude-3-5-haiku-latest");
	});

	it("returns undefined when fast is not configured", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());

		assert.equal(resolveTitleModel(), undefined);
	});
});

describe("resolveTitleModelForContext", () => {
	it("uses modelRegistry.find for canonical provider/modelId and returns the found model", () => {
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

		assert.equal(resolveTitleModelForContext(ctx, "anthropic/claude-3-5-haiku-latest"), fast);
		assert.deepEqual(findArgs, ["anthropic", "claude-3-5-haiku-latest"]);
	});

	it("returns the unique exact bare model id from getAll", () => {
		const fast = model("anthropic", "claude-3-5-haiku-latest");
		const ctx = contextWithModels([model("openai", "gpt-4o-mini"), fast]);

		assert.equal(resolveTitleModelForContext(ctx, "claude-3-5-haiku-latest"), fast);
	});

	it("falls back to ctx.model for ambiguous bare model ids", () => {
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("provider-a", "shared-id"), model("provider-b", "shared-id")], current);

		assert.equal(resolveTitleModelForContext(ctx, "shared-id"), current);
	});

	it("falls back to ctx.model for missing bare model ids", () => {
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("anthropic", "claude-3-5-haiku-latest")], current);

		assert.equal(resolveTitleModelForContext(ctx, "missing-model"), current);
	});

	it("falls back to ctx.model when modelName is undefined", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		const current = model("current", "current-model");
		const ctx = contextWithModels([model("anthropic", "claude-3-5-haiku-latest")], current);

		assert.equal(resolveTitleModelForContext(ctx, undefined), current);
	});
});
