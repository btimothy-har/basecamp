import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerWorkstreams from "./index.ts";

const WORKSTREAM_TOOLS = [
	"create_workstream",
	"edit_workstream",
	"launch_workstream",
	"list_workstreams",
	"set_workstream_status",
];

type ToolSpec = { name: string };

type MockPi = {
	tools: ToolSpec[];
	commands: string[];
	onEvents: Array<{ event: string; handler: (event: unknown) => void }>;
	flags: Map<string, unknown>;
	registerTool: (tool: ToolSpec) => void;
	registerCommand: (name: string, _spec: unknown) => void;
	registerFlag: (name: string, _spec: unknown) => void;
	getFlag: (_name: string) => unknown;
	getAllTools: () => unknown[];
	getSessionName: () => string;
	setSessionName: (_name: string) => void;
	on: (event: string, handler: (event: unknown) => void) => void;
};

function createMockPi(): MockPi {
	const flags = new Map<string, unknown>();
	return {
		tools: [],
		commands: [],
		onEvents: [],
		flags,
		registerTool(tool) {
			this.tools.push(tool);
		},
		registerCommand(name) {
			this.commands.push(name);
		},
		registerFlag(name, _spec) {
			this.flags.set(name, undefined);
		},
		getFlag(_name) {
			return undefined;
		},
		getAllTools() {
			return [];
		},
		getSessionName() {
			return "session";
		},
		setSessionName(_name: string) {
			/* no-op */
		},
		on(event, handler) {
			this.onEvents.push({ event, handler });
		},
	};
}

describe("workstreams entrypoint", () => {
	const originalArgv = process.argv;
	let priorDepth: string | undefined;

	beforeEach(() => {
		priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		process.env.BASECAMP_AGENT_DEPTH = "0";
	});

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
		process.argv = originalArgv;
	});

	// The gate runs at registration, before Pi has applied any CLI flag value, so the
	// launch signal has to come from argv — reading pi.getFlag here always yields
	// undefined and silently withholds every tool.
	it("registers the workstream tools for a copilot session", () => {
		process.argv = [...originalArgv, "--copilot"];
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.deepEqual(
			WORKSTREAM_TOOLS.filter((name) => !toolNames.has(name)),
			[],
		);
		assert.equal(pi.flags.has("workstream"), true);
	});

	it("registers the workstream tools for --copilot=<value>", () => {
		process.argv = [...originalArgv, "--copilot=false"];
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.deepEqual(
			WORKSTREAM_TOOLS.filter((name) => !toolNames.has(name)),
			[],
		);
	});

	it("withholds the tools from a non-copilot top-level session but keeps --workstream", () => {
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		// shaping and staging is the copilot's job; a --workstream session only attaches
		assert.equal(pi.tools.length, 0);
		assert.equal(pi.flags.has("workstream"), true);
	});

	// Depth wins over the launch flag: --copilot never reaches a spawned agent's argv,
	// but the gate must not depend on that.
	it("registers nothing for a non-top-level (daemon-spawned) session", () => {
		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.argv = [...originalArgv, "--copilot"];
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		assert.equal(pi.tools.length, 0);
		assert.equal(pi.flags.has("workstream"), false);
	});
});
