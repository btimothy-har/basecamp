import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { resolveModel } from "#core/swarm/agents/model-resolution.ts";

describe("resolveModel", () => {
	it("passes through reserved model strategies", () => {
		const deps = {
			resolveModelAlias: (alias: string) => (alias === "inherit" || alias === "default" ? "provider/alias" : undefined),
		};

		assert.deepEqual(resolveModel("default", { provider: "anthropic", id: "claude-sonnet" }, deps), {
			model: undefined,
			aliasFallback: null,
		});
		assert.deepEqual(resolveModel("inherit", undefined, deps), { model: undefined, aliasFallback: null });
		assert.deepEqual(resolveModel("inherit", { provider: "anthropic", id: "claude-sonnet" }, deps), {
			model: "anthropic/claude-sonnet",
			aliasFallback: null,
		});
	});

	it("resolves configured aliases and passes through explicit model ids", () => {
		const deps = {
			resolveModelAlias: (alias: string) => (alias === "fast" ? "anthropic/claude-3-5-haiku-latest" : undefined),
		};

		assert.deepEqual(resolveModel("fast", undefined, deps), {
			model: "anthropic/claude-3-5-haiku-latest",
			aliasFallback: null,
		});
		assert.deepEqual(resolveModel("openai/gpt-4.1", undefined, deps), {
			model: "openai/gpt-4.1",
			aliasFallback: null,
		});
	});

	it("degrades an unresolvable slashless alias to the parent model and reports it", () => {
		const deps = { resolveModelAlias: () => undefined };

		// With parent context the persona rides the session model instead of failing the
		// child launch on a nonsense --model id.
		assert.deepEqual(resolveModel("complex", { provider: "anthropic", id: "claude-sonnet" }, deps), {
			model: "anthropic/claude-sonnet",
			aliasFallback: "complex",
		});
		// Without parent context there is nothing to inherit: no --model flag at all.
		assert.deepEqual(resolveModel("complex", undefined, deps), {
			model: undefined,
			aliasFallback: "complex",
		});
		// Slash-bearing strings are explicit ids, never treated as failed aliases.
		assert.deepEqual(resolveModel("openai/unknown-model", { provider: "anthropic", id: "claude-sonnet" }, deps), {
			model: "openai/unknown-model",
			aliasFallback: null,
		});
	});
});
