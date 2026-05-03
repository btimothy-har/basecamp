import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { clearModelAliasProvidersForTesting, registerModelAliasProvider } from "../../platform/model-aliases.ts";
import { resolveModel } from "../src/agents/model-resolution.ts";

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

		assert.equal(resolveModel("default", { provider: "anthropic", id: "claude-sonnet" }), undefined);
		assert.equal(resolveModel("inherit", undefined), undefined);
		assert.equal(resolveModel("inherit", { provider: "anthropic", id: "claude-sonnet" }), "anthropic/claude-sonnet");
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

		assert.equal(resolveModel("fast", undefined), "anthropic/claude-3-5-haiku-latest");
		assert.equal(resolveModel("openai/gpt-4.1", undefined), "openai/gpt-4.1");
	});
});
