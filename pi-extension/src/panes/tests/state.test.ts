import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { getPaneState, isCompanionActive } from "../state.ts";

describe("panes/state", () => {
	afterEach(() => {
		const state = getPaneState();
		state.paneId = null;
		state.currentCwd = null;
		state.unsubscribeWorkspace = null;
	});

	describe("isCompanionActive", () => {
		it("returns false when no pane is open", () => {
			getPaneState().paneId = null;
			assert.equal(isCompanionActive(), false);
		});

		it("returns true once a pane id is set", () => {
			getPaneState().paneId = "%7";
			assert.equal(isCompanionActive(), true);
		});
	});
});
