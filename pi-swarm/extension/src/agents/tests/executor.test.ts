import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	buildAgentRunName,
	buildAgentTaskText,
	buildPiArgs,
	ensureAgentDir,
	sanitizeAgentSpawnEnv,
} from "../executor.ts";
import { getBasecampExtensionToolNames } from "../launch.ts";
import type { AgentConfig } from "../types.ts";

describe("buildAgentRunName", () => {
	it("accepts readable suffixes and trims outer whitespace", () => {
		assert.equal(buildAgentRunName("agent-abc", "review-auth"), "agent-abc-review-auth");
		assert.equal(buildAgentRunName("agent-abc", "qa_1"), "agent-abc-qa_1");
		assert.equal(buildAgentRunName("agent-abc", "  review auth  "), "agent-abc-review auth");
	});

	it("rejects malformed suffixes", () => {
		assert.throws(() => buildAgentRunName("agent-abc", "../bad"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "bad\\suffix"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "foo/../bar"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", ".."), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "bad\nname"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "   "), /suffix cannot be empty/i);
	});
});

describe("ensureAgentDir", () => {
	it("defends path traversal attempts outside the base agent directory", () => {
		assert.throws(() => ensureAgentDir("../outside"), /outside basecamp-agents directory/i);
	});

	it("creates safe directories under basecamp-agents", () => {
		const name = `agent-valid-${randomUUID()}`;
		const dir = ensureAgentDir(name);
		try {
			assert.equal(path.basename(dir), name);
			assert.equal(path.dirname(dir), path.resolve(os.tmpdir(), "basecamp-agents"));
			assert.equal(fs.existsSync(dir), true);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});

describe("buildPiArgs task text", () => {
	it("passes short tasks with the completion contract as the final arg", () => {
		const sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-agent-session-"));
		const { args, agentDir } = buildPiArgs(null, "hello world", {
			name: `agent-task-${randomUUID()}`,
			model: undefined,
			sessionDir,
			extensionTools: [],
		});

		try {
			assert.equal(args.at(-1), buildAgentTaskText("hello world"));
		} finally {
			fs.rmSync(sessionDir, { recursive: true, force: true });
			fs.rmSync(agentDir, { recursive: true, force: true });
		}
	});

	it("writes long wrapped task text to task.md", () => {
		const sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-agent-session-"));
		const longTask = "x".repeat(9_000);
		const { args, agentDir } = buildPiArgs(null, longTask, {
			name: `agent-task-${randomUUID()}`,
			model: undefined,
			sessionDir,
			extensionTools: [],
		});

		try {
			const taskArg = args.at(-1);
			assert.match(taskArg ?? "", /^@/);
			const taskFile = taskArg?.slice(1) ?? "";
			assert.equal(path.basename(taskFile), "task.md");
			assert.equal(fs.readFileSync(taskFile, "utf8"), buildAgentTaskText(longTask));
		} finally {
			fs.rmSync(sessionDir, { recursive: true, force: true });
			fs.rmSync(agentDir, { recursive: true, force: true });
		}
	});
});

function toolNamesFromArgs(args: string[]): string[] {
	const toolsIndex = args.indexOf("--tools");
	assert.notEqual(toolsIndex, -1);
	return args[toolsIndex + 1]?.split(",") ?? [];
}

function buildToolArgs(agent: AgentConfig | null): string[] {
	const sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-agent-session-"));
	const { args, agentDir } = buildPiArgs(agent, "inspect tools", {
		name: `agent-tools-${randomUUID()}`,
		model: undefined,
		sessionDir,
		extensionTools: ["dispatch_agent", "list_agents", "wait_for_agent"],
	});
	fs.rmSync(sessionDir, { recursive: true, force: true });
	fs.rmSync(agentDir, { recursive: true, force: true });
	return args;
}

const SUPPORT_TOOLS = [
	"skill",
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"get_task",
	"annotate_task",
	"delete_task",
	"bq_query",
];

const PARENT_ONLY_TOOLS = ["plan", "escalate", "review_packet"];

describe("subagent tool allowlist", () => {
	it("adds support tools for read-only agents without parent-only tools", () => {
		const tools = toolNamesFromArgs(buildToolArgs(null));

		for (const tool of ["read", "bash", "grep", "find", "ls", ...SUPPORT_TOOLS]) {
			assert.equal(tools.includes(tool), true, `${tool} should be available`);
		}
		for (const tool of ["write", "edit", ...PARENT_ONLY_TOOLS]) {
			assert.equal(tools.includes(tool), false, `${tool} should not be available`);
		}
	});

	it("keeps mutative tools worker-only while preserving support tools", () => {
		const worker: AgentConfig = {
			name: "worker",
			description: "Execute implementation tasks",
			model: "inherit",
			systemPrompt: "Worker prompt",
			source: "builtin",
			filePath: "/tmp/worker.md",
		};
		const tools = toolNamesFromArgs(buildToolArgs(worker));

		for (const tool of ["read", "write", "edit", "bash", "grep", "find", "ls", ...SUPPORT_TOOLS]) {
			assert.equal(tools.includes(tool), true, `${tool} should be available`);
		}
		for (const tool of PARENT_ONLY_TOOLS) {
			assert.equal(tools.includes(tool), false, `${tool} should not be available`);
		}
	});
});

describe("buildPiArgs skill discovery", () => {
	it("never disables skill discovery for subagents", () => {
		assert.equal(buildToolArgs(null).includes("--no-skills"), false);
	});
});

describe("getBasecampExtensionToolNames", () => {
	it("excludes parent-only and browser tools from subagent extension tools", () => {
		const extensionRoot = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-extension-root-"));
		try {
			const sourceInfo = (name: string) => ({
				source: "package",
				baseDir: extensionRoot,
				path: path.join(extensionRoot, `${name}.ts`),
			});
			const tools = ["bq_query", "browser_eval", "browser_screenshot", "agent", "escalate"].map((name) => ({
				name,
				sourceInfo: sourceInfo(name),
			}));
			const pi = { getAllTools: () => tools } as unknown as ExtensionAPI;

			assert.deepEqual(getBasecampExtensionToolNames(pi, extensionRoot), ["bq_query"]);
		} finally {
			fs.rmSync(extensionRoot, { recursive: true, force: true });
		}
	});
});

describe("sanitizeAgentSpawnEnv", () => {
	it("removes daemon report-identity vars while preserving allowed env values", () => {
		const env = sanitizeAgentSpawnEnv({
			BASECAMP_REPORT_TOKEN: "report-token",
			BASECAMP_AGENT_ID: "agent-id",
			BASECAMP_AGENT_HANDLE: "parent-handle",
			BASECAMP_RUN_ID: "run-id",
			BASECAMP_DAEMON_UDS: "/tmp/daemon.sock",
			BASECAMP_PROJECT: "proj",
			BASECAMP_PARENT_SESSION: "parent-session",
			BASECAMP_AGENT_DEPTH: "2",
			BASECAMP_AGENT_MAX_DEPTH: "9",
			OPENAI_API_KEY: "openai-key",
			CUSTOM_API_KEY: "custom-key",
		});

		assert.equal(env.BASECAMP_REPORT_TOKEN, undefined);
		assert.equal(env.BASECAMP_AGENT_ID, undefined);
		assert.equal(env.BASECAMP_AGENT_HANDLE, undefined);
		assert.equal(env.BASECAMP_RUN_ID, undefined);
		assert.equal(env.BASECAMP_DAEMON_UDS, undefined);
		assert.equal(env.BASECAMP_PROJECT, "proj");
		assert.equal(env.BASECAMP_PARENT_SESSION, "parent-session");
		assert.equal(env.BASECAMP_AGENT_DEPTH, "2");
		assert.equal(env.BASECAMP_AGENT_MAX_DEPTH, "9");
		assert.equal(env.OPENAI_API_KEY, "openai-key");
		assert.equal(env.CUSTOM_API_KEY, "custom-key");
	});
});
