import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import registerCompanionPackage from "../index.ts";
import { isCompanionActive, setCompanionActive } from "../panes/state.ts";
import { createMockPi, resetPaneState } from "./panes-harness.ts";

describe("panes/registerPanes", () => {
	afterEach(() => {
		delete process.env.TMUX;
		delete process.env.TMUX_PANE;
		delete process.env.HERDR_ENV;
		delete process.env.HERDR_PANE_ID;
		delete process.env.HERDR_SOCKET_PATH;
		delete process.env.BASECAMP_AGENT_DEPTH;
		resetPaneState();
	});

	it("package registration initializes companion active and registers analysis", () => {
		process.env.BASECAMP_AGENT_DEPTH = "0";
		setCompanionActive(true);
		const { pi, registeredEvents } = createMockPi();

		registerCompanionPackage(pi);

		assert.equal(isCompanionActive(), false);
		assert.ok(registeredEvents().includes("agent_end"));
	});
});
