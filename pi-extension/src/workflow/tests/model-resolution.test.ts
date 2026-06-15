import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolveModel } from "../../../../pi-swarm/extension/src/agents/model-resolution.ts";
import {
	clearModelAliasProvidersForTesting,
	registerModelAliasProvider,
	resolveModelAlias,
} from "../../platform/model-aliases.ts";

describe("resolveModel", () => {
	it("passes through reserved model strategies", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());
		registerModelAliasProvider({
			id: "test",
			resolve(alias) {
				return alias === "inherit" || alias === "default" ? "provider/alias" : undefined;
			},
			list() {
				return [];
			},
		});

		assert.equal(
			resolveModel("default", { provider: "anthropic", id: "claude-sonnet" }, { resolveModelAlias }),
			undefined,
		);
		assert.equal(resolveModel("inherit", undefined, { resolveModelAlias }), undefined);
		assert.equal(
			resolveModel("inherit", { provider: "anthropic", id: "claude-sonnet" }, { resolveModelAlias }),
			"anthropic/claude-sonnet",
		);
	});

	it("resolves configured aliases and falls back to explicit model strings", (t) => {
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

		assert.equal(resolveModel("fast", undefined, { resolveModelAlias }), "anthropic/claude-3-5-haiku-latest");
		assert.equal(resolveModel("openai/gpt-4.1", undefined, { resolveModelAlias }), "openai/gpt-4.1");
	});
});
