import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	clearModelAliasProvidersForTesting,
	listModelAliases,
	registerModelAliasProvider,
	resolveModelAlias,
} from "../model-aliases.ts";

describe("model alias provider registry", () => {
	it("resolves aliases from the most recently registered matching provider", (t) => {
		clearModelAliasProvidersForTesting();
		t.after(() => clearModelAliasProvidersForTesting());

		registerModelAliasProvider({
			id: "first",
			resolve(alias) {
				return alias === "fast" ? "provider/first" : undefined;
			},
			list() {
				return [{ alias: "fast", model: "provider/first", providerId: "first" }];
			},
		});
		registerModelAliasProvider({
			id: "second",
			resolve(alias) {
				return alias === "fast" ? "provider/second" : undefined;
			},
			list() {
				return [{ alias: "fast", model: "provider/second", providerId: "second" }];
			},
		});

		assert.equal(resolveModelAlias("fast"), "provider/second");
		assert.equal(resolveModelAlias("missing"), undefined);
	});

	it("lists aliases from all providers and can clear providers for tests", () => {
		clearModelAliasProvidersForTesting();

		registerModelAliasProvider({
			id: "native",
			resolve(alias) {
				return alias === "fast" ? "provider/fast" : undefined;
			},
			list() {
				return [
					{ alias: "fast", model: "provider/fast", providerId: "native" },
					{ alias: "strong", model: "provider/strong", providerId: "native" },
				];
			},
		});

		assert.deepEqual(listModelAliases(), [
			{ alias: "fast", model: "provider/fast", providerId: "native" },
			{ alias: "strong", model: "provider/strong", providerId: "native" },
		]);

		clearModelAliasProvidersForTesting();

		assert.deepEqual(listModelAliases(), []);
		assert.equal(resolveModelAlias("fast"), undefined);
	});
});
