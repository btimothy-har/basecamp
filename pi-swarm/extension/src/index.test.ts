import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import defaultPiSwarm, { registerPiSwarm } from "./index.ts";
import { attachPiSwarmSkillTracking, createLocalPiSwarmDependencies } from "./local-adapters.ts";

type ToolSpec = { name: string };

type MockPi = {
	tools: ToolSpec[];
	commands: string[];
	onEvents: Array<{ event: string; handler: (event: unknown) => void }>;
	registerTool: (tool: ToolSpec) => void;
	registerCommand: (name: string, _spec: unknown) => void;
	getAllTools: () => unknown[];
	getSessionName: () => string;
	setSessionName: (_name: string) => void;
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
		setSessionName(_name: string) {
			/* no-op */
		},
		on(event, handler) {
			this.onEvents.push({ event, handler });
		},
	};
}

function clearPiSwarmTrackingState(): void {
	delete (globalThis as Record<symbol, unknown>)[Symbol.for("basecamp.skillTracker")];
	delete (globalThis as Record<symbol, unknown>)[Symbol.for("basecamp.swarmSkillTrackingInstalled")];
}

describe("pi-swarm extension entrypoint", () => {
	let priorDepth: string | undefined;

	beforeEach(() => {
		priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		process.env.BASECAMP_AGENT_DEPTH = "0";
		clearPiSwarmTrackingState();
	});

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
	});

	it("default export registers only async daemon tools", () => {
		const pi = createMockPi();
		defaultPiSwarm(pi as unknown as ExtensionAPI);

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.equal(pi.commands.length, 0);
		assert.equal(toolNames.has("dispatch_agent"), true);
		assert.equal(toolNames.has("list_agents"), true);
		assert.equal(toolNames.has("wait_for_agent"), true);
		assert.equal(toolNames.has("agent"), false);
	});

	it("registerPiSwarm registers sync and async tools", () => {
		const pi = createMockPi();
		registerPiSwarm(pi as unknown as ExtensionAPI, createLocalPiSwarmDependencies());

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.equal(toolNames.has("agent"), true);
		assert.equal(toolNames.has("dispatch_agent"), true);
		assert.equal(toolNames.has("list_agents"), true);
		assert.equal(toolNames.has("wait_for_agent"), true);
		assert.equal(pi.commands.includes("agents"), true);
	});
});

describe("attachPiSwarmSkillTracking", () => {
	let priorDepth: string | undefined;

	beforeEach(() => {
		priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		process.env.BASECAMP_AGENT_DEPTH = "0";
		clearPiSwarmTrackingState();
	});

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
		clearPiSwarmTrackingState();
	});

	it("tracks skill invocation from tool_call events and trims whitespace", () => {
		const pi = createMockPi();
		const deps = createLocalPiSwarmDependencies();

		attachPiSwarmSkillTracking(pi as unknown as ExtensionAPI);
		const toolCall = pi.onEvents.find(({ event }) => event === "tool_call");
		assert.ok(toolCall);

		toolCall.handler({ toolName: "skill", input: { name: "  agents  " } });
		assert.equal(deps.hasInvokedSkill("agents"), true);
	});

	it("does not duplicate tool_call handlers across duplicate attachment", () => {
		const pi = createMockPi();
		attachPiSwarmSkillTracking(pi as unknown as ExtensionAPI);
		attachPiSwarmSkillTracking(pi as unknown as ExtensionAPI);

		assert.equal(pi.onEvents.filter((entry) => entry.event === "tool_call").length, 1);
	});
});
