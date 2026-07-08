import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolveModel } from "../model-resolution.ts";

describe("resolveModel", () => {
	it("passes through reserved model strategies", () => {
		const deps = {
			resolveModelAlias: (alias: string) => (alias === "inherit" || alias === "default" ? "provider/alias" : undefined),
		};

		assert.equal(resolveModel("default", { provider: "anthropic", id: "claude-sonnet" }, deps), undefined);
		assert.equal(resolveModel("inherit", undefined, deps), undefined);
		assert.equal(
			resolveModel("inherit", { provider: "anthropic", id: "claude-sonnet" }, deps),
			"anthropic/claude-sonnet",
		);
	});

	it("resolves configured aliases and falls back to explicit model strings", () => {
		const deps = {
			resolveModelAlias: (alias: string) => (alias === "fast" ? "anthropic/claude-3-5-haiku-latest" : undefined),
		};

		assert.equal(resolveModel("fast", undefined, deps), "anthropic/claude-3-5-haiku-latest");
		assert.equal(resolveModel("openai/gpt-4.1", undefined, deps), "openai/gpt-4.1");
	});
});
