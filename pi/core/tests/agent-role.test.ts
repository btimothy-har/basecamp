import assert from "node:assert/strict";
import { afterEach, describe, it, mock } from "node:test";
import {
	getAgentRoleProvider,
	registerAgentRoleProvider,
	resetAgentRoleForTesting,
	resolveAgentRoleOverride,
} from "../agent-role.ts";

describe("session agent-role seam", () => {
	afterEach(() => {
		mock.restoreAll();
		resetAgentRoleForTesting();
	});

	it("returns null when no provider is registered", () => {
		resetAgentRoleForTesting();
		assert.equal(getAgentRoleProvider(), null);
		assert.equal(resolveAgentRoleOverride(), null);
	});

	it("resolves a agent-role override through a registered provider", () => {
		registerAgentRoleProvider({ resolveAgentRole: () => "workstream_agent" });
		assert.equal(resolveAgentRoleOverride(), "workstream_agent");
	});

	it("degrades to null when the provider throws", () => {
		registerAgentRoleProvider({
			resolveAgentRole: () => {
				throw new Error("boom");
			},
		});
		assert.equal(resolveAgentRoleOverride(), null);
	});

	it("warns when replacing an existing provider", () => {
		const warn = mock.method(console, "warn", () => {});
		const first = { resolveAgentRole: () => "copilot" };
		const second = { resolveAgentRole: () => "workstream_agent" };

		registerAgentRoleProvider(first);
		registerAgentRoleProvider(first);
		registerAgentRoleProvider(second);

		assert.equal(resolveAgentRoleOverride(), "workstream_agent");
		assert.equal(warn.mock.callCount(), 1);
		assert.deepEqual(warn.mock.calls[0]?.arguments, ["basecamp: replacing an existing session agent-role provider"]);
	});
});
