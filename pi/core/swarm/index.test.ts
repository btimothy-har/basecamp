import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { listCatalogItemsByType } from "../catalog/index.ts";
import registerSwarm from "./index.ts";

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

describe("core/swarm primitive entrypoint", () => {
	let priorDepth: string | undefined;

	beforeEach(() => {
		priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		process.env.BASECAMP_AGENT_DEPTH = "0";
	});

	afterEach(() => {
		if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
	});

	it("registerSwarm registers the async daemon tools and the builtin agent catalog", () => {
		const pi = createMockPi();
		registerSwarm(pi as unknown as ExtensionAPI);

		const toolNames = new Set(pi.tools.map((tool) => tool.name));
		assert.equal(toolNames.has("dispatch_agent"), true);
		assert.equal(toolNames.has("list_agents"), true);
		assert.equal(toolNames.has("wait_for_agent"), true);
		// The runtime primitive owns no slash command and no `agent` tool;
		// code-review ships as a skill + report_findings tool in its own domain.
		assert.equal(pi.commands.includes("code-review"), false);
		assert.equal(toolNames.has("agent"), false);

		const agentNames = new Set(listCatalogItemsByType("agents", { cwd: process.cwd() }).map((item) => item.name));
		assert.deepEqual(
			agentNames,
			new Set([
				"code-clarity-specialist",
				"conventions-specialist",
				"devils-advocate",
				"docs-specialist",
				"general-reviewer",
				"scout",
				"security-specialist",
				"testing-specialist",
				"worker",
			]),
		);
	});
});
