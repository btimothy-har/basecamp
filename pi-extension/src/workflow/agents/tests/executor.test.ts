import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { buildAgentRunName, buildSpawnEnv, ensureAgentDir } from "../executor.ts";

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

describe("buildSpawnEnv", () => {
	it("removes daemon report-identity vars while preserving sync child env", () => {
		const prior = {
			runId: process.env.BASECAMP_RUN_ID,
			reportToken: process.env.BASECAMP_REPORT_TOKEN,
			agentId: process.env.BASECAMP_AGENT_ID,
			daemonUds: process.env.BASECAMP_DAEMON_UDS,
			depth: process.env.BASECAMP_AGENT_DEPTH,
			project: process.env.BASECAMP_PROJECT,
			parentSession: process.env.BASECAMP_PARENT_SESSION,
			maxDepth: process.env.BASECAMP_AGENT_MAX_DEPTH,
			openai: process.env.OPENAI_API_KEY,
			custom: process.env.SYNC_TEST_API_KEY,
			parentCustom: process.env.SYNC_TEST_PARENT_KEY,
		};
		process.env.BASECAMP_RUN_ID = "run-parent";
		process.env.BASECAMP_REPORT_TOKEN = "report-parent";
		process.env.BASECAMP_AGENT_ID = "agent-parent";
		process.env.BASECAMP_DAEMON_UDS = "/tmp/daemon-parent.sock";
		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_PROJECT = "proj-parent";
		process.env.BASECAMP_PARENT_SESSION = "parent-session";
		process.env.BASECAMP_AGENT_MAX_DEPTH = "5";
		process.env.OPENAI_API_KEY = "parent-openai";
		process.env.SYNC_TEST_PARENT_KEY = "keep-parent";

		try {
			const env = buildSpawnEnv({
				BASECAMP_REPORT_TOKEN: "child-report",
				BASECAMP_AGENT_ID: "child-agent",
				BASECAMP_RUN_ID: "child-run",
				BASECAMP_DAEMON_UDS: "/tmp/daemon-child.sock",
				BASECAMP_PROJECT: "proj-child",
				BASECAMP_PARENT_SESSION: "child-session",
				BASECAMP_AGENT_DEPTH: "2",
				BASECAMP_AGENT_MAX_DEPTH: "9",
				OPENAI_API_KEY: "child-openai",
				SYNC_TEST_API_KEY: "child-nonbasecamp",
				SYNC_TEST_PARENT_KEY: "child-overrides-parent",
			});

			assert.equal(env.BASECAMP_REPORT_TOKEN, undefined);
			assert.equal(env.BASECAMP_AGENT_ID, undefined);
			assert.equal(env.BASECAMP_RUN_ID, undefined);
			assert.equal(env.BASECAMP_DAEMON_UDS, undefined);
			assert.equal(env.BASECAMP_PROJECT, "proj-child");
			assert.equal(env.BASECAMP_PARENT_SESSION, "child-session");
			assert.equal(env.BASECAMP_AGENT_DEPTH, "2");
			assert.equal(env.BASECAMP_AGENT_MAX_DEPTH, "9");
			assert.equal(env.OPENAI_API_KEY, "child-openai");
			assert.equal(env.SYNC_TEST_PARENT_KEY, "child-overrides-parent");
			assert.equal(env.SYNC_TEST_API_KEY, "child-nonbasecamp");
		} finally {
			if (prior.runId === undefined) delete process.env.BASECAMP_RUN_ID;
			else process.env.BASECAMP_RUN_ID = prior.runId;
			if (prior.reportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = prior.reportToken;
			if (prior.agentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = prior.agentId;
			if (prior.daemonUds === undefined) delete process.env.BASECAMP_DAEMON_UDS;
			else process.env.BASECAMP_DAEMON_UDS = prior.daemonUds;
			if (prior.depth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = prior.depth;
			if (prior.project === undefined) delete process.env.BASECAMP_PROJECT;
			else process.env.BASECAMP_PROJECT = prior.project;
			if (prior.parentSession === undefined) delete process.env.BASECAMP_PARENT_SESSION;
			else process.env.BASECAMP_PARENT_SESSION = prior.parentSession;
			if (prior.maxDepth === undefined) delete process.env.BASECAMP_AGENT_MAX_DEPTH;
			else process.env.BASECAMP_AGENT_MAX_DEPTH = prior.maxDepth;
			if (prior.openai === undefined) delete process.env.OPENAI_API_KEY;
			else process.env.OPENAI_API_KEY = prior.openai;
			if (prior.custom === undefined) delete process.env.SYNC_TEST_API_KEY;
			else process.env.SYNC_TEST_API_KEY = prior.custom;
			if (prior.parentCustom === undefined) delete process.env.SYNC_TEST_PARENT_KEY;
			else process.env.SYNC_TEST_PARENT_KEY = prior.parentCustom;
		}
	});
});
