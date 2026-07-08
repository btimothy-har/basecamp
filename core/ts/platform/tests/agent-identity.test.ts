import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
	deriveCurrentAgentHandle,
	getAgentIdentityProvider,
	registerAgentIdentityProvider,
	resetAgentIdentityForTesting,
} from "../agent-identity.ts";

const ctx = { sessionManager: { getSessionId: () => "session-1" } } as unknown as ExtensionContext;

describe("agent identity seam", () => {
	afterEach(resetAgentIdentityForTesting);

	it("returns null when no provider is registered", () => {
		resetAgentIdentityForTesting();
		assert.equal(getAgentIdentityProvider(), null);
		assert.equal(deriveCurrentAgentHandle(ctx), null);
	});

	it("derives the handle through a registered provider", () => {
		registerAgentIdentityProvider({ deriveHandle: (c) => `handle-for-${c.sessionManager.getSessionId()}` });
		assert.equal(deriveCurrentAgentHandle(ctx), "handle-for-session-1");
	});

	it("degrades to null when the provider throws", () => {
		registerAgentIdentityProvider({
			deriveHandle: () => {
				throw new Error("boom");
			},
		});
		assert.equal(deriveCurrentAgentHandle(ctx), null);
	});
});
