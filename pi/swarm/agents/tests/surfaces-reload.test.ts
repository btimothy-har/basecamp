import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { getConnectListeners } from "#core/hub/state.ts";
import { registerAgentSurfaces } from "../surfaces.ts";
import { daemonToolDeps, MockConnection, MockPi } from "./harness.ts";

// Regression guard for the /reload double-subscribe bug: the hub WebSocket survives
// /reload (core's processScoped connection), so onDaemonConnect re-fires on the SAME
// connection. The agent connect-wiring state must survive reload too, or the pre-reload
// peer_message_delivery handler is never unsubscribed and every peer message is
// delivered + acked twice for the rest of the session.
describe("agent surfaces — /reload connect wiring", () => {
	const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
	const priorMaxDepth = process.env.BASECAMP_AGENT_MAX_DEPTH;

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
		if (priorMaxDepth === undefined) delete process.env.BASECAMP_AGENT_MAX_DEPTH;
		else process.env.BASECAMP_AGENT_MAX_DEPTH = priorMaxDepth;
	});

	it("does not double-subscribe peer delivery when a reload re-wires a surviving connection", () => {
		// Top-level session; MAX_DEPTH=0 skips tool registration so only the connect
		// listener is exercised.
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.BASECAMP_AGENT_MAX_DEPTH = "0";

		const before = getConnectListeners().length;
		// A /reload re-imports the module and re-registers; simulate two loads.
		registerAgentSurfaces(new MockPi() as never, daemonToolDeps);
		registerAgentSurfaces(new MockPi() as never, daemonToolDeps);
		const listeners = getConnectListeners();
		const firstLoad = listeners[before];
		const reload = listeners[before + 1];
		assert.ok(firstLoad && reload, "both loads registered a connect listener");

		// The surviving WebSocket means both listeners fire on the SAME connection.
		const connection = new MockConnection();
		const ctx = { hasUI: false } as never;
		firstLoad(connection, ctx);
		reload(connection, ctx);

		// Exactly one delivery handler must remain — the reload unsubscribed the prior
		// one via the surviving connect-state.
		assert.equal(connection.handlers.get("peer_message_delivery")?.size, 1);
	});
});
