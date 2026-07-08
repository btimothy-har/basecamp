import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { isCopilotLaunch, resetCopilotLaunchForTesting, setCopilotLaunchReader } from "../copilot-launch.ts";

afterEach(resetCopilotLaunchForTesting);

describe("copilot launch reader", () => {
	it("returns false when no reader is registered", () => {
		assert.equal(isCopilotLaunch(), false);
	});

	it("reflects the registered reader", () => {
		setCopilotLaunchReader(() => true);
		assert.equal(isCopilotLaunch(), true);

		setCopilotLaunchReader(() => false);
		assert.equal(isCopilotLaunch(), false);
	});

	it("degrades to false when the reader throws", () => {
		setCopilotLaunchReader(() => {
			throw new Error("boom");
		});
		assert.equal(isCopilotLaunch(), false);
	});
});
