import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import registerCompanionPackage from "../index.ts";
import { isCompanionActive, setCompanionActive } from "../panes/state.ts";
import { createMockPi, resetPaneState } from "./panes-harness.ts";

describe("companion/registerCompanionPackage", () => {
	afterEach(() => {
		delete process.env.TMUX;
		delete process.env.TMUX_PANE;
		delete process.env.HERDR_ENV;
		delete process.env.HERDR_PANE_ID;
		delete process.env.HERDR_SOCKET_PATH;
		delete process.env.BASECAMP_AGENT_DEPTH;
		resetPaneState();
	});

	it("initializes companion active to false on registration", () => {
		process.env.BASECAMP_AGENT_DEPTH = "0";
		setCompanionActive(true);
		const { pi } = createMockPi();

		registerCompanionPackage(pi);

		assert.equal(isCompanionActive(), false);
	});

	it("wires both the snapshot writer and the panes lifecycle", () => {
		process.env.BASECAMP_AGENT_DEPTH = "0";
		const { pi, registeredEvents, handlerCount } = createMockPi();

		registerCompanionPackage(pi);

		// registerCompanion (snapshot) is the only sub-registration that wires tool_result,
		// so its presence proves that half is still wired.
		assert.ok(registeredEvents().includes("tool_result"), "snapshot writer wired");
		// Both registerCompanion and registerPanes wire the lifecycle events; requiring two
		// handlers each means dropping either registration fails this contract test.
		assert.equal(handlerCount("session_start"), 2, "companion + panes both wired session_start");
		assert.equal(handlerCount("session_shutdown"), 2, "companion + panes both wired session_shutdown");
	});
});
