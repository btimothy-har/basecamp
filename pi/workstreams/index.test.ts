import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resetCopilotLaunchForTesting, setCopilotLaunchReader } from "#core/agent-mode/copilot.ts";
import registerWorkstreams from "./index.ts";

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
	let priorDepth: string | undefined;

	beforeEach(() => {
		priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		process.env.BASECAMP_AGENT_DEPTH = "0";
	});

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
		resetCopilotLaunchForTesting();
	});

	it("registers the workstream tools and skill for a copilot session", () => {
		setCopilotLaunchReader(() => true);
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.equal(toolNames.has("create_workstream"), true);
		assert.equal(toolNames.has("edit_workstream"), true);
		assert.equal(toolNames.has("launch_workstream"), true);
		assert.equal(toolNames.has("list_workstreams"), true);
		assert.equal(toolNames.has("set_workstream_status"), true);
		assert.equal(pi.flags.has("workstream"), true);
		assert.ok(pi.onEvents.some((entry) => entry.event === "resources_discover"));
	});

	it("withholds the tools from a non-copilot top-level session but keeps --workstream", () => {
		setCopilotLaunchReader(() => false);
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		// shaping and staging is the copilot's job; a --workstream session only attaches
		assert.equal(pi.tools.length, 0);
		assert.equal(pi.flags.has("workstream"), true);
		assert.ok(!pi.onEvents.some((entry) => entry.event === "resources_discover"));
	});

	it("registers nothing for a non-top-level (daemon-spawned) session", () => {
		process.env.BASECAMP_AGENT_DEPTH = "1";
		const pi = createMockPi();
		registerWorkstreams(pi as unknown as ExtensionAPI);

		assert.equal(pi.tools.length, 0);
		assert.equal(pi.flags.has("workstream"), false);
	});
});
