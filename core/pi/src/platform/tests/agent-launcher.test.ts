import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import {
	type AgentLauncher,
	clearAgentLauncherForTesting,
	getAgentLauncher,
	registerAgentLauncher,
} from "../agent-launcher.ts";

describe("agent launcher registry", () => {
	afterEach(() => {
		clearAgentLauncherForTesting();
	});

	it("registers, returns, and clears a launcher", () => {
		clearAgentLauncherForTesting();

		const launcher: AgentLauncher = {
			id: "test",
			async launch() {
				return { ok: true, agentHandle: "handle", agent: "worker" };
			},
		};

		assert.equal(getAgentLauncher(), null);
		registerAgentLauncher(launcher);
		assert.equal(getAgentLauncher(), launcher);

		clearAgentLauncherForTesting();
		assert.equal(getAgentLauncher(), null);
	});

	it("replaces the existing launcher with the most recently registered one", () => {
		clearAgentLauncherForTesting();
		const first: AgentLauncher = {
			id: "first",
			async launch() {
				return { ok: false, agent: "worker", message: "first" };
			},
		};
		const second: AgentLauncher = {
			id: "second",
			async launch() {
				return { ok: true, agentHandle: "second-handle", agent: "worker" };
			},
		};

		registerAgentLauncher(first);
		registerAgentLauncher(second);

		assert.equal(getAgentLauncher(), second);
		clearAgentLauncherForTesting();
	});
});
