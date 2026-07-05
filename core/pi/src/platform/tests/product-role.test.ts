import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import {
	getSessionProductRoleProvider,
	registerSessionProductRoleProvider,
	resetSessionProductRoleForTesting,
	resolveSessionProductRoleOverride,
} from "../product-role.ts";

describe("session product-role seam", () => {
	afterEach(resetSessionProductRoleForTesting);

	it("returns null when no provider is registered", () => {
		resetSessionProductRoleForTesting();
		assert.equal(getSessionProductRoleProvider(), null);
		assert.equal(resolveSessionProductRoleOverride(), null);
	});

	it("resolves a product-role override through a registered provider", () => {
		registerSessionProductRoleProvider({ resolveProductRole: () => "workstream_agent" });
		assert.equal(resolveSessionProductRoleOverride(), "workstream_agent");
	});

	it("degrades to null when the provider throws", () => {
		registerSessionProductRoleProvider({
			resolveProductRole: () => {
				throw new Error("boom");
			},
		});
		assert.equal(resolveSessionProductRoleOverride(), null);
	});
});
