import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { clearModelAliasProvidersForTesting, registerModelAliasProvider } from "../../platform/model-aliases.ts";
import { resolveTitleModel } from "../src/ui/title-model.ts";

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

	it("returns undefined when fast is not configured", () => {
		clearModelAliasProvidersForTesting();

		assert.equal(resolveTitleModel(), undefined);
	});
});
