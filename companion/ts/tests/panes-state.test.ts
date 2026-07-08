import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { getPaneState, isCompanionActive, setCompanionActive } from "../panes-state.ts";

describe("panes/state", () => {
	afterEach(() => {
		const state = getPaneState();
		state.provider = null;
		state.paneId = null;
		setCompanionActive(false);
	});

	describe("isCompanionActive", () => {
		it("returns false when companion is not active", () => {
			setCompanionActive(false);
			assert.equal(isCompanionActive(), false);
		});

		it("returns true once setCompanionActive(true) is called", () => {
			setCompanionActive(true);
			assert.equal(isCompanionActive(), true);
		});
	});
});
