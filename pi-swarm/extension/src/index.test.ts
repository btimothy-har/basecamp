import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import defaultPiSwarm from "./index.ts";

type ToolSpec = { name: string };

type MockPi = {
	tools: ToolSpec[];
	commands: string[];
	onEvents: Array<{ event: string }>;
	registerTool: (tool: ToolSpec) => void;
	registerCommand: (name: string, _spec: unknown) => void;
	getAllTools: () => unknown[];
	getSessionName: () => string;
	on: (event: string, handler: (event: unknown) => void) => void;
};

function createMockPi(): MockPi {
	return {
		tools: [],
		commands: [],
		onEvents: [],
		registerTool(tool) {
			this.tools.push(tool);
		},
		registerCommand(name) {
			this.commands.push(name);
		},
		getAllTools() {
			return [];
		},
		getSessionName() {
			return "session";
		},
		on(event, _handler) {
			this.onEvents.push({ event });
		},
	};
}

describe("pi-swarm extension entrypoint", () => {
	let priorDepth: string | undefined;

	beforeEach(() => {
		priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		process.env.BASECAMP_AGENT_DEPTH = "0";
	});

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
	});

	it("default export registers only async daemon tools", () => {
		const pi = createMockPi();
		defaultPiSwarm(pi);

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.equal(pi.commands.length, 0);
		assert.equal(toolNames.has("dispatch_agent"), true);
		assert.equal(toolNames.has("list_agents"), true);
		assert.equal(toolNames.has("wait_for_agent"), true);
		assert.equal(toolNames.has("agent"), false);
	});
});
