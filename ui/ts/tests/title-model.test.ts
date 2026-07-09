import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { clearModelAliasProvidersForTesting, registerModelAliasProvider } from "#core/platform/model-aliases.ts";
import { resolveTitleModel, resolveTitleModelForContext } from "../title-model.ts";

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
	it("uses the configured title alias", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		registerModelAliasProvider({
			id: "test",
			resolve(alias) {
				return alias === "title" ? "anthropic/claude-3-5-haiku-latest" : undefined;
			},
			list() {
				return [{ alias: "title", model: "anthropic/claude-3-5-haiku-latest", providerId: "test" }];
			},
		});

		assert.equal(resolveTitleModel(), "anthropic/claude-3-5-haiku-latest");
	});

	it("returns undefined when title is not configured", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());

		assert.equal(resolveTitleModel(), undefined);
	});
});

describe("resolveTitleModelForContext", () => {
	it("uses modelRegistry.find for canonical provider/modelId and returns the found model", () => {
		const titleModel = model("anthropic", "claude-3-5-haiku-latest");
		let findArgs: [string, string] | null = null;
		const ctx = {
			model: model("current", "current-model"),
			modelRegistry: {
				find: (provider: string, id: string) => {
					findArgs = [provider, id];
					return titleModel;
				},
				getAll: () => [titleModel],
			},
		} as unknown as ExtensionContext;

		assert.equal(resolveTitleModelForContext(ctx, "anthropic/claude-3-5-haiku-latest"), titleModel);
		assert.deepEqual(findArgs, ["anthropic", "claude-3-5-haiku-latest"]);
	});

	it("returns the unique exact bare model id from getAll", () => {
		const titleModel = model("anthropic", "claude-3-5-haiku-latest");
		const ctx = contextWithModels([model("openai", "gpt-4o-mini"), titleModel]);

		assert.equal(resolveTitleModelForContext(ctx, "claude-3-5-haiku-latest"), titleModel);
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
