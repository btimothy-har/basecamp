import assert from "node:assert/strict";
import { afterEach, describe, it, mock } from "node:test";
import {
	getSessionProductRoleProvider,
	registerSessionProductRoleProvider,
	resetSessionProductRoleForTesting,
	resolveSessionProductRoleOverride,
} from "../product-role.ts";

describe("session product-role seam", () => {
	afterEach(() => {
		mock.restoreAll();
		resetSessionProductRoleForTesting();
	});

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

	it("warns when replacing an existing provider", () => {
		const warn = mock.method(console, "warn", () => {});
		const first = { resolveProductRole: () => "copilot" };
		const second = { resolveProductRole: () => "workstream_agent" };

		registerSessionProductRoleProvider(first);
		registerSessionProductRoleProvider(first);
		registerSessionProductRoleProvider(second);

		assert.equal(resolveSessionProductRoleOverride(), "workstream_agent");
		assert.equal(warn.mock.callCount(), 1);
		assert.deepEqual(warn.mock.calls[0]?.arguments, ["basecamp: replacing an existing session product-role provider"]);
	});
});
